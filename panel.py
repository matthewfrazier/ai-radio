#!/usr/bin/env python3
"""Minimal control panel for the ai-radio WRIT-FM radio.

Exposes the knobs that actually shape the broadcast — Kokoro endpoint, voice,
speed, and the script the DJ reads — auditions voices in-page, then re-renders
through Kokoro and restarts the Icecast stream. Zero deps (stdlib only)."""
import glob
import json
import os
import re
import subprocess
import threading
import time
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from tts_engines import kokoro_voices, kokoro_speech
import block_render
import blocks_page
import jellyfin_client
import live_source
import llm_backends
import tts_engines

BASE = "/opt/writ-fm"
AUDIO = os.path.join(BASE, "stub_audio")
CFG = os.path.join(BASE, "station.json")
ICECAST = "http://127.0.0.1:8000"
STREAM_URL = "https://ai-radio.tailbe5094.ts.net/stream"
AIRD = "http://192.168.1.74:8899"  # radioscript render/air service on raserver (LAN)
PORT = 8080

DEFAULT = {
    "kokoro": "http://192.168.1.74:8880",
    "voice": "am_michael",
    "speed": 1.0,
    "segments": [
        "You are listening to WRIT F M, standing up on threadeval, the twenty four seven A I talk radio experiment. Now with a real voice.",
        "Station note. The stub espeak voice is retired. Speech is now synthesized by Kokoro, running on a real G P U across the tailnet, and streamed over Icecast.",
        "Time check. The operator still has nothing better to do, so the broadcast continues, unlike a certain D J who quit.",
        "WRIT F M. Reachable, disposable, and spun up by the repo stand up pattern. If this is not worth your time, it will be spun right back down.",
    ],
}


def load_cfg():
    try:
        with open(CFG) as f:
            c = json.load(f)
        for k, v in DEFAULT.items():
            c.setdefault(k, v)
        return c
    except Exception:
        return dict(DEFAULT)


def save_cfg(c):
    with open(CFG, "w") as f:
        json.dump(c, f, indent=2)


def icecast_status():
    try:
        with urllib.request.urlopen(ICECAST + "/status-json.xsl", timeout=4) as r:
            d = json.load(r)["icestats"]
        s = d.get("source")
        if not s:
            return {"live": False, "listeners": 0}
        if isinstance(s, dict):
            s = [s]
        m = s[0]
        return {"live": True, "listeners": m.get("listeners", 0),
                "title": m.get("title") or m.get("server_name", "")}
    except Exception:
        return {"live": False, "listeners": 0}


def render(cfg):
    base = cfg["kokoro"].rstrip("/")
    voice = cfg["voice"]
    speed = float(cfg.get("speed", 1.0))
    for f in glob.glob(os.path.join(AUDIO, "seg_*.ogg")):
        os.remove(f)
    lines = []
    for i, text in enumerate(cfg["segments"]):
        if not text.strip():
            continue
        wav = os.path.join(AUDIO, f"seg_{i:02d}.wav")
        ogg = os.path.join(AUDIO, f"seg_{i:02d}.ogg")
        with open(wav, "wb") as f:
            f.write(kokoro_speech(base, voice, speed, text, fmt="wav"))
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", wav,
                        "-c:a", "libvorbis", "-q:a", "4", ogg], check=True)
        os.remove(wav)
        lines.append(f"file '{ogg}'")
    if not lines:
        raise RuntimeError("no non-empty segments to render")
    with open(os.path.join(AUDIO, "concat.txt"), "w") as f:
        f.write("\n".join(lines) + "\n")
    return len(lines)


def apply(cfg):
    save_cfg(cfg)
    n = render(cfg)
    # Cut over from the espeak tmux loop (run #1) to the systemd stream unit.
    subprocess.run(["tmux", "kill-session", "-t", "writstub"], capture_output=True)
    subprocess.run(["systemctl", "enable", "--now", "writ-stream.service"], capture_output=True)
    subprocess.run(["systemctl", "restart", "writ-stream.service"], capture_output=True)
    return n


PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>WRIT-FM control</title>
<style>
:root{color-scheme:light dark}
body{font-family:system-ui,sans-serif;max-width:820px;margin:0 auto;padding:1.2rem;line-height:1.4}
h1{font-size:1.3rem;margin:.2rem 0}
.sub{opacity:.7;font-size:.85rem;margin-bottom:1rem}
fieldset{border:1px solid #8884;border-radius:8px;margin:0 0 1rem;padding:.8rem 1rem}
legend{font-weight:600;padding:0 .4rem}
label{display:block;font-size:.8rem;opacity:.8;margin:.6rem 0 .2rem}
input,select,textarea{width:100%;box-sizing:border-box;font:inherit;padding:.4rem;border:1px solid #8886;border-radius:6px;background:transparent;color:inherit}
textarea{min-height:9rem;resize:vertical;font-family:ui-monospace,monospace;font-size:.85rem}
.row{display:flex;gap:.8rem;flex-wrap:wrap}
.row>div{flex:1;min-width:9rem}
button{font:inherit;padding:.5rem 1rem;border:0;border-radius:6px;background:#3b82f6;color:#fff;cursor:pointer}
button.ghost{background:#8883;color:inherit}
button:disabled{opacity:.5;cursor:progress}
.status{display:flex;gap:1.2rem;flex-wrap:wrap;align-items:center;font-size:.85rem;margin-bottom:.6rem}
.dot{display:inline-block;width:.6rem;height:.6rem;border-radius:50%;background:#888;margin-right:.35rem;vertical-align:middle}
.dot.ok{background:#22c55e}.dot.bad{background:#ef4444}
.actions{display:flex;gap:.6rem;flex-wrap:wrap;align-items:center}
pre{white-space:pre-wrap;background:#8881;padding:.6rem;border-radius:6px;font-size:.78rem;max-height:14rem;overflow:auto}
audio{width:100%;margin-top:.4rem}
a{color:#3b82f6}
</style></head><body>
<h1>WRIT-FM control</h1>
<div class="sub">ai-radio &middot; repo stand-up pattern &middot; issue #38 &middot; <a href="/blocks">programming blocks</a></div>

<div class="status">
  <span><span id="kdot" class="dot"></span>Kokoro <span id="kstate">?</span></span>
  <span><span id="sdot" class="dot"></span>Stream <span id="sstate">?</span> <span id="listeners"></span></span>
  <span>URL: <a id="surl" href="#" target="_blank"></a></span>
</div>
<audio id="live" controls preload="none"></audio>

<fieldset><legend>Program</legend>
  <label>What airs on the stream</label>
  <select id="program">
    <option value="station">Station segments (voice + script below)</option>
    <option value="radioscript">Radioscript hour (NPR news, liked-songs music, weather, markets)</option>
  </select>
  <div id="rsbox" hidden>
    <div class="status" style="margin-top:.7rem">
      <span><span id="rsjelly" class="dot"></span>Jellyfin music</span>
      <span><span id="rsloc" class="dot"></span>Weather location</span>
      <span id="rslast"></span>
    </div>
    <p class="sub" id="rsnote">Uses the host voice selected below. News + markets air now; music + weather go live once the vault delivers creds.</p>
    <div class="actions">
      <button id="btnAir" type="button">Render &amp; air radioscript hour</button>
      <span id="rsmsg"></span>
    </div>
    <pre id="rslog"></pre>
  </div>
</fieldset>

<fieldset><legend>Music Source</legend>
  <label>What the music stream plays</label>
  <select id="source"></select>
  <div class="actions" style="margin-top:.6rem">
    <button id="btnSource" type="button">Apply source</button>
    <span id="srcmsg" class="sub"></span>
  </div>
</fieldset>

<fieldset><legend>Voice</legend>
  <div class="row">
    <div><label>Voice</label><select id="voice"></select></div>
    <div><label>Speed (0.5&ndash;2.0)</label><input id="speed" type="number" min="0.5" max="2" step="0.1"></div>
  </div>
  <label>Audition text</label>
  <input id="sample" value="This is WRIT F M. Testing the voice for the station.">
  <div class="actions" style="margin-top:.6rem">
    <button class="ghost" id="btnSample" type="button">Play sample</button>
    <button class="ghost" id="btnVoices" type="button">Refresh voices</button>
    <audio id="preview" preload="none"></audio>
  </div>
</fieldset>

<div id="stationbox">
<fieldset><legend>Kokoro endpoint</legend>
  <input id="kokoro">
</fieldset>

<fieldset><legend>Script</legend>
  <label>One segment per paragraph &mdash; blank line separates segments.</label>
  <textarea id="script"></textarea>
</fieldset>

<div class="actions">
  <button id="btnApply" type="button">Apply &amp; restart stream</button>
  <span id="msg"></span>
</div>
<pre id="log"></pre>
</div>

<script>
const $=id=>document.getElementById(id);
// The panel may be mounted under a path prefix (tailscale serve routes /admin -> :8080),
// so build API URLs from the current path, not relative, or they hit the Icecast root.
const BASE=location.pathname.replace(/\/+$/,'');
function setDot(el,ok){el.className='dot '+(ok?'ok':'bad');}
async function loadState(){
  const s=await (await fetch(BASE+'/api/state')).json();
  $('kokoro').value=s.cfg.kokoro; $('speed').value=s.cfg.speed;
  $('script').value=s.cfg.segments.join('\\n\\n');
  const sel=$('voice'); sel.innerHTML='';
  (s.voices||[]).forEach(v=>{const o=document.createElement('option');o.value=o.textContent=v;sel.appendChild(o);});
  if(s.voices&&s.voices.includes(s.cfg.voice))sel.value=s.cfg.voice;
  else{const o=document.createElement('option');o.value=o.textContent=s.cfg.voice;sel.appendChild(o);sel.value=s.cfg.voice;}
  $('kstate').textContent=s.kokoro_online?('online ('+(s.voices||[]).length+' voices)'):'offline';
  setDot($('kdot'),s.kokoro_online);
  $('sstate').textContent=s.stream.live?'live':'offline';
  setDot($('sdot'),s.stream.live);
  $('listeners').textContent=s.stream.live?('· '+s.stream.listeners+' listening'):'';
  $('surl').textContent=s.stream_url; $('surl').href=s.stream_url;
  $('live').src='/stream';
}
$('btnVoices').onclick=loadState;
$('btnSample').onclick=()=>{
  const q=new URLSearchParams({voice:$('voice').value,speed:$('speed').value,text:$('sample').value});
  const a=$('preview'); a.src=BASE+'/api/sample?'+q.toString(); a.play();
};
$('btnApply').onclick=async()=>{
  const b=$('btnApply'); b.disabled=true; $('msg').textContent='rendering…'; $('log').textContent='';
  const segs=$('script').value.split(/\\n\\s*\\n/).map(x=>x.trim()).filter(Boolean);
  const body={kokoro:$('kokoro').value,voice:$('voice').value,speed:parseFloat($('speed').value),segments:segs};
  try{
    const r=await fetch(BASE+'/api/apply',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const j=await r.json();
    $('msg').textContent=j.ok?('applied · '+j.segments+' segments live'):('error: '+j.error);
    $('log').textContent=j.log||'';
  }catch(e){$('msg').textContent='error: '+e;}
  b.disabled=false; setTimeout(loadState,1500);
};
async function loadRs(){
  try{
    const s=await (await fetch(BASE+'/api/rs/status')).json();
    const c=s.creds||{};
    setDot($('rsjelly'), !!c.jellyfin); setDot($('rsloc'), !!c.location);
    $('rslast').textContent = s.last ? ('last render: '+s.last.total_s+'s · '
      +(s.last.music_real?'real music':'placeholder music')+' · '
      +(s.last.weather?'local weather':'no weather')) : '';
  }catch(e){}
}
function syncProgram(){
  const rs=$('program').value==='radioscript';
  $('rsbox').hidden=!rs; $('stationbox').hidden=rs;
  if(rs) loadRs();
}
$('program').onchange=syncProgram;
$('btnAir').onclick=async()=>{
  const b=$('btnAir'); b.disabled=true; $('rsmsg').textContent='rendering + airing (up to ~2 min)…'; $('rslog').textContent='';
  try{
    const r=await fetch(BASE+'/api/rs/air',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({voice:$('voice').value})});
    const j=await r.json();
    $('rsmsg').textContent=j.ok?('aired · '+(j.last?j.last.total_s+'s on '+STATION:'')):('failed at '+(j.stage||'?'));
    $('rslog').textContent=j.log||'';
  }catch(e){$('rsmsg').textContent='error: '+e;}
  b.disabled=false; loadRs(); setTimeout(loadState,1500);
};
const STATION='the stream';
loadState();
syncProgram();

async function loadSources(){
  try{const r=await fetch(BASE+'/api/sources');const d=await r.json();
    const s=$('source');s.innerHTML='';
    (d.sources||[]).forEach(x=>{const o=document.createElement('option');o.value=x.id;o.textContent=x.name;if(x.id===d.current)o.selected=true;s.appendChild(o);});
    if(d.error)$('srcmsg').textContent='jellyfin: '+d.error;
  }catch(e){$('srcmsg').textContent='load failed: '+e;}
}
$('btnSource').onclick=async()=>{
  const b=$('btnSource');b.disabled=true;$('srcmsg').textContent='sourcing...';
  try{const r=await fetch(BASE+'/api/source',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({source:$('source').value})});
    const d=await r.json();$('srcmsg').textContent=d.ok?('OK '+d.tracks+' tracks, stream restarted'):('ERR '+(d.error||'failed'));}
  catch(e){$('srcmsg').textContent='ERR '+e;}finally{b.disabled=false;}
};
loadSources();
</script>
</body></html>"""


PLAYER_UNIT = "writ-block-player.service"


def _api_route(path):
    """Path segments after '/api/', tolerating a tailscale-serve mount prefix
    (same reason the existing routes above match via .endswith())."""
    idx = path.find("/api/")
    if idx == -1:
        return None
    return path[idx + len("/api/"):].strip("/").split("/")


def _player_active():
    return subprocess.run(["systemctl", "is-active", "--quiet", PLAYER_UNIT]).returncode == 0


def _start_player():
    # systemd's Conflicts= stops the static writ-stream loop for us.
    subprocess.run(["systemctl", "start", PLAYER_UNIT], capture_output=True)


def _cutover_player():
    # SIGHUP = "abandon current block, re-read the queue" -- an in-process
    # cutover that avoids stopping the unit (which would flap writ-stream).
    subprocess.run(["systemctl", "kill", "-s", "HUP", PLAYER_UNIT], capture_output=True)


def schedule_block(block_id, mode):
    # Render now so resolve/render errors surface in the UI immediately; the
    # player re-renders again at air time, so a block that waits in the queue
    # never airs stale content.
    block_render.render_block(block_id, force=False)
    if mode == "now":
        block_render.queue_now(block_id)  # overwrite: play-now drops the rest of the queue
        if _player_active():
            _cutover_player()
        else:
            _start_player()
    else:
        block_render.queue_append(block_id)
        if not _player_active():
            _start_player()
    block_render.mark_scheduled(block_id, "queued")
    return {"ok": True, "queue": block_render.load_queue()}


def stop_block_player():
    block_render.save_queue([])
    subprocess.run(["systemctl", "stop", PLAYER_UNIT], capture_output=True)


_sched_last_fired = {}


def _scheduler_tick():
    """Background thread: once every 30s (so each minute is sampled), queue
    any schedule entry that's due. 30s < 60s guarantees no minute is skipped;
    due_entries dedups so an entry fires once per matching minute."""
    while True:
        time.sleep(30)
        try:
            due = block_render.due_entries(block_render.load_schedule(), datetime.now(), _sched_last_fired)
            for block_id in due:
                try:
                    schedule_block(block_id, "queue")
                except Exception:
                    pass
        except Exception:
            pass


def delete_block_safe(block_id):
    queue = block_render.load_queue()
    if queue and queue[0] == block_id:
        # currently airing (or about to) -- the player has this block's dir
        # open mid-segment, so it must stop before the files disappear
        # underneath it, not just get its queue entry dropped.
        stop_block_player()
    elif block_id in queue:
        block_render.save_queue([b for b in queue if b != block_id])
    block_render.delete_block(block_id)


class H(BaseHTTPRequestHandler):
    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/", "/admin", "/admin/"):
            return self._send(200, "text/html; charset=utf-8", PAGE.encode())
        if u.path.endswith("/api/state"):
            cfg = load_cfg()
            voices = kokoro_voices(cfg["kokoro"])
            out = {"cfg": cfg, "voices": voices, "kokoro_online": bool(voices),
                   "stream": icecast_status(), "stream_url": STREAM_URL}
            return self._send(200, "application/json", json.dumps(out).encode())
        if u.path.endswith("/api/rs/status"):
            try:
                with urllib.request.urlopen(AIRD + "/status", timeout=8) as r:
                    return self._send(200, "application/json", r.read())
            except Exception as e:
                return self._send(200, "application/json",
                                  json.dumps({"error": str(e), "creds": {}}).encode())
        if u.path.endswith("/api/sample"):
            q = parse_qs(u.query)
            cfg = load_cfg()
            try:
                audio = kokoro_speech(cfg["kokoro"], q.get("voice", ["am_michael"])[0],
                                      q.get("speed", ["1.0"])[0],
                                      q.get("text", ["This is WRIT FM."])[0], fmt="mp3")
                return self._send(200, "audio/mpeg", audio)
            except Exception as e:
                return self._send(502, "text/plain", str(e).encode())
        if u.path.endswith("/api/sources"):
            p=subprocess.run(["python3","/opt/writ-fm/jf_source.py","list"],capture_output=True,text=True)
            return self._send(200,"application/json",(p.stdout or '{"sources":[]}').encode())
        if "/api/" not in u.path and u.path.rstrip("/").endswith("/blocks"):
            return self._send(200, "text/html; charset=utf-8", blocks_page.BLOCKS_PAGE.encode())

        route = _api_route(u.path)
        if route is not None:
            try:
                if route == ["blocks"]:
                    return self._send(200, "application/json", json.dumps(block_render.list_blocks()).encode())
                if route == ["live_sources"]:
                    return self._send(200, "application/json", json.dumps(live_source.load_sources()).encode())
                if route == ["schedule"]:
                    return self._send(200, "application/json", json.dumps({"entries": block_render.load_schedule()}).encode())
                if route == ["live_test"]:
                    q = parse_qs(u.query)
                    r = live_source.resolve_live(q.get("source_id", [""])[0])
                    return self._send(200, "application/json", json.dumps(r).encode())
                if route == ["music_test"]:
                    q = parse_qs(u.query)
                    r = jellyfin_client.resolve_music(q.get("q", [""])[0], limit=20)
                    return self._send(200, "application/json", json.dumps(r).encode())
                if route == ["tts_test"]:
                    q = {k: v[0] for k, v in parse_qs(u.query).items()}
                    cfg = load_cfg()
                    text, _title = block_render.build_tts_text(q.get("topic", "weather"), q)
                    engine = q.get("engine", "kokoro")
                    voice = q.get("voice") or cfg.get("voice", "am_michael")
                    speed = q.get("speed") or cfg.get("speed", 1.0)
                    audio = tts_engines.speech(engine, voice, speed, text, cfg, fmt="mp3")
                    return self._send(200, "audio/mpeg", audio)
                if route == ["tts_engines"]:
                    return self._send(200, "application/json", json.dumps(tts_engines.list_engines(load_cfg())).encode())
                if route == ["llm_backends"]:
                    q = parse_qs(u.query)
                    backend = q.get("backend", [None])[0]
                    if backend:
                        return self._send(200, "application/json", json.dumps({"models": llm_backends.list_models(backend)}).encode())
                    return self._send(200, "application/json", json.dumps(llm_backends.list_backends()).encode())
                if len(route) == 2 and route[0] == "blocks":
                    return self._send(200, "application/json", json.dumps(block_render.load_block(route[1])).encode())
                if len(route) == 3 and route[0] == "blocks" and route[2] == "markdown":
                    with open(os.path.join(block_render.block_dir(route[1]), "block.md")) as f:
                        return self._send(200, "text/markdown; charset=utf-8", f.read().encode())
                if len(route) == 4 and route[0] == "blocks" and route[2] == "audio":
                    block = block_render.load_block(route[1])
                    seg = next((s for s in block["segments"] if s["id"] == route[3]), None)
                    if not seg or "audio_path" not in seg.get("resolved", {}):
                        return self._send(404, "text/plain", b"not found")
                    with open(os.path.join(block_render.block_dir(route[1]), seg["resolved"]["audio_path"]), "rb") as f:
                        return self._send(200, "audio/ogg", f.read())
                if len(route) == 4 and route[0] == "blocks" and route[2] == "tracks":
                    # The URLs actually rendered into this music segment's
                    # playlist (what will air), so the whole-block preview
                    # auditions the real tracks, not a fresh random roll.
                    block = block_render.load_block(route[1])
                    seg = next((s for s in block["segments"] if s["id"] == route[3]), None)
                    if not seg or "playlist_path" not in seg.get("resolved", {}):
                        return self._send(404, "text/plain", b"not found")
                    urls = []
                    with open(os.path.join(block_render.block_dir(route[1]), seg["resolved"]["playlist_path"])) as f:
                        for line in f:
                            m = re.match(r"file '(.*)'\s*$", line.strip())
                            if m:
                                urls.append(m.group(1))
                    return self._send(200, "application/json", json.dumps({"urls": urls}).encode())
            except FileNotFoundError:
                return self._send(404, "text/plain", b"not found")
            except Exception as e:
                return self._send(502, "text/plain", str(e).encode())
        self._send(404, "text/plain", b"not found")

    def do_POST(self):
        u = urlparse(self.path)
        if u.path.endswith("/api/rs/air"):
            n = int(self.headers.get("Content-Length", 0) or 0)
            body = self.rfile.read(n) if n else b"{}"
            try:
                req = urllib.request.Request(AIRD + "/render-air", data=body,
                                             headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=900) as r:  # render can take a minute+
                    return self._send(200, "application/json", r.read())
            except Exception as e:
                return self._send(200, "application/json",
                                  json.dumps({"ok": False, "log": str(e)}).encode())
        if u.path.endswith("/api/apply"):
            n = int(self.headers.get("Content-Length", 0) or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            cfg = load_cfg()
            for k in ("kokoro", "voice", "speed", "segments"):
                if k in body:
                    cfg[k] = body[k]
            try:
                count = apply(cfg)
                st = icecast_status()
                return self._send(200, "application/json", json.dumps(
                    {"ok": True, "segments": count,
                     "log": f"rendered {count} segments · stream live={st['live']}"}).encode())
            except Exception as e:
                return self._send(200, "application/json", json.dumps(
                    {"ok": False, "error": str(e), "log": ""}).encode())
        if u.path.endswith("/api/source"):
            n=int(self.headers.get("Content-Length",0) or 0)
            body=json.loads(self.rfile.read(n) or b"{}")
            p=subprocess.run(["python3","/opt/writ-fm/jf_source.py","set",body.get("source","")],capture_output=True,text=True)
            return self._send(200,"application/json",(p.stdout or '{"ok":false}').encode())

        route = _api_route(u.path)
        if route is not None:
            n = int(self.headers.get("Content-Length", 0) or 0)
            body = json.loads(self.rfile.read(n) or b"{}") if n else {}
            try:
                if route == ["blocks", "stop"]:
                    stop_block_player()
                    return self._send(200, "application/json", json.dumps({"ok": True}).encode())
                if route == ["schedule"]:
                    block_render.save_schedule(body.get("entries", []))
                    return self._send(200, "application/json", json.dumps({"ok": True, "entries": block_render.load_schedule()}).encode())
                if route == ["llm_test"]:
                    text = llm_backends.generate(body["backend"], body["model"], body["prompt"])
                    return self._send(200, "application/json", json.dumps({"text": text}).encode())
                if route == ["blocks"]:
                    return self._send(200, "application/json", json.dumps(block_render.create_block(body.get("title", ""))).encode())
                if len(route) == 2 and route[0] == "blocks":
                    block = block_render.load_block(route[1])
                    if "title" in body:
                        block["title"] = body["title"]
                    if "segments" in body:
                        block["segments"] = body["segments"]
                    block_render.save_block(block)
                    return self._send(200, "application/json", json.dumps(block).encode())
                if len(route) == 3 and route[0] == "blocks" and route[2] == "render":
                    result = block_render.render_block(route[1], force=bool(body.get("force")))
                    return self._send(200, "application/json", json.dumps(result).encode())
                if len(route) == 3 and route[0] == "blocks" and route[2] == "schedule":
                    result = schedule_block(route[1], body.get("mode", "queue"))
                    return self._send(200, "application/json", json.dumps(result).encode())
            except FileNotFoundError:
                return self._send(404, "text/plain", b"not found")
            except Exception as e:
                return self._send(502, "text/plain", str(e).encode())
        self._send(404, "text/plain", b"not found")

    def do_DELETE(self):
        route = _api_route(urlparse(self.path).path)
        if route is not None and len(route) == 2 and route[0] == "blocks":
            try:
                delete_block_safe(route[1])
                return self._send(200, "application/json", json.dumps({"ok": True}).encode())
            except Exception as e:
                return self._send(502, "text/plain", str(e).encode())
        self._send(404, "text/plain", b"not found")


if __name__ == "__main__":
    os.makedirs(AUDIO, exist_ok=True)
    if not os.path.exists(CFG):
        save_cfg(DEFAULT)
    # Reboot recovery: if a block was still queued when the box went down,
    # resume it. writ-stream is already airing the static loop (it's the
    # enabled fallback), and the player re-renders at air time, so resuming
    # a pre-reboot queue is safe.
    try:
        if block_render.load_queue() and not _player_active():
            _start_player()
    except Exception:
        pass
    threading.Thread(target=_scheduler_tick, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
