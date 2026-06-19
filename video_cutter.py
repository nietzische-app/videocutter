import argparse
import json
import math
import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from openai import OpenAI

try:
    from moviepy import VideoFileClip
except ImportError:  # MoviePy 1.x
    from moviepy.editor import VideoFileClip


DEFAULT_CLIP_SECONDS = 30.0
DEFAULT_ASPECT_RATIO = 9 / 16
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}


def is_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def is_youtube_url(value: str) -> bool:
    parsed = urlparse(value)
    host = parsed.netloc.lower()
    return host in YOUTUBE_HOSTS or host.endswith(".youtube.com")


def seconds_to_stamp(seconds: float) -> str:
    seconds = max(0, float(seconds))
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(int(minutes), 60)
    return f"{hours:02d}:{minutes:02d}:{sec:05.2f}"


def extract_audio(video_path: Path, audio_path: Path) -> None:
    with VideoFileClip(str(video_path)) as video:
        if video.audio is None:
            raise RuntimeError("Videoda ses parçası bulunamadı.")
        video.audio.write_audiofile(
            str(audio_path),
            fps=16000,
            bitrate="64k",
            codec="libmp3lame",
            logger=None,
        )


def download_youtube_video(url: str, output_dir: Path) -> Path:
    try:
        from yt_dlp import YoutubeDL
    except ImportError as exc:
        raise RuntimeError(
            "YouTube linki kullanmak icin yt-dlp gerekli. Kurulum: python -m pip install yt-dlp"
        ) from exc

    output_template = str(output_dir / "youtube_source.%(ext)s")
    options = {
        "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best",
        "merge_output_format": "mp4",
        "outtmpl": output_template,
        "quiet": False,
        "noplaylist": True,
    }

    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)
        downloaded = Path(ydl.prepare_filename(info))
        merged = downloaded.with_suffix(".mp4")
        if merged.exists():
            return merged
        if downloaded.exists():
            return downloaded

    candidates = sorted(output_dir.glob("youtube_source.*"))
    if not candidates:
        raise RuntimeError("YouTube videosu indirildi gibi gorunuyor ama dosya bulunamadi.")
    return candidates[0]


def transcribe_audio(client: OpenAI, audio_path: Path, whisper_model: str, language: str | None) -> dict:
    with audio_path.open("rb") as audio_file:
        kwargs = {
            "model": whisper_model,
            "file": audio_file,
            "response_format": "verbose_json",
            "timestamp_granularities": ["word"],
        }
        if language:
            kwargs["language"] = language
        result = client.audio.transcriptions.create(**kwargs)
        if hasattr(result, "model_dump"):
            return result.model_dump()
        if isinstance(result, dict):
            return result
        return json.loads(result.model_dump_json())


def words_to_timed_lines(words: list[dict], line_seconds: float = 5.0) -> list[dict]:
    lines: list[dict] = []
    current_words: list[str] = []
    start = None
    end = None

    for item in words:
        word = str(item.get("word", "")).strip()
        if not word:
            continue
        word_start = float(item.get("start", 0))
        word_end = float(item.get("end", word_start))
        if start is None:
            start = word_start
        current_words.append(word)
        end = word_end

        if end - start >= line_seconds:
            lines.append({"start": start, "end": end, "text": " ".join(current_words)})
            current_words = []
            start = None
            end = None

    if current_words and start is not None and end is not None:
        lines.append({"start": start, "end": end, "text": " ".join(current_words)})
    return lines


def transcript_for_prompt(lines: list[dict], max_chars: int) -> str:
    rendered = [
        f"[{seconds_to_stamp(line['start'])} - {seconds_to_stamp(line['end'])}] {line['text']}"
        for line in lines
    ]
    text = "\n".join(rendered)
    if len(text) <= max_chars:
        return text

    keep = max_chars // 2
    return (
        text[:keep]
        + "\n\n[TRANSKRIPT ORTASI COK UZUN OLDUGU ICIN KISALTILDI]\n\n"
        + text[-keep:]
    )


def ask_gpt_for_clip(
    client: OpenAI,
    model: str,
    transcript: str,
    video_duration: float,
    clip_seconds: float,
) -> dict:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "start_time": {"type": "number", "description": "Chosen clip start time in seconds."},
            "end_time": {"type": "number", "description": "Chosen clip end time in seconds."},
            "score": {"type": "integer", "minimum": 1, "maximum": 10},
            "reason": {"type": "string"},
            "title": {"type": "string"},
        },
        "required": ["start_time", "end_time", "score", "reason", "title"],
    }

    response = client.responses.create(
        model=model,
        input=[
            {
                "role": "system",
                "content": (
                    "Sen kısa video editörüsün. Transkriptte en heyecanlı, merak uyandıran, "
                    "duygusal, komik veya vurucu anı bul. Yalnızca JSON şemasına uygun yanıt ver."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Video suresi: {video_duration:.2f} saniye.\n"
                    f"Istenen klip suresi: {clip_seconds:.2f} saniye.\n\n"
                    "Gorev: En iyi tek klip araligini sec. Secilen aralik mumkun oldugunca "
                    "tam istenen surede olsun, video sinirlarini asmasin ve cumlenin ortasinda "
                    "baslamamaya calissin.\n\n"
                    f"Transkript:\n{transcript}"
                ),
            },
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "clip_selection",
                "strict": True,
                "schema": schema,
            }
        },
    )
    return json.loads(response.output_text)


