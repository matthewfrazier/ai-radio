# Programming blocks

An admin surface at `/blocks` (alongside `/admin`) for building and airing
~1-hour "programming blocks": ordered sequences of segments mixing live news
relays, TTS content, and Jellyfin music, each individually testable/auditionable
before anything airs.

This doc exists so the goal and design survive a host rebuild — it previously
existed only in an ephemeral Claude Code subagent transcript on this box, which
is exactly the kind of thing that got lost once already.

## Goal (as specified)

Build a new admin UI to manage "programming blocks" (~1 hour each) — an ordered
sequence of segments mixing:

- **live** — live news segments (NPR, BBC), sourced from an editable live-sources
  config, pulling in the right streaming URL + title.
- **tts** — TTS-generated content (e.g. latest weather — accepts a zip code or
  other location string; extensible to any other TTS topic).
- **music** — automated music blocks from Jellyfin (playlist name or search term;
  blank = shuffle all). Reuses `jf_source.py`'s existing Jellyfin auth/resolution,
  no reinvented client.

Requirements:
- The system generates a markdown-structured "script" document for a block (the
  rundown: ordered segments with type + params + resolved metadata).
- Every segment type is individually testable from the UI: live (audition the
  actual stream + confirm title), music (resolve + show track list, playable
  inline), TTS (hit the external API, render via TTS, play the result).
- Whole-block test: browser-playable preview, skippable forward/backward —
  preview only, never touches Icecast.
