#!/usr/bin/env python3
"""TTS script text: the deterministic weather template plus the AI-mediated
recap/factoid builders. Weather never touches an LLM; recap/factoid try the
LLM but ALWAYS degrade to a deterministic template on any failure, so a dead
Ollama can never error a whole programming hour."""
import json
import re
import urllib.parse
import urllib.request

import llm_backends  # one-directional: llm_backends imports only stdlib, no cycle

WEATHER_CONF = "/opt/writ-fm/weather.conf"

# Rough seconds per track, used to estimate how much of a music segment's
# resolved head actually airs under its duration_s cap (for recaps).
AVG_TRACK_S = 210


def load_weather_conf(path=WEATHER_CONF):
    c = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                c[k] = v
    return c


def geocode(location, api_key):
    location = location.strip()
    if re.match(r"^\d", location):
        url = "https://api.openweathermap.org/geo/1.0/zip?" + urllib.parse.urlencode(
            {"zip": location, "appid": api_key})
        with urllib.request.urlopen(url, timeout=10) as r:
            d = json.load(r)
        return d["lat"], d["lon"], d.get("name", location)
    else:
        url = "https://api.openweathermap.org/geo/1.0/direct?" + urllib.parse.urlencode(
            {"q": location, "limit": 1, "appid": api_key})
        with urllib.request.urlopen(url, timeout=10) as r:
            d = json.load(r)
        if not d:
            raise RuntimeError("location not found: %s" % location)
        place = d[0]
        label = place["name"] + (", " + place["country"] if place.get("country") else "")
        return place["lat"], place["lon"], label


def current_weather(lat, lon, api_key, units="imperial"):
    url = "https://api.openweathermap.org/data/2.5/weather?" + urllib.parse.urlencode(
        {"lat": lat, "lon": lon, "appid": api_key, "units": units})
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.load(r)


def weather_script(place, w):
    temp = round(w["main"]["temp"])
    feels = round(w["main"]["feels_like"])
    desc = w["weather"][0]["description"]
    wind = round(w.get("wind", {}).get("speed", 0))
    humidity = w["main"]["humidity"]
    return (
        f"Here's the weather for {place}. Currently {temp} degrees and {desc}. "
        f"Feels like {feels}. Winds at {wind} miles per hour, humidity {humidity} percent."
    )


def build_weather_text(location):
    if not (location or "").strip():
        raise RuntimeError("no weather location set (set one in /day, or a station default)")
    conf = load_weather_conf()
    api_key = conf.get("OWM_API_KEY", "")
    if not api_key:
        raise RuntimeError("weather.conf missing OWM_API_KEY")
    lat, lon, place = geocode(location, api_key)
    w = current_weather(lat, lon, api_key)
    return weather_script(place, w), place


# --- AI-mediated recap / factoid (LLM with deterministic fallback) ---

def _aired_tracks(seg):
    """The music track names estimated to actually air from a resolved music
    segment: the resolved head, truncated to duration_s // AVG_TRACK_S."""
    head = (seg.get("resolved") or {}).get("tracks_head", [])
    dur = (seg.get("params") or {}).get("duration_s", 720)
    k = max(1, int(dur // AVG_TRACK_S))
    return head[:k]


def _prior_music_tracks(context, scope):
    """Track names from music segments before this recap's slot, in air order.
    scope 'music' = since the previous recap; scope 'hour' = all prior music.
    Relies on render_block having resolved earlier segments in the same pass."""
    segs = context["segments"]
    idx = context["index"]
    prior = segs[:idx]
    if scope == "music":
        last_recap = -1
        for j, s in enumerate(prior):
            if (s.get("params") or {}).get("topic") == "recap":
                last_recap = j
        prior = prior[last_recap + 1:]
    tracks = []
    for s in prior:
        if s.get("type") == "music":
            tracks += _aired_tracks(s)
    return tracks


_PLAIN = ("Return plain spoken prose only: no markdown, no headings or titles, "
          "no bullet points, no bold, no section labels.")


def _spoken(text):
    """Strip markdown so Kokoro doesn't read '#'/'**' aloud (LLMs return it
    even when asked not to)."""
    if not text:
        return text
    t = re.sub(r"[*_`#]+", "", text)                 # emphasis / headers / code
    t = re.sub(r"^\s*[-•]\s+", "", t, flags=re.M)  # bullet markers
    t = re.sub(r"\n{2,}", " ", t)                    # collapse paragraph breaks
    t = re.sub(r"[ \t]{2,}", " ", t)
    return t.strip()


def _try_llm(params, prompt):
    backend = params.get("llm_backend")
    model = params.get("llm_model")
    if not backend or not model:
        return None
    try:
        return _spoken((llm_backends.generate(backend, model, prompt) or "").strip()) or None
    except Exception:
        return None


def build_recap_text(params, context):
    if not context:
        raise RuntimeError("recap preview is only available in whole-block preview")
    tracks = _prior_music_tracks(context, params.get("scope", "music"))
    want_factoid = bool(params.get("include_factoid"))
    seed = params.get("factoid_seed", "")
    if want_factoid and seed:
        factoid_clause = " Then add one short, accurate factoid about %s." % seed
    elif want_factoid:
        factoid_clause = " Then add one short, accurate factoid about one of these songs or artists."
    else:
        factoid_clause = ""
    prompt = (
        "Write a warm radio recap of about 100 words (~40 seconds spoken) of the music "
        "just played, naming a few of these tracks and inviting the listener to stay. "
        "Use only these track names, invent nothing. No preamble. %s%s\nTracks: %s"
        % (_PLAIN, factoid_clause,
           ", ".join(tracks[:8]) if tracks else "(the recent set)")
    )
    text = _try_llm(params, prompt)
    if not text:
        listed = ", ".join(tracks[:6]) if tracks else "a great set"
        text = "That was %s. Stay with us." % listed
    return text, "Recap"


def build_factoid_text(params, context):
    source = params.get("source", "freeform")
    seed = params.get("seed_topic", "")
    if source == "music" and context:
        tracks = _prior_music_tracks(context, "hour")
        seed = ", ".join(tracks[:6]) or seed
    prompt = (
        "Share one short, accurate, interesting factoid or piece of trivia in 2 to 3 "
        "spoken sentences about: %s. No preamble, do not start with 'did you know'. %s"
        % (seed or "music history", _PLAIN)
    )
    text = _try_llm(params, prompt)
    if not text:
        text = ("Here's a thought between songs. Music marks time -- where you were, "
                "who you were with. Stay with us.")
    return text, "Factoid"
