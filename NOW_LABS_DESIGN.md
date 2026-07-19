# WRIT-FM `/now` — "Labs" Design System & Redesign Blueprint

A drop-in visual system for the `/now` operator surface. Token-driven, dark-first, mobile-first, zero-framework, CSP-safe (system fonts, unicode glyphs, no images/CDN). It restyles the **existing class + id vocabulary** in `now_page.py` so the wired `<script>` keeps working untouched, and adds a small set of optional additive classes for the Labs flow.

Load-bearing rule for the integrating engineer: the JS references these class names and `data-*` hooks and must not change. Everything below **keeps every existing selector name** (`nowcard`, `seg`, `bcard`, `badge`, `prog`, `line1`, `segt`, `meta`, `segctl`, `fields`, `detail`, `quote`, `tracks`, `runlog .lt/.k/.w`, `blocklist`, `bt`, `bs`, `edithead`, `title`, `dot ok/bad/live`, `sub`, `hd2`, `row`, `mini`, `ghost`, `danger`, `mb4`, `segnav`, `status`, `now`). New classes are purely additive — apply them by editing markup only, never the script.

## 1. Design principles

- **Glanceable monitor first.** The single most important question is "what is airing right now, and is output going where I think?" The now-playing card and the output state must be readable at arm's length, in one glance, with color + shape + text agreeing (never color alone).
- **Unambiguous state over decoration.** Every live/transient state (airing, switching, casting, stale, error, in-flight request) has a distinct, named visual treatment. "Looks dead" is the enemy — a button that was tapped and a stream that is rendering must both look busy.
- **Fast tinkering, low commitment.** `/now` is a Labs bench: build a throwaway block from a preset, poke at segment fields, ▶ to hear it on-air, then **commit** the good ones (Save / Save as new). Editing affordances are inline and immediate; "commit" actions are visually heavier than "tinker" actions.
- **Thumb-reachable, phone-native.** Primary device is a phone held one-handed. All interactive targets ≥44px, fluid single column, no horizontal body scroll; only intentionally-wide content (block library, run log, track lists) scrolls inside its own container.
- **Calm, dark-first palette.** The bench runs for long sessions in a home studio. Dark is the confident default; surfaces are near-black with low-chroma text. Saturated color is rationed for meaning (on-air green, warn amber, danger red, and the three segment-type accents) — not chrome.
- **Segment types are a language.** live / music / tts are the vocabulary of every block. Each gets a consistent accent + unicode glyph everywhere it appears (chip, monitor, editor row) so the operator reads a block's shape without reading its words.
- **Progressive disclosure.** Monitor and output are always visible; building, the block library, the day strip, and the log stack below in a predictable order. The editor appears in context under the library, not as a modal.
- **Reuse the sibling grammar.** `/blocks` and `/day` already speak in `.hd2` section headers, `.sub` captions, `.dot` status, pill buttons, `.seg`/`.badge`. This system is a superset so it can later re-skin those pages with the same tokens.

## 2. Design tokens (`:root`)

Dark is the base `:root` (confident default even with no system preference). Light is applied when the system asks for it OR when `data-theme="light"` is set; `data-theme="dark"` forces dark back. Recommended: ship `<html data-theme="dark">` to lock the bench dark, or omit `data-theme` to follow the OS.

