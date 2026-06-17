import argparse
import json
import math
import os
import shutil
import struct
import subprocess
import tempfile
import wave
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
CHUNKED_THRESHOLD_SECONDS = 300.0
NUM_CANDIDATES = 3

SUBTITLE_STYLES = {
    "bold": {
        "fontname": "Bangers",
        "fontsize": 96,
        "primary_color": "&H00FFFFFF",  # white
        "outline_color": "&H00000000",  # black
        "back_color": "&H80000000",
        "bold": 0,
        "outline": 5,
        "shadow": 3,
        "alignment": 2,  # bottom center
        "margin_v": 140,
        "verb_color": "&H005FFFED",  # vibrant cyan-green (BGR)
    },
    "highlight": {
        "fontname": "Bangers",
        "fontsize": 100,
        "primary_color": "&H0000FFFF",  # yellow
        "outline_color": "&H00000000",
        "back_color": "&H80000000",
        "bold": 0,
        "outline": 5,
        "shadow": 0,
        "alignment": 5,  # center
        "margin_v": 60,
        "verb_color": "&H003CFFFF",  # hot orange (BGR)
    },
    "minimal": {
        "fontname": "Bangers",
        "fontsize": 78,
        "primary_color": "&H00FFFFFF",
        "outline_color": "&H00000000",
        "back_color": "&H00000000",
        "bold": 0,
        "outline": 3,
        "shadow": 1,
        "alignment": 2,
        "margin_v": 100,
        "verb_color": "&H006464FF",  # warm red (BGR)
    },
}

_TURKISH_VERB_SUFFIXES = (
    "yor", "iyor", "ıyor", "uyor", "üyor",
    "dı", "di", "du", "dü", "tı", "ti", "tu", "tü",
    "mış", "miş", "muş", "müş",
    "cak", "cek", "acak", "ecek",
    "malı", "meli",
    "sin", "sın", "sun", "sün",
    "lar", "ler",
    "mak", "mek",
    "yor", "ken",
    "ıyorum", "iyorum", "uyorum", "üyorum",
    "ıyorsun", "iyorsun", "uyorsun", "üyorsun",
    "ıyoruz", "iyoruz", "uyoruz", "üyoruz",
    "dım", "dim", "dum", "düm",
    "dın", "din", "dun", "dün",
    "tım", "tim", "tum", "tüm",
    "tın", "tin", "tun", "tün",
    "mıştı", "mişti", "muştu", "müştü",
    "se", "sa",
    "abil", "ebil",
)


def is_turkish_verb(word: str) -> bool:
    w = word.lower().rstrip(".,!?;:'\"")
    if len(w) < 3:
        return False
    return any(w.endswith(s) for s in _TURKISH_VERB_SUFFIXES)


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
            raise RuntimeError("Videoda ses parcasi bulunamadi.")
        video.audio.write_audiofile(
            str(audio_path),
            fps=16000,
            bitrate="64k",
            codec="libmp3lame",
            logger=None,
        )


def extract_audio_wav(video_path: Path, wav_path: Path) -> None:
    with VideoFileClip(str(video_path)) as video:
        if video.audio is None:
            raise RuntimeError("Videoda ses parcasi bulunamadi.")
        video.audio.write_audiofile(
            str(wav_path),
            fps=16000,
            nbytes=2,
            codec="pcm_s16le",
            logger=None,
        )


def analyze_audio_energy(wav_path: Path, window_seconds: float = 1.0) -> list[dict]:
    with wave.open(str(wav_path), "rb") as wf:
        n_channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        framerate = wf.getframerate()
        n_frames = wf.getnframes()

        window_frames = int(framerate * window_seconds)
        energies = []
        offset = 0

        while offset < n_frames:
            chunk_size = min(window_frames, n_frames - offset)
            raw = wf.readframes(chunk_size)
            if not raw:
                break

            if sample_width == 2:
                fmt = f"<{chunk_size * n_channels}h"
                try:
                    samples = struct.unpack(fmt, raw)
                except struct.error:
                    break
            else:
                break

            if n_channels > 1:
                samples = samples[::n_channels]

            rms = math.sqrt(sum(s * s for s in samples) / max(len(samples), 1))
            t_start = offset / framerate
            t_end = (offset + chunk_size) / framerate

            energies.append({
                "start": t_start,
                "end": t_end,
                "rms": rms,
            })
            offset += chunk_size

    return energies


