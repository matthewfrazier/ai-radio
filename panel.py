#!/usr/bin/env python3
"""Minimal control panel for the ai-radio WRIT-FM radio.

Exposes the knobs that actually shape the broadcast — Kokoro endpoint, voice,
speed, and the script the DJ reads — auditions voices in-page, then re-renders
through Kokoro and restarts the Icecast stream. Zero deps (stdlib only)."""
import glob
import html
import json
import os
import re
import socket
import subprocess
import queue
import threading
import time
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from tts_engines import kokoro_voices, kokoro_speech
import block_presets
import block_render
import blocks_page
import browse_page
import day_page
import day_program
import hour_templates
import jellyfin_client
import live_source
import llm_backends
import music_browser
import now_page
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


# Icecast serves each new listener a burst of buffered audio on connect
# (burst-size in icecast.xml), so the stream a listener hears trails what the
# player is feeding the mount by burst_bytes / byte_rate. The mount is MP3 128k
# (see block_player Sink). This is the server-side floor of "behind live"; the
# listener's own player adds a variable client-side jitter buffer on top, which
# /now measures in the browser when playing locally.
_STREAM_BURST_BYTES = 65536      # icecast.xml <burst-size>
_STREAM_BYTE_RATE = 128000 / 8   # 128 kbps mount
_STREAM_BUFFER_S = round(_STREAM_BURST_BYTES / _STREAM_BYTE_RATE, 1)


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
        # Icecast's status-json HTML-encodes non-ASCII in the title (em-dash ->
        # &#8212;, accents -> &#nnn;); decode so /now shows real characters.
        # (Direct listeners and Cast read the raw ICY title, unaffected.)
        return {"live": True, "listeners": m.get("listeners", 0),
                "buffer_s": _STREAM_BUFFER_S,
                "title": html.unescape(m.get("title") or m.get("server_name", ""))}
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
<div class="sub">ai-radio &middot; <a href="/blocks">blocks</a> &middot; <a href="/day">24-hour day</a> &middot; <a href="/now">▶ now · listen · cast</a></div>

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
PANEL_UNIT = "writ-panel.service"
PLAYER_STATE_FILE = os.path.join(BASE, "player_state.json")


def _log_cast(msg):
    # goes to writ-panel journald; surfaced in the /now run log alongside the
    # player's own events so cast outcomes are visible where the operator looks.
    print("cast: %s" % msg, flush=True)


CAST_PY = os.path.join(BASE, ".venv-cast", "bin", "python")
CAST_CTL = os.path.join(BASE, "cast_ctl.py")
# The active cast target, persisted so /now can restore its output state on a
# page refresh (casting is device-side and outlives the browser session).
CAST_TARGET_FILE = os.path.join(BASE, "cast_target.json")
# Cached device list so a page load (or many) doesn't trigger an ~8s LAN scan
# every time -- devices rarely change. The Rescan button forces a fresh scan.
CAST_DEVICES_FILE = os.path.join(BASE, "cast_devices.json")
CAST_DEVICES_TTL = 600


def cast_devices(refresh=False):
    if not refresh:
        try:
            with open(CAST_DEVICES_FILE) as f:
                c = json.load(f)
            if isinstance(c.get("devices"), list) and time.time() - c.get("ts", 0) < CAST_DEVICES_TTL:
                return c["devices"]
        except Exception:
            pass
    r = _cast("list")
    if isinstance(r, list):
        try:
            tmp = CAST_DEVICES_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"ts": time.time(), "devices": r}, f)
            os.replace(tmp, CAST_DEVICES_FILE)
        except OSError:
            pass
    return r


def _cast_target_read():
    try:
        with open(CAST_TARGET_FILE) as f:
            return json.load(f)
    except Exception:
        return None


def _cast_target_write(d):
    try:
        tmp = CAST_TARGET_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(d, f)
        os.replace(tmp, CAST_TARGET_FILE)
    except OSError:
        pass