```css
/* ============ TOKENS ============ */
:root{
  color-scheme: light dark;

  /* --- color roles (DARK = default) --- */
  --bg:#0d1117;            /* app background */
  --surface:#161b22;       /* cards, sections */
  --surface-2:#1c2431;     /* nested / inputs / raised */
  --surface-3:#232d3b;     /* hover / active fill */
  --border:#2a3644;        /* hairlines, card edges */
  --border-strong:#3a4757;
  --text:#e6edf3;          /* primary text */
  --muted:#93a1b0;         /* secondary text, captions */
  --faint:#63707e;         /* tertiary, disabled labels */

  --primary:#4c8dfb;       /* actions, links, selection */
  --primary-fg:#0b1220;    /* text ON a primary fill */
  --primary-weak:#4c8dfb26;/* primary tint fill */
  --success:#2fbf6b;       /* on-air, stream live, ok */
  --success-weak:#2fbf6b1f;
  --warn:#f0a935;          /* switching, stale, trouble */
  --warn-weak:#f0a9351f;
  --danger:#f26d6d;        /* destructive, error */
  --danger-weak:#f26d6d1f;

  /* segment-type accents (distinct from status + primary) */
  --live:#2dd4bf;          --live-weak:#2dd4bf24;   /* teal — news relay  */
  --music:#a78bfa;         --music-weak:#a78bfa24;  /* violet — music      */
  --tts:#f472b6;           --tts-weak:#f472b624;    /* pink — spoken/voice */

  /* --- typography --- */
  --font: system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  --mono: ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  --fs-xs:.72rem; --fs-sm:.82rem; --fs-md:.92rem;
  --fs-lg:1.1rem; --fs-xl:1.35rem;
  --lh:1.45; --lh-tight:1.25;
  --fw-med:600; --fw-bold:700;
  --track-caps:.04em;      /* letter-spacing for h2 caps labels */

  /* --- spacing scale (4px base) --- */
  --s1:.25rem; --s2:.5rem; --s3:.75rem; --s4:1rem;
  --s5:1.5rem; --s6:2rem;  --s7:3rem;

  /* --- radii --- */
  --r-sm:8px; --r-md:12px; --r-lg:16px; --r-pill:999px;

  /* --- controls / touch --- */
  --tap:44px;              /* min touch target */
  --ctl-h:44px;            /* full-size control height */
  --ctl-h-sm:34px;         /* compact editor control height */
  --ctl-pad-x:.85rem;

  /* --- elevation --- */
  --sh-1:0 1px 2px rgba(0,0,0,.35);
  --sh-2:0 6px 20px rgba(0,0,0,.45);
  --focus:0 0 0 2px var(--bg),0 0 0 4px var(--primary);

  --maxw:760px;            /* content column cap */
}

/* --- LIGHT: system asks for it (and not overridden to dark) --- */
@media (prefers-color-scheme: light){
  :root:not([data-theme="dark"]){
    --bg:#f5f7fa; --surface:#ffffff; --surface-2:#eef2f7; --surface-3:#e4eaf1;
    --border:#d7dee7; --border-strong:#c2ccd8;
    --text:#141c26; --muted:#586573; --faint:#8a97a5;
    --primary:#2563eb; --primary-fg:#ffffff; --primary-weak:#2563eb14;
    --success:#15a34a; --success-weak:#15a34a17;
    --warn:#c2790a;     --warn-weak:#c2790a17;
    --danger:#dc2626;   --danger-weak:#dc262617;
    --live:#0d9488;  --live-weak:#0d948817;
    --music:#7c3aed; --music-weak:#7c3aed17;
    --tts:#db2777;   --tts-weak:#db277717;
    --primary-fg:#ffffff;
    --sh-1:0 1px 2px rgba(16,24,40,.08);
    --sh-2:0 8px 24px rgba(16,24,40,.12);
  }
}

/* --- explicit overrides (user toggle stamps data-theme on <html>) --- */
:root[data-theme="light"]{
  --bg:#f5f7fa; --surface:#ffffff; --surface-2:#eef2f7; --surface-3:#e4eaf1;
  --border:#d7dee7; --border-strong:#c2ccd8;
  --text:#141c26; --muted:#586573; --faint:#8a97a5;
  --primary:#2563eb; --primary-fg:#ffffff; --primary-weak:#2563eb14;
  --success:#15a34a; --success-weak:#15a34a17;
  --warn:#c2790a; --warn-weak:#c2790a17;
  --danger:#dc2626; --danger-weak:#dc262617;
  --live:#0d9488; --live-weak:#0d948817;
  --music:#7c3aed; --music-weak:#7c3aed17;
  --tts:#db2777; --tts-weak:#db277717;
  --sh-1:0 1px 2px rgba(16,24,40,.08);
  --sh-2:0 8px 24px rgba(16,24,40,.12);
}
/* data-theme="dark" needs no block — dark is the base :root above.
   Its only job is to WIN over a light system preference, which the
   :not([data-theme="dark"]) guard on the media query already grants. */
```

Palette at a glance (dark / light):

| role | dark | light |
|---|---|---|
| bg | `#0d1117` | `#f5f7fa` |
| surface | `#161b22` | `#ffffff` |
| surface-2 | `#1c2431` | `#eef2f7` |
| border | `#2a3644` | `#d7dee7` |
| text | `#e6edf3` | `#141c26` |
| muted | `#93a1b0` | `#586573` |
| primary | `#4c8dfb` | `#2563eb` |
| success (on-air) | `#2fbf6b` | `#15a34a` |
| warn | `#f0a935` | `#c2790a` |
| danger | `#f26d6d` | `#dc2626` |
| live (news) | `#2dd4bf` | `#0d9488` |
| music | `#a78bfa` | `#7c3aed` |
| tts (voice) | `#f472b6` | `#db2777` |

