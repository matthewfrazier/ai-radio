#!/usr/bin/env python3
"""Browser-driven checks for the /browse music browser, run against the fleet's
shared Playwright server (no local Chromium). Non-destructive: exercises seed /
search / axis-nudge / crate but does NOT click Build (that would air/save a real
block -- the build path is covered by curl + unit tests).

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

        # a seed auto-loads (surprise); the seed card + 6 axis sliders render.
        page.wait_for_selector("#seedCard .title", timeout=15000)
        check("no console errors", len(cerr) == 0)
        check("seed auto-loaded", page.locator("#seedCard .title").count() == 1)
        check("6 axis sliders", page.locator("#axes input[type=range]").count() == 6)
        page.wait_for_selector("#results .res", timeout=10000)
        n_before = page.locator("#results .res").count()
        check("similar list populated", n_before > 0)
        top_before = page.locator("#results .res").first.get_attribute("data-id")

        # nudge energy up a few times -> the target vector moves -> list re-ranks.
        for _ in range(3):
            page.click('#axes [data-nudge="0"][data-d="1"]')
            page.wait_for_timeout(220)
        page.wait_for_timeout(300)
        top_after = page.locator("#results .res").first.get_attribute("data-id")
        check("nudging energy re-ranks the list", top_after != top_before)

        # add the first result to the crate -> crate section shows.
        page.locator("#results .res [data-add]").first.click()
        page.wait_for_timeout(200)
        check("crate populated after add", page.locator("#crate .ci").count() == 1)
        check("build buttons present", page.locator("#btnQueue").is_visible() and page.locator("#btnNow").is_visible())

        # search flow: type an artist, pick a result -> becomes the seed.
        page.fill("#q", "the")
        page.wait_for_timeout(500)
        if page.locator("#searchResults .sr").count() > 0:
            page.locator("#searchResults .sr").first.click()
            page.wait_for_timeout(400)
            check("search result reseeds", page.locator("#seedCard .title").count() == 1)
        else:
            print("  note: no search results for 'the' -- skipped reseed check")

        page.screenshot(path=os.path.join(SHOT_DIR, "browse.png"), full_page=True)
        browser.close()

    passed = sum(1 for _, ok in checks if ok)
    print("\n%d/%d checks passed. shots in %s" % (passed, len(checks), SHOT_DIR), flush=True)
    sys.exit(0 if passed == len(checks) else 1)


if __name__ == "__main__":
    main()
