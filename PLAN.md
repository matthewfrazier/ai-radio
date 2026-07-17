# Revision plan: programming blocks → reliable 24/7 management surface

Written 2026-07-17 from a three-agent review (architecture/strategy, code
correctness, product/ops) of the overlay against `PROGRAM_BLOCKS.md`'s goal.
This plan supersedes ad-hoc iteration: work the phases in order, each phase
lands as its own verified commit(s), and nothing outside a phase gets touched
while it's in flight.

## Resolution (2026-07-17) — executed

P0–P3 all landed as verified commits (traversal/rmtree, play-now no-op,
player wedge; air-time re-render, systemd-supervised player with Conflicts=
mount arbitration + journald logging + flock; save-before-act, preview
fidelity, FIFO write loop, HTML escaping; disk hygiene + Content-Length +
conf handles; the time-based scheduler). Each was exercised against the live
service (play-now cutover, drain, SIGKILL recovery, boot reconciliation, a
real timed scheduler fire) plus 44 unit tests. Strategic: live sources
relabeled honestly (3 real bulletins vs 8 "(live)" relays, item 16); fleet
Playwright host requested on the bus (item 17). **Item 15 (config lift of
BASE/endpoints into station.json) intentionally NOT done** — BASE is a fixed
dedicated-CT path (not an environment that varies), llm_backends can't import
block_render without a cycle, and the plan's own "do NOT churn / defer the
package move" guidance applies; it's a testability nicety with no goal/safety
value, so forcing a cross-module refactor into a live 24/7 station was judged
the wrong call. Revisit only alongside a future "graduate to own CT" move.

## Where the project actually stands

Everything in the literal goal list is implemented and most of it is
genuinely verified (the review confirmed the progress log is honest, not
rubber-stamped). Module-level quality is good: the FIFO sink design, the
single `render_block()` path, the atomic JSON writes, the minimal registries,
and the stdlib-only constraint all hold up and should not be churned.

The gap is concentrated in exactly the two properties a radio station needs
most: **never air stale content** and **always be airing something**. Both
are currently the least-guaranteed parts of the system, and one confirmed bug
can destroy the whole install. Focus follows severity, not novelty: no new
features (including the wanted time-based scheduler) until the P0/P1 items
are closed, because they all sit under any feature that would be added.

## P0 — safety: fix before anything else

1. **Path traversal in `DELETE /api/blocks/{id}` can rmtree the entire app.**
   `delete_block()` joins the raw URL segment into `block_dir()` and only
   checks `isdir` — `DELETE /api/blocks/..` resolves to `/opt/writ-fm` and
   deletes code, secrets (`jellyfin.conf`, `.stubenv`, `anthropic.conf`,
   `weather.conf`), and all state while the service runs. Confirmed by trace.
   Fix: validate `block_id` against the id format
   (`^[0-9]{8}T[0-9]{6}(-[0-9]+)?$`) in one helper used by every
   block-id-consuming route, not just DELETE.

2. **"Play Now" while a block is airing silently plays nothing.**
   `schedule_block("now")` overwrites the queue before SIGTERMing the old
   player; the dying player's loop then unconditionally `pop_front()`s —
   popping the new block. The new player finds an empty queue, exits, and
   restarts the static loop. Deterministic, not a race window; this is the
   primary use case of the button. Fix: kill-and-wait first, write the queue
   after; and make the player only pop the block it actually played
   (`pop_front(expected_id)`).

3. **Player wedges unkillable on any Icecast/credential failure.**
   `Sink.respawn()`'s `os.open(FIFO, O_WRONLY)` blocks forever if the sink
   ffmpeg dies at startup, and PEP-475 retry semantics mean SIGTERM never
   interrupts it — silent dead air (writ-stream already stopped) requiring
   SIGKILL. Fix: open the FIFO non-blocking in a bounded retry loop that
   checks `_stop_requested` and `sink_proc.poll()` each iteration; treat
   "sink died before opening reader" as a failed spawn, restore writ-stream,
   exit nonzero.

## P1 — broadcast reliability (the "always airing, never stale" layer)

4. **Staleness is enforced at schedule time, not air time.** A block queued
   behind an hour of programming airs hour-old weather, an hour-old
   "latest" bulletin, and hour-old Jellyfin URLs — the exact thing the goal
   forbids. Fix (~2 lines): `block_player.main` calls
   `br.render_block(block_id, force=False)` and reloads before playing each
   block. Keep the schedule-time render too (it surfaces errors in the UI
   early). Then actually run the never-executed staleness test and record it.

