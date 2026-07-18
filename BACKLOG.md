# Backlog

Tracked future work for the ai-radio overlay, durable in-repo (survives host
rebuilds, same rationale as `PROGRAM_BLOCKS.md`). Items may have an
investigation agent attached; their findings are folded in here before the
item is scheduled for a build.

---

## cast to Google Nest / Home devices

**Status:** BUILT 2026-07-18 (direct pychromecast). Remaining: optional Home
Assistant path (below).

**Shipped:** `cast_ctl.py` (pychromecast in `.venv-cast`), panel
`/api/cast/{devices,start,stop}`, a Cast picker on `/now`. The primary stream
was switched to **MP3** (`/stream`, `audio/mpeg`) — Cast won't play live
Ogg/Vorbis — which also dropped Vorbis + a transcoder and simplified to one
source. Verified end-to-end: casts to speaker **groups** and standalone
devices; individual group *members* return `LAUNCH_ERROR NOT_ALLOWED` (the UI
surfaces a "cast to its group" hint). Devices fetch the LAN URL. Also fixed a
real dead-air bug found along the way: Icecast `source-timeout` was 10s but
the block player's air-time render (Claude recaps) now runs longer, so the
idle sink was being dropped mid-render → raised to 60s.

**Remaining — optional Home Assistant path (do not rely on it).** HA is on the
network and its cast integration can drive devices too. Add an optional path:
if `station.json` has `ha_url` + a token (`ha.conf`, vault), also list HA
`media_player` cast entities and cast via HA's `media_player.play_media`
service — an alternate to pychromecast, useful if a device is unreachable by
direct control. Config-gated; direct pychromecast stays the default. Needs HA
url + long-lived token to activate/test.

---

## live now-playing metadata (real artist/title) from the playlist

**Status:** idea (2026-07-18). Directly reduces recap hallucination.

**Goal.** Emit the actual current track's artist/title so (a) `/now` shows the
real song playing and (b) recaps/factoids use **real artist metadata instead
of the LLM inferring the artist from track titles** — the source of the only
remaining recap-accuracy slips (e.g. "featuring Jay Dunne" on obscure tracks).

**What we already have / what's missing.** Jellyfin returns artist fields we
currently discard — `resolve_music_segment` keeps only track `Name` in
`tracks_head`. First cheap step: also capture `AlbumArtist`/`Artists` per
track. Then the recap prompt can be given "Title — Artist" pairs (no more
guessing), and `/now` can show the real now-playing.

**Emitting to the live stream (harder).** The music segment is one ffmpeg
decoding a concat playlist of Jellyfin URLs into the sink, so per-track
boundaries aren't visible to the sink. Options to weigh: (a) the block player
tracks elapsed time against the resolved per-track durations and pushes
Icecast metadata updates via `/admin/metadata?mount=/stream&song=...` as each
track starts (needs per-track durations captured at resolve time); (b) play
music track-by-track (one producer ffmpeg per track) so boundaries are known
— cleaner metadata but more process churn. (a) is the smaller change and fits
the existing FIFO-sink model. Ties into `player_state.json` (the /now feed).

**Status:** idea (2026-07-18). Recaps/factoids currently run on Claude
(`recap_llm_backend=claude` station default); Ollama is available but its
factoids are ungrounded (parametric memory only, higher hallucination risk on
specifics).

**Goal.** Give the Ollama backend web-search / tool-use so its factoids are
grounded in retrieved facts rather than memory, then run an A/B test of
Claude vs tool-augmented Ollama for recap/factoid quality (accuracy,
liveliness, latency, cost) and pick the default per-slot.

**Notes.** Ollama's `/api/chat` supports tools; would need a search tool
(the project has no web-fetch/search dependency today — this is where one
would enter, scoped to the tool call). The A/B harness can reuse the existing
`llm_backends` registry and the deterministic fallback. Ties into the
news-distillation feature below (shared grounding/retrieval).