def find_energy_peaks(
    energies: list[dict],
    clip_seconds: float,
    video_duration: float,
    top_n: int = 5,
) -> list[dict]:
    if not energies:
        return []

    max_rms = max(e["rms"] for e in energies) or 1.0
    for e in energies:
        e["norm_rms"] = e["rms"] / max_rms

    window_count = max(1, int(clip_seconds / (energies[0]["end"] - energies[0]["start"])))

    scored_windows: list[dict] = []
    for i in range(len(energies) - window_count + 1):
        window = energies[i:i + window_count]
        avg_energy = sum(e["norm_rms"] for e in window) / len(window)
        peak_energy = max(e["norm_rms"] for e in window)
        variance = sum((e["norm_rms"] - avg_energy) ** 2 for e in window) / len(window)

        # High energy + high variance = exciting (loud moments with contrast)
        score = avg_energy * 0.4 + peak_energy * 0.3 + math.sqrt(variance) * 0.3

        w_start = window[0]["start"]
        w_end = min(window[-1]["end"], video_duration)

        scored_windows.append({
            "start": w_start,
            "end": w_end,
            "energy_score": round(score, 4),
            "avg_energy": round(avg_energy, 4),
            "peak_energy": round(peak_energy, 4),
        })

    scored_windows.sort(key=lambda w: w["energy_score"], reverse=True)

    # Deduplicate: remove overlapping windows
    selected = []
    for w in scored_windows:
        overlaps = False
        for s in selected:
            if w["start"] < s["end"] and w["end"] > s["start"]:
                overlaps = True
                break
        if not overlaps:
            selected.append(w)
        if len(selected) >= top_n:
            break

    return selected


def download_youtube_video(url: str, output_dir: Path, cookies_file: Path | None = None) -> Path:
    try:
        from yt_dlp import YoutubeDL
    except ImportError as exc:
        raise RuntimeError(
            "YouTube linki kullanmak icin yt-dlp gerekli. Kurulum: python -m pip install yt-dlp"
        ) from exc

    output_template = str(output_dir / "youtube_source.%(ext)s")
    options = {
        "format": "bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[ext=mp4][height<=720]/best[height<=720]/best",
        "merge_output_format": "mp4",
        "outtmpl": output_template,
        "quiet": False,
        "noplaylist": True,
        "extractor_args": {"youtube": {"js_runtimes": ["deno"]}},
    }

    if cookies_file and cookies_file.exists():
        options["cookiefile"] = str(cookies_file)

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


SYSTEM_PROMPT = """\
Sen viral kisa video editorusun. Gorevin transkriptten TikTok/Reels/Shorts icin \
en cok izlenecek, paylasilacak ve begeni alacak anlari bulmak.

Aradigin sey:
1. HOOK - Ilk 3 saniyede izleyiciyi yakalayan surpriz, soru veya carpici ifade
2. CATISMA/GERILIM - Tartisma, sasirma, beklenmedik cevap, provokasyon
3. DUYGU PATLAMASI - Kahkaha, ofke, heyecan, saskinlik, aglamalik an
4. SURPRIZ/TWIST - Beklenmedik bilgi, ters kose, "bunu bilmiyordunuz" ani
5. VIRAL REPLIK - Tek basina paylasilabilir, meme olabilecek cumleler

KACINMAN gerekenler:
- Sıradan tanitim, giris veya kapanıs konusmasi
- Monoton anlatim, liste okuma, teknik aciklama
- Sessizlik veya duraklama agirlikli bolumler

Her zaman izleyicinin KAYDIRMAYI DURDURACAGI ani sec.\
"""


def ask_gpt_for_clips(
    client: OpenAI,
    model: str,
    transcript: str,
    video_duration: float,
    clip_seconds: float,
    energy_hints: str,
    num_clips: int = NUM_CANDIDATES,
) -> list[dict]:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "clips": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "start_time": {"type": "number"},
                        "end_time": {"type": "number"},
                        "score": {"type": "integer", "minimum": 1, "maximum": 10},
                        "viral_type": {"type": "string", "description": "hook/catisma/duygu/surpriz/replik"},
                        "reason": {"type": "string"},
                        "title": {"type": "string"},
                    },
                    "required": ["start_time", "end_time", "score", "viral_type", "reason", "title"],
                },
            },
        },
        "required": ["clips"],
    }

    user_content = (
        f"Video suresi: {video_duration:.2f} saniye.\n"
        f"Istenen klip suresi: ~{clip_seconds:.0f} saniye.\n"
        f"Istenen aday sayisi: {num_clips}\n\n"
    )

    if energy_hints:
        user_content += (
            "SES ENERJISI ANALIZI (yuksek enerji = heyecanli, bagirma, kahkaha vs.):\n"
            f"{energy_hints}\n\n"
        )

    user_content += (
        "Gorev:\n"
        f"- Transkriptten en iyi {num_clips} farkli klip araligi sec\n"
        "- Her klip farkli bir andan olmali (ust uste binmesin)\n"
        "- Ses enerjisi yuksek bolgeler oncelikli olsun\n"
        "- Her klip mumkun oldugunca tam istenen surede olsun\n"
        "- Cumlenin ortasinda baslamasin\n"
        "- En yuksek puanlisi ilk sirada olsun\n\n"
        f"Transkript:\n{transcript}"
    )

    response = client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
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
    result = json.loads(response.output_text)
    return result.get("clips", [])


