# Music DNA overlay — attribute/taxonomy layer for WRIT-FM selection

Research + design for an attribute overlay on top of the Jellyfin music
library, so the station can select and sequence music by more than a genre
search string. Durable in-repo (survives host rebuilds, same rationale as
`PROGRAM_BLOCKS.md`/`BACKLOG.md`). Every prior-art claim below is cited; the
Sources section at the end has the full URL list.

## Summary / TL;DR

- Today music resolves by a single Jellyfin **search string** per segment
  (`resolve_music` in `jellyfin_client.py`; day-parts map hours → genre words
  in `hour_templates.py`). Jellyfin exposes only Name/Artists/Album/Genres/
  Year. There is no energy, mood, tempo, or similarity signal to sequence on.
- The "legacy musicDNA from AllMusic" the operator remembers is really **two
  different prior-art systems** plus a **name-collision**: (1) AllMusic's
  hand-authored editorial taxonomy — 21 Genres → ~1,400 Styles, plus ~290
  cross-cutting **Moods** and ~180 **Themes**; (2) Pandora's **Music Genome
  Project** — ~450 analyst-scored numeric "genes" per song driving
  similarity. "MusicDNA" (capital-D, ~2010) is a **red herring**: a rich-media
  MP3 container format, not a descriptor taxonomy.
- We cannot and should not rebuild 450 hand-scored genes. The buildable
  synthesis is a **small per-track attribute record** (energy, valence, tempo
  band, acousticness, danceability, instrumental, era) plus a **controlled
  subset of AllMusic-style mood/theme tags** — keyed by Jellyfin item id, in a
  flat `overlay.json` next to `library_snapshot.json` (no DB, repo convention).
- We can populate most of the numeric axes **for free, with no new infra**:
  resolve each track to a MusicBrainz **recording MBID** (artist+title), then
  look up **AcousticBrainz** (BPM, key, danceability, mood_*, acoustic/
  electronic, voice/instrumental) — all **CC0**. AcousticBrainz stopped
  collecting in 2022 but the data/API for existing recordings is still there.