## 3. Component CSS (drop-in classes)

Paste after the token block. Selectors that already exist in `now_page.py` are re-declared here token-driven (they override the old inline rules by later position / equal specificity — during integration, replace the old `<style>` body wholesale rather than layering). New additive classes are marked `/* NEW */`.

```css
/* ============ RESET / BASE ============ */
*{box-sizing:border-box}
html,body{margin:0}
body{
  font-family:var(--font); color:var(--text); background:var(--bg);
  max-width:var(--maxw); margin:0 auto; padding:var(--s3) var(--s3) var(--s7);
  line-height:var(--lh); font-size:var(--fs-md);
  -webkit-text-size-adjust:100%;
}
a{color:var(--primary); text-decoration:none}
a:hover{text-decoration:underline}
:focus-visible{outline:none; box-shadow:var(--focus); border-radius:var(--r-sm)}
h1{font-size:var(--fs-xl); margin:var(--s1) 0; letter-spacing:-.01em}
h2{font-size:var(--fs-sm); margin:0; text-transform:uppercase;
   letter-spacing:var(--track-caps); color:var(--muted); font-weight:var(--fw-med)}
.sub{color:var(--muted); font-size:var(--fs-sm); margin-bottom:var(--s4)}
.mb4{margin:0 0 var(--s2)}                 /* existing utility, kept */

/* ============ APP HEADER / NAV ============ */
.appbar{                                    /* NEW: wrap <h1> + nav */
  display:flex; align-items:baseline; justify-content:space-between;
  gap:var(--s3); flex-wrap:wrap; margin-bottom:var(--s2);
}
.nav{                                       /* NEW: replaces the .sub link row */
  display:flex; gap:var(--s1); flex-wrap:wrap; align-items:center;
  font-size:var(--fs-sm); margin-bottom:var(--s4);
}
.nav a{
  color:var(--muted); padding:var(--s1) var(--s2); border-radius:var(--r-pill);
  min-height:var(--tap); display:inline-flex; align-items:center;
}
.nav a:hover{background:var(--surface-2); color:var(--text); text-decoration:none}
.nav a[aria-current="page"]{background:var(--primary-weak); color:var(--primary)}

/* ============ SECTION / CARD ============ */
section{margin:0 0 var(--s5)}
section>.hd2{                               /* existing header rule, restyled */
  display:flex; align-items:center; gap:var(--s2);
  border-bottom:1px solid var(--border); padding-bottom:var(--s2);
  margin-bottom:var(--s3);
}
.card{                                      /* NEW: optional boxed grouping */
  background:var(--surface); border:1px solid var(--border);
  border-radius:var(--r-lg); padding:var(--s4); box-shadow:var(--sh-1);
}
.hd2 .spacer{margin-left:auto}             /* NEW: push a control to the right of a header */

/* ============ NOW-PLAYING MONITOR ============ */
/* id="now"; JS toggles class: "nowcard" | "nowcard on" | "nowcard on switching" */
.nowcard{
  position:relative; border:1px solid var(--border); border-radius:var(--r-lg);
  padding:var(--s4); background:var(--surface); box-shadow:var(--sh-1);
  overflow:hidden;
}
.nowcard.on{ border-color:var(--success); background:var(--success-weak); }
/* LIVE treatment: pure-CSS "ON AIR" pip in the corner, no JS hook needed */
.nowcard.on::before{
  content:"● ON AIR"; position:absolute; top:var(--s3); right:var(--s3);
  font-size:var(--fs-xs); font-weight:var(--fw-bold); letter-spacing:.06em;
  color:var(--success);
}
.nowcard.on::after{                         /* pulsing accent bar */
  content:""; position:absolute; left:0; top:0; bottom:0; width:4px;
  background:var(--success); animation:pulse 2.2s ease-in-out infinite;
}
.nowcard.switching{ border-color:var(--warn); background:var(--warn-weak); }
.nowcard.switching::before{ content:"◐ SWITCHING"; color:var(--warn) }
.nowcard.switching::after{ background:var(--warn) }
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}
@media (prefers-reduced-motion:reduce){ .nowcard.on::after{animation:none} }

.nowcard .line1{display:flex; align-items:center; gap:var(--s2); flex-wrap:wrap; padding-right:5.5rem}
.nowcard .segt{font-weight:var(--fw-bold); font-size:var(--fs-lg); letter-spacing:-.01em}
.nowcard .meta{font-size:var(--fs-sm); color:var(--muted); margin-top:var(--s2)}
.nowcard .meta b{color:var(--text); font-weight:var(--fw-med)}
.nowcard .prog{
  height:6px; border-radius:var(--r-pill); background:var(--surface-3);
  margin-top:var(--s3); overflow:hidden;
}
.nowcard .prog>i{display:block; height:100%; background:var(--success);
  width:0; transition:width .6s ease}
.now{font-size:var(--fs-md)}               /* fallback text state, kept */
.now b{font-weight:var(--fw-med)}

/* prev / next segment nav under the monitor */
.segnav{display:flex; align-items:center; gap:var(--s2); margin-top:var(--s3)}
.segnav .sub{flex:1; text-align:center; margin:0}

/* ============ BUTTONS ============ */
button{
  font:inherit; font-size:var(--fs-sm); font-weight:var(--fw-med);
  min-height:var(--ctl-h); padding:0 var(--ctl-pad-x);
  border:1px solid transparent; border-radius:var(--r-pill);
  background:var(--primary); color:var(--primary-fg); cursor:pointer;
  display:inline-flex; align-items:center; justify-content:center; gap:var(--s1);
  transition:background .12s,border-color .12s,opacity .12s; white-space:nowrap;
}
button:hover{filter:brightness(1.06)}
button:active{transform:translateY(1px)}
button.ghost{background:transparent; color:var(--primary); border-color:var(--border-strong)}
button.ghost:hover{background:var(--primary-weak); filter:none}
button.danger{background:transparent; color:var(--danger); border-color:var(--danger)}
button.danger:hover{background:var(--danger-weak); filter:none}
button:disabled{opacity:.4; cursor:not-allowed; filter:none; transform:none}
/* in-flight: JS already swaps label text ("Connecting…", "⋯"); this makes it read as busy */
button:disabled[aria-busy="true"], button.busy{opacity:.7; cursor:progress}
.mini{min-height:var(--ctl-h-sm); padding:0 var(--s3); font-size:var(--fs-sm)}
.icon-btn{                                  /* NEW: square glyph-only tap target */
  min-width:var(--ctl-h-sm); padding:0; font-size:var(--fs-md);
}
/* legacy .seg .play kept harmless (now editor uses .ghost.mini) */
.seg .play{margin-left:auto; background:transparent; color:var(--primary);
  border:1px solid var(--border-strong); min-height:var(--ctl-h-sm)}

/* ============ SEGMENTED CONTROL / PILL GROUP ============ */
.segmented{                                 /* NEW: e.g. a local|cast toggle */
  display:inline-flex; background:var(--surface-2); border:1px solid var(--border);
  border-radius:var(--r-pill); padding:3px; gap:2px;
}
.segmented button{
  background:transparent; color:var(--muted); border:none; min-height:var(--ctl-h-sm);
  border-radius:var(--r-pill); flex:1;
}
.segmented button[aria-pressed="true"], .segmented button.on{
  background:var(--primary); color:var(--primary-fg);
}

/* ============ INPUTS / SELECTS / LABELS ============ */
select,input,textarea{
  width:100%; box-sizing:border-box; font:inherit; font-size:var(--fs-md);
  min-height:var(--ctl-h); padding:var(--s2) var(--s3);
  border:1px solid var(--border-strong); border-radius:var(--r-md);
  background:var(--surface-2); color:var(--text);
}
select{appearance:none; background-image:
  linear-gradient(45deg,transparent 50%,var(--muted) 50%),
  linear-gradient(135deg,var(--muted) 50%,transparent 50%);
  background-position:calc(100% - 18px) 50%,calc(100% - 13px) 50%;
  background-size:5px 5px,5px 5px; background-repeat:no-repeat; padding-right:2rem}
input::placeholder,textarea::placeholder{color:var(--faint)}
input:focus,select:focus,textarea:focus{border-color:var(--primary); outline:none}
label{display:block; font-size:var(--fs-xs); color:var(--muted); margin:0 0 var(--s1)}
audio{width:100%; margin:var(--s2) 0; border-radius:var(--r-md)}

/* one-line control clusters */
.row{display:flex; gap:var(--s2); flex-wrap:wrap; align-items:center}
#target{flex:1; min-width:11rem}           /* existing hook, kept */

/* ============ STATUS / DOTS / CHIPS-BADGES ============ */
.status{display:flex; gap:var(--s4); flex-wrap:wrap; align-items:center; font-size:var(--fs-sm); color:var(--muted)}
.dot{display:inline-block; width:.6rem; height:.6rem; border-radius:50%;
  background:var(--faint); margin-right:var(--s1); vertical-align:middle}
.dot.ok,.dot.live{background:var(--success)}
.dot.bad{background:var(--danger)}
.dot.live{box-shadow:0 0 0 3px var(--success-weak)}

/* base badge/chip — pill, low-key */
.badge{
  display:inline-flex; align-items:center; gap:.3em;
  font-size:var(--fs-xs); font-weight:var(--fw-med); line-height:1;
  padding:.32rem .55rem; border-radius:var(--r-pill);
  background:var(--surface-3); color:var(--muted);
}
.badge.role{background:var(--primary-weak); color:var(--primary)}   /* existing: segment_role */

/* NEW: segment-type accent chips. Content includes a unicode glyph.
   Apply .badge--live / --music / --tts (one-line JS hook, see §5). */
.badge--live{ background:var(--live-weak);  color:var(--live) }
.badge--music{background:var(--music-weak); color:var(--music) }
.badge--tts{  background:var(--tts-weak);   color:var(--tts) }
.badge--airing{background:var(--success-weak); color:var(--success)}  /* replaces JS inline green */
.badge--stale{background:var(--warn-weak); color:var(--warn)}
/* left accent border for a whole card, keyed to type (NEW, see §5) */
.t-live{  --seg-accent:var(--live) }
.t-music{ --seg-accent:var(--music) }
.t-tts{   --seg-accent:var(--tts) }

/* ============ BLOCK LIBRARY (scrollable cards) ============ */
.blocklist{
  display:flex; flex-direction:column; gap:var(--s2);
  max-height:16rem; overflow:auto; margin-bottom:var(--s3);
  -webkit-overflow-scrolling:touch;
  scrollbar-width:thin; scrollbar-color:var(--border-strong) transparent;
}
.bcard{
  border:1px solid var(--border); border-left:3px solid var(--border);
  border-radius:var(--r-md); padding:var(--s3); cursor:pointer;
  background:var(--surface); min-height:var(--tap); transition:border-color .12s,background .12s;
}
.bcard:hover{border-color:var(--border-strong)}
.bcard.sel{border-color:var(--primary); border-left-color:var(--primary); background:var(--primary-weak)}
.bcard.airing{border-left-color:var(--success)}
.bcard .bt{font-weight:var(--fw-med); display:flex; gap:var(--s2); align-items:center; flex-wrap:wrap}
.bcard .bs{font-size:var(--fs-sm); color:var(--muted); margin-top:var(--s1);
  overflow:hidden; text-overflow:ellipsis; white-space:nowrap}

/* ============ SEGMENT EDITOR ROW ============ */
/* editHead: title + add-type + Save/Save-as */
.edithead{display:flex; gap:var(--s2); flex-wrap:wrap; align-items:center; margin:var(--s1) 0 var(--s3)}
.edithead input.title{flex:1; min-width:9rem; font-weight:var(--fw-med)}

/* a segment card (id-less; class "seg", "seg airing" when the airing one) */
.seg{
  border:1px solid var(--border); border-left:3px solid var(--seg-accent,var(--border));
  border-radius:var(--r-md); padding:var(--s3); margin-bottom:var(--s2);
  background:var(--surface);
}
.seg.airing{border-color:var(--success); background:var(--success-weak)}
.seg .hd{display:flex; align-items:center; gap:var(--s2); flex-wrap:wrap}
.seg .name{font-weight:var(--fw-med); overflow:hidden; text-overflow:ellipsis; min-width:0}
.seg .detail{font-size:var(--fs-sm); color:var(--muted); margin-top:var(--s2)}
.seg .quote{border-left:3px solid var(--border-strong); padding-left:var(--s3);
  margin:var(--s2) 0; font-style:italic; color:var(--muted)}
.tracks{font-size:var(--fs-sm); color:var(--muted); margin-top:var(--s2)}

/* compact editable field grid */
.seg .fields{display:flex; gap:var(--s2); flex-wrap:wrap; margin-top:var(--s3)}
.seg .fields label{font-size:var(--fs-xs); color:var(--muted);
  display:flex; flex-direction:column; gap:var(--s1); flex:1 1 8rem}
.seg .fields input,.seg .fields select{min-height:var(--ctl-h-sm); padding:var(--s2);
  font-size:var(--fs-sm)}

/* control cluster (▶ cutover, move, remove) — pushed to the right edge of .hd */
.seg .segctl{margin-left:auto; display:flex; gap:var(--s1); flex-shrink:0}
.seg .segctl button{min-height:var(--ctl-h-sm); min-width:var(--ctl-h-sm); padding:0 var(--s2); font-size:var(--fs-sm)}

/* ============ RUN-LOG CONSOLE ============ */
.runlog{
  font:var(--fs-xs)/1.6 var(--mono); background:#0a0e14; color:#c9d4e0;
  border:1px solid var(--border); border-radius:var(--r-md);
  padding:var(--s3); max-height:15rem; overflow:auto;
  -webkit-overflow-scrolling:touch;
  scrollbar-width:thin; scrollbar-color:var(--border-strong) transparent;
}
:root[data-theme="light"] .runlog,
:root:not([data-theme="dark"]) .runlog{background:#0f1620; color:#d5e0ec} /* console stays dark for legibility in both themes */
.runlog .lt{color:var(--faint); margin-right:var(--s2)}
.runlog .k{color:var(--primary)}           /* ok events */
.runlog .w{color:var(--warn)}              /* trouble events */

/* ============ MOBILE BOTTOM ACTION BAR (optional) ============ */
.actionbar{                                 /* NEW: sticky output control on phones */
  position:sticky; bottom:0; z-index:5;
  display:flex; gap:var(--s2); align-items:center;
  padding:var(--s2) var(--s3);
  margin:var(--s4) calc(-1 * var(--s3)) 0;   /* bleed to viewport edges */
  background:color-mix(in srgb,var(--surface) 88%,transparent);
  backdrop-filter:blur(8px); border-top:1px solid var(--border);
}
.actionbar button{flex:1}
@media (min-width:640px){ .actionbar{position:static; margin:var(--s3) 0 0; border:0; background:none; backdrop-filter:none} }

/* ============ WIDE-CONTENT GUARD ============ */
pre{white-space:pre-wrap; overflow-wrap:anywhere; background:var(--surface-2);
  padding:var(--s3); border-radius:var(--r-sm); font:var(--fs-xs)/1.5 var(--mono);
  max-height:16rem; overflow:auto}
```