def _cast_target_clear():
    try:
        os.remove(CAST_TARGET_FILE)
    except OSError:
        pass


def _lan_ip():
    # the box's LAN (192.168.x) address -- Cast devices fetch the stream from
    # here, and they're not on the tailnet, so the tailnet URL won't do.
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.168.1.1", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def _cast_stream_url():
    return "http://%s:8000/stream" % _lan_ip()  # /stream is MP3 -> Cast-compatible


def _cast(*args, timeout=40):
    if not os.path.exists(CAST_PY):
        return {"error": "cast not installed (.venv-cast missing)"}
    try:
        p = subprocess.run([CAST_PY, CAST_CTL, *args], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"state": "failed", "hint": "the speaker didn't respond in time -- it may be "
                "asleep or off. Wake it (tap the screen / Home app) and try again."}
    try:
        return json.loads(p.stdout.strip() or "{}")
    except Exception:
        return {"error": (p.stdout or p.stderr or "cast error").strip()[:200]}


# Repeated cast attempts to one uuid within a short window escalate the connect
# budget -- a stubborn speaker often connects on a later, longer, try.
_cast_attempts = {}


def _cast_device(uuid):
    """Cached host/port/model/name for a uuid so cast_ctl can cold-start
    (connect straight to the last-known address) instead of waiting on mDNS."""
    for d in (cast_devices() or []):
        if isinstance(d, dict) and d.get("uuid") == uuid:
            host, _, port = (d.get("host") or "").rpartition(":")
            return host, port, d.get("model") or "", d.get("name") or ""
    return "", "", "", ""


def _cast_budget(uuid):
    now = time.time()
    hist = [t for t in _cast_attempts.get(uuid, []) if now - t < 90] + [now]
    _cast_attempts[uuid] = hist
    return min(12 + (len(hist) - 1) * 6, 24)  # 12s, 18s, 24s cap, within a 90s window


_JF_TOKEN = {}  # cached (base, tok, uid) so browse endpoints don't re-auth per request


def _jf_creds():
    now = time.time()
    if _JF_TOKEN and now - _JF_TOKEN["at"] < 600:
        return _JF_TOKEN["base"], _JF_TOKEN["tok"], _JF_TOKEN["uid"]
    # force a genuine re-mint past the TTL so the panel recovers if its token was
    # invalidated out of band -- safe now that DeviceId is per-process (this only
    # rotates the PANEL's own token, never the player's in-flight music URLs).
    base, tok, uid = jellyfin_client.auth(force=True)
    _JF_TOKEN.update(base=base, tok=tok, uid=uid, at=now)
    return base, tok, uid


def _with_urls(recs):
    """Copy each browse record and attach a playable Jellyfin stream URL (never
    mutate music_browser's cached records with an expiring token)."""
    try:
        base, tok, _ = _jf_creds()
        return [dict(r, url=jellyfin_client.track_url(base, tok, r["id"])) for r in recs]
    except Exception:
        return [dict(r) for r in recs]


# --- live on-air state -------------------------------------------------------
# The panel OWNS the live state in memory. The player pushes an event on every
# transition (render-start / segment-start / each track boundary / idle) to
# POST /api/player/state; the panel fans it out to /now over SSE. The file is
# only a restart-recovery snapshot the panel writes -- never the live channel.
_PLAYER_STATE = {}
_STATE_LOCK = threading.Lock()
_STATE_SUBS = set()   # a queue.Queue per open SSE connection
_LAST_PUSH = 0.0
try:
    with open(PLAYER_STATE_FILE) as _f:
        _PLAYER_STATE = json.load(_f)
        _LAST_PUSH = time.time() - 6  # trust the snapshot briefly; heartbeat re-confirms
except Exception:
    pass


def _persist_state(st):
    try:
        tmp = PLAYER_STATE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(st, f)
        os.replace(tmp, PLAYER_STATE_FILE)
    except OSError:
        pass


