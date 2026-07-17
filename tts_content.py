#!/usr/bin/env python3
"""Deterministic weather TTS script. No LLM in this path — fast, free,
predictable, safe to hit repeatedly from a Test button."""
import json
import re
import urllib.parse
import urllib.request

WEATHER_CONF = "/opt/writ-fm/weather.conf"


def load_weather_conf(path=WEATHER_CONF):
    c = {}
    for line in open(path):
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
    conf = load_weather_conf()
    api_key = conf.get("OWM_API_KEY", "")
    if not api_key:
        raise RuntimeError("weather.conf missing OWM_API_KEY")
    lat, lon, place = geocode(location, api_key)
    w = current_weather(lat, lon, api_key)
    return weather_script(place, w), place
