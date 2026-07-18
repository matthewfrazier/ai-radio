#!/usr/bin/env python3
"""Google Cast control for the station, run in its own venv (.venv-cast, which
has pychromecast -- a heavy non-stdlib dep). panel.py shells out to this like
it does jf_source.py, so the stdlib-only panel process never imports
pychromecast. Speaker groups are just cast endpoints with cast_type "group",
so they work through the same path.

Commands (all print JSON to stdout):
  list                          discover devices + groups on the LAN
  start <uuid> <url> <ctype>    cast a media URL to one endpoint (live stream)
  stop  <uuid>                  stop casting on one endpoint
  status <uuid>                 player state of one endpoint
"""
import json
import sys
import time
import uuid as uuidlib

import pychromecast

DISCOVERY_TIMEOUT = 8


def _info(cc):
    ci = cc.cast_info
    return {"uuid": str(ci.uuid), "name": ci.friendly_name, "type": str(ci.cast_type),
            "model": ci.model_name, "host": "%s:%s" % (ci.host, ci.port)}


def _all():
    casts, browser = pychromecast.get_chromecasts(timeout=DISCOVERY_TIMEOUT)
    return casts, browser


def _one(target_uuid):
    casts, browser = pychromecast.get_listed_chromecasts(
        uuids=[uuidlib.UUID(target_uuid)], timeout=DISCOVERY_TIMEOUT)
    cc = casts[0] if casts else None
    return cc, browser


def _stop_browser(browser):
    try:
        browser.stop_discovery()
    except Exception:
        pass


def cmd_list():
    casts, browser = _all()
    out = sorted((_info(c) for c in casts), key=lambda d: (d["type"] != "group", d["name"]))
    _stop_browser(browser)
    return out


def cmd_start(target_uuid, url, ctype):
    cc, browser = _one(target_uuid)
    if cc is None:
        raise RuntimeError("cast endpoint not found: %s" % target_uuid)
    cc.wait(timeout=DISCOVERY_TIMEOUT)
    mc = cc.media_controller
    mc.play_media(url, content_type=ctype, stream_type="LIVE", title="ai-radio")
    mc.block_until_active(timeout=DISCOVERY_TIMEOUT)
    # poll for the player to accept the media (BUFFERING/PLAYING). Receivers
    # load LIVE media but sit in PAUSED/IDLE for ~1s until told to play, and a
    # single early play() fires before the receiver is ready and is silently
    # dropped -- leaving it stuck IDLE (the "could not cast (state IDLE)" bug).
    # So nudge play() on EVERY idle/paused poll until it starts. A real load
    # failure (IDLE + idle_reason=ERROR) can't be nudged out of -- stop early.
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
    cc, browser = _one(target_uuid)
    if cc is None:
        raise RuntimeError("cast endpoint not found: %s" % target_uuid)
    cc.wait(timeout=DISCOVERY_TIMEOUT)
    try:
        cc.media_controller.stop()
    except Exception:
        pass
    cc.quit_app()
    name = cc.name
    _stop_browser(browser)
    return {"uuid": target_uuid, "name": name, "stopped": True}


def cmd_status(target_uuid):
    cc, browser = _one(target_uuid)
    if cc is None:
        raise RuntimeError("cast endpoint not found: %s" % target_uuid)
    cc.wait(timeout=DISCOVERY_TIMEOUT)
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
            out = cmd_start(argv[2], argv[3], argv[4])
        elif cmd == "stop":
            out = cmd_stop(argv[2])
        elif cmd == "status":
            out = cmd_status(argv[2])
        else:
            out = {"error": "unknown command: %s" % cmd}
        print(json.dumps(out))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
