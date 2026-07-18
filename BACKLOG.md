# Backlog

Tracked future work for the ai-radio overlay, durable in-repo (survives host
rebuilds, same rationale as `PROGRAM_BLOCKS.md`). Items may have an
investigation agent attached; their findings are folded in here before the
item is scheduled for a build.

---

## news-topic distillation → 70-second research briefs

**Status:** investigation in progress (agent attached, 2026-07-18).

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

**Technical body:** to be filled from the investigation agent's report.
