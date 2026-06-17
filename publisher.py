"""Sosyal medya paylasim modulu - YouTube Shorts + TikTok API entegrasyonu.

YouTube: OAuth2 flow ile token alma, resumable upload
TikTok: OAuth2 flow ile token alma, Content Posting API
Instagram: Manuel (kullanici kendisi yukler)
"""

import json
import os
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
PUBLISH_LOG = PROJECT_DIR / "publish_log.json"
PUBLISH_CONFIG = PROJECT_DIR / "publish_config.json"
TOKENS_FILE = PROJECT_DIR / "tokens.json"


# ── Config ───────────────────────────────────────────────────────────


def _default_publish_config():
    return {
        "youtube": {
            "enabled": False,
            "client_id": "",
            "client_secret": "",
            "default_tags": ["shorts", "viral", "trending"],
            "default_visibility": "public",
            "description_template": "{title}\n\n#shorts #viral #trending",
        },
        "tiktok": {
            "enabled": False,
            "client_key": "",
            "client_secret": "",
            "description_template": "{title} #fyp #viral #trending",
        },
    }


def load_publish_config():
    if PUBLISH_CONFIG.exists():
        try:
            cfg = json.loads(PUBLISH_CONFIG.read_text(encoding="utf-8"))
            merged = _default_publish_config()
            for k in merged:
                if k in cfg and isinstance(cfg[k], dict):
                    merged[k].update(cfg[k])
            return merged
        except Exception:
            pass
    return _default_publish_config()


def save_publish_config(config):
    PUBLISH_CONFIG.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Token Storage ────────────────────────────────────────────────────


