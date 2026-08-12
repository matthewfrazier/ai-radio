#!/usr/bin/env python3
"""Google Cast control for the station, run in its own venv (.venv-cast, which
has pychromecast -- a heavy non-stdlib dep). panel.py shells out to this like
it does jf_source.py, so the stdlib-only panel process never imports
pychromecast. Speaker groups are just cast endpoints with cast_type "group",
so they work through the same path.

Connecting to Nest displays is the fussy part: an asleep/moved Nest Hub keeps
answering mDNS (so discovery still lists it) but DROPS TCP on 8009 -- a plain
cc.wait() then hangs the whole budget and returns a cryptic timeout. So start:
  1. fast TCP reachability probe on the last-known address -> if dead, one fresh
     re-discovery (catches a moved IP), else FAIL FAST with a 'wake it' hint;
  2. cold-start by connecting the socket DIRECTLY to the reachable address
     (wakes a drowsy device better than waiting on mDNS), retried once;
  3. nudge play() until the receiver leaves IDLE/PAUSED.
The connect budget is caller-supplied so the panel can escalate it on repeated
attempts within a short window.

Commands (all print JSON to stdout):
  list                                           discover devices + groups
  start <uuid> <url> <ctype> [host port model name budget stream_type title]
                                                 cast a URL to one endpoint
  stop  <uuid>                                   stop casting on one endpoint
  status <uuid> [host port]                      player state (direct addr = fast poll)
"""
import json
import socket
import sys
import time
import uuid as uuidlib

import pychromecast

DISCOVERY_TIMEOUT = 10   # mDNS discovery
CONNECT_TIMEOUT = 12     # base socket handshake (cc.wait); escalated by the caller
PROBE_TIMEOUT = 4        # quick "is the device even reachable" TCP check


def _info(cc):
    ci = cc.cast_info
    return {"uuid": str(ci.uuid), "name": ci.friendly_name, "type": str(ci.cast_type),
            "model": ci.model_name, "host": "%s:%s" % (ci.host, ci.port)}


def _reachable(host, port, timeout=PROBE_TIMEOUT):
    """True if the device accepts a TCP connection. An asleep/off/moved Nest
    times out here (SYN dropped) even though mDNS still lists it."""
    try:
        s = socket.create_connection((host, int(port)), timeout=timeout)
        s.close()
        return True
    except OSError:
        return False


def _stop_browser(browser):
    if browser is None:
        return
    try:
        browser.stop_discovery()
    except Exception:
        pass


def _discover(target_uuid, timeout=DISCOVERY_TIMEOUT):
    casts, browser = pychromecast.get_listed_chromecasts(
        uuids=[uuidlib.UUID(target_uuid)], timeout=timeout)
    return (casts[0] if casts else None), browser


def _direct(target_uuid, host, port, model, name):
    """Connect straight to a known address, skipping mDNS -- faster and wakes a
    drowsy device more reliably than waiting for it to answer discovery."""
    return pychromecast.get_chromecast_from_host(
        (host, int(port), uuidlib.UUID(target_uuid), model or "", name or ""))


def _asleep(target_uuid, name):
    return {"uuid": target_uuid, "name": name or target_uuid, "state": "failed",
            "hint": "device unreachable -- it's likely asleep or off. Wake it (tap the "
                    "screen / say 'Hey Google' / open the Home app), then try again."}


def cmd_list():
    casts, browser = pychromecast.get_chromecasts(timeout=DISCOVERY_TIMEOUT)
    out = sorted((_info(c) for c in casts), key=lambda d: (d["type"] != "group", d["name"]))
    _stop_browser(browser)
    return out


