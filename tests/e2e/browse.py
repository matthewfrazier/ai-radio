#!/usr/bin/env python3
"""Browser-driven checks for the /browse music page, run against the fleet's
shared Playwright server (no local Chromium). Exercises facet browse / search /
seed / axis-nudge / playlist queue-next. Cleans up after itself (deletes the
playlist it creates); does NOT click the on-air or cast buttons (those touch
the live station -- covered by curl + unit tests).

  PW_WS=ws://playwright-test.tailbe5094.ts.net:3000/ \\
  URL=http://100.108.249.107:8080/browse \\
  SHOT_DIR=/tmp/browse-shots  python tests/e2e/browse.py
"""
import os
import sys

from playwright.sync_api import sync_playwright

WS = os.environ.get("PW_WS", "ws://playwright-test.tailbe5094.ts.net:3000/")
URL = os.environ.get("URL", "http://100.108.249.107:8080/browse")
SHOT_DIR = os.environ.get("SHOT_DIR", "/tmp/browse-shots")
VP = {"width": 390, "height": 844}


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

        # facet-first: the page opens straight into a Browse listing.
        page.wait_for_selector("#brResults .res", timeout=15000)
        check("no console errors", len(cerr) == 0)
        check("browse listing on load", page.locator("#brResults .res").count() > 0)
        check("filters visible without a seed", page.locator("#eraChips .chip").count() > 0)

        # era filter narrows the browse listing (count line changes).
        total_before = page.locator("#brCount").inner_text()
        page.locator("#eraChips .chip").first.click()
        page.wait_for_timeout(600)
        check("era filter re-queries browse", page.locator("#brCount").inner_text() != total_before)
        page.locator("#eraChips .chip").first.click()  # clear it again
        page.wait_for_timeout(400)

        # surprise -> seed card + 6 axis sliders + similar list.
        page.click("#btnSurprise")
        page.wait_for_selector("#seedCard .title", timeout=15000)
        check("surprise seeds the vibe view", page.locator("#seedCard .title").count() == 1)
        check("6 axis sliders", page.locator("#axes input[type=range]").count() == 6)
        page.wait_for_selector("#results .res", timeout=10000)
        top_before = page.locator("#results .res").first.get_attribute("data-id")

        # nudge energy up a few times -> the target vector moves -> list re-ranks.
        for _ in range(3):
            page.click('#axes [data-nudge="0"][data-d="1"]')
            page.wait_for_timeout(220)
        page.wait_for_timeout(300)
        top_after = page.locator("#results .res").first.get_attribute("data-id")
        check("nudging energy re-ranks the list", top_after != top_before)

        # queue-next: + on the first result auto-creates a playlist and queues it.
        page.locator("#results .res [data-add]").first.click()
        page.wait_for_timeout(600)
        check("queue-next lands in the playlist", page.locator("#plTracks .ci").count() == 1)
        check("air + cast controls present", page.locator("#plQueue").is_visible()
              and page.locator("#plCast").is_visible())

        # instant search: typing renders grouped results; clicking one reseeds.
        page.fill("#q", "the")
        page.wait_for_timeout(600)
        if page.locator("#searchResults .sr").count() > 0:
            check("search grouped by artist", page.locator("#searchResults .gart").count() > 0)
            page.locator("#searchResults .sr").first.click()
            page.wait_for_timeout(400)
            check("search result reseeds", page.locator("#seedCard .title").count() == 1)
        else:
            print("  note: no search results for 'the' -- skipped search checks")

        page.screenshot(path=os.path.join(SHOT_DIR, "browse.png"), full_page=True)

        # clean up the playlist this run created.
        page.on("dialog", lambda d: d.accept())
        page.click("#plDelete")
        page.wait_for_timeout(400)
        check("cleanup: playlist deleted", page.locator("#plTracks .ci").count() == 0)

        browser.close()

    passed = sum(1 for _, ok in checks if ok)
    print("\n%d/%d checks passed. shots in %s" % (passed, len(checks), SHOT_DIR), flush=True)
    sys.exit(0 if passed == len(checks) else 1)


if __name__ == "__main__":
    main()
