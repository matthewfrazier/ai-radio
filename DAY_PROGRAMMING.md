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

## The experience

- **Generate a 24h day** from the template in one action (24 hour-blocks + 24
  schedule entries), with sensible per-hour variation.
- **Edit on a 24h horizon**: a day view where the operator adjusts per-block
  music (playlist/topic) and the factoid/recap briefs, without hand-building
  every segment.

## Status

- IA / experience design: **agent engaged** (in progress).
- Related backlog: news-topic distillation → 70s research briefs — see
  `BACKLOG.md` (investigation agent engaged).
- Build: not started; awaiting design, then phased implementation.