def clamp_clip(selection: dict, video_duration: float, clip_seconds: float) -> tuple[float, float]:
    raw_start = float(selection.get("start_time", 0))
    raw_end = float(selection.get("end_time", raw_start + clip_seconds))

    center = (raw_start + raw_end) / 2
    start = center - clip_seconds / 2
    end = center + clip_seconds / 2

    if video_duration <= clip_seconds:
        return 0.0, video_duration

    start = max(0.0, min(start, video_duration - clip_seconds))
    end = start + clip_seconds
    return start, end


def crop_clip(clip, *, x1: int, y1: int, width: int, height: int):
    if hasattr(clip, "crop"):
        return clip.crop(x1=x1, y1=y1, width=width, height=height)
    if hasattr(clip, "cropped"):
        return clip.cropped(x1=x1, y1=y1, width=width, height=height)

    from moviepy import vfx

    return clip.with_effects([vfx.Crop(x1=x1, y1=y1, width=width, height=height)])


def resize_clip(clip, *, height: int):
    if hasattr(clip, "resize"):
        return clip.resize(height=height)
    if hasattr(clip, "resized"):
        return clip.resized(height=height)

    from moviepy import vfx

    return clip.with_effects([vfx.Resize(height=height)])


def crop_to_vertical(clip, target_height: int):
    width, height = clip.size
    current_ratio = width / height

    if current_ratio > DEFAULT_ASPECT_RATIO:
        new_width = int(height * DEFAULT_ASPECT_RATIO)
        x1 = int((width - new_width) / 2)
        cropped = crop_clip(clip, x1=x1, y1=0, width=new_width, height=height)
    else:
        new_height = int(width / DEFAULT_ASPECT_RATIO)
        y1 = int((height - new_height) / 2)
        cropped = crop_clip(clip, x1=0, y1=y1, width=width, height=new_height)

    return resize_clip(cropped, height=target_height)


def cut_vertical_video(
    input_path: Path,
    output_path: Path,
    start: float,
    end: float,
    target_height: int,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with VideoFileClip(str(input_path)) as video:
        try:
            subclip = video.subclip(start, end)
        except AttributeError:  # MoviePy 2.x
            subclip = video.subclipped(start, end)

        vertical = crop_to_vertical(subclip, target_height)
        vertical.write_videofile(
            str(output_path),
            codec="libx264",
            audio_codec="aac",
            fps=video.fps or 30,
            preset="medium",
            threads=max(1, min(4, os.cpu_count() or 1)),
        )

        vertical.close()
        subclip.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="OpenAI Whisper + GPT API ile videodan en iyi dikey 30 saniyelik klibi keser."
    )
    parser.add_argument("input", help="Kaynak video yolu veya YouTube linki")
    parser.add_argument("-o", "--output", type=Path, default=Path("outputs/clip_vertical.mp4"))
    parser.add_argument("--clip-seconds", type=float, default=DEFAULT_CLIP_SECONDS)
    parser.add_argument("--language", default="tr", help="Transkripsiyon dili. Otomatik algılama için boş bırakın.")
    parser.add_argument("--whisper-model", default="whisper-1")
    parser.add_argument("--gpt-model", default="gpt-5.5")
    parser.add_argument("--target-height", type=int, default=1920)
    parser.add_argument("--max-transcript-chars", type=int, default=100_000)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = args.output.resolve()

    if args.clip_seconds <= 0 or not math.isfinite(args.clip_seconds):
        raise ValueError("--clip-seconds pozitif bir sayı olmalı.")

    client = OpenAI()

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        if is_url(args.input):
            if not is_youtube_url(args.input):
                raise ValueError("Su an yalnizca YouTube linkleri destekleniyor.")
            print("0/4 YouTube videosu indiriliyor...")
            input_path = download_youtube_video(args.input, tmp_path)
        else:
            input_path = Path(args.input).resolve()
            if not input_path.exists():
                raise FileNotFoundError(f"Video bulunamadı: {input_path}")

        with VideoFileClip(str(input_path)) as video:
            video_duration = float(video.duration)

        audio_path = Path(tmpdir) / "audio.mp3"
        print("1/4 Ses çıkarılıyor...")
        extract_audio(input_path, audio_path)

        print("2/4 Ses metne dökülüyor...")
        transcript_json = transcribe_audio(
            client=client,
            audio_path=audio_path,
            whisper_model=args.whisper_model,
            language=args.language or None,
        )

    words = transcript_json.get("words") or []
    if not words:
        raise RuntimeError("Transkripsiyondan kelime zaman damgası alınamadı.")

    lines = words_to_timed_lines(words)
    prompt_transcript = transcript_for_prompt(lines, args.max_transcript_chars)

    print("3/4 GPT en iyi anı seçiyor...")
    selection = ask_gpt_for_clip(
        client=client,
        model=args.gpt_model,
        transcript=prompt_transcript,
        video_duration=video_duration,
        clip_seconds=args.clip_seconds,
    )
    start, end = clamp_clip(selection, video_duration, args.clip_seconds)

    print(
        "Seçilen aralık:",
        f"{seconds_to_stamp(start)} - {seconds_to_stamp(end)}",
        f"(puan: {selection.get('score')}/10)",
    )
    print("Gerekçe:", selection.get("reason", ""))

    print("4/4 Dikey video kesiliyor...")
    cut_vertical_video(input_path, output_path, start, end, args.target_height)
    print(f"Bitti: {output_path}")


if __name__ == "__main__":
    main()