---

## news-topic distillation → 70-second research briefs

**Status:** investigated 2026-07-18 (agent report below); ready to schedule
Phase 1 (buildable now, no new infra).

**Goal.** Instead of only relaying source news audio, the station reads the
text/headlines behind the verbal news briefs (NPR / BBC / DW), distills the
topics appearing across the news, and generates its own ~70-second spoken
"research briefs" on those topics (via the existing Kokoro TTS) — turning the
news into station-original topic deep-dives.

**Why it matters.** Directly serves the overarching goal ("never disconnect
because it missed the mark"): the station becomes a source of substance about
what's happening, not just a relay, and can fill the "factoid / trivia" and
topical-segment slots of the standard hour (see `DAY_PROGRAMMING.md`) with
fresh, relevant content.

**Open questions the investigation is resolving:**
- Get the text via the sources' own text/RSS feeds, or speech-to-text on the
  bulletin audio? (STT would need GPU/infra this CPU-only LXC lacks.)
- Topic distillation approach (LLM via the existing Ollama/Claude backends vs
  lighter entity extraction) and how to rank/dedupe over a rolling window.
- 70s brief generation: word budget, sourcing, hallucination bounding for
  news-adjacent content, and how a brief becomes an airable segment.
- Freshness/caching in a 24/7 loop; infra/fleet dependencies.

### Technical findings (investigation agent, 2026-07-18)

**Recommendation: build the text-feed route first; defer STT.** NPR, BBC and
DW all publish headline+summary text RSS that the box can parse with the exact
`urllib` + `xml.etree.ElementTree` idiom already in
`live_source.resolve_podcast_latest` — zero new dependencies. STT on the
bulletin audio is **blocked on infra that doesn't exist** (CT112 is CPU-only;
the only tailnet GPU service is Kokoro TTS; no Whisper/STT anywhere in the
tree or fleet) and isn't needed for topic distillation. STT becomes a
Phase-2 fleet request to raserver-homelab only if the operator specifically
wants *the exact spoken bulletin wording* rather than the outlets' newsroom
text.

**Text sources (verified reachable pattern):**
- NPR topic RSS `https://feeds.npr.org/1001/rss.xml` (title + description;
  the `newscast.mp3` we air has no text).
- BBC `https://feeds.bbci.co.uk/news/world/rss.xml` (clean headline + 1-sentence
  summary), plus the existing bulletin feed's item titles/descriptions.
- DW `https://rss.dw.com/atom/rss-en-all` (box's urllib already reaches
  rss.dw.com for the podcast feed).
- Honest caveat: these are the outlets' *written* output, not a transcript of
  the specific audio bulletin — for "distill the day's topics" that's
  equivalent or better (broader, cross-source corroboration).

**Pipeline (all via existing machinery, no player changes):**
1. **Ingest**: pull item title+description from the 3 text feeds over a rolling
   ~6h window, dedup — reuse the `resolve_podcast_latest` fetch/parse/fallback
   pattern (a new small text-ingestion module).
2. **Distill**: one `llm_backends.generate()` call clustering cross-outlet
   items → JSON `[{topic, one_line, source_headlines[], outlet_count}]`; rank
   by `outlet_count`; keep a rolling `topics.json` of recently-aired topic ids
   to avoid hourly repetition (load-bearing, not optional).
3. **Brief**: ~70s ≈ **150–170 words** at Kokoro ~150 wpm. Generate GROUNDED
   in the fetched `source_headlines`/summaries passed into the prompt (not
   parametric memory); instruct "use only facts in the provided material, do
   not invent names/numbers/quotes," attribute ("according to reporting
   from…"), prefer the Claude backend for this step. `_probe_duration()`
   already measures actual length for a later regen-if-too-long refinement.
