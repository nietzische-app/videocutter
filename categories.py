"""Shorts kanal kategorileri ve arama sorgulari."""

CATEGORIES: dict[str, dict] = {
    "comedy": {
        "name": "Komedi",
        "emoji": "😂",
        "search_queries": [
            "funny viral moments shorts",
            "best comedy clips viral 2024",
            "hilarious moments compilation shorts",
        ],
        "hashtags": ["#comedy", "#funny", "#viral", "#shorts", "#fyp"],
    },
    "film": {
        "name": "Film Sahneleri",
        "emoji": "🎬",
        "search_queries": [
            "iconic movie scenes viral",
            "best movie moments shorts",
            "legendary film scenes clip",
        ],
        "hashtags": ["#movie", "#film", "#cinema", "#shorts", "#viral"],
    },
    "football": {
        "name": "Futbol Editleri",
        "emoji": "⚽",
        "search_queries": [
            "football skills viral shorts",
            "best soccer goals edit shorts",
            "football moments viral",
        ],
        "hashtags": ["#football", "#soccer", "#skills", "#shorts", "#viral"],
    },
    "roblox": {
        "name": "Roblox",
        "emoji": "🎮",
        "search_queries": [
            "roblox funny moments viral",
            "roblox shorts viral",
            "roblox best moments",
        ],
        "hashtags": ["#roblox", "#gaming", "#robloxshorts", "#shorts", "#viral"],
    },
    "foodporn": {
        "name": "Foodporn",
        "emoji": "🍔",
        "search_queries": [
            "satisfying food viral shorts",
            "food porn cooking viral",
            "amazing food shorts",
        ],
        "hashtags": ["#food", "#foodporn", "#cooking", "#shorts", "#viral"],
    },
    "streamer": {
        "name": "Yayinci Klipleri",
        "emoji": "🎙️",
        "search_queries": [
            "streamer funny moments viral",
            "twitch clips viral shorts",
            "best streamer moments",
        ],
        "hashtags": ["#streamer", "#twitch", "#clips", "#shorts", "#viral"],
    },
}


def list_categories() -> list[dict]:
    return [
        {
            "id": cat_id,
            "name": data["name"],
            "emoji": data["emoji"],
            "hashtags": data["hashtags"],
        }
        for cat_id, data in CATEGORIES.items()
    ]


def get_category(category_id: str) -> dict:
    if category_id not in CATEGORIES:
        raise ValueError(f"Gecersiz kategori: {category_id}")
    return CATEGORIES[category_id]