## 4. `/now` "Labs" layout blueprint

Flow, top to bottom, reframed as a Labs bench: **Monitor → Output → Build/Tinker/Commit → Library+Editor → Day → Log.** Output sits directly under the monitor because "what's airing" and "where it goes" are the two always-glance concerns; everything below is bench work.

Ordering rationale: the monitor answers *what*; output answers *where*; Build → Library/Editor is the tinker→commit loop; Day is the forthcoming higher-level scheduler (placed after the block bench because you compose a day out of committed blocks); the log is reference, last.

### Mobile wireframe (single column, ~360px)

```
┌───────────────────────────────┐
│ WRIT-FM · now        [☾ theme] │  .appbar  (h1 + optional theme toggle)
│ station · blocks · day · now   │  .nav
├───────────────────────────────┤
│ NOW AIRING            ● ON AIR │  .nowcard.on   ← green pulse bar at left
│ [role][tts] Weather · KDVS     │  .line1 (accent type chip + segt)
│ Morning Drive · seg 2/5 · 1m3s │  .meta
│ ▓▓▓▓▓▓▓░░░░░░░░░░░░             │  .prog
│ [◀ prev]   seg 2/5   [next ▶]  │  .segnav
├───────────────────────────────┤
│ OUTPUT                         │  hd2
│ Play here OR one speaker.      │  .sub
│ [ This device ▾ ] [Play][Stop] │  .row  (#target select + pill buttons)
│ [Rescan]                       │
│ ● Stream live · 3 listening    │  .status
│ casting to Kitchen             │  #outMsg
│ ♫ /stream ↗                    │
├───────────────────────────────┤
│ BUILD A BLOCK                  │  hd2 — the "new experiment" launcher
│ [ preset ▾ ][genre1][genre2]   │  .row
│ [ Create ]                     │
├───────────────────────────────┤
│ BLOCKS (library)               │  hd2
│ ┌───────────────────────────┐  │  .blocklist (scrolls inside)
│ │▎Morning Drive  5 seg  airing│ │  .bcard.airing (green left edge)
│ │ Weather → news → jazz…      │ │  .bs
│ │▎Late Night     4 seg  saved │ │  .bcard
│ └───────────────────────────┘  │
│ ── editor (selected block) ──  │  #editHead / #blockView
│ [ Morning Drive        ] +tts  │  .edithead
│                    +music +news│
│                    [Save][as new]
│ ┌─▎tts──────────────────────┐  │  .seg.t-tts (pink left edge)
│ │● 🎙 Weather   ▶ ↑ ↓ ✕      │ │  .hd + .segctl
│ │ topic[▾] voice[▾] loc[__]  │ │  .fields
│ └───────────────────────────┘  │
│ ┌─▎music────────────────────┐  │  .seg.t-music (violet)
│ │● ♫ jazz       ▶ ↑ ↓ ✕      │ │
│ └───────────────────────────┘  │
├───────────────────────────────┤
│ DAY SCHEDULE          (soon)   │  #daySection  ← placeholder, see below
│ 24-hour strip; assign blocks.  │
├───────────────────────────────┤
│ RUN LOG                        │  hd2
│ ┌───────────────────────────┐  │  .runlog (mono console, scrolls)
│ │12:04 airing block morning… │ │
│ │12:05 cutover → seg 2       │ │
│ └───────────────────────────┘  │
└───────────────────────────────┘
```

