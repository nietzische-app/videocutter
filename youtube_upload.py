"""YouTube'a Shorts yukleme (OAuth ile)."""

from __future__ import annotations

import json
import os
from pathlib import Path

TOKEN_PATH = Path(os.getenv("YOUTUBE_TOKEN_PATH", "youtube_token.json"))
CLIENT_SECRETS = Path(os.getenv("YOUTUBE_CLIENT_SECRETS", "client_secrets.json"))
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def is_configured() -> bool:
    return CLIENT_SECRETS.exists() and TOKEN_PATH.exists()


def get_credentials():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:
        raise RuntimeError(
            "YouTube yukleme icin: python -m pip install google-api-python-client google-auth-oauthlib"
        ) from exc

    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CLIENT_SECRETS.exists():
                raise RuntimeError(
                    f"Google OAuth dosyasi bulunamadi: {CLIENT_SECRETS}. "
                    "Google Cloud Console'dan OAuth client indirin."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRETS), SCOPES)
            creds = flow.run_local_server(port=8090)

        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")

    return creds


def upload_short(
    video_path: Path,
    *,
    title: str,
    description: str,
    tags: list[str] | None = None,
    privacy: str = "private",
) -> dict:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    creds = get_credentials()
    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": (tags or [])[:30],
            "categoryId": "24",
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(str(video_path), mimetype="video/mp4", resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = request.execute()
    return {
        "video_id": response.get("id"),
        "url": f"https://www.youtube.com/shorts/{response.get('id')}",
    }


def load_metadata(metadata_path: Path) -> dict:
    return json.loads(metadata_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="YouTube OAuth ve Shorts yukleme")
    parser.add_argument("--auth", action="store_true", help="OAuth ile giris yap")
    parser.add_argument("--video", type=Path, help="Yuklenecek video")
    parser.add_argument("--metadata", type=Path, help="metadata.json dosyasi")
    parser.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"])
    args = parser.parse_args()

    if args.auth:
        get_credentials()
        print(f"Token kaydedildi: {TOKEN_PATH}")
    elif args.video and args.metadata:
        meta = load_metadata(args.metadata)
        result = upload_short(
            args.video,
            title=meta["youtube_title"],
            description=meta["description"],
            tags=[t.lstrip("#") for t in meta.get("hashtags", [])],
            privacy=args.privacy,
        )
        print(json.dumps(result, indent=2))
    else:
        parser.print_help()