def now_state():
    """Everything /now needs: the live in-memory player state + stream/queue/cast.
    `player_active` is push-freshness -- the player heartbeats every 5s, so a
    state older than 12s (or never seen) means it isn't on air."""
    with _STATE_LOCK:
        st = dict(_PLAYER_STATE)
    active = bool(_LAST_PUSH and time.time() - _LAST_PUSH < 12)
    return {"player_active": active, "state": st,
            "queue": block_render.load_queue(), "stream": icecast_status(),
            "stream_url": STREAM_URL, "cast": _cast_target_read()}


def _receive_state(st):
    """A push from the player: become the new authority, persist, fan out."""
    global _PLAYER_STATE, _LAST_PUSH
    with _STATE_LOCK:
        _PLAYER_STATE = st or {}
        _LAST_PUSH = time.time()
        subs = list(_STATE_SUBS)
    _persist_state(st or {})
    payload = now_state()
    for q in subs:
        try:
            q.put_nowait(payload)
        except queue.Full:
            pass


def _now_ticker():
    """Refresh ambient fields (listeners/cast/queue) for open streams and act as
    the SSE keepalive; on-air changes arrive instantly via the player push."""
    while True:
        time.sleep(4)
        with _STATE_LOCK:
            subs = list(_STATE_SUBS)
        if not subs:
            continue
        payload = now_state()
        for q in subs:
            try:
                q.put_nowait(payload)
            except queue.Full:
                pass


def _api_route(path):
    """Path segments after '/api/', tolerating a tailscale-serve mount prefix
    (same reason the existing routes above match via .endswith())."""
    idx = path.find("/api/")
    if idx == -1:
        return None
    return path[idx + len("/api/"):].strip("/").split("/")


def _player_active():
    return subprocess.run(["systemctl", "is-active", "--quiet", PLAYER_UNIT]).returncode == 0


def player_log(n=30):
    """Recent station events for the /now run log, so the operator can see WHY
    the stream did what it did: player narrative ('block_player:' -- cutover,
    render/filler, idle, drain) merged with cast outcomes ('cast:' from the
    panel), sorted by time. Both units log to journald on this host."""
    out = []
    for unit, needle in ((PLAYER_UNIT, "block_player:"), (PANEL_UNIT, "cast:")):
        try:
            p = subprocess.run(
                ["journalctl", "-u", unit, "-n", "300", "--no-pager", "-o", "short-iso"],
                capture_output=True, text=True, timeout=5)
            for ln in p.stdout.splitlines():
                if needle not in ln:
                    continue
                # "2026-07-18T20:01:02+0000 host unit[pid]: <needle> msg"
                out.append({"ts": ln[:19], "t": ln[11:19], "m": ln.split(needle, 1)[1].strip()})
        except Exception as e:
            out.append({"ts": "", "t": "", "m": "%s log unavailable: %s" % (unit, e)})
    out.sort(key=lambda r: r["ts"])
    return [{"t": r["t"], "m": r["m"]} for r in out[-n:]]


def _start_player():
    # systemd's Conflicts= stops the static writ-stream loop for us.
    subprocess.run(["systemctl", "start", PLAYER_UNIT], capture_output=True)


def _cutover_player():
    # SIGHUP = "abandon current block, re-read the queue" -- an in-process
    # cutover that avoids stopping the unit (which would flap writ-stream).
    # --kill-who=main is REQUIRED: the default control-group kill broadcasts
    # SIGHUP to every process in the unit, including the persistent sink
    # ffmpeg, which terminates on SIGHUP -> the Icecast source drops for ~1.5s
    # mid-cutover and any Cast receiver quits. Only the main python loop must
    # get the signal (it handles it as "re-read the queue").
    subprocess.run(["systemctl", "kill", "--kill-who=main", "-s", "HUP", PLAYER_UNIT],
                   capture_output=True)


