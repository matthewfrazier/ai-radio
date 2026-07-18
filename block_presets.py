#!/usr/bin/env python3
"""Named single-block presets for the /now constructable view. Each build fn
turns a few opts into a segment list (same shape as hour_templates.build_hour),
so /now can one-click a starting block and then edit its segments. Kept as
plain data + small builders -- the fill-in options will grow over time.

opts keys (all optional; UI supplies what it has):
  genre_1, genre_2   Jellyfin search terms for the music slots ("" = shuffle)
  voice              default TTS voice for every tts segment (per-segment
                     override happens in the editor)
  weather_location   zip/city for weather
  llm_backend, llm_model   for recap/factoid tts
"""


def _tts(role, params, voice=""):
    p = {"voice": voice}
    p.update(params)
    return {"id": role, "role": role, "type": "tts", "params": p}


def _live(role, source_id="auto", dur=300):
    return {"id": role, "role": role, "type": "live",
            "params": {"source_id": source_id, "duration_s": dur}}


def _music(role, query, dur):
    return {"id": role, "role": role, "type": "music",
            "params": {"query": query, "duration_s": dur}}


def _weather(role, opts):
    return _tts(role, {"topic": "weather", "location": opts.get("weather_location", ""),
                       "ttl_s": 1800}, opts.get("voice", ""))


def _recap(role, opts, scope="music", factoid=False):
    return _tts(role, {"topic": "recap", "scope": scope, "include_factoid": factoid,
                       "ttl_s": 0, "llm_backend": opts.get("llm_backend", ""),
                       "llm_model": opts.get("llm_model", "")}, opts.get("voice", ""))


def news_talk(opts):
    """News & talk, no music: weather, a fresh brief, an AI factoid, another
    disjoint brief. TTS voice overridable per segment in the editor."""
    return [
        _weather("weather", opts),
        _live("news_1", "auto", 300),
        _tts("factoid", {"topic": "factoid", "ttl_s": 0,
                         "llm_backend": opts.get("llm_backend", ""),
                         "llm_model": opts.get("llm_model", "")}, opts.get("voice", "")),
        _live("news_2", "auto", 300),
    ]


def brief_music(opts):
    """Weather + a single brief at the top, then two 25-min music sets
    separated only by a recap and a weather update."""
    g1 = opts.get("genre_1", "")
    g2 = opts.get("genre_2", g1)
    return [
        _weather("weather", opts),
        _live("news_1", "auto", 300),
        _music("music_1", g1, 1500),
        _recap("recap_mid", opts, scope="music", factoid=True),
        _weather("weather_mid", opts),
        _music("music_2", g2, 1500),
    ]


def all_music(opts):
    """All music with only a weather TTS every 30 minutes."""
    g1 = opts.get("genre_1", "")
    g2 = opts.get("genre_2", g1)
    return [
        _weather("weather", opts),
        _music("music_1", g1, 1800),
        _weather("weather_mid", opts),
        _music("music_2", g2, 1800),
    ]


# id -> {label, build, needs_genre}. `label` shows in the /now preset picker.
PRESETS = {
    "news_talk": {"label": "News & talk (no music)", "build": news_talk, "needs_genre": False},
    "brief_music": {"label": "Weather + brief, two 25-min music sets", "build": brief_music, "needs_genre": True},
    "all_music": {"label": "All music, weather every 30 min", "build": all_music, "needs_genre": True},
}


def build_preset(preset, opts=None):
    if preset not in PRESETS:
        raise ValueError("unknown preset: %s" % preset)
    return PRESETS[preset]["build"](opts or {})


def preset_menu():
    """[{id, label, needs_genre}] for the UI, stable order."""
    return [{"id": k, "label": v["label"], "needs_genre": v["needs_genre"]}
            for k, v in PRESETS.items()]
