#!/usr/bin/env python3
"""LLM backend registry for freeform TTS script text (non-templated topics).
Weather stays a deterministic template (tts_content.py) and never goes
through here. Ollama needs no credentials; Claude reads a key from
anthropic.conf (vault-provisioned, mirrors jellyfin.conf's format).
"""
import json
import urllib.request

ANTHROPIC_CONF = "/opt/writ-fm/anthropic.conf"

LLM_BACKENDS = {
    "ollama": {"label": "Ollama (rac-wsl)", "kind": "ollama", "base_url": "http://rac-wsl:11434"},
    "claude": {"label": "Claude API", "kind": "anthropic-api",
               "models": ["claude-sonnet-5", "claude-opus-4-8", "claude-haiku-4-5"]},
}


def _load_anthropic_conf(path=ANTHROPIC_CONF):
    c = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                c[k] = v
    return c


def list_models(backend_id):
    b = LLM_BACKENDS.get(backend_id)
    if not b:
        raise ValueError("unknown llm backend: %s" % backend_id)
    if b["kind"] == "ollama":
        try:
            with urllib.request.urlopen(b["base_url"].rstrip("/") + "/api/tags", timeout=6) as r:
                d = json.load(r)
            return sorted(m["name"] for m in d.get("models", []))
        except Exception:
            return []
    return list(b["models"])


def list_backends():
    out = []
    for bid in LLM_BACKENDS:
        out.append({"id": bid, "label": LLM_BACKENDS[bid]["label"], "models": list_models(bid)})
    return out


def generate(backend_id, model, prompt):
    b = LLM_BACKENDS.get(backend_id)
    if not b:
        raise ValueError("unknown llm backend: %s" % backend_id)

    if b["kind"] == "ollama":
        body = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode()
        req = urllib.request.Request(
            b["base_url"].rstrip("/") + "/api/generate", data=body,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read())["response"].strip()

    if b["kind"] == "anthropic-api":
        conf = _load_anthropic_conf()
        body = json.dumps({
            "model": model, "max_tokens": 512,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages", data=body,
            headers={"Content-Type": "application/json",
                     "x-api-key": conf["ANTHROPIC_API_KEY"],
                     "anthropic-version": "2023-06-01"})
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.loads(r.read())
        return "".join(block.get("text", "") for block in d.get("content", [])).strip()

    raise ValueError("unhandled backend kind: %s" % b["kind"])
