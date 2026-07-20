#!/usr/bin/env python3
"""Shared HTML shell for the panel's pages: ONE design system (tokens + base
components), ONE nav bar, and a visible JS-error banner so a broken page shows
the error instead of failing silently. Each page supplies only its own body,
page-specific CSS and script; page() wraps them in the shared document. This is
what keeps the styling universal and the pages concise -- no page re-declares
colors, buttons, forms, nav, or cards."""

BRAND = "HOME-FM"

# The single source of truth for the top nav. (href, label, active-key). A page
# passes its active-key to page(); the matching tab gets aria-current.
NAV = [
    ("/admin", "station", "station"),
    ("/blocks", "blocks", "blocks"),
    ("/day", "day", "day"),
    ("/browse", "music", "music"),
    ("/now", "now", "now"),
]

# The design system: tokens (light/dark), reset, typography, nav, cards,
# buttons, form controls, badges, status dots. Everything shared across pages
# lives here so a page's own CSS only carries what's unique to it.
BASE_CSS = """
:root{
  color-scheme:light dark;
  --bg:#0d1117;--surface:#161b22;--surface-2:#1c2431;--surface-3:#232d3b;
  --border:#2a3644;--border-strong:#3a4757;
  --text:#e6edf3;--muted:#93a1b0;--faint:#7f8c9b;
  --primary:#4c8dfb;--primary-fg:#0b1220;--primary-weak:#4c8dfb26;
  --success:#2fbf6b;--success-weak:#2fbf6b1f;--warn:#f0a935;--warn-weak:#f0a9351f;
  --danger:#f26d6d;--danger-weak:#f26d6d1f;
  --live:#2dd4bf;--live-weak:#2dd4bf24;--music:#a78bfa;--music-weak:#a78bfa24;--tts:#f472b6;--tts-weak:#f472b624;
  --font:system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  --mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  --fs-xs:.72rem;--fs-sm:.82rem;--fs-md:.92rem;--fs-lg:1.1rem;--fs-xl:1.35rem;
  --lh:1.45;--fw-med:600;--fw-bold:700;--track-caps:.04em;
  --s1:.25rem;--s2:.5rem;--s3:.75rem;--s4:1rem;--s5:1.5rem;--s6:2rem;--s7:3rem;
  --r-sm:8px;--r-md:12px;--r-lg:16px;--r-pill:999px;
  --tap:44px;--ctl-h:44px;--ctl-h-sm:40px;--ctl-pad-x:.85rem;
  --sh-1:0 1px 2px rgba(0,0,0,.35);--sh-2:0 6px 20px rgba(0,0,0,.45);
  --focus:0 0 0 2px var(--bg),0 0 0 4px var(--primary);--maxw:760px;
}
@media (prefers-color-scheme:light){:root:not([data-theme="dark"]){
  --bg:#f5f7fa;--surface:#fff;--surface-2:#eef2f7;--surface-3:#e4eaf1;
  --border:#d7dee7;--border-strong:#c2ccd8;--text:#141c26;--muted:#586573;--faint:#707b89;
  --primary:#2563eb;--primary-fg:#fff;--primary-weak:#2563eb14;
  --success:#15a34a;--success-weak:#15a34a17;--warn:#c2790a;--warn-weak:#c2790a17;
  --danger:#dc2626;--danger-weak:#dc262617;
  --live:#0d9488;--live-weak:#0d948817;--music:#7c3aed;--music-weak:#7c3aed17;--tts:#db2777;--tts-weak:#db277717;
  --sh-1:0 1px 2px rgba(16,24,40,.08);--sh-2:0 8px 24px rgba(16,24,40,.12);
}}
:root[data-theme="light"]{
  --bg:#f5f7fa;--surface:#fff;--surface-2:#eef2f7;--surface-3:#e4eaf1;
  --border:#d7dee7;--border-strong:#c2ccd8;--text:#141c26;--muted:#586573;--faint:#8a97a5;
  --primary:#2563eb;--primary-fg:#fff;--primary-weak:#2563eb14;
  --success:#15a34a;--success-weak:#15a34a17;--warn:#c2790a;--warn-weak:#c2790a17;
  --danger:#dc2626;--danger-weak:#dc262617;
  --live:#0d9488;--live-weak:#0d948817;--music:#7c3aed;--music-weak:#7c3aed17;--tts:#db2777;--tts-weak:#db277717;
  --sh-1:0 1px 2px rgba(16,24,40,.08);--sh-2:0 8px 24px rgba(16,24,40,.12);
}
*{box-sizing:border-box}html,body{margin:0}
body{font-family:var(--font);color:var(--text);background:var(--bg);max-width:var(--maxw);margin:0 auto;padding:var(--s3) var(--s3) var(--s7);line-height:var(--lh);font-size:var(--fs-md);-webkit-text-size-adjust:100%}
a{color:var(--primary);text-decoration:none}a:hover{text-decoration:underline}
:focus-visible{outline:none;box-shadow:var(--focus);border-radius:var(--r-sm)}
h1{font-size:var(--fs-xl);margin:var(--s1) 0;letter-spacing:-.01em}
h2{font-size:var(--fs-sm);margin:0;text-transform:uppercase;letter-spacing:var(--track-caps);color:var(--muted);font-weight:var(--fw-med)}
.sub{color:var(--muted);font-size:var(--fs-sm);margin-bottom:var(--s4)}
.mb4{margin:0 0 var(--s2)}
.mt2{margin-top:var(--s2)}.mt3{margin-top:var(--s3)}
.appbar{display:flex;align-items:baseline;justify-content:space-between;gap:var(--s3);flex-wrap:wrap;margin-bottom:var(--s2)}
.nav{display:flex;gap:var(--s1);flex-wrap:wrap;align-items:center;font-size:var(--fs-sm);margin-bottom:var(--s3)}
.nav a{color:var(--muted);padding:var(--s1) var(--s2);border-radius:var(--r-pill);min-height:var(--tap);display:inline-flex;align-items:center}
.nav a:hover{background:var(--surface-2);color:var(--text);text-decoration:none}
.nav a[aria-current="page"]{background:var(--primary-weak);color:var(--primary)}
section{margin:0 0 var(--s5)}
section>.hd2{display:flex;align-items:center;gap:var(--s2);border-bottom:1px solid var(--border);padding-bottom:var(--s2);margin-bottom:var(--s3)}
.hd2 .spacer{margin-left:auto}
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--r-lg);padding:var(--s4);box-shadow:var(--sh-1)}
button{font:inherit;font-size:var(--fs-sm);font-weight:var(--fw-med);min-height:var(--ctl-h);padding:0 var(--ctl-pad-x);border:1px solid transparent;border-radius:var(--r-pill);background:var(--primary);color:var(--primary-fg);cursor:pointer;display:inline-flex;align-items:center;justify-content:center;gap:var(--s1);transition:background .12s,border-color .12s,opacity .12s;white-space:nowrap}
button:hover{filter:brightness(1.06)}button:active{transform:translateY(1px)}
button.ghost{background:transparent;color:var(--primary);border-color:var(--border-strong)}
button.ghost:hover{background:var(--primary-weak);filter:none}
button.danger{background:transparent;color:var(--danger);border-color:var(--danger)}
button.danger:hover{background:var(--danger-weak);filter:none}
button:disabled{opacity:.4;cursor:not-allowed;filter:none;transform:none}
.mini{min-height:var(--ctl-h-sm);padding:0 var(--s3);font-size:var(--fs-sm)}
.icon-btn{min-width:var(--ctl-h-sm);padding:0 var(--s2);font-size:var(--fs-md)}
select,input,textarea{width:100%;box-sizing:border-box;font:inherit;font-size:var(--fs-md);min-height:var(--ctl-h);padding:var(--s2) var(--s3);border:1px solid var(--border-strong);border-radius:var(--r-md);background:var(--surface-2);color:var(--text)}
select{appearance:none;background-image:linear-gradient(45deg,transparent 50%,var(--muted) 50%),linear-gradient(135deg,var(--muted) 50%,transparent 50%);background-position:calc(100% - 18px) 50%,calc(100% - 13px) 50%;background-size:5px 5px,5px 5px;background-repeat:no-repeat;padding-right:2rem}
input::placeholder,textarea::placeholder{color:var(--faint)}
input:focus,select:focus,textarea:focus{border-color:var(--primary);outline:none}
label{display:block;font-size:var(--fs-xs);color:var(--muted);margin:0 0 var(--s1)}
audio{width:100%;margin:var(--s2) 0;border-radius:var(--r-md)}
.row{display:flex;gap:var(--s2);flex-wrap:wrap;align-items:center}
.status{display:flex;gap:var(--s4);flex-wrap:wrap;align-items:center;font-size:var(--fs-sm);color:var(--muted)}
.dot{display:inline-block;width:.6rem;height:.6rem;border-radius:50%;background:var(--faint);margin-right:var(--s1);vertical-align:middle}
.dot.ok,.dot.live{background:var(--success)}.dot.bad{background:var(--danger)}.dot.live{box-shadow:0 0 0 3px var(--success-weak)}
.badge{display:inline-flex;align-items:center;gap:.3em;font-size:var(--fs-xs);font-weight:var(--fw-med);line-height:1;padding:.32rem .55rem;border-radius:var(--r-pill);background:var(--surface-3);color:var(--muted)}
.badge.role{background:var(--primary-weak);color:var(--primary)}
.badge--live{background:var(--live-weak);color:var(--live)}
.badge--music{background:var(--music-weak);color:var(--music)}
.badge--tts{background:var(--tts-weak);color:var(--tts)}
.badge--airing{background:var(--success-weak);color:var(--success)}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:var(--surface-2);padding:var(--s3);border-radius:var(--r-sm);font:var(--fs-xs)/1.5 var(--mono);max-height:16rem;overflow:auto}
#errbar{position:sticky;top:0;z-index:100;margin:0 0 var(--s3);padding:var(--s2) var(--s3);border:1px solid var(--danger);border-radius:var(--r-md);background:var(--danger-weak);color:var(--danger);font-size:var(--fs-sm);font-family:var(--mono);white-space:pre-wrap;overflow-wrap:anywhere}
"""