5. **Supervise the player with systemd; let systemd arbitrate the mount.**
   Today: detached Popen, cleanup only in a `finally` (skipped on
   OOM/SIGKILL → dead air with no recovery), PID-reuse can fake "running",
   reboot strands queued blocks as `"queued"` forever, and the dying
   player's writ-stream restart races the new player's sink for the mount
   (worsened by `stream.sh`'s broad pkill). Fix: `writ-block-player.service`
   (Type=simple, no auto-restart — natural drain exits 0) with
   `Conflicts=writ-stream.service` both ways and
   `ExecStopPost=systemctl start writ-stream.service` (runs even on kill);
   panel uses `systemctl start/stop/is-active` instead of Popen/PID-file
   guesswork; on panel startup, reconcile a non-empty queue (resume or
   clear). This removes the dead-air, stranded-queue, and mount-fight modes
   in one move.

6. **Give the player logs.** It currently runs with stdout/stderr DEVNULL —
   the one process feeding the live mount is a black box; "why did X not
   air" is unanswerable. The systemd unit from item 5 gets this for free via
   journald. Add one-line segment start/finish/skip prints so the journal
   actually says what aired.

7. **Cross-process locking.** `block.json` render vs save is an unlocked
   read-modify-write (lost updates between panel threads); `block_queue.json`
   is mutated by two processes (append can clobber pop); double-clicked
   Queue/Play buttons can spawn two players onto one FIFO. Fix: one ~15-line
   `with locked(path):` helper using `fcntl.flock`, wrapped around block
   mutation and the four queue functions; disable schedule buttons while a
   request is in flight (the Test buttons already do this).

## P2 — operator trust (what you see is what airs)

8. **Acting on a block must act on what's on screen.** Preview refetching
   the server copy discards unsaved edits (known); worse, Play Now/Queue
   silently air the old saved config after an unsaved edit — no warning at
   all. Fix: Preview and Schedule save first (reuse the existing save POST,
   call-ordering only).

9. **Music preview must play what will air.** Preview re-resolves music
   randomly (`SortBy=Random`, limit 20) independent of the rendered
   `music_seg-*.txt` (limit 200) — previewed tracks can share nothing with
   broadcast. Fix: serve preview tracks from the segment's already-resolved
   playlist file (new small `GET /api/blocks/{id}/tracks/{seg_id}`), not a
   fresh `music_test` roll.

10. **FIFO partial writes.** 64KB chunks against a pipe under backpressure
    can short-write; the remainder is dropped → clicks/channel-desync until
    the next segment. Fix: standard write-until-consumed loop
    (`memoryview` + offset).

11. **Escape user text in the UI.** Block titles, queries, prompts, and
    Jellyfin track names are interpolated into `innerHTML` unescaped —
    persistent XSS-class defect (low blast radius single-operator, still a
    defect, and Jellyfin metadata is externally sourced). Fix: one `esc()`
    helper applied at every interpolation; keep the zero-framework
    convention.

## P3 — completing the stated goal

12. **Time-based scheduler — the largest remaining goal gap.** Only
    play-now/queue exist; the goal says *scheduled* hour-long blocks.
    Smallest viable: flat `schedule.json` (`{time, block_id, days?}`), a
    once-a-minute tick thread in the already-running panel that queues
    blocks when due, and a small Schedule section in `/blocks`. Reconcile
    with upstream's `config/schedule.yaml` model first so we extend rather
    than duplicate. No task-queue framework.

13. **Disk hygiene on a 20G box (7G free).** Nothing ever cleans
    `program_blocks/` render artifacts (unbounded at 24/7 cadence) and a
    failed ffmpeg convert strands `.wav`s. Fix: `try/finally` the wav
    removal; one systemd timer running
    `find program_blocks -maxdepth 1 -mtime +14` cleanup for
    played/unreferenced blocks.

14. **Content-Length parsing consistency + conf-parser file handles** —
    two `int()` calls crash on an empty header where every sibling route
    degrades gracefully; four conf parsers leak fds (flagged by tests).
    Mechanical fixes, fold into whichever phase touches those files.

## Strategic (do once, deliberately)

15. **Lift environment literals into `station.json`.** `BASE`, Kokoro,
    Ollama, and the radioscript endpoint are hardcoded across ~6 modules —
    the single biggest obstacle to testing without monkeypatching and to a
    future "graduate to own CT" move. Config-only change, no restructuring;
    defer any package-dir reshuffle (upstream doesn't collide at root today).

16. **De-scope the live-source list.** 11 sources but only 3 genuine
    bulletins (npr, bbc_world, dw_brief); the other 8 full-channel relays
    add URL-rot surface the goal never asked for. Decision wanted from the
    operator: trim to bulletins + 1–2 relays, or keep all with honest
    "(live)" labels.

17. **Stand up the fleet Playwright host.** Every UI bug found in this
    project was caught by a real browser, never by curl — browser testing is
    load-bearing. The current install-810MB-Chromium-then-delete cycle on
    this disk-tight box is the top testing bottleneck. Action: bus request
    to raserver-homelab for the dedicated test host (or an on-demand CT);
    out of scope for this repo's code.

## Explicitly not doing

Async frameworks or job queues (ThreadingHTTPServer + locking is enough);
databases; auth/multi-user; plugin layers on the registries; moving overlay
files into a package while upstream doesn't collide; caching in the Jellyfin
client; replacing the FIFO sink mechanism (only its supervision changes).

## Verification discipline

Each phase ends with: lint+tests green (pre-commit enforces), the affected
flow exercised against the real service (curl for API, a browser pass for UI
changes — Playwright until the fleet host exists), `PROGRAM_BLOCKS.md`
status updated, then commit. P0 items additionally get a regression test in
`tests/test_ai_radio_blocks.py` (the traversal and queue-race bugs are both
unit-testable).
