# 24-hour programming (design in progress)

The next major capability: auto-generate a full day of coherent hour-long
blocks from a standard template, on a 24h horizon, editable by the operator.
The bar is explicit and high:

> "I can connect to this stream and never have to disconnect because it
> missed the mark."

This is a multi-phase effort (the operator expects it to take a while). This
doc captures the vision durably (same reason as `PROGRAM_BLOCKS.md`); the
concrete data model, the day-generator, and the create/edit UX are being
designed by an information-architecture agent and will be folded in here,
then built in verified phases per `PLAN.md` discipline.

## The standard hour (operator's spec, verbatim intent)

An ~1-hour block, roughly three content arcs, sequence:

1. **Weather** (TTS)
2. **News brief** (live/bulletin) — source A
3. **News brief** (live/bulletin) — source B
4. **Music** (10–14 min)
5. **News brief** (live/bulletin) — source C
6. **Recap of what played** + optionally an **AI-mediated factoid / trivia** (TTS)
7. **Music** (10–16 min)
8. *(optional)* **News brief from sources NOT used earlier this hour** (live/bulletin)
9. **End-of-hour recap** (TTS)

New segment concepts this introduces beyond today's `live`/`music`/`tts`:
- **recap-of-play** — TTS that references the music that actually aired this
  hour. Hard problem: music is resolved fresh at AIR time, so the played
  tracklist isn't known at generation time. The IA design must resolve
  whether to pin tracklists at generation or render recaps at air time.
- **factoid / trivia** — AI-mediated TTS (LLM), optionally tied to what played.
- **end-of-hour recap** — AI-mediated TTS summarizing the hour.
- **source-disjoint news brief** — a later brief that avoids the sources
  already used earlier in the same hour (needs per-block source tracking).

## Design (information-architecture agent, 2026-07-18)

### The recap problem — decided: hybrid, **no player change**

The tension ("music is chosen fresh at air, so tracks aren't known at
generation") dissolves given *when* and *in what order* rendering happens:
the player calls `render_block(force=False)` **once at block start**, and
`render_block` walks segments **in document order**. So when it reaches a
`recap` tts at index 6, the `music` at index 4 was already re-resolved in the
**same pass** — its tracklist is on disk. The recap reads the preceding music
segments' resolved track names and describes what *will* air before its slot.
"What played" = the resolved leading prefix truncated to
`duration_s // ~210s`, phrased loosely so the one-track cutoff is invisible.

Rejected: (a) pinning tracklists at generation (violates the P1 "never stale"
rule we just fixed); (b) true mid-block rendering (dead-air/complexity, fights
"always airing", reopens the hardened player). **`block_player.py` is
deliberately untouched** — recaps ship through the player's existing air-time
`render_block` call.

### Standard hour (`standard_hour`, ~48–57 min with end-recap slack)

All new content is **new `tts` topics**, not new segment types — the existing
tts machinery (voice, TTL, render, audio route, preview) is reused. Segments
gain an optional `role` tag so the generator/quick-editor target them by role,
not order.

| # | role | type / topic | ~dur | new |
|---|------|------|------|-----|
| 1 | weather | tts/weather | 15s | — |
| 2 | news_1 | live (bulletin A) | 5m | — |
| 3 | news_2 | live (bulletin B) | 5m | — |
| 4 | music_1 | music (daypart genre) | 12m | — |
| 5 | news_3 | live (bulletin C) | 5m | — |
| 6 | recap_mid | tts/**recap** (`scope:music`, `include_factoid`) | 45s | **new** |
| 7 | music_2 | music (daypart genre 2) | 14m | — |
| 8 | news_fresh | live (`source_id:"auto"`, disjoint) | 5m | — |
| 9 | recap_hour | tts/**recap** (`scope:hour`) | 40s | **new** |

New tts topics `recap` and `factoid` (both AI-mediated) live in
`tts_content.py` alongside the weather template and **degrade to a
deterministic template on any LLM failure** — a dead Ollama must never error a
whole hour (the same discipline weather already follows). `ttl_s:0` → always
re-render at air (context changes every air).

### "News not from original sources"

Primary: the day-generator assigns disjoint `source_id`s and picks the fresh
brief from the complement of genuine bulletins. Robustness: a `source_id:"auto"`
sentinel resolved in `render_block` against the `prior_source_ids` accumulated
as it walks the segments — disjoint even if the operator hand-edits an earlier
brief to collide. No new state file; the block is the ledger.

### 24h generator + edit experience

- `hour_templates.py` (template data + `build_hour` + per-hour `variation`)
  and `day_program.py` (`generate_day`, `day_summary`, past-day prune). Blocks
  use **deterministic wall-clock ids** (`20260718T140000`) so regeneration
  overwrites idempotently and schedule `block_id`s are predictable.
- Per-hour variation: rotate music genre by daypart, rotate the leading
  bulletin by `hour % n`, weather cadence, factoid seed from the hour's genre.
- New `/day` inline page (sibling to `/blocks`, same zero-framework
  convention): a 24-hour timeline grid; per-hour quick-edit exposing only
  operator knobs (two music queries, factoid/recap seed, weather location)
  targeted **by role**; bulk edits across day-parts; "Edit full segments →"
  deep-links into `/blocks`. Routes: `GET/POST /api/day/{date}`,
  `POST /api/day/{date}/generate|hour/{hh}|bulk`, `DELETE /api/day/{date}`.
- Scheduler gains an additive entry `mode` (`"now"|"queue"`, default queue);
  generated hourly entries use `mode:"now"` for predictable top-of-hour
  cutover. **← operator decision needed before Phase 3** (see below).

### Change ledger (all additive / backward-compatible)

- **block.json**: tts topics `recap`/`factoid`; optional `role` on segments;
  optional `template {name,day,hour}` on blocks; `resolved.tracks_head` (first
  ~20 music names — also fixes the preview UI's lost names); `live` params
  `source_id` may be `"auto"`.
- **schedule.json**: optional entry `mode`.
- **block_render.py**: context args on `build_tts_text`/`render_tts_segment`/
  `resolve_live_segment`; recap/factoid always re-render; `prior_source_ids`;
  `tracks_head`; scheduler passes `mode`.
- **block_player.py**: **none.**

### Refactor: add 3 modules, move nothing

`hour_templates.py`, `day_program.py`, `day_page.py`; extend `tts_content.py`,
`block_render.py`, `panel.py` in place. Honors PLAN item 15's deferral (no
package move, no `BASE`/endpoint lift). Explicitly NOT: a template DSL, a
plugin layer, an HTTP framework, or unifying the two inline UI pages.

## Phasing (stream stays live throughout; per-phase verified commit)

1. **recap/factoid topics + auto-disjoint news** — no scheduling change,
   nothing airs until played. (this phase)
2. **templates + single-hour generation** (`POST /api/blocks/from_template`).
3. **day generator + scheduler `mode`** — needs the `mode:"now"` cutover sign-off.
4. **day UI** (`/day` + `/api/day/*`), browser-verified.
5. **polish** — retention/cleanup alignment, docs, coherence + staleness runs.

## Status

- IA / experience design: **done** (above).
- News-distillation backlog: investigated, Phase-1-ready — see `BACKLOG.md`.
- Build: Phase 1 in progress.