4. **Air**: new `topic == "news_brief"` branch in `build_tts_text()` →
   `render_tts_segment` → Kokoro → ogg → `status:"ok"`. Params carry
   `{topic:"news_brief", topic_id, source_material, llm_backend, llm_model,
   ttl_s}`. The block player airs it unchanged.

**Freshness/caching:** a distillation job on a systemd timer (modeled on
`cleanup_blocks`) aligned to the hourly newscast cadence; brief rendering
reuses the existing TTS staleness path verbatim (`is_stale` + per-segment
`ttl_s`, ~3600 for news vs weather's 1800; `render_block(force=False)`
re-renders only stale tts). ~1 distillation call/hour + 1 brief call per *new*
topic (cache by `topic_id`) — a couple of small LLM calls/hour, not per air.

**Risks:** (1) hallucination on news facts — highest; bounded by strict
grounding + attribution + Claude, not eliminable, needs operator spot-check.
(2) source ToS — RSS is syndication-intended; keep it distilled-not-verbatim
and attributed, never read article bodies aloud. (3) feed drift — best-effort
parse-with-fallback like `live_source.py`. (4) loop repetition — the rolling
seen-topics file.

**Effort/deps:** Phase 1 is buildable now (stdlib + ffmpeg + existing
Ollama/Claude/Kokoro backends, no new dependency, no new infra). Phase 2 (true
bulletin transcription) is optional and infra-gated on a tailnet GPU STT host.

**Touches:** `block_render.py` (`build_tts_text` new branch; reuse
`is_stale`/TTL/`render_block`), `llm_backends.py` (distillation + brief calls,
API unchanged), `tts_engines.py` (Kokoro, unchanged), `live_source.py`
(`resolve_podcast_latest` as the fetch/parse template), a new text-ingestion
module + a distillation timer.

This feature is a natural supplier for `DAY_PROGRAMMING.md`'s "factoid /
trivia" and topical-brief slots.

---

## multi-streamer sync / drift for unified live streams

**Status:** idea (2026-07-18). Prerequisite continuity work is DONE: the
source now survives every automatic transition without flapping — cutover
(`--kill-who=main` so SIGHUP hits only the player loop, not the sink ffmpeg),
air-time render (the cutover filler bumper), and queue-drain (the player holds
the mount playing idle music instead of handing off to the fallback service).
So a single listener/Cast can now stay connected indefinitely.

**Goal.** Experiment with multiple simultaneous streamers feeding one logical
"live" station, and keep them in sync (bounded drift) so a listener can move
between outputs — the local `<audio>`, a Cast speaker/group, and eventually a
second box — and hear the same programme at nearly the same wall-clock
position.

**Why it matters.** Today there is exactly one Icecast source (the block
player's sink) and one mount. "Never disconnect because it missed the mark"
is met for a single output; the next step is a *unified* live experience
across outputs and, later, redundancy (a second streamer that can take over
without a gap).

**Open questions to investigate (not yet scoped):**
- What "sync" means here: multiple Icecast mounts fed from one PCM source vs
  one mount consumed by many clients (clients already share the mount; drift
  there is just client-buffer, ~seconds). Real divergence appears only with
  *separate encoders/sources*, so first define the actual multi-streamer
  topology we want (redundant failover? geographically separate boxes? per-
  room low-latency?).
- Drift measurement + correction: shared wall-clock anchor (the block player
  already stamps `started_at` per segment in `player_state.json`); how much
  drift is tolerable; resync by trimming/padding at segment boundaries vs
  continuous PLL-style adjustment.
- Failover: a standby streamer that mirrors the queue and can seize the mount
  within the Icecast `source-timeout` window without a listener-visible gap.
- Cast group sync is partly handled by Google's own group timing; measure it
  before building our own for the Cast path.

**Touches (likely):** `block_player.py` (source topology, shared timing
anchor), Icecast config (multiple mounts?), `panel.py`/`/now` (which streamer
/ which mount a listener is on). No new deps identified yet; this is a
research item to be scoped before any build.