# Registered as early as possible (in <head>) so it catches errors thrown by the
# page's own script. Surfaces uncaught errors + rejected promises in #errbar
# instead of leaving a silently half-rendered page -- the "visual error
# detecting" the pages otherwise lacked.
ERROR_JS = """
(function(){function show(m){var b=document.getElementById('errbar');if(!b)return;
b.hidden=false;b.textContent=(b.textContent?b.textContent+'\\n':'')+'\\u26a0 '+m;}
window.addEventListener('error',function(e){show(e.message+(e.lineno?(' ('+(e.filename||'').split('/').pop()+':'+e.lineno+')'):''));});
window.addEventListener('unhandledrejection',function(e){var r=e.reason;show('Unhandled: '+((r&&r.message)||r));});})();
"""


def _nav(active):
    items = "".join(
        '<a href="%s"%s>%s</a>' % (href, ' aria-current="page"' if key == active else "", label)
        for href, label, key in NAV
    )
    return '<div class="nav">%s</div>' % items


def page(active, title, body, css="", js=""):
    """Full HTML document: shared head (brand title, design system + page css,
    early error handler), unified appbar + nav, the page's body, then the page's
    script. `active` is the NAV key to highlight; `title` names the page."""
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>%s &middot; %s</title>"
        "<style>%s%s</style>"
        "<script>%s</script></head><body>"
        '<div class="appbar"><h1>%s &middot; %s</h1></div>%s'
        '<div id="errbar" role="alert" hidden></div>'
        "%s"
        "<script>%s</script></body></html>"
    ) % (BRAND, title, BASE_CSS, css, ERROR_JS, BRAND, title, _nav(active), body, js)
