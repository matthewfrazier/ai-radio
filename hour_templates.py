#!/usr/bin/env python3
"""Programming-hour templates: the standard-hour segment plan as plain data,
plus build_hour() to materialize a block's segments with `role` tags and
per-hour variation (music genre by day-part, rotating news lead). Data, not a
DSL -- the day generator (day_program.py) and the /day UI read/override these.
"""

# genuine short bulletins (not the full-channel "(live)" relays) for the news
# slots; news_fresh uses "auto" to pick one not already used this hour.
BULLETINS = ["npr", "bbc_world", "dw_brief"]

# music genre (Jellyfin search term) per day-part; two slots -> two genres.
# Empty string = shuffle-all. Operator retunes per hour in the /day UI.
DEFAULT_DAY_PARTS = [
    {"hours": [0, 1, 2, 3, 4, 5], "genres": ["ambient", "downtempo"]},       # overnight
    {"hours": [6, 7, 8, 9, 10, 11], "genres": ["upbeat", "indie"]},          # morning
    {"hours": [12, 13, 14, 15, 16, 17], "genres": ["rock", "electronic"]},   # afternoon
    {"hours": [18, 19, 20, 21, 22, 23], "genres": ["soul", "jazz"]},         # evening
]

# The two music segments are sized to fill most of the hour (leaving end-recap
# slack) so the queue-mode gap to the next :00 stays small (see DAY_PROGRAMMING.md).
MUSIC_1_S = 780   # ~13 min
MUSIC_2_S = 900   # ~15 min


def _genres_for_hour(hour, day_parts):
    for dp in day_parts:
        if hour in dp["hours"]:
            return list(dp["genres"])[:2] + ["", ""]
    return ["", ""]


# When news is off, the two music sets each absorb this much of the freed ~20
# min of bulletin time so the hour still fills.
NEWS_OFF_MUSIC_BONUS_S = 600


def build_hour(hour, opts=None):
    """Return the standard-hour segment list for a given clock hour (0-23),
    with role tags and per-hour variation. opts overrides: day_parts,
    weather_location, voice, llm_backend, llm_model, include_news.

    News bulletins are OFF by default (they were interruptive and rarely
    useful); set opts['include_news']=True to bring back the 4 news slots."""
    opts = opts or {}
    day_parts = opts.get("day_parts", DEFAULT_DAY_PARTS)
    location = opts.get("weather_location", "")
    voice = opts.get("voice", "")
    backend = opts.get("llm_backend", "")
    model = opts.get("llm_model", "")
    include_news = opts.get("include_news", False)
    g1, g2 = _genres_for_hour(hour, day_parts)[:2]

    def tts(role, params):
        p = {"voice": voice}
        p.update(params)
        return {"id": role, "role": role, "type": "tts", "params": p}

    def music(role, query, dur):
        return {"id": role, "role": role, "type": "music",
                "params": {"query": query, "duration_s": dur}}

    weather = tts("weather", {"topic": "weather", "location": location, "ttl_s": 1800})
    recap_mid = tts("recap_mid", {"topic": "recap", "scope": "music", "include_factoid": True,
                                  "ttl_s": 0, "llm_backend": backend, "llm_model": model})
    recap_hour = tts("recap_hour", {"topic": "recap", "scope": "hour", "ttl_s": 0,
                                    "llm_backend": backend, "llm_model": model})

    if not include_news:
        b = NEWS_OFF_MUSIC_BONUS_S
        return [weather,
                music("music_1", g1, MUSIC_1_S + b),
                recap_mid,
                music("music_2", g2, MUSIC_2_S + b),
                recap_hour]

    n = len(BULLETINS)
    b1, b2, b3 = BULLETINS[hour % n], BULLETINS[(hour + 1) % n], BULLETINS[(hour + 2) % n]
    return [
        weather,
        {"id": "news_1", "role": "news_1", "type": "live", "params": {"source_id": b1, "duration_s": 300}},
        {"id": "news_2", "role": "news_2", "type": "live", "params": {"source_id": b2, "duration_s": 300}},
        music("music_1", g1, MUSIC_1_S),
        {"id": "news_3", "role": "news_3", "type": "live", "params": {"source_id": b3, "duration_s": 300}},
        recap_mid,
        music("music_2", g2, MUSIC_2_S),
        {"id": "news_fresh", "role": "news_fresh", "type": "live", "params": {"source_id": "auto", "duration_s": 300}},
        recap_hour,
    ]


TEMPLATES = {"standard_hour": build_hour}