def schedule_block(block_id, mode, prerender=True, start_index=0):
    # prerender surfaces resolve/render errors in the UI immediately (the
    # /blocks schedule button wants that). The /now live switcher passes
    # prerender=False so the cutover POST returns fast -- the player does the
    # single air-time render either way, so this just avoids a wasteful double
    # render and a ~13s blocking request.
    if prerender:
        block_render.render_block(block_id, force=False)
    if mode == "now":
        # play-now-at-segment: record the start segment before overwriting the
        # queue so the player begins this block partway in (per-segment ▶ / scrub).
        block_render.set_cutover(block_id, start_index)
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

    def _sse_now(self):
        """Server-Sent Events stream of the live now-payload. Sends the current
        state on connect, then every push/refresh; the handler thread blocks here
        for the life of the connection (ThreadingHTTPServer gives it its own)."""
        q = queue.Queue(maxsize=16)
        with _STATE_LOCK:
            _STATE_SUBS.add(q)
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")  # don't let a proxy buffer it
            self.end_headers()
            self.wfile.write(b"retry: 3000\n\n")
            self._sse_send(now_state())
            while True:
                try:
                    payload = q.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b": ka\n\n")  # keepalive comment
                    self.wfile.flush()
                    continue
                self._sse_send(payload)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass  # client went away
        finally:
            with _STATE_LOCK:
                _STATE_SUBS.discard(q)

    def _sse_send(self, payload):
        self.wfile.write(b"data: " + json.dumps(payload).encode() + b"\n\n")
        self.wfile.flush()

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
        if "/api/" not in u.path and u.path.rstrip("/").endswith("/day"):
            return self._send(200, "text/html; charset=utf-8", day_page.DAY_PAGE.encode())
        if "/api/" not in u.path and u.path.rstrip("/").endswith("/now"):
            return self._send(200, "text/html; charset=utf-8", now_page.NOW_PAGE.encode())
        if "/api/" not in u.path and u.path.rstrip("/").endswith("/browse"):
            return self._send(200, "text/html; charset=utf-8", browse_page.BROWSE_PAGE.encode())
        if u.path.rstrip("/").endswith("/api/now/stream"):
            return self._sse_now()

        route = _api_route(u.path)
        if route is not None:
            try:
                if route == ["blocks"]:
                    return self._send(200, "application/json", json.dumps(block_render.list_blocks()).encode())
                if route == ["live_sources"]:
                    return self._send(200, "application/json", json.dumps(live_source.load_sources()).encode())
                if route == ["schedule"]:
                    return self._send(200, "application/json", json.dumps({"entries": block_render.load_schedule()}).encode())
                if route == ["now"]:
                    return self._send(200, "application/json", json.dumps(now_state()).encode())
                if route == ["log"]:
                    return self._send(200, "application/json", json.dumps(player_log()).encode())
                if route == ["presets"]:
                    return self._send(200, "application/json", json.dumps(block_presets.preset_menu()).encode())
                if route == ["cast", "devices"]:
                    refresh = parse_qs(u.query).get("refresh", ["0"])[0] in ("1", "true")
                    return self._send(200, "application/json", json.dumps(cast_devices(refresh)).encode())
                if len(route) == 2 and route[0] == "day":
                    return self._send(200, "application/json", json.dumps(day_program.day_summary(route[1])).encode())
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
                if route == ["browse", "meta"]:
                    return self._send(200, "application/json", json.dumps(music_browser.facets()).encode())
                if route == ["browse", "search"]:
                    q = parse_qs(u.query).get("q", [""])[0]
                    return self._send(200, "application/json", json.dumps({"results": _with_urls(music_browser.search(q))}).encode())
                if route == ["browse", "random"]:
                    r = music_browser.random_track()
                    return self._send(200, "application/json", json.dumps(_with_urls([r])[0] if r else None).encode())
                if len(route) == 3 and route[0] == "browse" and route[1] == "track":
                    r = music_browser.get(route[2])
                    if not r:
                        return self._send(404, "text/plain", b"not found")
                    return self._send(200, "application/json", json.dumps(_with_urls([r])[0]).encode())
                if len(route) == 3 and route[0] == "browse" and route[1] == "similar":
                    q = parse_qs(u.query)
                    moods = q.get("moods", [""])[0]
                    res = music_browser.similar(
                        route[2], k=int(q.get("k", ["40"])[0]),
                        studio_only=q.get("studio", ["1"])[0] not in ("0", "false"),
                        era=(q.get("era", [""])[0] or None),
                        moods=(moods.split(",") if moods else None))
                    return self._send(200, "application/json", json.dumps(
                        {"seed": music_browser.get(route[2]), "results": _with_urls(res)}).encode())
            except FileNotFoundError:
                return self._send(404, "text/plain", b"not found")
            except Exception as e:
                return self._send(502, "text/plain", str(e).encode())
        self._send(404, "text/plain", b"not found")

    def do_POST(self):
        u = urlparse(self.path)
        if u.path.endswith("/api/player/state"):
            # Internal: the player publishes its live on-air state here. Localhost
            # only -- nobody on the LAN gets to spoof what's on air.
            if (self.client_address or ("",))[0] not in ("127.0.0.1", "::1", "localhost"):
                return self._send(403, "text/plain", b"forbidden")
            n = int(self.headers.get("Content-Length", 0) or 0)
            body = json.loads(self.rfile.read(n) or b"{}") if n else {}
            _receive_state(body)
            return self._send(200, "application/json", b'{"ok":true}')
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
                if len(route) == 3 and route[0] == "day" and route[2] == "generate":
                    today = datetime.now().strftime("%Y-%m-%d")
                    result = day_program.generate_day(route[1], body.get("template", "standard_hour"),
                                                       body.get("opts"), today=today)
                    return self._send(200, "application/json", json.dumps(result).encode())
                if route == ["cast", "start"]:
                    uuid = body["uuid"]
                    host, port, model, name = _cast_device(uuid)
                    budget = _cast_budget(uuid)
                    r = _cast("start", uuid, _cast_stream_url(), "audio/mpeg",
                              host, port, model, name, str(budget), timeout=budget * 2 + 30)
                    ok = r.get("state") in ("PLAYING", "BUFFERING")
                    _log_cast("start %s -> %s%s" % (
                        r.get("name") or body.get("uuid", "?"), r.get("state") or r.get("error") or "?",
                        (" [%s]" % r["hint"]) if r.get("hint") else ""))
                    if ok:
                        _cast_target_write({"uuid": r.get("uuid"), "name": r.get("name")})
                    return self._send(200, "application/json", json.dumps(r).encode())
                if route == ["cast", "stop"]:
                    r = _cast("stop", body["uuid"])
                    _log_cast("stop %s" % (r.get("name") or body.get("uuid", "?")))
                    _cast_target_clear()
                    return self._send(200, "application/json", json.dumps(r).encode())
                if route == ["station"]:
                    cfg = load_cfg()
                    for k in ("weather_location", "recap_llm_backend", "recap_llm_model"):
                        if k in body:
                            cfg[k] = body[k]
                    save_cfg(cfg)
                    return self._send(200, "application/json", json.dumps(
                        {"ok": True, "weather_location": cfg.get("weather_location", ""),
                         "recap_llm_backend": cfg.get("recap_llm_backend", "")}).encode())
                if len(route) == 3 and route[0] == "day" and route[2] == "bulk":
                    r = day_program.bulk_edit(route[1], body["field"], body["value"], body.get("hours"))
                    if body["field"] == "weather_location":
                        cfg = load_cfg()  # persist as the station default for future days
                        cfg["weather_location"] = body["value"]
                        save_cfg(cfg)
                    return self._send(200, "application/json", json.dumps(r).encode())
                if len(route) == 4 and route[0] == "day" and route[2] == "hour":
                    block = day_program.patch_hour(route[1], route[3], body)
                    return self._send(200, "application/json", json.dumps(block).encode())
                if route == ["llm_test"]:
                    text = llm_backends.generate(body["backend"], body["model"], body["prompt"])
                    return self._send(200, "application/json", json.dumps({"text": text}).encode())
                if route == ["blocks", "preset"]:
                    preset = body.get("preset", "")
                    if preset not in block_presets.PRESETS:
                        return self._send(400, "text/plain", ("unknown preset: %s" % preset).encode())
                    cfg = block_render.load_station_cfg()
                    opts = dict(body.get("opts") or {})
                    opts.setdefault("weather_location", cfg.get("weather_location", ""))
                    opts.setdefault("voice", cfg.get("voice", ""))
                    opts.setdefault("llm_backend", cfg.get("recap_llm_backend", ""))
                    opts.setdefault("llm_model", cfg.get("recap_llm_model", ""))
                    segs = block_presets.build_preset(preset, opts)
                    label = block_presets.PRESETS[preset]["label"]
                    title = body.get("title") or ("%s · %s" % (label, datetime.now().strftime("%b %-d %H:%M")))
                    block = block_render.create_block_from_segments(
                        title, segs, template={"name": preset, "preset": True})
                    return self._send(200, "application/json", json.dumps(block).encode())
                if route == ["blocks", "from_template"]:
                    template = body.get("template", "standard_hour")
                    builder = hour_templates.TEMPLATES.get(template)
                    if not builder:
                        return self._send(400, "text/plain", ("unknown template: %s" % template).encode())
                    hour = int(body.get("hour", datetime.now().hour))
                    segs = builder(hour, body.get("opts"))
                    title = body.get("title") or ("%s %02d:00" % (template, hour))
                    block = block_render.create_block_from_segments(
                        title, segs, template={"name": template, "hour": hour})
                    return self._send(200, "application/json", json.dumps(block).encode())
                if route == ["blocks", "save_as"]:
                    # Clone the (edited) segments into a fresh auto-named block.
                    title = body.get("title") or ("Block · " + datetime.now().strftime("%b %-d %H:%M"))
                    block = block_render.create_block_from_segments(title, body.get("segments", []))
                    return self._send(200, "application/json", json.dumps(block).encode())
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
                    result = schedule_block(route[1], body.get("mode", "queue"),
                                            prerender=body.get("prerender", True),
                                            start_index=int(body.get("start_index", 0)))
                    return self._send(200, "application/json", json.dumps(result).encode())
                if route == ["browse", "navigate"]:
                    filt = body.get("filters") or {}
                    res = music_browser.nearest(
                        body["vec"], k=int(body.get("k", 40)),
                        studio_only=filt.get("studio_only", True),
                        era=filt.get("era") or None, moods=filt.get("moods") or None,
                        themes=filt.get("themes") or None, exclude=body.get("exclude") or None)
                    return self._send(200, "application/json", json.dumps({"results": _with_urls(res)}).encode())
                if route == ["browse", "build"]:
                    # Air a hand-picked crate: one music segment with an explicit
                    # track_ids list (resolve_music_segment builds the playlist).
                    ids = body.get("track_ids") or []
                    if not ids:
                        return self._send(400, "text/plain", b"no track_ids")
                    title = body.get("title") or ("Crate · " + datetime.now().strftime("%b %-d %H:%M"))
                    seg = {"id": "music_1", "role": "music_1", "type": "music",
                           "params": {"track_ids": ids, "duration_s": int(body.get("duration_s") or 0)}}
                    block = block_render.create_block_from_segments(title, [seg])
                    air = body.get("air")
                    if air in ("now", "queue"):
                        schedule_block(block["id"], air, prerender=False)
                    return self._send(200, "application/json", json.dumps({"block": block, "aired": air}).encode())
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
        if route is not None and len(route) == 2 and route[0] == "day":
            try:
                return self._send(200, "application/json", json.dumps(day_program.delete_day(route[1])).encode())
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
    threading.Thread(target=_now_ticker, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
