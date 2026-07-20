#!/usr/bin/env python3
"""Prune same-recording duplicate tracks from the Jellyfin library, keeping the
best copy per song (studio > tagged album > longer > has-year). DRY-RUN by
default -- writes a manifest and deletes nothing. Pass --apply to delete. Only
touches groups whose copies match on duration AND audio features (the "safe"
set); live/alternate takes are never pruned. A library backup is assumed.

  python3 prune_dupes.py            # dry-run: write manifest + counts
  python3 prune_dupes.py --apply    # delete the prune set (probes one first)

The manifest (keep + pruned copies per group) is kept at dedup_manifest.json so
any deletion can be reversed from the backup.
"""
import json
import sys

import jellyfin_client as jc
import music_browser as mb

MANIFEST = "/opt/writ-fm/dedup_manifest.json"


def main(apply):
    plan = mb.safe_prune_plan()
    with open(MANIFEST, "w") as f:
        json.dump(plan["manifest"], f)
    print("safe duplicate groups: %d | keep %d | prune %d"
          % (plan["groups"], plan["keep"], plan["prune"]), flush=True)
    print("manifest -> %s" % MANIFEST, flush=True)
    ids = plan["prune_ids"]
    if not apply:
        print("DRY-RUN: nothing deleted. Re-run with --apply to prune.", flush=True)
        return 0
    if not ids:
        print("nothing to prune.")
        return 0
    base, tok, _uid = jc.auth()
    # Probe a single deletion first -- if the account can't delete, stop here
    # rather than failing 3000 times.
    try:
        jc.delete_item(base, tok, ids[0])
    except Exception as e:
        print("ABORT: delete probe failed (account may lack delete permission): %s" % e)
        return 1
    done = fail = 1
    fail = 0
    for tid in ids[1:]:
        try:
            jc.delete_item(base, tok, tid)
            done += 1
        except Exception as e:
            fail += 1
            if fail <= 5:
                print("  fail %s: %s" % (tid, str(e)[:80]), flush=True)
        if (done + fail) % 250 == 0:
            print("  %d/%d done (%d failed)" % (done, len(ids), fail), flush=True)
    print("pruned %d of %d (%d failed). manifest kept for restore: %s"
          % (done, len(ids), fail, MANIFEST), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main("--apply" in sys.argv))
