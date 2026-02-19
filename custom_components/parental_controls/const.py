"""Constants for the Parental Controls integration."""

from __future__ import annotations

DOMAIN = "parental_controls"

# Platforms
PLATFORMS = ["sensor", "switch", "binary_sensor", "number", "select"]

# Config keys
CONF_MONITORED_PLAYERS = "monitored_players"
CONF_BLOCKED_APPS = "blocked_apps"
CONF_ALLOWED_APPS = "allowed_apps"
CONF_BLOCKED_KEYWORDS = "blocked_keywords"
CONF_CONTENT_RATING_MAX = "content_rating_max"
CONF_MUSIC_RATING_MAX = "music_rating_max"
CONF_YOUTUBE_DAILY_LIMIT = "youtube_daily_limit"
CONF_MEDIA_USAGE_DAILY_LIMIT = "media_usage_daily_limit"
CONF_MEDIA_USAGE_START = "media_usage_start"
CONF_MEDIA_USAGE_END = "media_usage_end"
CONF_MEDIA_USAGE_TRACK_ONLY_ALLOWED_HOURS = "media_usage_track_only_allowed_hours"
CONF_MAX_STRIKES = "max_strikes"
CONF_TTS_ENABLED = "tts_enabled"
CONF_TTS_SERVICE = "tts_service"
CONF_OPENAI_ENABLED = "openai_enabled"
CONF_OPENAI_AGENT_ID = "openai_agent_id"
CONF_FILTER_STRICTNESS = "filter_strictness"

# Defaults
DEFAULT_BLOCKED_APPS = "TikTok,Twitch,YouTube"
DEFAULT_ALLOWED_APPS = "Disney+,PBS Kids,Khan Academy"
DEFAULT_BLOCKED_KEYWORDS = "explicit,nsfw,mature,18+,uncensored"
DEFAULT_CONTENT_RATING = "PG"
DEFAULT_MUSIC_RATING = "Clean Only"
DEFAULT_YOUTUBE_DAILY_LIMIT = 120  # minutes
DEFAULT_MEDIA_USAGE_DAILY_LIMIT = 240  # minutes
DEFAULT_MEDIA_USAGE_START = "08:00"
DEFAULT_MEDIA_USAGE_END = "20:00"
DEFAULT_MEDIA_USAGE_TRACK_ONLY_ALLOWED_HOURS = True
DEFAULT_MAX_STRIKES = 3
DEFAULT_TTS_ENABLED = False
DEFAULT_TTS_SERVICE = ""
DEFAULT_OPENAI_ENABLED = False
DEFAULT_OPENAI_AGENT_ID = ""
DEFAULT_FILTER_STRICTNESS = "moderate"

# Content rating options
CONTENT_RATINGS = ["G", "PG", "PG-13", "R", "Unrated"]
MUSIC_RATINGS = ["Clean Only", "Allow Mild Language", "Allow All"]
FILTER_STRICTNESS_OPTIONS = ["relaxed", "moderate", "strict"]

# Repeat-block cooldown in seconds
LOCKOUT_COOLDOWN_SECONDS = 10

# OpenAI cache max entries
OPENAI_CACHE_MAX_ENTRIES = 200

# Title pattern word lists organized by category and strictness
# Word-boundary matching (\b) is applied at filter time to avoid false positives.
# These are starter lists — users extend via blocked_keywords config.
TITLE_PATTERNS = {
    "relaxed": {
        "profanity": [
            "fuck", "shit", "bitch", "ass", "damn", "hell",
            "crap", "dick", "cock", "pussy", "bastard", "whore",
            "slut", "piss",
        ],
        "sexual": [
            "porn", "xxx", "sex", "nude", "naked", "stripper",
            "hentai", "orgasm", "erotic", "fetish",
        ],
    },
    "moderate": {
        "suggestive": [
            "sexy", "thong", "booty", "boobs", "twerk",
            "hookup", "one night stand", "friends with benefits",
            "milf", "dilf", "sugar daddy", "sugar mama",
        ],
        "drugs_alcohol": [
            "cocaine", "heroin", "meth", "weed", "marijuana",
            "molly", "ecstasy", "lsd", "shrooms", "blunt",
            "420", "stoned", "high af", "drunk", "vodka shots",
            "xanax", "percocet", "lean", "codeine",
        ],
        "violence": [
            "murder", "kill", "stabbing", "shooting", "bloodbath",
            "massacre", "slaughter", "torture", "decapitate",
            "dismember",
        ],
    },
    "strict": {
        "crude_humor": [
            "fart", "poop", "butt", "booger", "burp",
            "vomit", "puke", "diarrhea", "toilet humor",
            "wedgie", "mooning",
        ],
        "mild_innuendo": [
            "naughty", "kinky", "dirty mind", "that's what she said",
            "bow chicka", "come to bed", "netflix and chill",
        ],
        "troll_meme": [
            "deez nuts", "ligma", "among us", "sussy",
            "rickroll", "never gonna give you up",
            "baby shark doo doo", "nyan cat",
            "what does the fox say", "pen pineapple apple pen",
        ],
    },
}