def ask_gpt_for_clips_chunked(
    client: OpenAI,
    model: str,
    lines: list[dict],
    video_duration: float,
    clip_seconds: float,
    max_transcript_chars: int,
    energy_hints: str,
    num_clips: int = NUM_CANDIDATES,
) -> list[dict]:
    window_seconds = clip_seconds * 10
    overlap_seconds = clip_seconds * 2
    step = window_seconds - overlap_seconds

    windows: list[tuple[float, float, list[dict]]] = []
    t = 0.0
    while t < video_duration:
        w_start = t
        w_end = min(t + window_seconds, video_duration)
        w_lines = [ln for ln in lines if ln["end"] > w_start and ln["start"] < w_end]
        if w_lines:
            windows.append((w_start, w_end, w_lines))
        t += step
        if w_end >= video_duration:
            break

    total = len(windows)
    print(f"  {total} pencere analiz edilecek...")

    all_clips: list[dict] = []
    for i, (w_start, w_end, w_lines) in enumerate(windows, 1):
        print(f"  Pencere {i}/{total}: {seconds_to_stamp(w_start)} - {seconds_to_stamp(w_end)}")
        prompt_text = transcript_for_prompt(w_lines, max_transcript_chars)
        try:
            clips = ask_gpt_for_clips(
                client, model, prompt_text, video_duration,
                clip_seconds, energy_hints, num_clips=1,
            )
            all_clips.extend(clips)
        except Exception as exc:
            print(f"  Pencere {i} hata: {exc}")

    if not all_clips:
        raise RuntimeError("Hicbir pencere icin GPT sonucu alinamadi.")

    all_clips.sort(key=lambda c: c.get("score", 0), reverse=True)
    return all_clips[:num_clips]


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


def words_for_clip(words: list[dict], start: float, end: float) -> list[dict]:
    clip_words = []
    for w in words:
        ws = float(w.get("start", 0))
        we = float(w.get("end", ws))
        if we > start and ws < end:
            clip_words.append({
                "word": w.get("word", ""),
                "start": max(ws - start, 0),
                "end": min(we - start, end - start),
            })
    return clip_words


def group_words_into_phrases(words: list[dict], max_words: int = 3, max_gap: float = 0.7) -> list[dict]:
    phrases = []
    current: list[dict] = []

    for w in words:
        text = str(w.get("word", "")).strip()
        if not text:
            continue

        if current and (
            len(current) >= max_words
            or w["start"] - current[-1]["end"] > max_gap
        ):
            phrases.append({
                "start": current[0]["start"],
                "end": current[-1]["end"],
                "text": " ".join(c["word"].strip() for c in current),
            })
            current = []

        current.append(w)

    if current:
        phrases.append({
            "start": current[0]["start"],
            "end": current[-1]["end"],
            "text": " ".join(c["word"].strip() for c in current),
        })

    return phrases


