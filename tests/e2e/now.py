#!/usr/bin/env python3
"""Browser-driven checks for the /now Labs surface, run against the fleet's
shared Playwright server (no local Chromium). This closes the gap where nothing
exercised the /now page in CI -- the stdlib unittest suite can't click a tab.

It connects a Playwright client to the hub browser and drives it against a
running panel, asserting the four reliability flows the operator relies on:
  1. what's airing is shown (now-card present) + playback/status controls sit
     in the viewport WITHOUT scrolling,
  2. skip/pause/play + output controls are reachable,
  3. selecting a segment populates the Details tab,
  4. setting/tapping a block loads it as the active block in the Editor.

Not a unittest (needs network + the hub); run manually / from a UX pass:
  PW_WS=ws://playwright-test.tailbe5094.ts.net:3000/ \\
  NOW_URL=http://100.108.249.107:8080/now \\
  SHOT_DIR=/tmp/now-shots  python tests/e2e/now.py
Exits non-zero if any hard check fails.
"""
import os
import sys

from playwright.sync_api import sync_playwright

WS = os.environ.get("PW_WS", "ws://playwright-test.tailbe5094.ts.net:3000/")
URL = os.environ.get("NOW_URL", "http://100.108.249.107:8080/now")
SHOT_DIR = os.environ.get("SHOT_DIR", "/tmp/now-shots")
VP = {"width": 390, "height": 844}  # a phone -- the primary device


def main():
    os.makedirs(SHOT_DIR, exist_ok=True)
    checks = []

    def check(name, cond):
        checks.append((name, bool(cond)))
        print(("  ok  " if cond else " FAIL ") + name, flush=True)

    with sync_playwright() as p:
        browser = p.chromium.connect(WS)
        page = browser.new_page(viewport=VP)
        cerr = []
        page.on("console", lambda m: cerr.append(m.text) if m.type == "error" else None)
        page.goto(URL, wait_until="networkidle")

        # 1. monitor + controls visible without scrolling
        check("now-card present", page.locator("#now").count() == 1)
        check("no console errors", len(cerr) == 0)
        vh = VP["height"]
        for cid in ("statusbar", "btnPrev", "btnNext", "btnOut", "btnAirActive"):
            box = page.locator("#" + cid).bounding_box()
            inview = box is not None and box["y"] >= -2 and (box["y"] + box["height"]) <= vh + 2
            check("%s in viewport (no scroll)" % cid, inview)

        # output is mode-gated: the local <audio> shows only when playing here;
        # while casting it's hidden and cast-details take its place. Assert the
        # invariant (exactly one surface) rather than presuming a mode -- the
        # live station may be casting right now.
        player_vis = page.locator("#player").is_visible()
        cast_vis = page.locator("#castDetails").is_visible()
        # never both at once; the local <audio> shows ONLY when listening here.
        check("never both output surfaces at once", not (player_vis and cast_vis))
        if cast_vis:
            check("cast-details names the speaker", "Casting to" in page.locator("#castDetails").inner_text())

        # 2. tabs switch, order = most-specific -> most-general
        order = [t.get_attribute("data-tab") for t in page.locator(".tab").all()]
        check("tab order editor,details,list,gen", order == ["editor", "details", "list", "gen"])
        for tab in ("details", "list", "gen", "editor"):
            page.click('.tab[data-tab="%s"]' % tab)
            check("tab %s shows its panel" % tab, page.locator("#panel-" + tab).is_visible())

        # ensure an active block: prefer an existing one via the List tab
        page.click('.tab[data-tab="list"]')
        page.wait_for_timeout(400)
        check("New empty block button", page.locator("#btnNewBlock").is_visible())
        sets = page.locator("#blockList [data-set]")
        have_block = sets.count() > 0
        if have_block:
            check("blocks list has Set active + Delete",
                  page.locator("#blockList [data-delb]").count() > 0)
            # 4. Set active loads it into the Editor
            sets.first.click()
            page.wait_for_timeout(400)
            check("Set active switched to Editor tab", page.locator("#panel-editor").is_visible())
            check("Editor shows the active block title", page.locator("#btitle").count() == 1)

            # 3 + add-at-bottom: add buttons live below the segment list; a new
            # element appends at the end.
            addbar = page.locator("#addBar [data-add]")
            check("add-element buttons present (bottom bar)", addbar.count() == 3)
            before = page.locator("#blockView .seg").count()
            page.click('#addBar [data-add="music"]')
            page.wait_for_timeout(300)
            after = page.locator("#blockView .seg").count()
            check("add appends a segment at the bottom", after == before + 1)
            # selecting a segment opens Details populated for it
            page.locator("#blockView .seg .name[data-sel]").last.click()
            page.wait_for_timeout(300)
            check("segment select opens Details", page.locator("#panel-details").is_visible())
            check("Details renders the selected segment",
                  page.locator("#detailView .seg").count() == 1)
        else:
            print("  note: no blocks in library -- skipped editor/details/set-active flows")

        # screenshots for the UX pass
        page.click('.tab[data-tab="editor"]')
        page.wait_for_timeout(200)
        page.screenshot(path=os.path.join(SHOT_DIR, "now-editor.png"), full_page=True)
        page.click('.tab[data-tab="details"]')
        page.wait_for_timeout(200)
        page.screenshot(path=os.path.join(SHOT_DIR, "now-details.png"), full_page=True)
        page.click('.tab[data-tab="list"]')
        page.wait_for_timeout(200)
        page.screenshot(path=os.path.join(SHOT_DIR, "now-list.png"), full_page=True)
        # top-of-page (above the fold) shot on the phone viewport
        page.click('.tab[data-tab="editor"]')
        page.evaluate("window.scrollTo(0,0)")
        page.screenshot(path=os.path.join(SHOT_DIR, "now-abovefold.png"))
        browser.close()

    passed = sum(1 for _, ok in checks if ok)
    print("\n%d/%d checks passed. shots in %s" % (passed, len(checks), SHOT_DIR), flush=True)
    sys.exit(0 if passed == len(checks) else 1)


if __name__ == "__main__":
    main()
