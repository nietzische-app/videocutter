"""YouTube Shorts yayin metadata uretimi."""

from __future__ import annotations

import json
import os
from pathlib import Path

from openai import OpenAI

from categories import get_category

DEFAULT_GPT_MODEL = os.getenv("GPT_MODEL", "gpt-4o-mini")

METADATA_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "youtube_title": {"type": "string"},
        "hook_line": {"type": "string"},
        "description": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["youtube_title", "hook_line", "description", "hashtags"],
}


def _build_description(
    hook: str,
    source_channel: str,
    source_url: str,
    hashtags: list[str],
    category_hashtags: list[str],
) -> str:
    via_line = f"via {source_channel}" if source_channel else "via original creator"
    tag_line = " ".join(dict.fromkeys(hashtags + category_hashtags))

    parts = [
        hook.strip(),
        "",
        f"Original: {source_url}" if source_url else "",
        via_line,
        "",
        tag_line,
    ]
    return "\n".join(part for part in parts if part)


def generate_metadata_chat(
    client: OpenAI,
    model: str,
    *,
    category_id: str,
    clip_title: str,
    source_channel: str,
    source_url: str,
    reason: str = "",
) -> dict:
    category = get_category(category_id)
    prompt = (
        f"Kategori: {category['name']}\n"
        f"Klip basligi: {clip_title}\n"
        f"Kaynak kanal: {source_channel}\n"
        f"Kaynak URL: {source_url}\n"
        f"Secim gerekcesi: {reason}\n\n"
        "YouTube Shorts icin cekici bir baslik, kisa aciklama ve hashtag listesi uret. "
        "Baslik max 80 karakter. Aciklama'da telif icin kaynak atfi yapma (biz ekleyecegiz). "
        "Hashtagler # ile baslasin."
    )

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": "Sen viral YouTube Shorts icerik editorusun. JSON formatinda yanit ver.",
            },
            {"role": "user", "content": prompt},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "shorts_metadata",
                "strict": True,
                "schema": METADATA_SCHEMA,
            },
        },
    )
    data = json.loads(response.choices[0].message.content)

    full_description = _build_description(
        hook=data.get("description") or data.get("hook_line", ""),
        source_channel=source_channel,
        source_url=source_url,
        hashtags=data.get("hashtags", []),
        category_hashtags=category["hashtags"],
    )

    return {
        "youtube_title": data["youtube_title"][:100],
        "hook_line": data.get("hook_line", ""),
        "description": full_description,
        "hashtags": data.get("hashtags", []) + category["hashtags"],
        "category": category_id,
        "category_name": category["name"],
        "source_url": source_url,
        "source_channel": source_channel,
        "template_title": clip_title,
        "via_credit": f"via {source_channel}" if source_channel else "via original",
    }


def generate_metadata(
    client: OpenAI,
    *,
    category_id: str,
    clip_title: str,
    source_channel: str,
    source_url: str,
    reason: str = "",
    model: str | None = None,
) -> dict:
    model = model or DEFAULT_GPT_MODEL
    try:
        return generate_metadata_chat(
            client,
            model,
            category_id=category_id,
            clip_title=clip_title,
            source_channel=source_channel,
            source_url=source_url,
            reason=reason,
        )
    except Exception:
        category = get_category(category_id)
        return {
            "youtube_title": clip_title[:80],
            "hook_line": clip_title,
            "description": _build_description(
                clip_title,
                source_channel,
                source_url,
                [],
                category["hashtags"],
            ),
            "hashtags": category["hashtags"],
            "category": category_id,
            "category_name": category["name"],
            "source_url": source_url,
            "source_channel": source_channel,
            "template_title": clip_title,
            "via_credit": f"via {source_channel}" if source_channel else "via original",
        }


def save_metadata(metadata: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