def _ass_timestamp(seconds: float) -> str:
    seconds = max(0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def generate_ass_subtitles(
    phrases: list[dict],
    style_name: str = "bold",
    video_width: int = 1080,
    video_height: int = 1920,
) -> str:
    style = SUBTITLE_STYLES.get(style_name, SUBTITLE_STYLES["bold"])

    header = f"""[Script Info]
Title: Auto Subtitles
ScriptType: v4.00+
PlayResX: {video_width}
PlayResY: {video_height}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{style['fontname']},{style['fontsize']},{style['primary_color']},&H000000FF,{style['outline_color']},{style['back_color']},{style['bold']},0,0,0,100,100,0,0,1,{style['outline']},{style['shadow']},{style['alignment']},40,40,{style['margin_v']},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    verb_color = style.get("verb_color", "&H0000FFFF")
    primary = style["primary_color"]

    events = []
    for phrase in phrases:
        start_ts = _ass_timestamp(phrase["start"])
        end_ts = _ass_timestamp(phrase["end"])
        words = phrase["text"].split()
        colored_parts = []
        for word in words:
            upper_word = word.upper()
            if is_turkish_verb(word):
                colored_parts.append(f"{{\\c{verb_color}}}{upper_word}{{\\c{primary}}}")
            else:
                colored_parts.append(upper_word)
        text = " ".join(colored_parts).replace("\n", "\\N")
        events.append(f"Dialogue: 0,{start_ts},{end_ts},Default,,0,0,0,,{text}")

    return header + "\n".join(events) + "\n"


def burn_subtitles(input_video: Path, ass_path: Path, output_path: Path) -> None:
    fonts_dir = Path(__file__).resolve().parent / "fonts"
    ass_filter = f"ass={str(ass_path)}"
    if fonts_dir.exists():
        ass_filter += f":fontsdir={str(fonts_dir)}"
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_video),
        "-vf", ass_filter,
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ffmpeg altyazi hatasi: {result.stderr[-500:]}")
        raise RuntimeError("Altyazi yakma basarisiz oldu.")


def apply_template(
    input_video: Path,
    output_path: Path,
    start: float,
    end: float,
    caption_text: str = "",
    source_credit: str = "",
    target_width: int = 1080,
    target_height: int = 1920,
) -> None:
    """Blurred-background vertical template: original video centered, blurred fill behind, caption on top, credit at bottom."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fonts_dir = Path(__file__).resolve().parent / "fonts"
    font_file = fonts_dir / "Bangers-Regular.ttf"

    def _dt_escape(text):
        t = text.replace("\\", "\\\\")
        t = t.replace("’", "")
        t = t.replace(":", "\\:")
        t = t.replace("%", "%%")
        t = t.replace("[", "\\[")
        t = t.replace("]", "\\]")
        return t

    safe_caption = _dt_escape(caption_text) if caption_text else ""
    safe_credit = _dt_escape(source_credit) if source_credit else ""

    fontfile_opt = ""
    if font_file.exists():
        escaped_path = str(font_file).replace(":", "\\:")
        fontfile_opt = "fontfile='" + escaped_path + "':"

    vf_parts = []

    # Trim the video segment and split into 3 copies (bg, fg, reserve)
    vf_parts.append(
        f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS,"
        f"split=2[bg_src][fg_src]"
    )

    # Background: scale to fill frame, crop center, blur + darken
    vf_parts.append(
        f"[bg_src]scale={target_width}:{target_height}:"
        f"force_original_aspect_ratio=increase,"
        f"crop={target_width}:{target_height},"
        f"gblur=sigma=40,eq=brightness=-0.1[bg]"
    )

    # Foreground: scale to fit inside frame (55% of height for video content)
    content_height = int(target_height * 0.55)
    vf_parts.append(
        f"[fg_src]scale={target_width}:{content_height}:"
        f"force_original_aspect_ratio=decrease[fg]"
    )

    # Overlay foreground on blurred background, shifted down for caption space
    caption_area_h = int(target_height * 0.16)
    overlay_y = f"({caption_area_h}+(main_h-{caption_area_h}-overlay_h)/2)"
    vf_parts.append(f"[bg][fg]overlay=(W-w)/2:{overlay_y}[composed]")

    # Add top caption text
    last_label = "[composed]"
    label_idx = 0

    if safe_caption:
        new_label = f"[cap{label_idx}]"
        text_filter = (
            f"{last_label}drawtext={fontfile_opt}"
            f"text='{safe_caption}':"
            f"fontcolor=white:fontsize=48:"
            f"borderw=3:bordercolor=black:"
            f"x=(w-text_w)/2:y={caption_area_h // 2 - 24}:"
            f"line_spacing=8{new_label}"
        )
        vf_parts.append(text_filter)
        last_label = new_label
        label_idx += 1

    # Add bottom credit/source text for copyright protection
    if safe_credit:
        new_label = f"[cap{label_idx}]"
        credit_y = target_height - 80
        credit_filter = (
            f"{last_label}drawtext={fontfile_opt}"
            f"text='{safe_credit}':"
            f"fontcolor=white@0.85:fontsize=32:"
            f"borderw=2:bordercolor=black@0.6:"
            f"x=(w-text_w)/2:y={credit_y}{new_label}"
        )
        vf_parts.append(credit_filter)
        last_label = new_label
        label_idx += 1

    filter_complex = ";".join(vf_parts)

    # Audio: trim with -ss/-t on output (after filter_complex handles video)
    duration = end - start
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_video),
        "-filter_complex", filter_complex,
        "-map", last_label,
        "-map", "0:a?",
        "-ss", str(start),
        "-t", str(duration),
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        "-shortest",
        "-movflags", "+faststart",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ffmpeg template hatasi: {result.stderr[-800:]}")
        raise RuntimeError("Template uygulama basarisiz oldu.")


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
        description="OpenAI Whisper + GPT API ile videodan en iyi dikey klibi keser."
    )
    parser.add_argument("input", help="Kaynak video yolu veya YouTube linki")
    parser.add_argument("-o", "--output", type=Path, default=Path("outputs/clip_vertical.mp4"))
    parser.add_argument("--clip-seconds", type=float, default=DEFAULT_CLIP_SECONDS)
    parser.add_argument("--language", default="tr", help="Transkripsiyon dili.")
    parser.add_argument("--whisper-model", default="whisper-1")
    parser.add_argument("--gpt-model", default="gpt-4.1-mini")
    parser.add_argument("--target-height", type=int, default=1920)
    parser.add_argument("--max-transcript-chars", type=int, default=100_000)
    parser.add_argument("--cookies", type=Path, default=None)
    parser.add_argument("--num-clips", type=int, default=NUM_CANDIDATES)
    parser.add_argument("--subtitle-style", default="bold", choices=["bold", "highlight", "minimal", "none"])
    parser.add_argument("--template", action="store_true", help="Blurred-background vertical template")
    parser.add_argument("--caption", default="", help="Caption text for template overlay")
    parser.add_argument("--source-credit", default="", help="Source attribution text (copyright protection)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = args.output.resolve()

    if args.clip_seconds <= 0 or not math.isfinite(args.clip_seconds):
        raise ValueError("--clip-seconds pozitif bir sayi olmali.")

    client = OpenAI()

    tmpdir = tempfile.mkdtemp()
    try:
        tmp_path = Path(tmpdir)
        if is_url(args.input):
            if not is_youtube_url(args.input):
                raise ValueError("Su an yalnizca YouTube linkleri destekleniyor.")
            print("STEP:1/6 YouTube videosu indiriliyor...")
            cookies_file = args.cookies or Path(__file__).resolve().parent / "cookies.txt"
            input_path = download_youtube_video(args.input, tmp_path, cookies_file=cookies_file)
        else:
            input_path = Path(args.input).resolve()
            if not input_path.exists():
                raise FileNotFoundError(f"Video bulunamadi: {input_path}")
            print("STEP:1/6 Video hazirlaniyor...")

        with VideoFileClip(str(input_path)) as video:
            video_duration = float(video.duration)

        audio_path = tmp_path / "audio.mp3"
        wav_path = tmp_path / "audio.wav"
        print("STEP:2/6 Ses cikariliyor ve analiz ediliyor...")
        extract_audio(input_path, audio_path)
        extract_audio_wav(input_path, wav_path)

        print("  Ses enerjisi analiz ediliyor...")
        energies = analyze_audio_energy(wav_path, window_seconds=1.0)
        energy_peaks = find_energy_peaks(energies, args.clip_seconds, video_duration, top_n=5)

        energy_hints = ""
        if energy_peaks:
            lines_hint = []
            for i, peak in enumerate(energy_peaks, 1):
                lines_hint.append(
                    f"  #{i} [{seconds_to_stamp(peak['start'])} - {seconds_to_stamp(peak['end'])}] "
                    f"enerji={peak['energy_score']}"
                )
            energy_hints = "En yuksek ses enerjisi olan bolumler:\n" + "\n".join(lines_hint)
            print(energy_hints)

        print("STEP:3/6 Ses metne dokuluyor...")
        transcript_json = transcribe_audio(
            client=client,
            audio_path=audio_path,
            whisper_model=args.whisper_model,
            language=args.language or None,
        )

        words = transcript_json.get("words") or []
        if not words:
            raise RuntimeError("Transkripsiyondan kelime zaman damgasi alinamadi.")

        lines = words_to_timed_lines(words)

        if video_duration > CHUNKED_THRESHOLD_SECONDS:
            print("STEP:4/6 GPT en iyi anlari seciyor (parcali analiz)...")
            candidates = ask_gpt_for_clips_chunked(
                client=client,
                model=args.gpt_model,
                lines=lines,
                video_duration=video_duration,
                clip_seconds=args.clip_seconds,
                max_transcript_chars=args.max_transcript_chars,
                energy_hints=energy_hints,
                num_clips=args.num_clips,
            )
        else:
            print("STEP:4/6 GPT en iyi anlari seciyor...")
            prompt_transcript = transcript_for_prompt(lines, args.max_transcript_chars)
            candidates = ask_gpt_for_clips(
                client=client,
                model=args.gpt_model,
                transcript=prompt_transcript,
                video_duration=video_duration,
                clip_seconds=args.clip_seconds,
                energy_hints=energy_hints,
                num_clips=args.num_clips,
            )

        # Output candidates as JSON for the web app to parse
        print("CANDIDATES_JSON:" + json.dumps(candidates, ensure_ascii=False))

        for i, cand in enumerate(candidates, 1):
            s, e = clamp_clip(cand, video_duration, args.clip_seconds)
            print(
                f"  Aday #{i}: {seconds_to_stamp(s)} - {seconds_to_stamp(e)} "
                f"(puan: {cand.get('score')}/10, tur: {cand.get('viral_type', '?')})"
            )
            print(f"    Baslik: {cand.get('title', '')}")
            print(f"    Gerekce: {cand.get('reason', '')}")

        if not candidates:
            raise RuntimeError("GPT hicbir klip adayi dondurmedi.")

        # Cut all candidates
        print("STEP:5/6 Klip adaylari kesiliyor...")
        use_subs = args.subtitle_style != "none"
        use_template = args.template
        caption = args.caption.strip()
        source_credit = args.source_credit.strip()

        for i, cand in enumerate(candidates):
            start, end = clamp_clip(cand, video_duration, args.clip_seconds)
            if i == 0:
                out = output_path
            else:
                out = output_path.parent / f"{output_path.stem}_aday{i+1}{output_path.suffix}"

            print(f"  Aday #{i+1} kesiliyor: {seconds_to_stamp(start)} - {seconds_to_stamp(end)}")

            target_w = int(args.target_height * DEFAULT_ASPECT_RATIO)

            if use_template:
                # Template mode: blurred background + centered video + caption + credit
                cand_caption = caption or cand.get("title", "")
                cand_credit = source_credit
                if not cand_credit and is_youtube_url(args.input):
                    cand_credit = f"Kaynak: {args.input.split('&')[0]}"
                raw_out = out.parent / f"{out.stem}_tmpl{out.suffix}"
                apply_template(
                    input_video=input_path,
                    output_path=raw_out,
                    start=start,
                    end=end,
                    caption_text=cand_caption,
                    source_credit=cand_credit,
                    target_width=target_w,
                    target_height=args.target_height,
                )

                if use_subs:
                    clip_words = words_for_clip(words, start, end)
                    phrases = group_words_into_phrases(clip_words, max_words=3)
                    if phrases:
                        ass_content = generate_ass_subtitles(
                            phrases, args.subtitle_style, target_w, args.target_height
                        )
                        ass_path = tmp_path / f"subs_{i}.ass"
                        ass_path.write_text(ass_content, encoding="utf-8")
                        print(f"  Aday #{i+1} altyazi yakilyor ({len(phrases)} grup)...")
                        burn_subtitles(raw_out, ass_path, out)
                        raw_out.unlink(missing_ok=True)
                    else:
                        raw_out.rename(out)
                else:
                    raw_out.rename(out)

            elif use_subs:
                raw_out = out.parent / f"{out.stem}_nosub{out.suffix}"
                cut_vertical_video(input_path, raw_out, start, end, args.target_height)

                clip_words = words_for_clip(words, start, end)
                phrases = group_words_into_phrases(clip_words, max_words=3)

                if phrases:
                    ass_content = generate_ass_subtitles(
                        phrases, args.subtitle_style, target_w, args.target_height
                    )
                    ass_path = tmp_path / f"subs_{i}.ass"
                    ass_path.write_text(ass_content, encoding="utf-8")

                    print(f"  Aday #{i+1} altyazi yakilyor ({len(phrases)} grup)...")
                    burn_subtitles(raw_out, ass_path, out)
                    raw_out.unlink(missing_ok=True)
                else:
                    raw_out.rename(out)
            else:
                cut_vertical_video(input_path, out, start, end, args.target_height)

        print("STEP:6/6 Tamamlandi!")
        print(f"Bitti: {output_path}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    main()
