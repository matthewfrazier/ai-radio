#!/usr/bin/env python3
"""TTS engine registry. Kokoro-FastAPI (tailnet HTTP) is the only concrete
engine wired up today; the registry shape is what makes adding a second
engine later a small diff rather than a rewrite.
"""
import json
import urllib.request

TTS_ENGINES = {
    "kokoro": {"label": "Kokoro (tailnet GPU)", "kind": "openai-http-tts"},
}


def kokoro_voices(base):
    try:
        with urllib.request.urlopen(base.rstrip("/") + "/v1/audio/voices", timeout=4) as r:
            d = json.load(r)
        v = d.get("voices", d) if isinstance(d, dict) else d
        if not isinstance(v, list):
            return []
        # Kokoro-FastAPI returns [{"id":..,"name":..}]; older builds return plain strings.
        names = [(x.get("id") or x.get("name")) if isinstance(x, dict) else x for x in v]
        return sorted(n for n in names if n)
    except Exception:
        return []


def kokoro_speech(base, voice, speed, text, fmt="mp3"):
    body = json.dumps({
        "model": "kokoro", "input": text, "voice": voice,
        "speed": float(speed), "response_format": fmt,
    }).encode()
    req = urllib.request.Request(
        base.rstrip("/") + "/v1/audio/speech", data=body,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return r.read()


def list_engines(cfg):
    out = []
    for eid, e in TTS_ENGINES.items():
        voices = kokoro_voices(cfg["kokoro"]) if eid == "kokoro" else []
        out.append({"id": eid, "label": e["label"], "online": bool(voices), "voices": voices})
    return out


def voices(engine_id, cfg):
    if engine_id == "kokoro":
        return kokoro_voices(cfg["kokoro"])
    raise ValueError("unknown tts engine: %s" % engine_id)


def speech(engine_id, voice, speed, text, cfg, fmt="mp3"):
    if engine_id == "kokoro":
        return kokoro_speech(cfg["kokoro"], voice, speed, text, fmt=fmt)
    raise ValueError("unknown tts engine: %s" % engine_id)