### Per-element mapping (every existing `id` → class/wrapper)

Restyle-only. Where a wrapper change is suggested it is markup-only and does not touch the script. "keep" = element already carries the right class, it just inherits the new token styling.

**Header / nav**
- Wrap `<h1>` in `<div class="appbar">`; the h1 keeps its text. (Optional: add a theme toggle button as a sibling — a `<button class="ghost mini icon-btn">` that flips `data-theme` on `<html>`; behavior is the engineer's, not specced here.)
- Replace `<div class="sub">` nav links with `<div class="nav">`; mark the current page `aria-current="page"`. (Purely presentational — the anchors are unchanged.)

**Output section**
- `#target` — keep (`.row` flex child, `#target` hook already sized). It is a `<select>` styled by the global select rule.
- `#btnOut` — primary button (default). Add `aria-busy` toggling is optional; JS already swaps its label to "Connecting…/Starting…", which now reads as busy via the label + `button.busy` if the engineer adds it.
- `#btnOutStop`, `#btnRescan` — `button.ghost` (keep). Consider grouping `#btnOut`/`#btnOutStop`/`#btnRescan` inside the optional `.actionbar` so output control is thumb-reachable while scrolling; leave the `<select>` and `<audio>` in the section body.
- `#player` (`<audio>`) — keep; styled by `audio{}`.
- `.status` block (`#sdot`,`#sstate`,`#listeners`,`#stitle`,`#surl`) — keep; `#sdot` uses `.dot.live/.bad`.
- `#outMsg` — keep as `.sub`.

**Now airing (Monitor) — move this section ABOVE Output in the markup**
- `#now` — keep id and the JS-driven `nowcard`/`on`/`switching` classes. The new `.nowcard.on::before/::after` gives the LIVE treatment with no JS change. Inner `.line1/.segt/.meta/.prog/#elapsed` all keep their classes.
- `#btnPrev`,`#btnNext` — `button.ghost` (keep). `#navMsg` — `.sub` (keep). Wrapper `.segnav` keep.
- `#queue` — keep `.sub`.

**Build a block**
- `#preset` select, `#genre1`/`#genre2` inputs, `#btnBuild` (primary), `#buildMsg` (`.sub`) — all keep, inside `.row`. Optionally wrap the section body in `.card` to read as "the experiment launcher."

**Blocks (library + editor)**
- `#blockList` (`.blocklist`) — keep; cards `.bcard/.sel/.airing` restyled with a left accent edge. The airing badge JS injects inline-green can be swapped to `.badge--airing` (a one-line JS edit if desired; not required — the inline style still works).
- `#editHead` (`.edithead`) — keep. Contains `#btitle` (`input.title`), the three `data-add` buttons (`.ghost.mini`), `#btnSave` (`.mini` primary = **commit**, visually heavier), `#btnSaveAs` (`.ghost.mini`).
- `#switchMsg` — `.sub` (keep).
- `#blockView` — keep; renders `.seg` cards. To get the type accent edge, add `t-<type>` to each seg's class (see §5) — one-line JS, optional.
- `#voiceList` (`<datalist>`) — vestigial (the editor uses `<select>` voice pickers via `optSel`, not this datalist). Leave in place; it is inert. Flag for removal in a later cleanup.

**Day (new placeholder)**
- Insert a new `<section id="daySection">` between Blocks and Run log:
  ```html
  <section id="daySection">
    <div class="hd2"><h2>Day schedule</h2></div>
    <div class="sub">24-hour strip — assign, generate, and edit the day's blocks. Coming to Labs.</div>
    <div class="card sub">Placeholder — the day builder mounts here.</div>
  </section>
  ```
  Positioned after the block bench (you assign committed blocks into the day). Uses the same `.hd2`/`.card` grammar so it drops in without new CSS. When the real builder lands, reuse `/day`'s `.hour` card idiom re-skinned with these tokens.

**Run log**
- `#runlog` (`.runlog`) — keep; restyled as a proper mono console (dark in both themes for legibility). `.lt/.k/.w` keep their meaning (timestamp / ok / trouble).

## 5. Segment-type & voice affordances

Three types, one consistent visual language everywhere they appear (monitor chip, library summary, editor row). Glyphs are unicode only:

| type | glyph | accent token | chip class | meaning |
|---|---|---|---|---|
| live | `📡` or `◉` | `--live` (teal) | `.badge--live` | live news relay (NPR/BBC/…) |
| music | `♫` | `--music` (violet) | `.badge--music` | Jellyfin music |
| tts | `🎙` or `🗣` | `--tts` (pink) | `.badge--tts` | spoken TTS content |

TTS **topics** (`weather`, `recap`, `factoid`, `freeform`) read as a secondary glyph next to the tts chip, so a tts segment shows both "it's voice" and "what it says":
- weather `☀`, recap `↺`, factoid `✦`, freeform `✎`.

Recommended presentation (each is markup/CSS only; the two starred items need a one-line JS touch, clearly optional):
- **Type chip** — the plain `<span class="badge">tts</span>` becomes `<span class="badge badge--tts">🎙 tts</span>`. *This is the single tiny JS change* (`segEntity`, `renderNow`, `loadList`): append `' badge--'+seg.type` to the badge class and prefix the glyph. Until that lands, all chips render as neutral `.badge` — correct, just un-accented. Flag as an enhancement, not a blocker.
- **Card accent edge** — add `t-<type>` to each `.seg` (sets `--seg-accent`, drawing the 3px left border in the type color). Same one-line hook. The library `.bcard` keeps its state-driven left edge (selected=blue, airing=green) and does not carry a type edge (a block mixes types).
- **Editor fields** stay in the existing `.fields` grid; no per-type layout change — the accent edge + chip already telegraph the type, keeping the tinker grid uniform and scannable.

**Voice picker** (tts segments): the existing `optSel('voice', …)` `<select>` with `(default)` first. Style: it is one `.fields label > select` like any other field, but give it a spoken glyph in its label — `<label>🗣 voice …</label>` — so voice is findable at a glance among topic/location/prompt. No component beyond the standard select is needed (keeps CSP-safe, no custom dropdown). Selected non-default voice can be signaled by the tts accent already on the row.

**Source picker** (live segments): the existing `optSel('source_id', …)` `<select>`, first option `Auto — rotating bulletin`. Prefix its label with the live glyph `<label>📡 source …</label>`. "Auto" is the meaningful default and should stay visually first; no extra treatment needed.

Design intent: the operator should never have to read a segment to know its shape — glyph + accent + chip color carry type; the field grid carries the tinker detail. Color is always paired with glyph/text (never the sole signal), for colorblind legibility and for the dark bench.

## 6. What to defer (nice-to-have later)

- **Theme toggle button** — the tokens already support `data-theme`; a header toggle that stamps `<html data-theme>` and persists to `localStorage` is a small later add (behavior = engineer's).
- **Type-accented chips/edges wiring** — the one-line JS hooks in §5 (`badge--<type>`, `t-<type>`, glyphs). Ships value but requires touching the script; land after the pure-CSS restyle is verified.
- **Real Day builder** — `#daySection` is a placeholder now; the 24-hour strip (reuse `/day`'s `.hour` idiom on these tokens) is its own effort.
- **Sticky `.actionbar`** — offered as optional; adopt only if testing shows the output controls scroll out of thumb reach in practice.
- **Segment field validation states** — `input.invalid` / inline hint styling (e.g. empty required source) — a later polish; today's fields are permissive.
- **Retire the vestigial `#voiceList` datalist** — dead markup; remove in a cleanup pass.
- **Collapse/expand for the Build and Log sections** — a `<details>`-based accordion to shorten the phone scroll once the Day section adds height. Deferred to avoid over-structuring now.
- **Micro-animations** beyond the on-air pulse (progress ease is included) — keep minimal; respect `prefers-reduced-motion` (already wired for the pulse).
