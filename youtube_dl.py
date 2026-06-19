"""YouTube indirme: cookies, PO Token, proxy."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

log = logging.getLogger(__name__)

PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_COOKIES_MAX_AGE_DAYS = 7


def _resolve_path(path_str: str) -> Path:
    path = Path(path_str)
    if not path.is_absolute():
        path = PROJECT_DIR / path
    return path.resolve()


def get_cookies_path() -> Path | None:
    raw = os.getenv("YOUTUBE_COOKIES", "cookies.txt").strip()
    if not raw or raw.lower() in {"none", "false", "0"}:
        return None
    return _resolve_path(raw)


def check_cookies_health() -> dict:
    """Cookie dosyasi durumunu kontrol eder."""
    cookies_path = get_cookies_path()
    max_age_days = int(os.getenv("COOKIES_MAX_AGE_DAYS", DEFAULT_COOKIES_MAX_AGE_DAYS))

    if not cookies_path:
        return {
            "configured": False,
            "path": None,
            "exists": False,
            "stale": True,
            "message": "YOUTUBE_COOKIES ayarlanmamis.",
        }

    if not cookies_path.exists():
        return {
            "configured": True,
            "path": str(cookies_path),
            "exists": False,
            "stale": True,
            "message": f"Cookie dosyasi bulunamadi: {cookies_path}",
        }

    age_seconds = time.time() - cookies_path.stat().st_mtime
    age_days = age_seconds / 86400
    stale = age_days > max_age_days

    message = "Cookie dosyasi guncel."
    if stale:
        message = (
            f"Cookie dosyasi {age_days:.0f} gunluk (limit {max_age_days}). "
            "scripts/sync-cookies ile yenileyin."
        )

    return {
        "configured": True,
        "path": str(cookies_path),
        "exists": True,
        "age_days": round(age_days, 1),
        "max_age_days": max_age_days,
        "stale": stale,
        "message": message,
    }


def warn_cookies_if_needed() -> None:
    health = check_cookies_health()
    if health.get("stale"):
        log.warning("YouTube cookies: %s", health.get("message"))


def build_ytdlp_options(
    *,
    output_template: str | None = None,
    quiet: bool = False,
    extract_flat: bool = False,
) -> dict:
    """yt-dlp seceneklerini cookies + PO Token + proxy ile olusturur."""
    options: dict = {
        "quiet": quiet,
        "no_warnings": quiet,
        "noplaylist": True,
    }

    if output_template:
        options["outtmpl"] = output_template
        options["format"] = "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best"
        options["merge_output_format"] = "mp4"

    if extract_flat:
        options["extract_flat"] = True
        options["skip_download"] = True

    cookies_path = get_cookies_path()
    if cookies_path and cookies_path.exists():
        options["cookiefile"] = str(cookies_path)
        warn_cookies_if_needed()
    elif cookies_path:
        log.warning("Cookie dosyasi yok: %s — bot hatasi alabilirsiniz.", cookies_path)

    proxy = os.getenv("YTDLP_PROXY", "").strip()
    if proxy:
        options["proxy"] = proxy

    pot_url = os.getenv("BGUTIL_POT_URL", "").strip()
    if pot_url:
        options.setdefault("extractor_args", {})
        options["extractor_args"]["youtubepot-bgutilhttp"] = {"base_url": pot_url.rstrip("/")}
        log.info("PO Token provider: %s", pot_url)

    # Daha az bot algilamasi icin istemci sirasi
    options.setdefault("extractor_args", {})
    youtube_args = options["extractor_args"].setdefault("youtube", {})
    if "player_client" not in youtube_args:
        youtube_args["player_client"] = ["mweb", "web", "android"]

    return options


def download_youtube_video(url: str, output_dir: Path) -> Path:
    try:
        from yt_dlp import YoutubeDL
    except ImportError as exc:
        raise RuntimeError(
            "YouTube linki kullanmak icin yt-dlp gerekli. Kurulum: python -m pip install yt-dlp"
        ) from exc

    output_template = str(output_dir / "youtube_source.%(ext)s")
    options = build_ytdlp_options(output_template=output_template, quiet=False)

    try:
        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
            downloaded = Path(ydl.prepare_filename(info))
            merged = downloaded.with_suffix(".mp4")
            if merged.exists():
                return merged
            if downloaded.exists():
                return downloaded
    except Exception as exc:
        hint = ""
        if "bot" in str(exc).lower() or "cookies" in str(exc).lower():
            hint = (
                " Cozum: cookies.txt yenileyin (scripts/sync-cookies) ve "
                "BGUTIL_POT_URL ile PO Token provider calistirin."
            )
        raise RuntimeError(f"YouTube indirme hatasi: {exc}.{hint}") from exc

    candidates = sorted(output_dir.glob("youtube_source.*"))
    if not candidates:
        raise RuntimeError("YouTube videosu indirildi gibi gorunuyor ama dosya bulunamadi.")
    return candidates[0]
