#!/usr/bin/env python3
"""Shorts fabrikasi: kesif, klip, sablon, metadata."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

from categories import get_category  # noqa: E402
from metadata import generate_metadata, save_metadata  # noqa: E402
from template import apply_shorts_template  # noqa: E402
from video_cutter import (  # noqa: E402
    DEFAULT_CLIP_SECONDS,
    DEFAULT_GPT_MODEL,
    ask_gpt_for_clip,
    check_ffmpeg,
    clamp_clip,
    cut_vertical_video,
    download_youtube_video,
    extract_audio,
    is_url,
    is_youtube_url,
    prepare_audio_for_whisper,
    seconds_to_stamp,
    transcribe_audio,
    transcript_for_prompt,
    words_to_timed_lines,
)

try:
    from moviepy import VideoFileClip
except ImportError:
    from moviepy.editor import VideoFileClip


def fetch_source_info(url: str) -> dict:
    from yt_dlp import YoutubeDL

    with YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True}) as ydl:
        info = ydl.extract_info(url, download=False)

    return {
        "title": info.get("title") or "Viral Clip",
        "channel": info.get("channel") or info.get("uploader") or "unknown",
        "url": info.get("webpage_url") or url,
    }


def run_pipeline(
    video_input: str,
    output_path: Path,
    *,
    category_id: str = "comedy",
    clip_seconds: float = DEFAULT_CLIP_SECONDS,
    whisper_model: str = "whisper-1",
    gpt_model: str = DEFAULT_GPT_MODEL,
    language: str | None = "tr",
    title_override: str | None = None,
    source_channel: str | None = None,
    source_url: str | None = None,
    skip_template: bool = False,
    skip_metadata: bool = False,
    target_height: int = 1600,
) -> dict:
    check_ffmpeg()
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY ayarlanmamis.")

    get_category(category_id)
    client = OpenAI()
    output_path = output_path.resolve()
    raw_path = output_path.with_name(output_path.stem + "_raw.mp4")
    metadata_path = output_path.with_suffix(".json")

    source_info = {"title": title_override or "Viral Clip", "channel": source_channel or "", "url": source_url or video_input}
    if is_url(video_input) and is_youtube_url(video_input):
        try:
            source_info = fetch_source_info(video_input)
        except Exception as exc:
            print(f"Kaynak bilgisi alinamadi: {exc}", file=sys.stderr)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        if is_url(video_input):
            if not is_youtube_url(video_input):
                raise ValueError("Yalnizca YouTube linkleri destekleniyor.")
            print("1/5 YouTube videosu indiriliyor...")
            input_path = download_youtube_video(video_input, tmp_path)
        else:
            input_path = Path(video_input).resolve()
            if not input_path.exists():
                raise FileNotFoundError(f"Video bulunamadi: {input_path}")

        with VideoFileClip(str(input_path)) as video:
            video_duration = float(video.duration)

        audio_path = tmp_path / "audio.mp3"
        print("2/5 Ses cikariliyor...")
        extract_audio(input_path, audio_path)
        audio_path = prepare_audio_for_whisper(audio_path)

        print("3/5 Transkript ve klip secimi...")
        transcript_json = transcribe_audio(client, audio_path, whisper_model, language)
        words = transcript_json.get("words") or []
        if not words:
            raise RuntimeError("Kelime zaman damgasi alinamadi.")

        lines = words_to_timed_lines(words)
        prompt_transcript = transcript_for_prompt(lines, 100_000)
        selection = ask_gpt_for_clip(
            client, gpt_model, prompt_transcript, video_duration, clip_seconds
        )
        start, end = clamp_clip(selection, video_duration, clip_seconds)
        clip_title = title_override or selection.get("title") or source_info["title"]

        print(
            "Secilen:",
            f"{seconds_to_stamp(start)} - {seconds_to_stamp(end)}",
            f"| {clip_title}",
        )

        print("4/5 Dikey klip kesiliyor...")
        cut_vertical_video(input_path, raw_path, start, end, target_height)

        channel = source_channel or source_info["channel"]
        url = source_url or source_info["url"]

        if skip_template:
            final_path = output_path
            raw_path.rename(final_path)
        else:
            print("5/5 Sablon uygulaniyor...")
            apply_shorts_template(
                raw_path,
                output_path,
                title=clip_title[:80],
                via_credit=f"via {channel}" if channel else "via original",
            )
            raw_path.unlink(missing_ok=True)
            final_path = output_path

    result: dict = {
        "output": str(final_path),
        "clip_title": clip_title,
        "source_channel": channel,
        "source_url": url,
        "category": category_id,
        "start": start,
        "end": end,
        "score": selection.get("score"),
        "reason": selection.get("reason", ""),
    }

    if not skip_metadata:
        print("Metadata uretiliyor...")
        meta = generate_metadata(
            client,
            category_id=category_id,
            clip_title=clip_title,
            source_channel=channel,
            source_url=url,
            reason=selection.get("reason", ""),
            model=gpt_model,
        )
        save_metadata(meta, metadata_path)
        result["metadata"] = meta
        result["metadata_path"] = str(metadata_path)

    print(f"Bitti: {final_path}")
    print(json.dumps({k: v for k, v in result.items() if k != "metadata"}, ensure_ascii=False))
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Shorts fabrikasi pipeline")
    parser.add_argument("input", help="YouTube linki veya video yolu")
    parser.add_argument("-o", "--output", type=Path, default=Path("outputs/short.mp4"))
    parser.add_argument("--category", default="comedy", choices=list(__import__("categories").CATEGORIES.keys()))
    parser.add_argument("--clip-seconds", type=float, default=DEFAULT_CLIP_SECONDS)
    parser.add_argument("--language", default=os.getenv("WHISPER_LANGUAGE", "tr"))
    parser.add_argument("--whisper-model", default=os.getenv("WHISPER_MODEL", "whisper-1"))
    parser.add_argument("--gpt-model", default=DEFAULT_GPT_MODEL)
    parser.add_argument("--title", default=None, help="Sablon basligi (opsiyonel)")
    parser.add_argument("--source-channel", default=None)
    parser.add_argument("--source-url", default=None)
    parser.add_argument("--skip-template", action="store_true")
    parser.add_argument("--skip-metadata", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_pipeline(
        args.input,
        args.output,
        category_id=args.category,
        clip_seconds=args.clip_seconds,
        whisper_model=args.whisper_model,
        gpt_model=args.gpt_model,
        language=args.language or None,
        title_override=args.title,
        source_channel=args.source_channel,
        source_url=args.source_url,
        skip_template=args.skip_template,
        skip_metadata=args.skip_metadata,
    )


if __name__ == "__main__":
    main()