def cmd_start(target_uuid, url, ctype, host="", port="", model="", name="", budget=None,
              stream_type="LIVE", title="ai-radio"):
    b = max(int(budget), 6) if budget else CONNECT_TIMEOUT
    browser = None
    cc = None

    # 1) reachability: probe the known address; if dead, one fresh discovery in
    #    case it MOVED; reprobe only the new address; else fail fast (~4s) with a
    #    wake hint rather than reprobing the same dead address.
    if host and port and not _reachable(host, port):
        cc, browser = _discover(target_uuid)
        moved = cc is not None and (str(cc.cast_info.host), str(cc.cast_info.port)) != (str(host), str(port))
        if moved and _reachable(cc.cast_info.host, cc.cast_info.port):
            host, port = cc.cast_info.host, cc.cast_info.port  # relocated & now reachable
        else:
            _stop_browser(browser)
            return _asleep(target_uuid, name)

    # 2) connect: direct to the reachable address, else via discovery.
    if cc is None:
        if host and port:
            cc = _direct(target_uuid, host, port, model, name)
        else:
            cc, browser = _discover(target_uuid)
    if cc is None:
        raise RuntimeError("cast endpoint not found: %s" % target_uuid)

    # socket handshake, retried once -- the first attempt often wakes a drowsy
    # device so the second connects.
    for i in range(2):
        try:
            cc.wait(timeout=b)
            break
        except Exception:
            if i == 1:
                _stop_browser(browser)
                return {"uuid": target_uuid, "name": name or cc.name, "state": "failed",
                        "hint": "the device answered discovery but not the connection in time "
                                "-- try again (it may have just woken up)."}

    mc = cc.media_controller
    mc.play_media(url, content_type=ctype, stream_type=stream_type, title=title)
    mc.block_until_active(timeout=min(b, 12))
    # poll for the player to accept the media (BUFFERING/PLAYING). Receivers
    # load LIVE media but sit in PAUSED/IDLE for ~1s until told to play, and a
    # single early play() fires before the receiver is ready and is silently
    # dropped -- leaving it stuck IDLE. So nudge play() on EVERY idle/paused
    # poll until it starts. A real load failure (IDLE + idle_reason=ERROR)
    # can't be nudged out of -- stop early.
    state = mc.status.player_state
    for _ in range(40):
        state = mc.status.player_state
        if state in ("PLAYING", "BUFFERING"):
            break
        if state == "IDLE" and mc.status.idle_reason == "ERROR":
            break
        if state in ("PAUSED", "IDLE"):
            try:
                mc.play()
            except Exception:
                pass
        time.sleep(0.25)
    result = {"uuid": target_uuid, "name": cc.name, "state": state,
              "idle_reason": mc.status.idle_reason}
    if state not in ("PLAYING", "BUFFERING") and cc.status.app_id is None:
        # the media receiver never launched -- almost always because this is
        # an individual member of a speaker group (Google returns
        # LAUNCH_ERROR NOT_ALLOWED); cast to the group instead.
        result["state"] = "failed"
        result["hint"] = "cast not allowed on this endpoint -- if it's a group member, cast to its group"
    elif state == "IDLE" and mc.status.idle_reason == "ERROR":
        result["state"] = "failed"
        result["hint"] = "the device could not play the stream (reachable? format?) -- try again or Rescan"
    _stop_browser(browser)
    return result


def cmd_stop(target_uuid):
    cc, browser = _discover(target_uuid)
    if cc is None:
        raise RuntimeError("cast endpoint not found: %s" % target_uuid)
    cc.wait(timeout=CONNECT_TIMEOUT)
    try:
        cc.media_controller.stop()
    except Exception:
        pass
    cc.quit_app()
    name = cc.name
    _stop_browser(browser)
    return {"uuid": target_uuid, "name": name, "stopped": True}


def cmd_status(target_uuid, host="", port=""):
    # A known address connects directly (~1s) -- polling callers (the playlist
    # caster) can't afford a 10s mDNS discovery per status check.
    browser = None
    if host and port:
        cc = _direct(target_uuid, host, port, "", "")
    else:
        cc, browser = _discover(target_uuid)
    if cc is None:
        raise RuntimeError("cast endpoint not found: %s" % target_uuid)
    cc.wait(timeout=CONNECT_TIMEOUT)
    st = cc.media_controller.status
    result = {"uuid": target_uuid, "name": cc.name, "state": st.player_state,
              "title": st.title, "content_id": st.content_id}
    _stop_browser(browser)
    return result


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "list"
    try:
        if cmd == "list":
            out = cmd_list()
        elif cmd == "start":
            out = cmd_start(argv[2], argv[3], argv[4],
                            host=argv[5] if len(argv) > 5 else "",
                            port=argv[6] if len(argv) > 6 else "",
                            model=argv[7] if len(argv) > 7 else "",
                            name=argv[8] if len(argv) > 8 else "",
                            budget=argv[9] if len(argv) > 9 else None,
                            stream_type=argv[10] if len(argv) > 10 else "LIVE",
                            title=argv[11] if len(argv) > 11 else "ai-radio")
        elif cmd == "stop":
            out = cmd_stop(argv[2])
        elif cmd == "status":
            out = cmd_status(argv[2],
                             host=argv[3] if len(argv) > 3 else "",
                             port=argv[4] if len(argv) > 4 else "")
        else:
            out = {"error": "unknown command: %s" % cmd}
        print(json.dumps(out))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