def _load_tokens():
    if TOKENS_FILE.exists():
        try:
            return json.loads(TOKENS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_tokens(tokens):
    TOKENS_FILE.write_text(json.dumps(tokens, ensure_ascii=False, indent=2), encoding="utf-8")


def get_token(platform, account_id="default"):
    tokens = _load_tokens()
    return tokens.get(f"{platform}_{account_id}", {})


def save_token(platform, token_data, account_id="default"):
    tokens = _load_tokens()
    token_data["saved_at"] = _now_str()
    tokens[f"{platform}_{account_id}"] = token_data
    _save_tokens(tokens)


def get_all_tokens():
    tokens = _load_tokens()
    result = {}
    for key, val in tokens.items():
        safe = dict(val)
        if "access_token" in safe:
            t = safe["access_token"]
            safe["access_token"] = t[:8] + "..." + t[-4:] if len(t) > 16 else "***"
        if "refresh_token" in safe:
            safe["refresh_token"] = "***"
        if "client_secret" in safe:
            safe["client_secret"] = "***"
        result[key] = safe
    return result


def remove_token(platform, account_id="default"):
    tokens = _load_tokens()
    key = f"{platform}_{account_id}"
    if key in tokens:
        del tokens[key]
        _save_tokens(tokens)
        return True
    return False


# ── Publish Log ──────────────────────────────────────────────────────


def _load_publish_log():
    if PUBLISH_LOG.exists():
        try:
            return json.loads(PUBLISH_LOG.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _append_publish_log(entry):
    log = _load_publish_log()
    log.append(entry)
    log = log[-500:]
    PUBLISH_LOG.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")


def get_publish_log(limit=50):
    return _load_publish_log()[-limit:]


def _now_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


# ── YouTube OAuth2 ───────────────────────────────────────────────────

YT_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
YT_TOKEN_URL = "https://oauth2.googleapis.com/token"
YT_SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube"


def youtube_get_auth_url(client_id, redirect_uri, account_id="default"):
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": YT_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": f"youtube_{account_id}",
    }
    return f"{YT_AUTH_URL}?{urllib.parse.urlencode(params)}"


def youtube_exchange_code(code, client_id, client_secret, redirect_uri, account_id="default"):
    data = urllib.parse.urlencode({
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }).encode("utf-8")

    req = urllib.request.Request(YT_TOKEN_URL, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    with urllib.request.urlopen(req, timeout=15) as resp:
        token_data = json.loads(resp.read().decode("utf-8"))

    token_data["platform"] = "youtube"
    token_data["account_id"] = account_id
    token_data["client_id"] = client_id
    token_data["client_secret"] = client_secret
    token_data["obtained_at"] = time.time()
    save_token("youtube", token_data, account_id)
    return token_data


def youtube_refresh_token(account_id="default"):
    token = get_token("youtube", account_id)
    refresh = token.get("refresh_token")
    client_id = token.get("client_id") or load_publish_config().get("youtube", {}).get("client_id", "")
    client_secret = token.get("client_secret") or load_publish_config().get("youtube", {}).get("client_secret", "")

    if not refresh or not client_id or not client_secret:
        raise ValueError("Refresh token veya client credentials eksik.")

    data = urllib.parse.urlencode({
        "refresh_token": refresh,
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
    }).encode("utf-8")

    req = urllib.request.Request(YT_TOKEN_URL, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    with urllib.request.urlopen(req, timeout=15) as resp:
        new_data = json.loads(resp.read().decode("utf-8"))

    token["access_token"] = new_data["access_token"]
    token["obtained_at"] = time.time()
    if "expires_in" in new_data:
        token["expires_in"] = new_data["expires_in"]
    save_token("youtube", token, account_id)
    return token


def _youtube_get_valid_token(account_id="default"):
    token = get_token("youtube", account_id)
    access = token.get("access_token")
    if not access:
        raise ValueError(f"YouTube hesabi '{account_id}' icin token yok. Once OAuth2 ile baglanin.")

    obtained = token.get("obtained_at", 0)
    expires_in = token.get("expires_in", 3600)
    if time.time() - obtained > expires_in - 120:
        token = youtube_refresh_token(account_id)
        access = token["access_token"]

    return access


def upload_to_youtube(video_path, title, description="", tags=None, visibility="public", account_id="default"):
    access_token = _youtube_get_valid_token(account_id)

    if not Path(video_path).exists():
        return {"status": "error", "error": f"Video bulunamadi: {video_path}"}

    tags = tags or ["shorts", "viral"]
    title = title[:100]

    metadata = {
        "snippet": {
            "title": title,
            "description": description[:5000],
            "tags": tags[:30],
            "categoryId": "22",
        },
        "status": {
            "privacyStatus": visibility,
            "selfDeclaredMadeForKids": False,
            "embeddable": True,
        },
    }

    init_url = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status"
    meta_bytes = json.dumps(metadata).encode("utf-8")
    req = urllib.request.Request(init_url, data=meta_bytes, method="POST")
    req.add_header("Authorization", f"Bearer {access_token}")
    req.add_header("Content-Type", "application/json; charset=UTF-8")
    req.add_header("X-Upload-Content-Type", "video/mp4")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            upload_url = resp.headers.get("Location")
            if not upload_url:
                return {"status": "error", "error": "Upload URL alinamadi."}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return {"status": "error", "error": f"YouTube init hatasi ({e.code}): {body[:300]}"}
    except Exception as e:
        return {"status": "error", "error": f"YouTube init hatasi: {e}"}

    file_size = Path(video_path).stat().st_size
    with open(video_path, "rb") as f:
        file_data = f.read()

    upload_req = urllib.request.Request(upload_url, data=file_data, method="PUT")
    upload_req.add_header("Content-Type", "video/mp4")
    upload_req.add_header("Content-Length", str(file_size))

    try:
        with urllib.request.urlopen(upload_req, timeout=600) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            video_id = result.get("id", "")
            log_entry = {
                "time": _now_str(),
                "platform": "youtube",
                "account": account_id,
                "status": "done",
                "video_id": video_id,
                "title": title,
                "url": f"https://youtube.com/shorts/{video_id}",
            }
            _append_publish_log(log_entry)
            return log_entry
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        entry = {"time": _now_str(), "platform": "youtube", "account": account_id,
                 "status": "error", "error": f"Upload hatasi ({e.code}): {body[:300]}", "title": title}
        _append_publish_log(entry)
        return entry
    except Exception as e:
        entry = {"time": _now_str(), "platform": "youtube", "account": account_id,
                 "status": "error", "error": str(e), "title": title}
        _append_publish_log(entry)
        return entry


# ── TikTok OAuth2 ────────────────────────────────────────────────────

TT_AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TT_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"


def tiktok_get_auth_url(client_key, redirect_uri, account_id="default"):
    params = {
        "client_key": client_key,
        "response_type": "code",
        "scope": "video.publish,video.upload",
        "redirect_uri": redirect_uri,
        "state": f"tiktok_{account_id}",
    }
    return f"{TT_AUTH_URL}?{urllib.parse.urlencode(params)}"


def tiktok_exchange_code(code, client_key, client_secret, redirect_uri, account_id="default"):
    data = json.dumps({
        "client_key": client_key,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }).encode("utf-8")

    req = urllib.request.Request(TT_TOKEN_URL, data=data, method="POST")
    req.add_header("Content-Type", "application/json")

    with urllib.request.urlopen(req, timeout=15) as resp:
        token_data = json.loads(resp.read().decode("utf-8"))

    if "data" in token_data:
        token_data = token_data["data"]

    token_data["platform"] = "tiktok"
    token_data["account_id"] = account_id
    token_data["client_key"] = client_key
    token_data["client_secret"] = client_secret
    token_data["obtained_at"] = time.time()
    save_token("tiktok", token_data, account_id)
    return token_data


def tiktok_refresh_token(account_id="default"):
    token = get_token("tiktok", account_id)
    refresh = token.get("refresh_token")
    client_key = token.get("client_key") or load_publish_config().get("tiktok", {}).get("client_key", "")
    client_secret = token.get("client_secret") or load_publish_config().get("tiktok", {}).get("client_secret", "")

    if not refresh or not client_key or not client_secret:
        raise ValueError("TikTok refresh token veya client credentials eksik.")

    data = json.dumps({
        "client_key": client_key,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh,
    }).encode("utf-8")

    req = urllib.request.Request(TT_TOKEN_URL, data=data, method="POST")
    req.add_header("Content-Type", "application/json")

    with urllib.request.urlopen(req, timeout=15) as resp:
        new_data = json.loads(resp.read().decode("utf-8"))

    if "data" in new_data:
        new_data = new_data["data"]

    token["access_token"] = new_data.get("access_token", token.get("access_token"))
    if "refresh_token" in new_data:
        token["refresh_token"] = new_data["refresh_token"]
    token["obtained_at"] = time.time()
    if "expires_in" in new_data:
        token["expires_in"] = new_data["expires_in"]
    save_token("tiktok", token, account_id)
    return token


def _tiktok_get_valid_token(account_id="default"):
    token = get_token("tiktok", account_id)
    access = token.get("access_token")
    if not access:
        raise ValueError(f"TikTok hesabi '{account_id}' icin token yok. Once OAuth2 ile baglanin.")

    obtained = token.get("obtained_at", 0)
    expires_in = token.get("expires_in", 86400)
    if time.time() - obtained > expires_in - 300:
        token = tiktok_refresh_token(account_id)
        access = token["access_token"]

    return access


def upload_to_tiktok(video_path, description="", account_id="default"):
    access_token = _tiktok_get_valid_token(account_id)

    if not Path(video_path).exists():
        return {"status": "error", "error": f"Video bulunamadi: {video_path}"}

    description = description[:2200]
    file_size = Path(video_path).stat().st_size

    # Step 1: Init upload
    init_url = "https://open.tiktokapis.com/v2/post/publish/video/init/"
    init_body = json.dumps({
        "post_info": {
            "title": description[:150],
            "privacy_level": "PUBLIC_TO_EVERYONE",
            "disable_duet": False,
            "disable_stitch": False,
            "disable_comment": False,
        },
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": file_size,
        },
    }).encode("utf-8")

    req = urllib.request.Request(init_url, data=init_body, method="POST")
    req.add_header("Authorization", f"Bearer {access_token}")
    req.add_header("Content-Type", "application/json; charset=UTF-8")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))

        err = result.get("error", {})
        if err.get("code") not in ("ok", None, ""):
            return {"status": "error", "error": f"TikTok init: {err.get('message', err)}"}

        upload_url = result.get("data", {}).get("upload_url", "")
        publish_id = result.get("data", {}).get("publish_id", "")
        if not upload_url:
            return {"status": "error", "error": "TikTok upload URL alinamadi."}

    except Exception as e:
        return {"status": "error", "error": f"TikTok init hatasi: {e}"}

    # Step 2: Upload
    with open(video_path, "rb") as f:
        file_data = f.read()

    upload_req = urllib.request.Request(upload_url, data=file_data, method="PUT")
    upload_req.add_header("Content-Range", f"bytes 0-{file_size - 1}/{file_size}")
    upload_req.add_header("Content-Type", "video/mp4")

    try:
        with urllib.request.urlopen(upload_req, timeout=600) as resp:
            log_entry = {
                "time": _now_str(),
                "platform": "tiktok",
                "account": account_id,
                "status": "done",
                "publish_id": publish_id,
                "description": description[:100],
            }
            _append_publish_log(log_entry)
            return log_entry
    except Exception as e:
        entry = {"time": _now_str(), "platform": "tiktok", "account": account_id,
                 "status": "error", "error": str(e)}
        _append_publish_log(entry)
        return entry


# ── Multi-platform publish ───────────────────────────────────────────


def publish_video(video_path, title, platforms=None, config=None, account_id="default"):
    config = config or load_publish_config()
    platforms = platforms or ["youtube", "tiktok"]

    results = []
    for platform in platforms:
        pcfg = config.get(platform, {})
        if not pcfg.get("enabled"):
            results.append({"platform": platform, "status": "skipped", "reason": "disabled"})
            continue

        try:
            if platform == "youtube":
                desc_template = pcfg.get("description_template", "{title}")
                description = desc_template.replace("{title}", title)
                tags = pcfg.get("default_tags", [])
                visibility = pcfg.get("default_visibility", "public")
                result = upload_to_youtube(video_path, title, description, tags, visibility, account_id)

            elif platform == "tiktok":
                desc_template = pcfg.get("description_template", "{title}")
                description = desc_template.replace("{title}", title)
                result = upload_to_tiktok(video_path, description, account_id)

            else:
                result = {"platform": platform, "status": "skipped", "reason": "desteklenmiyor"}
        except Exception as e:
            result = {"platform": platform, "status": "error", "error": str(e)}

        result["platform"] = platform
        results.append(result)

    return results