- A built block can be scheduled: "play immediately" (cut over the live stream
  now) or "add to playlist" (queue after whatever's currently airing/queued).
- Blocks are always available as an offline rendered playlist, regenerable on
  demand.
- Blocks are NOT rendered all at once — only assets that need rendering are
  rendered (TTS renders; music is resolved/referenced by remote URL, never
  downloaded; live segments are never pre-rendered, only their live URL+title is
  resolved).
- Any TTS segment backed by an external API tracks a `rendered_at` timestamp +
  staleness TTL, and re-renders automatically if stale before it airs (e.g.
  never serve an hour-old weather report).

Related, adjacent requirement from the same conversation: pluggable, testable
inference backends. The station currently relies on remote Ollama for anything
LLM-driven; that needs to stay swappable/configurable rather than hardcoded —
this is why `tts_engines.py` and `llm_backends.py` exist as small registries
rather than direct calls.

Constraints: single-operator homelab box, not a multi-tenant product — no auth/
user-management, no database (flat JSON/text files, matching `station.json`'s
existing convention), no task-queue framework, no new dependencies beyond
stdlib + ffmpeg (already required). Smallest diff that solves the stated
problem; reuse existing patterns (`jf_source.py`'s Jellyfin client, panel.py's
Kokoro call, the `.dot`/`<audio>`/fetch() UI conventions) rather than
reinventing them.

## Design

- **Data model**: `program_blocks/{block_id}/block.json` (manifest, source of
  truth) + derived `block.md` (markdown rundown). Segment `status`:
  `unresolved` → `ok` → `stale` (TTS only, TTL expired) → `error`.
- **Shared Jellyfin client**: extracted from `jf_source.py` into
  `jellyfin_client.py` (auth, list, resolve, search, track URL) — `jf_source.py`
  becomes a thin wrapper, CLI output unchanged. Adds `resolve_music(query)`, the
  high-level entry point the music segment uses (blank → library shuffle;
  substring match against playlist names; else free-text search).
- **Live sources**: `live_sources.json` (gitignored, seeded from
  `live_sources.json.example`) + `live_source.py`. Title fetch is a best-effort
  raw-socket ICY metadata probe (public streams only expose "now playing" inside
  the stream, not via a separate API); falls back to the static configured name
  on any failure. 60s in-memory cache per source.
- **TTS/weather**: `tts_content.py` — OpenWeatherMap geocode + current-weather +
  a deterministic string-template script (no LLM in this path — fast, free,
  predictable, safe to hit repeatedly from a Test button). `weather.conf`
  (gitignored) holds `OWM_API_KEY`.
- **TTS/freeform**: routes through `llm_backends.py` (Ollama or Claude API) for
  topics that aren't weather. `anthropic.conf` (gitignored) holds
  `ANTHROPIC_API_KEY` for the Claude backend; Ollama needs no credentials.
- **TTS engines**: `tts_engines.py` is a small registry (`kokoro` wired up
  today) so adding a second TTS engine is a small diff, not a rewrite.
- **The block player**: `block_player.py`, spawned by `panel.py` as a tracked
  subprocess (PID file, not an in-memory handle, so state survives
  `writ-panel.service` restarts). One persistent "sink" ffmpeg holds the Icecast
  source connection for the whole queue, fed via a FIFO; each segment is a
  short-lived producer ffmpeg (bounded-duration live relay, local TTS file, or
  capped-duration music concat) whose raw-PCM output is relayed into the FIFO.
  Avoids an audible reconnect gap at every segment boundary. Respawns sink+FIFO
  if the sink dies mid-block. `writ-stream.service` (the static Jellyfin loop)
  is the fallback — the two never run concurrently; the player stops it on
  start and restarts it when the queue drains or on shutdown.
- **Panel UI**: `blocks_page.py` (own `BLOCKS_PAGE` HTML/CSS/JS string, same
  zero-framework/no-build-step convention as `panel.py`'s `PAGE`), served at
  `/blocks`. Business logic (`block_render.py`) is imported by `panel.py`'s
  route handlers — panel.py stays thin HTTP glue.
- **Render orchestration**: `block_render.render_block(block_id, force=False)`
  is the single entry point used by whole-block test, regenerate, and
  schedule("play now"/"queue") alike — one render code path, not three.
  Per-segment failures are captured as `status="error"` without aborting the
  rest of the block.

Full plan detail (file-by-file, function signatures, exact JSON shapes,
ffmpeg command lines): see the implementation history — no separate design doc
beyond this one and the code itself; the code is the source of truth for
specifics, this doc is the source of truth for intent.

## Status (2026-07-16)

Implemented and live — `writ-panel.service` is serving `/blocks` and
`/api/blocks` with this code. `tailscale serve` now maps
`https://ai-radio.tailbe5094.ts.net/blocks` → `http://127.0.0.1:8080/blocks`
(the target URL must include the `/blocks` suffix — `tailscale serve
--set-path` strips the mount prefix before forwarding, so a bare-port target
collapses every mount to `/` on the backend and silently served the wrong
page; confirmed via a raw-socket capture of the forwarded request). Not yet
committed to git.

Verified end-to-end (through the real tailscale-proxied URL, not just
localhost):
- Full block lifecycle: create → save `live`+`music` segments → render (both
  resolved `status: "ok"`) → markdown rundown → play-now (cut the real
  Icecast stream) → block player aired the segments → drained →
  `writ-stream.service` auto-restarted → block marked `"played"`.
- `jf_source.py` CLI regression-clean after the Jellyfin-client extraction.
- `ANTHROPIC_API_KEY` delivered and confirmed working — freeform TTS
  (Claude-generated text → Kokoro render) produces valid audio.
- Ollama backend reachable, real model list returned.

Also fixed: `blocks_page.py`'s `BASE` path computation had a regex bug
(`location.pathname.replace(/\/blocks\/?$/,'')` stripped the `/blocks` prefix
entirely instead of just trimming trailing slashes like `panel.py`'s admin
page does), so every `fetch(BASE+'/api/...')` call in the UI silently missed
the tailscale mount and failed — "New block" and every other button appeared
to do nothing. Caught via a real Playwright/Chromium browser test (curl alone
verified the API layer but missed this client-side bug) after the user
reported the UI wasn't responding. Fixed to match `panel.py`'s pattern; a
full browser pass afterward (create block, add live+music segments, test
both, save) showed zero console/page errors.

Also fixed: the `npr` live source pointed at NPR's full 24/7 program stream
(`npr-ice.streamguys1.com/live.mp3`, whatever's currently airing), not the
actual newscast, despite being labeled "NPR Newscast." Replaced with
`pd.npr.org/anon.npr-mp3/npr/news/newscast.mp3` (verified via ffprobe: 280s,
matching NPR's real ~5min hourly bulletin) and expanded `live_sources.json`/
`live_sources.json.example` from 2 to 10 sources (NPR Newscast, BBC World
Service, CNN, Fox News Radio, MSNBC, NBC News Radio, Bloomberg Radio,
Deutschlandfunk, RFI Monde, NPO Radio 1). Candidates sourced from the
Radio-Browser directory (api.radio-browser.info) and each verified reachable
with a real bounded GET (not HEAD — several of these reject HEAD) before
inclusion.

Also added: a Voice dropdown on TTS segments (Kokoro voices, "(station
default)" as the blank/first option) — the backend already accepted a
per-segment `voice` override, it just had no UI. Verified end-to-end: picked
`af_alloy` renders through Kokoro correctly (not just a cosmetic select).

Weather TTS now confirmed fully working — `OWM_API_KEY`'s earlier `401` was
indeed just OpenWeatherMap's new-key activation delay; it's since resolved.

Follow-up round after user testing found the URL fix alone hadn't visibly
taken effect:
- **Root cause**: `render_block()` only re-resolved `live`/`music` segments
  when `status != "ok"`, contradicting the original design intent ("always
  re-resolved on demand, no TTL, cheap calls"). Any already-resolved segment
  kept its cached URL forever, surviving config fixes indefinitely. Now
  `live`/`music` always re-resolve; `tts` is still the only type gated by
  staleness/TTL (verified by injecting a stale cached npr segment and
  confirming `render(force=False)` corrects it).
- `blocks_page.py`'s preview-track label used `.textContent` with an HTML
  entity (`&middot;`), which only parses inside `.innerHTML` — rendered as
  literal `&middot;` text. Switched to the actual `·` character.
- Segment status was a static text label reflecting only the last full save.
  Replaced with a `.dot` indicator (the ok/bad convention already in the CSS
  but never used) that updates live on Test success/failure and resets to
  neutral the instant a param is edited.
- Whole-block preview only queued one track per music segment regardless of
  `duration_s` — a 900s segment stopped after one ~3min song. Now queues up
  to 10 distinct tracks so Next/auto-advance actually cycles through them.
- **BBC wasn't actually a brief either** (unlike npr, whose URL was simply
  wrong — bbc_world's URL was honestly the full live World Service stream,
  which just isn't a bulletin). Added `kind: "podcast_latest"` as a second
  live-source resolution mode: fetches a podcast RSS feed and resolves to
  its most-recent `<enclosure>` — a genuinely different URL per episode,
  same "always re-resolve, never cache" treatment as everything else.
  `bbc_world` (id kept for compatibility with any block already referencing
  it) now resolves to BBC's real "5 minute news bulletin" podcast feed
  (verified 300s via ffprobe); added `dw_brief` (Deutsche Welle's "DW News
  Brief," verified ~90s) as a second genuine bulletin via the same
  mechanism. `resolve_podcast_latest()` is generic — more feeds can be added
  by config alone, no new code. 11 sources total now; only npr/bbc_world/
  dw_brief are genuine bulletins, the other 8 are honest full-live-channel
  relays (CNN, Fox News Radio, MSNBC, NBC News Radio, Bloomberg Radio,
  Deutschlandfunk, RFI Monde, NPO Radio 1) — no dedicated bulletin feed was
  found for those in this pass.

Not yet done:
- Staleness re-render test (needs a working `tts` segment — now unblocked
  now that weather works, just hasn't been run).
- A dedicated playwright test host for the fleet was requested earlier but
  not yet stood up — this session installed Chromium ad-hoc in a venv for
  browser tests (multiple rounds), then removed it each time (~810MB, not
  appropriate to keep on this small 20G-disk production box, 6.7G free).
  Worth actually requesting via the bus if browser-level UI testing becomes
  routine.

UI pass after direct user feedback (screenshots + a live click-through):
Redesigned `/blocks` to a flatter, less "boxy" mobile layout (sections with a
thin divider instead of bordered fieldsets, pill buttons); "New block" now
creates immediately with an auto title (editable after) instead of demanding
a title upfront; "Add segment" is three direct type buttons instead of a
dropdown+button; Test buttons now show phase state ("resolving...",
"generating via ollama...", "rendering audio...") and surface real
errors/timeouts (`AbortController`, 20s non-TTS / 90s TTS) instead of failing
silently. Also fixed a real bug this surfaced: the freeform-TTS LLM
backend/model `<select>`s showed a default value visually but never wrote it
into the segment's params unless the user manually re-picked it, so Test
always 502'd with `KeyError: 'llm_backend'` on a fresh segment — pickers now
write their default into params as soon as they populate. Verified with a
mobile-viewport (390x844) Playwright pass: create-before-naming, one-tap
segment add, and a full freeform-TTS round trip (Ollama generate → Kokoro
render → played) all confirmed working with zero console/page errors.
- No systemd unit for `block_player.py` — it's a plain tracked subprocess for
  this iteration; a `writ-block-player.service` would be a small later upgrade,
  not needed now since all its state is file-based.