- Mood/theme *tags* (AllMusic's contribution) have no free numeric source;
  fill those with a **bounded LLM pass** over artist+title+genre+year using the
  existing `llm_backends.py`, constrained to a fixed vocabulary and only for
  low-harm subjective axes. Local **Essentia** audio analysis is the fallback
  for coverage gaps (CPU-feasible but heavyweight; models are NC-licensed).
- **Top recommendation:** build the **MBID → AcousticBrainz lookup (CC0, zero
  new infra)** as the backbone, add a **bounded LLM mood/theme pass** for the
  AllMusic-style tags AcousticBrainz can't give, and defer Essentia to fill
  only the coverage misses. Details in Population options and Phased build plan.

## The legacy prior art

### AllMusic's editorial descriptor system (Genres / Styles / Moods / Themes)

AllMusic (print *All Music Guide*, 1990–91, Michael Erlewine; database built by
"a hybrid of historians, critics, and passionate collectors") is the source of
the "musicDNA from AllMusic long ago" memory. Its taxonomy is **four separate
vocabularies**, defined verbatim in AllMusic's own FAQ:

- **Genres** — "the broad categorization of music into a grouping. Things like
  jazz, blues, country and pop/rock are all examples of the **21 genres** that
  AllMusic breaks music into."
- **Styles** — "more specific **sub-categories of music that fall under the
  broad genres**. They usually relate to a specific time period (like power
  pop, old-school rap) or a regional breakdown (such as northern soul or new
  wave)." Wikipedia: AllMusic developed **~1,400 subgenres/styles**.
- **Moods** — "**Adjectives that describe the sound and feel** of a song,
  album, or overall body of work."
- **Themes** — "**Activities or events particularly suited** for a song, album
  or overall body of work."

So the shape is: **Genre (21, top level) → Style (the deep ~1,400-node tree)**;
**Moods** and **Themes** are two *cross-cutting* descriptor axes layered on top,
independent of the genre tree. Moods = adjectival feel; Themes = situational/
activity fit. Everything is **hand-authored by AllMusic's editorial staff and
applied per song/album/artist** — an ISMIR 2009 study using AllMusic states the
"classifications of songs and albums according to themes, moods or instruments
… are **manually created by music experts from the AllMusic.com team**."

Counts (extracted from archived AllMusic browse pages via the Wayback Machine —
the live site 403s all fetchers — so these are real slugs, not inferred):

| Vocabulary | Count | Cross-check |
|---|---|---|
| Genres | **21** | matches the FAQ's "21 genres" |
| Styles | **~1,400** total; **212** under Pop/Rock alone (counted) | Wikipedia 1,400 figure |
| Moods | **~290** | ISMIR 2009 counted 178 at the time |
| Themes | **~180** | ISMIR 2009 counted 73 at the time |

The 21 Genres (complete): Avant-Garde, Blues, Children's, Classical, Comedy/
Spoken, Country, Easy Listening, Electronic, Folk, Holiday, International, Jazz,
Latin, New Age, Pop/Rock, Rap, R&B, Reggae, Religious, Stage & Screen, Vocal.

Style hierarchy shape (real slice of the 212 under **Pop/Rock**): Alternative/
Indie Rock, Adult Contemporary, Album Rock, Alternative Metal, Arena Rock, Art
Rock, Baroque Pop, Black Metal, Blues-Rock, Brill Building Pop, British
Invasion, British Psychedelia, Britpop, Bubblegum, Chamber Pop, College Rock,
Country-Rock, Dream Pop — plus era/region fragments like American Trad Rock,
Aussie Rock, Austropop, Canterbury Scene, Chinese Pop/Rock. (Styles fragment by
**era** and **region**, per the FAQ.)

Mood sample (35 real terms of ~290): Acerbic, Aggressive, Airy, Ambitious,
Angst-Ridden, Atmospheric, Bittersweet, Bleak, Boisterous, Brooding, Cathartic,
Cerebral, Confrontational, Cynical/Sarcastic, Detached, Dreamy, Druggy,
Ethereal, Exuberant, Gritty, Hypnotic, Intimate, Laid-Back/Mellow, Lush,
Melancholy, Nihilistic, Nocturnal, Ominous, Plaintive, Rollicking, Sardonic,
Sleazy, Swaggering, Trippy, Yearning.

Theme sample (25 real terms of ~180): Breakup, Celebration, Club, Day Driving,
Dinner Ambiance, Drinking, Empowering, Girls' Night Out, Graduation, Hanging
Out, Heartbreak, In Love, Introspection, Late Night, Motivation, Night Driving,
Party Time, Rainy Day, Road Trip, Romantic Evening, Seduction, Sex, Sports,
Summer, TGIF. (Themes map almost directly onto **day-parts and activity
blocks** — exactly what a radio clock wants.)

### Pandora Music Genome Project (MGP)

The other "DNA" system, and the closer analogy to a numeric attribute overlay.
Conceived by Will Glaser (1999) with Tim Westergren (2000); protected under
**U.S. Patent 7,003,515**. The full gene list and the matching algorithm are a
**guarded trade secret** — only the following is publicly documented:

- Each song is scored on **~450 distinct musical attributes ("genes")** — an
  explicit genetics analogy. Per-genre depth varies: **Pop/Rock ~150, Rap ~350,
  Jazz ~400, World & Classical 300–450**.
- Genes span **melody, harmony, rhythm, form/composition, instrumentation,
  vocals (arrangement + performance), and lyrics** — e.g. lead-vocalist gender,
  use of groove, electric-guitar distortion level, background-vocal type.
- Each gene is scored **0–5 in half-integer steps** (11 possible values) by
  **trained musicologists** (four-year music degree), taking **20–30 minutes
  per song**; ~10% re-analyzed for inter-rater reliability.
- A song becomes a **vector in gene space**; similarity = distance between song
  vectors (the exact metric/weighting is not public).

The transferable idea for us: **per-track numeric attribute vector → distance =
similarity**. The un-transferable part: 450 hand-scored genes at 20–30 min each
is impossible for a homelab library. Our overlay keeps the *vector/distance*
concept but with ~7 machine-derivable axes, not 450 human ones.

### "MusicDNA" the file format (~2010) — red herring

MusicDNA (Norwegian developer Dagfinn Bach, **Bach Technology A.S.**, with
MP3 co-inventor Karlheinz Brandenburg; demoed at **MIDEM 2010**, Cannes) was an
**enhanced-MP3 container** — a "deluxe MP3" wrapping the audio with lyrics,
artwork, video, blog posts, band news, and "**dynamically updatable**" online
content (Bach: "carry up to **32GB of extra information** in the file itself").
Built on MPEG-7/XML; no major label adopted it (independents Beggars Group and
Tommy Boy trialed it); the company later pivoted to fingerprinting.

**Verdict: not our thing.** MusicDNA is a *distribution/metadata-container*
format — its "DNA" branding is about bundling rich media *inside the file*, not
a curated descriptor vocabulary. It's easily conflated with AllMusic's taxonomy
and Pandora's genes but overlaps only superficially. The overlay we want is the
**AllMusic (moods/themes) + Genome (numeric vector)** idea; treat "MusicDNA the
format" as a naming coincidence.

## Open data sources we can actually use

For each: what it yields, license, and how to get it. Licensing note for our
context — WRIT-FM is a non-commercial single-operator homelab station, so
**NonCommercial (NC) licenses are fine to use today**; they are flagged only
because they would block a future commercial product.

| Source | Attributes it yields | License | How to get it | Commercial-safe? |
|---|---|---|---|---|
| **MusicBrainz** core | Stable IDs (recording/artist/release **MBIDs**) — the join key for everything else | **CC0** | Web API `ws/2/` (~1 req/s anon); twice-weekly PG dumps; JSON dumps | Yes |
| **MusicBrainz** tags/genres | Community folksonomy genres/tags | **CC BY-NC-SA 3.0** (supplementary, not the CC0 core) | Same API `inc=genres`/`inc=tags` | No (NC) |
| **AcousticBrainz** | Per-MBID: **BPM, key/scale**, ~120 low-level descriptors; high-level classifiers: **danceability, mood_happy/sad/aggressive/relaxed/party, genre, voice-gender, voice/instrumental, acoustic/electronic, timbre** | **CC0** | Static dumps (`acousticbrainz.org/download`; low-level ~589 GB, high-level ~39 GB compressed) + legacy REST API by MBID | Yes — but **project ended 2022**, data is frozen; nothing for recordings added after |
| **Essentia** (MTG-UPF) | The audio-analysis engine itself (BPM/key/features + TF model inference) — recompute any of the above for tracks AcousticBrainz lacks | Library **AGPL-3.0** | `pip`/source; runs locally | Yes w/ AGPL compliance |
| **Essentia pretrained models** | mood, danceability, genre (Discogs400/MTG-Jamendo), arousal/valence, voice/gender, acoustic/electronic | **CC BY-NC-SA 4.0** | `essentia.upf.edu/models.html` | No (NC) w/o proprietary license |
| **Discogs** dumps | `genres` + finer **`styles`** taxonomy, formats, labels | **CC0** (monthly dumps) | `data.discogs.com` monthly XML; API (already wired in `mac/discogs_lookup.py`) | Yes |
| **Last.fm** tags | Folksonomy tags, similar-artist/track | **Proprietary ToS**, non-commercial, no sub-license, usage-capped, **no bulk dump** | API only (`ws.audioscrobbler.com/2.0/`) | No — most restrictive |
| **ListenBrainz** | Listens, CF recommendations, recording-to-recording similarity | **CC0** | API + full/daily dumps | Yes |

Key facts to internalize:

- **AcousticBrainz is the jackpot but frozen.** It stopped accepting
  submissions in **Feb 2022** (data quality: key detection style-limited, BPM
  often wrong without confidence, weak mood/genre classifiers). ~30M
  submissions → **~7M unique MBIDs** remain queryable/CC0. For any recording in
  it, we get the numeric axes for free; for recordings *not* in it (obscure
  tracks, newer releases, our own rips that never got submitted) we get
  nothing and must fall back to Essentia or LLM.
- **The CC0, no-strings stack is: MusicBrainz MBIDs + AcousticBrainz +
  Discogs styles + ListenBrainz.** MusicBrainz *tags* and Last.fm are NC/ToS-
  restricted; Essentia *models* are NC. All NC constraints are acceptable for
  this non-commercial station but should be recorded in provenance.

## Proposed overlay schema

A flat file `overlay.json` alongside `library_snapshot.json` (no DB, matching
`station.json`/snapshot convention), keyed by **Jellyfin item id** — the same
id `jellyfin_client` already uses to build `track_url`. Every field is optional
and carries provenance so partial population is first-class and any single axis
can be re-derived from a better source later.

Axes are the buildable synthesis of the legacy systems: the **numeric vector**
is Genome-lite (7 machine-derivable axes, not 450 genes); the **mood/theme
tags** are a *controlled subset* of AllMusic's vocabularies chosen for radio
sequencing, not the full ~290/~180.

```json
{
  "generated_at": "2026-07-16T12:00:00",
  "vocab_version": 1,
  "tracks": {
    "<jellyfin_item_id>": {
      "recording_mbid": "b1a9c0e9-...",        // join key, null if unresolved
      "energy": 0.72,                          // 0..1
      "valence": 0.55,                         // 0..1  (mood positivity)
      "tempo_bpm": 122.0,                      // measured BPM, null if unknown
      "tempo_band": "up",                      // slow|mid|up|fast (derived from bpm)
      "acousticness": 0.18,                    // 0..1  (acoustic<->electronic)
      "danceability": 0.63,                    // 0..1
      "instrumental": 0.05,                    // 0..1  P(no vocals)
      "era": "1990s",                          // decade band, derived from year
      "moods": ["Atmospheric", "Yearning"],    // <= 3, from MOOD_VOCAB
      "themes": ["Late Night", "Rainy Day"],   // <= 3, from THEME_VOCAB
      "provenance": {
        "energy":   {"src": "acousticbrainz", "conf": 0.8, "at": "2026-07-16"},
        "tempo_bpm":{"src": "acousticbrainz", "conf": 0.9, "at": "2026-07-16"},
        "moods":    {"src": "llm:claude",     "conf": 0.5, "at": "2026-07-16"},
        "era":      {"src": "derived:year",   "conf": 1.0, "at": "2026-07-16"}
      }
    }
  }
}
```

Controlled vocabularies (curated *subsets* of the real AllMusic terms above,
sized for a radio clock — kept as small constants in an `overlay.py`, editable):

- `MOOD_VOCAB` (~24): Aggressive, Ambitious, Atmospheric, Bittersweet, Bleak,
  Boisterous, Brooding, Cathartic, Dreamy, Ethereal, Exuberant, Gritty,
  Hypnotic, Intimate, Laid-Back/Mellow, Lush, Melancholy, Nocturnal, Ominous,
  Plaintive, Rollicking, Swaggering, Trippy, Yearning.
- `THEME_VOCAB` (~16, chosen to line up with day-parts/blocks): Late Night,
  Night Driving, Day Driving, Road Trip, Rainy Day, Party Time, Club,
  Workout/Exercise, Introspection, Romantic Evening, Dinner Ambiance, Summer,
  Morning, Hanging Out, Empowering, Heartbreak.

Axis rationale (what's rejected and why): no per-instrument genes, no lyrics
genes, no key/scale as a *selection* axis (interesting but hard to use for
sequencing) — those are the parts of the Genome that need a human musicologist
or add complexity without serving a day-part clock. The seven kept axes are all
either directly in AcousticBrainz's high-level output or trivially derived
(`era` from the `year` we already have; `tempo_band` from `tempo_bpm`).

## Population options (ranked, cheapest first)

### (a) MusicBrainz MBID → AcousticBrainz lookup — CHEAPEST, CC0, no new infra

- **Method:** for each snapshot track, resolve a **recording MBID** via the
  MusicBrainz API (search by `artist` + `recording` title; store the top match
  + a match-confidence). Then GET AcousticBrainz high-level + low-level for that
  MBID → fill `tempo_bpm`, `key`, `danceability`, `acousticness`
  (acoustic/electronic classifier), `instrumental` (voice/instrumental),
  `energy`/`valence` (derived from mood classifiers, e.g. valence ≈ mood_happy
  − mood_sad; energy ≈ mood_aggressive/party blend).
- **Coverage:** good for well-known catalog tracks (of the ~7M AcousticBrainz
  MBIDs); **weak for obscure/new/personal rips** and anything with messy
  Artist/Title metadata. Realistic hit rate is unknown until we run it against
  our real library — measure it before committing.
- **Accuracy:** MBID match is the main risk (wrong recording → wrong data); AB's
  own BPM/mood quality is imperfect (the reason the project ended) but "good
  enough to sequence a homelab station" for energy/tempo bands.
- **Cost/infra:** two HTTP calls per track, MB rate-limited to **~1 req/s** →
  ~a few hours for a few-thousand-track library, run once, cached. **stdlib
  `urllib` only** (same idiom as `jellyfin_client.py`/`live_source.py`); no new
  dependency, no new infra. Optionally use local MB/AB dumps instead of the API
  to avoid rate limits (large downloads; only worth it for a big library).
- **Licensing:** **CC0** end to end. Cleanest option.

### (b) Local Essentia audio analysis — fills gaps, heavier

- **Method:** run Essentia over the actual audio (fetch each track via the
  existing `track_url`, or read files if co-located) to compute BPM/key/features
  and run the pretrained TF models for mood/danceability/genre/voice.
- **Coverage:** **100%** — works on any audio regardless of MBID/metadata; the
  only way to cover obscure tracks and our own rips.
- **Accuracy:** same model family as AB (it *is* AB's engine), so comparable;
  the valence/arousal regression models add a real valence axis.
- **Cost/infra:** CPU-only box — Essentia's lightweight **MusiCNN** models are
  documented to run **real-time** on CPU, so a library batch is feasible as a
  **one-time overnight job**, but it's heavyweight: a `pip`/Docker Essentia
  install (~big), TensorFlow on CPU, and decode+analyze per track. This is the
  "needs real compute" tier — CPU-doable but the first thing that would justify
  a fleet/GPU host if the library is large or re-run often.
- **Licensing:** library is **AGPL-3.0** (fine self-hosted); pretrained
  **models are CC BY-NC-SA 4.0** (fine for this non-commercial station, would
  block a commercial product). Record `src: "essentia"` + NC in provenance.

### (c) LLM tagging from artist+title+genre+year — fast, ungrounded

- **Method:** one `llm_backends.generate()` call per track (or batched) returns
  JSON `{moods:[...], themes:[...], energy, valence}` **constrained to
  `MOOD_VOCAB`/`THEME_VOCAB`**, given only Artist/Title/Genre/Year.
- **Coverage:** **100%**, instantly, for the *subjective tag* axes AcousticBrainz
  cannot provide at all (themes especially — there is no free numeric theme
  source anywhere).
- **Accuracy / hallucination bound:** this is **parametric memory**, ungrounded
  — the model is guessing "Late Night / Yearning" from the title. Acceptable
  **only for low-harm subjective axes** (mood/theme), where a wrong tag just
  makes a slightly-off block, not a factual error. **Never** use the LLM for
  `tempo_bpm`/`key` (it will confidently fabricate numbers). Bound the risk by:
  (1) constraining output to the fixed vocab (reject anything off-list); (2)
  storing `conf ≤ 0.5` and `src: "llm:<backend>"` so a grounded source always
  wins on merge; (3) operator spot-check; (4) prefer this only where (a)/(b)
  left the field empty. Familiar territory — same grounding discipline the
  news-brief and recap features already follow (`BACKLOG.md`).
- **Cost/infra:** reuses `llm_backends.py` (Ollama free / Claude paid) — no new
  infra. A few-thousand small calls is minutes on Ollama, cheap on Claude.

### (d) Hybrid — RECOMMENDED

Merge by provenance confidence, grounded sources winning:
1. Derive `era` from `year`, `tempo_band` from `tempo_bpm` (free, deterministic).
2. **(a)** fill numeric axes from AcousticBrainz for every track that resolves
   to an MBID — the CC0 backbone.
3. **(c)** run the **bounded LLM pass only for `moods`/`themes`** (and
   `energy`/`valence` where AB missed) — the AllMusic-style layer no free
   numeric source provides.
4. **(b)** Essentia batch **only for tracks (a) couldn't cover** — deferred
   until we've measured the AcousticBrainz miss rate on our real library.

This gets the highest coverage at the lowest cost/infra: most numeric axes free
and grounded, the distinctive AllMusic tag layer cheap-but-bounded, and the
expensive local-analysis step scoped to only the residual gaps.

## Selection use-cases for WRIT-FM

How music resolves **today:** each music segment carries a `query` string;
`resolve_music(query)` (in `jellyfin_client.py`) does blank→library shuffle,
else playlist substring match, else a **free-text Jellyfin search**, returning
up to `limit` items in Jellyfin's order (shuffle or search-rank). `hour_
templates.py` `DEFAULT_DAY_PARTS` hard-codes a genre *word* per day-part
(overnight `ambient/downtempo`, morning `upbeat/indie`, afternoon `rock/
electronic`, evening `soul/jazz`). There is **no re-ranking, no sequencing, and
no cross-track continuity** — the overlay adds exactly that as a **post-resolve
selection/ordering step**, without touching the hardened `block_player.py`.

Concretely, a small `overlay.py` `select(candidates, targets, n)` reads
`overlay.json` + `library_snapshot.json` and, given the item ids Jellyfin
returned (or the whole library), filters/re-ranks to a target profile. The
music segment resolution gains an optional overlay-driven mode; the rest of the
pipeline (track_url, the FIFO sink player) is unchanged.

- **Day-part energy arcs.** Replace/augment the genre *word* in `DEFAULT_DAY_
  PARTS` with an **energy/valence target curve**: overnight low-energy/low-
  arousal (energy ≤ 0.35), morning rising, afternoon peak, evening warm-down.
  The resolver picks tracks whose `energy` fits the hour's target band instead
  of trusting a genre string. Directly upgrades the existing day-part table.
- **Mood/theme blocks.** New block presets (`block_presets.py`) that select by
  **theme tag** — a "Late Night" block (themes ⊇ Late Night/Night Driving,
  energy low, valence brooding), a "Rainy Day" block, a "Workout" block. This
  is the AllMusic Themes vocabulary doing exactly what it was authored for
  (activity/situation fit), feeding the day generator's slots.
- **Similarity "more like this."** The Genome-lite idea: represent each track as
  its numeric vector `[energy, valence, tempo, acousticness, danceability,
  instrumental]` and select nearest neighbors by distance — a "seed a set from
  this track" mode for a segment, or ListenBrainz CF recommendations as an
  alternate similarity source.
- **Avoiding jarring transitions.** After selecting a segment's candidate set,
  **order** it so adjacent tracks have bounded deltas in `tempo_bpm`/`energy`/
  `valence` (greedy nearest-neighbor walk, or sort by energy). This removes the
  "ambient track slams into a thrash track" problem the current shuffle/search
  order has no defense against — and it's a pure post-processing sort, cheap and
  player-invisible.

## Phased build plan

In the spirit of `BACKLOG.md`: what's buildable now with no new infra vs. what
needs real compute. The stream stays live throughout; the overlay is read-only
enrichment that the selection step *consults* — nothing airs differently until
Phase 4 wires it in.

- **Phase 0 — snapshot + scaffold (now, stdlib only).** Run
  `library_snapshot.py` to produce `library_snapshot.json` (it already exports
  Genres/Tags/Year/Artists). Add `overlay.py` with the schema, the two
  controlled vocabularies, `era`/`tempo_band` derivations, and a load/merge/save
  for `overlay.json`. No network, no deps.
- **Phase 1 — CC0 backbone (now, network only).** MusicBrainz MBID resolution
  (artist+title, ~1 req/s, cached) → AcousticBrainz high-level/low-level lookup
  → numeric axes. stdlib `urllib`, a flat on-disk cache keyed by MBID, best-
  effort parse-with-fallback (the `live_source.py` idiom). **Measure the
  AcousticBrainz hit rate on our real library** — that number decides how much
  Phase 3 we need.
- **Phase 2 — bounded LLM tag pass (now, existing backends).** `moods`/`themes`
  (+ `energy`/`valence` where AB missed) via `llm_backends.generate()`,
  output constrained to `MOOD_VOCAB`/`THEME_VOCAB`, `conf ≤ 0.5`, grounded
  sources win on merge. Reuses Ollama/Claude — no new infra. Operator spot-check
  before trusting theme blocks.
- **Phase 3 — Essentia gap-fill (needs real compute; optional/deferred).** Only
  for the tracks Phase 1 couldn't resolve. Essentia + TF on CPU as a one-time
  overnight batch (feasible per the real-time MusiCNN note, but heavyweight —
  the first thing that would justify a fleet/GPU host). AGPL lib + NC models,
  recorded in provenance. Scope it by the Phase-1 miss rate; skip entirely if
  coverage is already good.
- **Phase 4 — wire into selection (now-buildable once data exists).**
  `overlay.py` `select()` as a post-resolve re-rank/order step; energy-arc day-
  parts in `hour_templates.py`; theme-block presets in `block_presets.py`;
  optional similarity mode. `block_player.py` untouched (same discipline as the
  recap feature). Verify with a coherence listen before it drives the live day.

Phases 0–2 and 4 need **no new dependency and no new infra** (stdlib + ffmpeg +
existing LLM backends). Only Phase 3 needs real compute, and it's optional and
gated on the measured coverage gap.

## Open questions / risks

- **AcousticBrainz coverage is unknown until measured.** Our library is a mix of
  known catalog and possibly obscure/personal rips; if the MBID→AB hit rate is
  low, the CC0 backbone thins out and Phase 3 (Essentia) becomes load-bearing
  rather than optional. Measure first (Phase 1), decide second.
- **MBID mismatch** — searching MusicBrainz by artist+title can return the wrong
  recording (live vs studio, remaster, cover). Store match confidence; consider
  requiring artist+title+album agreement before trusting the MBID.
- **AB data quality** — the project ended *because* BPM/mood/key were imperfect.
  Fine for coarse energy/tempo *bands* and sequencing; do not present these as
  precise ground truth.
- **LLM hallucination on tags** — bounded (fixed vocab, low-harm axes, low conf,
  spot-check) but not eliminated; never let the LLM touch numeric/factual axes.
- **Licensing for the future** — everything works today (non-commercial), but
  Essentia *models*, MusicBrainz *tags*, and Last.fm are NC/ToS-restricted; a
  commercial pivot would need to drop or re-license them. Provenance records
  which axis came from an NC source so this is auditable.
- **Vocab drift / staleness** — AllMusic's live vocab differs slightly from the
  2018–2020 archived captures used here; our subset is a curated constant we
  own, so this is cosmetic, but `vocab_version` lets us evolve it.
- **Snapshot freshness** — `overlay.json` keys on Jellyfin item ids; new imports
  need a re-snapshot + incremental enrichment (only the new ids). Cheap, but
  needs a "enrich only unseen ids" path, not a full re-run.

## Sources

AllMusic taxonomy (via Wayback Machine captures — the live site 403s fetchers):
- https://www.allmusic.com/faq — verbatim Genres/Styles/Moods/Themes definitions, "21 genres"
- https://www.allmusic.com/moods — mood vocabulary A–Z (~290 terms)
- https://www.allmusic.com/themes — theme vocabulary (~180 terms)
- https://www.allmusic.com/genres — the 21 genres
- https://www.allmusic.com/genre/pop-rock-ma0000002613 — 212 styles under Pop/Rock (genre→style shape)
- https://en.wikipedia.org/wiki/AllMusic — ~1,400 subgenres, Erlewine/founding, editorial authorship
- https://archives.ismir.net/ismir2009/paper/000106.pdf — "manually created by music experts"; 178 moods / 73 themes (2009)

Pandora Music Genome Project:
- https://en.wikipedia.org/wiki/Music_Genome_Project — ~450 genes, per-genre counts, 0–5 half-integer scale, 20–30 min/song, 10% QA, US Patent 7,003,515
- https://www.pandora.com/corporate/mgp.shtml — Pandora's own MGP description

MusicDNA (file format):
- https://en.wikipedia.org/wiki/MusicDNA_(file_format) — definition, metadata types, Jan-2010 non-adoption
- https://en.wikipedia.org/wiki/MusicDNA_(company) — Bach Technology, MIDEM 2010, later fingerprinting pivot
- https://www.rollingstone.com/music/music-news/mp3-creators-unveil-new-music-file-format-musicdna-100586/ — Bach "32GB / dynamically updatable" quote, Brandenburg
- https://thenextweb.com/news/musicdna-deluxe-file-format-mp3-innovators — MIDEM 2010, MPEG-7, Beggars Group & Tommy Boy trials

Open data sources:
- https://musicbrainz.org/doc/MusicBrainz_API — API, inc=genres/tags, ~1 req/s
- https://metabrainz.org/datasets/postgres-dumps — twice-weekly PG dumps
- https://musicbrainz.org/doc/MusicBrainz_Database/Download — CC0 core vs CC BY-NC-SA supplementary (tags/genres)
- https://musicbrainz.org/doc/Development/JSON_Data_Dumps — JSON dumps + per-item tag/genre licensing note
- https://blog.metabrainz.org/2018/11/02/musicbrainz-introducing-genres/ — genres = promoted tags
- https://musicbrainz.org/doc/AcousticBrainz — AB overview, "stopped collecting 2022," CC0, feature categories
- https://musicbrainz.wordpress.com/2022/02/16/acousticbrainz-making-a-hard-decision-to-end-the-project/ — shutdown announcement + reasons
- https://community.metabrainz.org/t/acousticbrainz-submissions-data-dumps-and-next-steps/589843 — ~30M submissions / ~7M unique MBIDs / ~900–1000 GB
- https://acousticbrainz.org/download — low-level (~589 GB) / high-level (~39 GB) dumps
- https://similarity.acousticbrainz.org/download — recording-similarity data (2022-07-06)
- https://acousticbrainz.readthedocs.io/api.html — REST API by MBID
- https://essentia.upf.edu/models.html — pretrained model catalog + CC BY-NC-SA 4.0 models license, real-time note
- https://mtg.github.io/essentia-labs/news/tensorflow/2020/01/16/tensorflow-models-released/ — TF model release / classifier list
- https://arxiv.org/pdf/2003.07393 — "TensorFlow Audio Models in Essentia"
- https://www.last.fm/api/tos — Last.fm ToS: non-commercial, no sub-license, usage cap
- https://www.last.fm/api — Last.fm Web Services 2.0 endpoint
- https://data.discogs.com/ — Discogs monthly XML dumps, CC0
- https://www.discogs.com/developers — Discogs API (genres/styles)
- https://listenbrainz.readthedocs.io/en/latest/users/api/recommendation.html — CF recommendation endpoint
- https://listenbrainz.readthedocs.io/en/latest/users/listenbrainz-dumps.html — full + daily dumps
- https://listenbrainz.org/data/ — data downloads index
