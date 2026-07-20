#!/usr/bin/env python3
"""/now -- the Labs operator surface. A sticky top zone always shows what is
airing right now (track-accurate) plus playback + output controls; below it a
tabbed workspace (Editor / Details / Blocks / Generate) walks from the most
specific container (a segment) out to the most general (the block generator),
with diagnostics + the run log at the foot. Zero-framework, CSP-safe."""

NOW_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ai-radio &middot; now</title>
<style>
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
.appbar{display:flex;align-items:baseline;justify-content:space-between;gap:var(--s3);flex-wrap:wrap;margin-bottom:var(--s2)}
.nav{display:flex;gap:var(--s1);flex-wrap:wrap;align-items:center;font-size:var(--fs-sm);margin-bottom:var(--s3)}
.nav a{color:var(--muted);padding:var(--s1) var(--s2);border-radius:var(--r-pill);min-height:var(--tap);display:inline-flex;align-items:center}
.nav a:hover{background:var(--surface-2);color:var(--text);text-decoration:none}
.nav a[aria-current="page"]{background:var(--primary-weak);color:var(--primary)}
section{margin:0 0 var(--s5)}
section>.hd2{display:flex;align-items:center;gap:var(--s2);border-bottom:1px solid var(--border);padding-bottom:var(--s2);margin-bottom:var(--s3)}
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--r-lg);padding:var(--s4);box-shadow:var(--sh-1)}
.hd2 .spacer{margin-left:auto}
/* --- sticky monitor: only what must never leave view (now-card + status +
   skip) pins; output + the air button scroll away so the workspace isn't crushed --- */
.topzone{position:sticky;top:0;z-index:10;background:var(--bg);padding:var(--s2) 0;box-shadow:0 1px 0 var(--border)}
.topzone>*{margin-bottom:var(--s2)}
.topzone>*:last-child{margin-bottom:0}
.outzone{margin:var(--s3) 0 var(--s4);padding-bottom:var(--s3);border-bottom:1px solid var(--border)}
.outzone>*{margin-bottom:var(--s2)}
.nowcard{position:relative;border:1px solid var(--border);border-radius:var(--r-lg);padding:var(--s4);background:var(--surface);box-shadow:var(--sh-1);overflow:hidden}
.nowcard.on{border-color:var(--success);background:var(--success-weak)}
.nowcard.on::before{content:"● ON AIR";position:absolute;top:var(--s3);right:var(--s3);font-size:var(--fs-xs);font-weight:var(--fw-bold);letter-spacing:.06em;color:var(--success)}
.nowcard.on::after{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--success);animation:pulse 2.2s ease-in-out infinite}
.nowcard.switching{border-color:var(--warn);background:var(--warn-weak)}
.nowcard.switching::before{content:"◐ SWITCHING";color:var(--warn)}
.nowcard.switching::after{background:var(--warn)}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}
@media (prefers-reduced-motion:reduce){.nowcard.on::after{animation:none}}
.nowcard .line1{display:flex;align-items:center;gap:var(--s2);flex-wrap:wrap;padding-right:5.5rem}
.nowcard .segt{font-weight:var(--fw-bold);font-size:var(--fs-lg);letter-spacing:-.01em}
.nowcard .meta{font-size:var(--fs-sm);color:var(--muted);margin-top:var(--s2)}
.nowcard .meta b{color:var(--text);font-weight:var(--fw-med)}
.nowcard .meta .blk{cursor:pointer;text-decoration:underline dotted}
.nowcard .prog{height:6px;border-radius:var(--r-pill);background:var(--surface-3);margin-top:var(--s3);overflow:hidden}
.nowcard .prog>i{display:block;height:100%;background:var(--success);width:0;transition:width .6s ease}
.now{font-size:var(--fs-md)}.now b{font-weight:var(--fw-med)}
button{font:inherit;font-size:var(--fs-sm);font-weight:var(--fw-med);min-height:var(--ctl-h);padding:0 var(--ctl-pad-x);border:1px solid transparent;border-radius:var(--r-pill);background:var(--primary);color:var(--primary-fg);cursor:pointer;display:inline-flex;align-items:center;justify-content:center;gap:var(--s1);transition:background .12s,border-color .12s,opacity .12s;white-space:nowrap}
button:hover{filter:brightness(1.06)}button:active{transform:translateY(1px)}
button.ghost{background:transparent;color:var(--primary);border-color:var(--border-strong)}
button.ghost:hover{background:var(--primary-weak);filter:none}
button.danger{background:transparent;color:var(--danger);border-color:var(--danger)}
button.danger:hover{background:var(--danger-weak);filter:none}
button:disabled{opacity:.4;cursor:not-allowed;filter:none;transform:none}
.mini{min-height:var(--ctl-h-sm);padding:0 var(--s3);font-size:var(--fs-sm)}
.icon-btn{min-width:var(--ctl-h-sm);padding:0 var(--s2);font-size:var(--fs-md)}
.playbig{width:100%}
select,input,textarea{width:100%;box-sizing:border-box;font:inherit;font-size:var(--fs-md);min-height:var(--ctl-h);padding:var(--s2) var(--s3);border:1px solid var(--border-strong);border-radius:var(--r-md);background:var(--surface-2);color:var(--text)}
select{appearance:none;background-image:linear-gradient(45deg,transparent 50%,var(--muted) 50%),linear-gradient(135deg,var(--muted) 50%,transparent 50%);background-position:calc(100% - 18px) 50%,calc(100% - 13px) 50%;background-size:5px 5px,5px 5px;background-repeat:no-repeat;padding-right:2rem}
input::placeholder,textarea::placeholder{color:var(--faint)}
input:focus,select:focus,textarea:focus{border-color:var(--primary);outline:none}
label{display:block;font-size:var(--fs-xs);color:var(--muted);margin:0 0 var(--s1)}
audio{width:100%;margin:var(--s2) 0;border-radius:var(--r-md)}
.row{display:flex;gap:var(--s2);flex-wrap:wrap;align-items:center}
.transport .segpos{flex:1;text-align:center;margin:0}
.output{flex-wrap:nowrap}
#target{flex:1;min-width:6rem}
.status{display:flex;gap:var(--s4);flex-wrap:wrap;align-items:center;font-size:var(--fs-sm);color:var(--muted)}
.notif{color:var(--warn)}
.dot{display:inline-block;width:.6rem;height:.6rem;border-radius:50%;background:var(--faint);margin-right:var(--s1);vertical-align:middle}
.dot.ok,.dot.live{background:var(--success)}.dot.bad{background:var(--danger)}.dot.live{box-shadow:0 0 0 3px var(--success-weak)}
.castdetails{background:var(--surface-2);border:1px solid var(--border);border-radius:var(--r-md);padding:var(--s3);font-size:var(--fs-sm);color:var(--muted)}
.castdetails b{color:var(--text)}
.badge{display:inline-flex;align-items:center;gap:.3em;font-size:var(--fs-xs);font-weight:var(--fw-med);line-height:1;padding:.32rem .55rem;border-radius:var(--r-pill);background:var(--surface-3);color:var(--muted)}
.badge.role{background:var(--primary-weak);color:var(--primary)}
.badge--live{background:var(--live-weak);color:var(--live)}
.badge--music{background:var(--music-weak);color:var(--music)}
.badge--tts{background:var(--tts-weak);color:var(--tts)}
.badge--airing{background:var(--success-weak);color:var(--success)}
.t-live{--seg-accent:var(--live)}.t-music{--seg-accent:var(--music)}.t-tts{--seg-accent:var(--tts)}
/* --- tabs: most-specific (segment) -> most-general (generator) --- */
.tabs{display:flex;gap:3px;background:var(--surface-2);border:1px solid var(--border);border-radius:var(--r-md);padding:3px;margin-bottom:var(--s3);overflow-x:auto;-webkit-overflow-scrolling:touch}
.tab{background:transparent;color:var(--muted);border:none;border-radius:var(--r-sm);min-height:var(--tap);padding:0 var(--s3);white-space:nowrap;flex:1}
.tab:hover{color:var(--text);filter:none}
.tab[aria-selected="true"]{background:var(--surface);color:var(--text);box-shadow:var(--sh-1)}
.tabpanel{display:none}.tabpanel.on{display:block}
.blocklist{display:flex;flex-direction:column;gap:var(--s2);margin-bottom:var(--s3)}
.bcard{border:1px solid var(--border);border-left:3px solid var(--border);border-radius:var(--r-md);padding:var(--s3);cursor:pointer;background:var(--surface);min-height:var(--tap);transition:border-color .12s,background .12s}
.bcard:hover{border-color:var(--border-strong)}
.bcard.sel{border-color:var(--primary);border-left-color:var(--primary);background:var(--primary-weak)}
.bcard.airing{border-left-color:var(--success)}
.bcard .bt{font-weight:var(--fw-med);display:flex;gap:var(--s2);align-items:center;flex-wrap:wrap}
.bcard .bs{font-size:var(--fs-sm);color:var(--muted);margin-top:var(--s1);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bactions{display:flex;gap:var(--s2);margin-top:var(--s2)}
.edithead{display:flex;gap:var(--s2);flex-wrap:wrap;align-items:center;margin:var(--s1) 0 var(--s3)}
.edithead input.title{flex:1;min-width:9rem;font-weight:var(--fw-med)}
.addbar{display:flex;gap:var(--s2);flex-wrap:wrap;align-items:center;margin-top:var(--s3);padding-top:var(--s3);border-top:1px dashed var(--border)}
.addbar .sub{margin:0}
.seg{border:1px solid var(--border);border-left:3px solid var(--seg-accent,var(--border));border-radius:var(--r-md);padding:var(--s3);margin-bottom:var(--s2);background:var(--surface)}
.seg.airing{border-color:var(--success);background:var(--success-weak)}
.seg--new{animation:flashnew 1.4s ease}
@keyframes flashnew{0%{box-shadow:0 0 0 2px var(--primary)}100%{box-shadow:none}}
.seg .hd{display:flex;align-items:center;gap:var(--s2);flex-wrap:wrap}
.seg .name{font-weight:var(--fw-med);overflow:hidden;text-overflow:ellipsis;min-width:0}
.seg .name[data-sel]{cursor:pointer;text-decoration:underline dotted}
.seg .detail{font-size:var(--fs-sm);color:var(--muted);margin-top:var(--s2)}
.seg .quote{border-left:3px solid var(--border-strong);padding-left:var(--s3);margin:var(--s2) 0;font-style:italic;color:var(--muted)}
.tracks{font-size:var(--fs-sm);color:var(--muted);margin-top:var(--s2)}
.detail.err{color:var(--danger)}
.seg .fields{display:flex;gap:var(--s2);flex-wrap:wrap;margin-top:var(--s3)}
.seg .fields label{font-size:var(--fs-xs);color:var(--muted);display:flex;flex-direction:column;gap:var(--s1);flex:1 1 8rem}
.seg .fields input,.seg .fields select{min-height:var(--ctl-h-sm);padding:var(--s2);font-size:var(--fs-sm)}
/* the live "▶ air" cutover is set apart (own group + divider) from the edit
   cluster so a broadcast-affecting tap isn't next to the destructive ✕ */
.seg .segctl{margin-left:auto;display:flex;gap:var(--s2);flex-shrink:0;align-items:center;flex-wrap:wrap;justify-content:flex-end}
.seg .segctl .editcluster{display:flex;gap:var(--s1);padding-left:var(--s2);border-left:1px solid var(--border)}
.seg .segctl button{min-height:40px;min-width:40px;padding:0 var(--s2);font-size:var(--fs-sm)}
.seg .segctl .cut{min-width:auto;padding:0 var(--s3);border-color:var(--primary);color:var(--primary)}
.diag{display:grid;grid-template-columns:auto 1fr;gap:var(--s1) var(--s3);font-size:var(--fs-sm);color:var(--muted)}
.diag b{color:var(--text);font-weight:var(--fw-med)}
.runlog{font:var(--fs-xs)/1.6 var(--mono);background:#0a0e14;color:#c9d4e0;border:1px solid var(--border);border-radius:var(--r-md);padding:var(--s3);max-height:15rem;overflow:auto;-webkit-overflow-scrolling:touch;scrollbar-width:thin;scrollbar-color:var(--border-strong) transparent}
.runlog .lt{color:var(--faint);margin-right:var(--s2)}
.runlog .k{color:var(--primary)}.runlog .w{color:var(--warn)}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:var(--surface-2);padding:var(--s3);border-radius:var(--r-sm);font:var(--fs-xs)/1.5 var(--mono);max-height:16rem;overflow:auto}
</style></head><body>
<div class="appbar"><h1>WRIT-FM &middot; now</h1></div>
<div class="nav"><a href="/admin">station</a><a href="/blocks">blocks</a><a href="/day">24-hour day</a><a href="/now" aria-current="page">now</a></div>

<div class="topzone">
  <div class="now" id="now">loading…</div>
  <div class="status" id="statusbar">
    <span><span id="sdot" class="dot"></span>Stream <span id="sstate">?</span> <span id="listeners"></span></span>
    <span id="stitle"></span>
    <span id="behind" class="sub" title="the monitor shows what's fed to the mount now; a listener hears it this much later (Icecast buffer + your player's buffer)"></span>
  </div>
  <div class="row transport">
    <button class="ghost icon-btn" id="btnPrev" type="button" title="skip to previous segment" disabled>◀</button>
    <span class="sub segpos" id="navMsg"></span>
    <button class="ghost icon-btn" id="btnNext" type="button" title="skip to next segment" disabled>▶</button>
  </div>
</div>
<div class="outzone">
  <div class="row output">
    <select id="target"></select>
    <button id="btnOut" type="button">Play here</button>
    <button class="ghost icon-btn" id="btnOutStop" type="button" title="stop output">■</button>
    <button class="ghost icon-btn" id="btnRescan" type="button" title="rescan speakers">⟳</button>
  </div>
  <audio id="player" src="/stream" controls preload="none"></audio>
  <div class="castdetails" id="castDetails" hidden></div>
  <div class="sub" id="outMsg">scanning for speakers…</div>
  <button class="playbig" id="btnAirActive" type="button" disabled>▶ Play active block from the top</button>
  <div class="sub" id="airReady"></div>
  <div class="sub notif" id="switchMsg"></div>
</div>

<div class="tabs" role="tablist" aria-label="workspace">
  <button class="tab" role="tab" id="tab-editor" aria-controls="panel-editor" data-tab="editor" aria-selected="true">Editor</button>
  <button class="tab" role="tab" id="tab-details" aria-controls="panel-details" data-tab="details" aria-selected="false">Details</button>
  <button class="tab" role="tab" id="tab-list" aria-controls="panel-list" data-tab="list" aria-selected="false">Blocks</button>
  <button class="tab" role="tab" id="tab-gen" aria-controls="panel-gen" data-tab="gen" aria-selected="false">Generate</button>
</div>

<div class="tabpanel on" id="panel-editor" role="tabpanel" aria-labelledby="tab-editor" tabindex="0">
  <div class="sub mb4">The active block. Tap a segment name for its details; ▶ on a segment cuts the station over there.</div>
  <div id="editHead"></div>
  <div id="blockView"></div>
  <div class="addbar" id="addBar"></div>
</div>

<div class="tabpanel" id="panel-details" role="tabpanel" aria-labelledby="tab-details" tabindex="0">
  <div id="detailView"><span class="sub">Select a segment in the Editor to see its details.</span></div>
</div>

<div class="tabpanel" id="panel-list" role="tabpanel" aria-labelledby="tab-list" tabindex="0">
  <div class="sub mb4">Your block library. <b>Set active</b> loads a block into the Editor; delete removes it.</div>
  <div class="row mb4"><button class="mini" id="btnNewBlock" type="button">+ New empty block</button></div>
  <div id="blockList" class="blocklist"></div>
</div>

<div class="tabpanel" id="panel-gen" role="tabpanel" aria-labelledby="tab-gen" tabindex="0">
  <div class="sub mb4">Auto-generate a starting block from a preset — it becomes the active block in the Editor.</div>
  <div class="row">
    <select id="preset"></select>
    <input id="genre1" placeholder="genre 1 (e.g. jazz)">
    <input id="genre2" placeholder="genre 2">
    <button id="btnBuild" type="button">Create</button>
  </div>
  <div class="sub" id="buildMsg"></div>
</div>

<section>
  <div class="hd2"><h2>Diagnostics</h2></div>
  <div class="diag" id="diag"></div>
</section>

<section>
  <div class="hd2"><h2>Run log</h2></div>
  <div id="runlog" class="runlog">loading…</div>
</section>

<script>
const $=id=>document.getElementById(id);
const BASE=location.pathname.replace(/\\/+$/,'');
let picked="", airingId="", airingIdx=-1, airingCount=0, airingStartedMs=0;
// Output is one-at-a-time: "" none, "local" this device's <audio>, or a cast
// device uuid. castUuid tracks the speaker we told to play (to stop it).
let outputTarget="", castUuid="", castName="";
// A cutover (▶ / skip / air) renders for a few seconds before the new segment
// airs; track it so the now-card shows an explicit "switching" state.
let switching=null; // {id, idx, since}
let lastNow=null;

function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}

function tickerFor(el,timeoutMs){
  const t0=Date.now();let label='';
  const paint=()=>{el.textContent=label+' ('+Math.round((Date.now()-t0)/1000)+'s)';};
  const id=setInterval(paint,1000);
  const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),timeoutMs);
  return {signal:controller.signal,set(l){label=l;paint();},
    done(t){clearInterval(id);clearTimeout(timer);el.textContent=t;},
    fail(e){clearInterval(id);clearTimeout(timer);const s=Math.round((Date.now()-t0)/1000);
      el.textContent=e.name==='AbortError'?('timed out after '+s+'s'):('error: '+(e.message||e)+' (after '+s+'s)');}};
}

function statusDot(st){return st==='ok'?'ok':(st==='error'?'bad':'');}

// segment-type visual language: glyph + accent chip, always paired with text.
const TYPE_GLYPH={live:'📡',music:'♫',tts:'🎙'};
function typeBadge(t){return `<span class="badge badge--${esc(t)}">${TYPE_GLYPH[t]||''} ${esc(t)}</span>`;}

let curBlock=null, selectedSeg=-1, voiceOpts=[], sourceOpts=[];  // active block + selection + lists
const TTS_TOPICS=['weather','recap','factoid','freeform','time_check','station_id'];

// --- tabs ---
function showTab(name){
  document.querySelectorAll('.tab').forEach(t=>t.setAttribute('aria-selected', t.dataset.tab===name?'true':'false'));
  document.querySelectorAll('.tabpanel').forEach(p=>p.classList.toggle('on', p.id==='panel-'+name));
  if(name==='list') loadList();
  if(name==='details') renderDetails();
}

// <select> from [{value,label}] items with the given current value selected.
function optSel(dataf, i, current, items){
  const o=items.map(it=>`<option value="${esc(it.value)}"${it.value===current?' selected':''}>${esc(it.label)}</option>`).join('');
  return `<select data-f="${dataf}" data-i="${i}">${o}</select>`;
}

function segFields(seg, i){
  const p=seg.params||{}, mins=v=>Math.round((v||0)/60);
  if(seg.type==='tts'){
    const topic=p.topic||'freeform';
    const voiceItems=[{value:'',label:'(default)'}].concat(voiceOpts.map(v=>({value:v,label:v})));
    let f=`<label>topic${optSel('topic', i, topic, TTS_TOPICS.map(t=>({value:t,label:t})))}</label>`
      +`<label>🗣 voice${optSel('voice', i, p.voice||'', voiceItems)}</label>`;
    if(topic==='weather') f+=`<label>location<input data-f="location" data-i="${i}" value="${esc(p.location||'')}" placeholder="zip / city"></label>`;
    if(topic==='freeform') f+=`<label>prompt<input data-f="prompt" data-i="${i}" value="${esc(p.prompt||'')}"></label>`;
    if(topic==='station_id') f+=`<label>tagline<input data-f="tagline" data-i="${i}" value="${esc(p.tagline||'')}" placeholder="optional"></label>`;
    return f;
  }
  if(seg.type==='music'){
    return `<label>genre / search<input data-f="query" data-i="${i}" value="${esc(p.query||'')}" placeholder="shuffle all"></label>`
      +`<label>minutes<input data-f="duration_s" data-i="${i}" type="number" min="1" value="${mins(p.duration_s)}"></label>`;
  }
  if(seg.type==='live'){
    const srcItems=[{value:'auto',label:'Auto — rotating bulletin'}].concat(sourceOpts.map(s=>({value:s.id,label:s.name})));
    return `<label>📡 source${optSel('source_id', i, p.source_id||'auto', srcItems)}</label>`
      +`<label>minutes<input data-f="duration_s" data-i="${i}" type="number" min="1" value="${mins(p.duration_s)}"></label>`;
  }
  return '';
}

function segEntity(seg, airing, idx){
  const r=seg.resolved||{}, p=seg.params||{};
  const title = r.title || p.topic || p.query || p.source_id || seg.type;
  let detail='';
  if(r.text) detail=`<div class="quote">${esc(r.text)}</div>`;
  else if(seg.type==='music' && r.tracks_head && r.tracks_head.length)
    detail=`<div class="tracks">${r.tracks_head.slice(0,6).map(esc).join(' &middot; ')}${r.tracks_head.length>6?' …':''}</div>`;
  return `<div class="seg t-${esc(seg.type)}${airing?' airing':''}">
      <div class="hd">
        <span class="dot ${statusDot(seg.status)}" role="img" aria-label="status: ${esc(seg.status||'unresolved')}" title="${esc(seg.status||'unresolved')}"></span>
        ${typeBadge(seg.type)}
        <span class="name" data-sel="${idx}" title="details">${esc(title)}</span>
        ${airing?'<span class="badge badge--airing">▶ airing</span>':''}
        <span class="segctl">
          <button class="ghost mini cut" data-play="${idx}" title="cut the station over to this segment">▶ air</button>
          <span class="editcluster">
            <button class="ghost mini" data-mv="-1" data-i="${idx}" title="move up">↑</button>
            <button class="ghost mini" data-mv="1" data-i="${idx}" title="move down">↓</button>
            <button class="danger mini" data-del="${idx}" title="remove segment">✕</button>
          </span>
        </span>
      </div>
      <div class="fields">${segFields(seg, idx)}</div>
      <div class="detail">${detail}</div>
      ${seg.error?`<div class="detail err">error: ${esc(seg.error)}</div>`:''}
    </div>`;
}

// --- Blocks library (Blocks tab) ---
async function loadList(){
  const list=await (await fetch(BASE+'/api/blocks')).json();
  $('blockList').innerHTML = list.length ? list.map(b=>{
    const st=b.schedule?b.schedule.state:'';
    const cls='bcard'+(b.id===picked?' sel':'')+(b.id===airingId?' airing':'');
    const tag=b.id===airingId?'<span class="badge badge--airing">airing</span>':`<span class="badge">${esc(st)}</span>`;
    return `<div class="${cls}" data-bid="${esc(b.id)}">
      <div class="bt">${esc(b.title)} <span class="badge">${b.segment_count} seg</span> ${tag}</div>
      <div class="bs">${esc(b.summary||'')}</div>
      <div class="bactions">
        <button class="ghost mini" data-set="${esc(b.id)}" type="button">Set active</button>
        <button class="danger mini" data-delb="${esc(b.id)}" type="button">Delete</button>
      </div></div>`;
  }).join('') : '<span class="sub">no blocks yet — make one in the Generate tab</span>';
  $('blockList').querySelectorAll('[data-set]').forEach(el=>{ el.onclick=e=>{e.stopPropagation();setActive(el.dataset.set);}; });
  $('blockList').querySelectorAll('[data-delb]').forEach(el=>{ el.onclick=e=>{e.stopPropagation();delBlock(el.dataset.delb);}; });
  $('blockList').querySelectorAll('[data-bid]').forEach(el=>{ el.onclick=()=>setActive(el.dataset.bid); });
}

function setActive(id){ inspect(id); showTab('editor'); }

async function delBlock(id){
  if(!confirm('Delete this block?')) return;
  try{ await fetch(BASE+'/api/blocks/'+id,{method:'DELETE'}); }catch(e){}
  if(picked===id){ picked=""; curBlock=null; selectedSeg=-1; renderEditor(); renderDetails(); }
  loadList();
}

async function inspect(id){
  picked=id; selectedSeg=-1;
  try{ curBlock=await (await fetch(BASE+'/api/blocks/'+id)).json(); }
  catch(e){ $('blockView').textContent='load failed'; return; }
  loadList(); renderEditor(); renderDetails();
  preRender(id);  // warm missing/stale segments now so cutover is near-instant
}

// Pre-render the active block's missing/stale segments in the background when
// it's loaded, so "Play active block" doesn't pay the (music-resolution-heavy)
// air-time render. force:false = selective, so a warm block is a cheap no-op.
let preRenderId=null;
function setAirReady(state){
  $('airReady').textContent = state==='preparing' ? '⏳ preparing segments…'
    : state==='ready' ? '✓ ready to air'
    : state==='error' ? '⚠ some segments failed to build — check Details'
    : '';
}
async function preRender(id){
  if(!id){ setAirReady(''); return; }
  if(id===airingId){ preRenderId=id; setAirReady('ready'); return; }  // on-air block is already built
  preRenderId=id; setAirReady('preparing');
  try{
    const b=await (await fetch(BASE+'/api/blocks/'+id+'/render',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({force:false})})).json();
    if(preRenderId!==id) return;  // superseded by a newer active block
    setAirReady((b.segments||[]).some(s=>s.status==='error') ? 'error' : 'ready');
  }catch(e){ if(preRenderId===id) setAirReady(''); }
}

// --- Editor tab ---
function renderEditor(){
  $('btnAirActive').disabled = !curBlock;
  if(!curBlock){
    $('editHead').innerHTML=''; $('addBar').innerHTML='';
    $('blockView').innerHTML='<span class="sub">No active block. Pick one in Blocks, or make one in Generate.</span>';
    return;
  }
  const b=curBlock, airing=(b.id===airingId);
  $('editHead').className='edithead';
  $('editHead').innerHTML=`<input class="title" id="btitle" value="${esc(b.title)}">
    <button class="mini" id="btnSave" type="button">Save</button>
    <button class="ghost mini" id="btnSaveAs" type="button">Save as new</button>`;
  $('blockView').innerHTML = b.segments.length
    ? b.segments.map((s,i)=>segEntity(s, airing&&i===airingIdx, i)).join('')
    : '<span class="sub">Empty block — add an element below.</span>';
  $('addBar').innerHTML=`<span class="sub">Add element:</span>
    <button class="ghost mini" data-add="tts" type="button">+ tts</button>
    <button class="ghost mini" data-add="music" type="button">+ music</button>
    <button class="ghost mini" data-add="live" type="button">+ live</button>`;
  wireEditor();
}

// wire [data-f] param inputs within `root`; `rerender` repaints after a topic
// change (which swaps the visible fields).
function wireFields(root, rerender){
  root.querySelectorAll('[data-f]').forEach(el=>{
    el.onchange=()=>{
      const i=+el.dataset.i, f=el.dataset.f; let v=el.value;
      if(f==='duration_s') v=Math.max(1,parseInt(v||'1',10))*60;
      curBlock.segments[i].params[f]=v;
      if(f==='topic') rerender();
    };
  });
}

function wireEditor(){
  const bv=$('blockView');
  wireFields(bv, renderEditor);
  bv.querySelectorAll('[data-sel]').forEach(el=>{ el.onclick=()=>{ selectedSeg=+el.dataset.sel; renderDetails(); showTab('details'); }; });
  bv.querySelectorAll('[data-play]').forEach(el=>{ el.onclick=async()=>{
    el.disabled=true; const t=el.textContent; el.textContent='⋯';
    try{ await playFrom(curBlock.id, +el.dataset.play); } finally{ el.disabled=false; el.textContent=t; }
  }; });
  bv.querySelectorAll('[data-del]').forEach(el=>{ el.onclick=()=>{
    if(!confirm('Remove this segment?')) return;
    curBlock.segments.splice(+el.dataset.del,1);
    if(selectedSeg>=curBlock.segments.length) selectedSeg=-1;
    renderEditor(); }; });
  bv.querySelectorAll('[data-mv]').forEach(el=>{ el.onclick=()=>moveSeg(+el.dataset.i, +el.dataset.mv); });
  $('addBar').querySelectorAll('[data-add]').forEach(el=>{ el.onclick=()=>addSeg(el.dataset.add); });
  $('btitle').onchange=()=>{ curBlock.title=$('btitle').value; };
  $('btnSave').onclick=saveBlock;
  $('btnSaveAs').onclick=saveAsBlock;
}

function moveSeg(i,dir){
  const j=i+dir, s=curBlock.segments; if(j<0||j>=s.length) return;
  [s[i],s[j]]=[s[j],s[i]]; renderEditor();
}

let addCount=0;
function addSeg(type){
  const id=type+'_'+(++addCount)+'_'+Date.now().toString(36);
  const params=type==='tts'?{topic:'weather',location:'',voice:'',ttl_s:1800}
    :type==='music'?{query:'',duration_s:900}:{source_id:'auto',duration_s:300};
  curBlock.segments.push({id, role:id, type, params}); renderEditor();
  // Show the element land right where the add buttons are (bottom of the list).
  const segs=$('blockView').querySelectorAll('.seg'); const el=segs[segs.length-1];
  if(el){ el.classList.add('seg--new'); el.scrollIntoView({behavior:'smooth', block:'center'}); }
}

// --- Details tab (the selected segment) ---
function renderDetails(){
  const box=$('detailView');
  if(!curBlock || selectedSeg<0 || selectedSeg>=curBlock.segments.length){
    box.innerHTML='<span class="sub">Select a segment in the Editor to see its details.</span>'; return;
  }
  const i=selectedSeg, seg=curBlock.segments[i], r=seg.resolved||{}, p=seg.params||{};
  const title=r.title||p.topic||p.query||p.source_id||seg.type;
  const mins=Math.round((p.duration_s||r.duration_s||0)/60);
  let parts=[`<div class="seg t-${esc(seg.type)}">
    <div class="hd">
      <span class="dot ${statusDot(seg.status)}" role="img" aria-label="status: ${esc(seg.status||'unresolved')}" title="${esc(seg.status||'unresolved')}"></span>
      ${typeBadge(seg.type)}
      ${seg.role?('<span class="badge role">'+esc(seg.role)+'</span>'):''}
      <span class="name">${esc(title)}</span>
    </div>
    <div class="fields">${segFields(seg, i)}</div>`];
  if(seg.error) parts.push(`<div class="detail err">error: ${esc(seg.error)}</div>`);
  if(r.text) parts.push(`<div class="quote">${esc(r.text)}</div>`);
  if(seg.type==='music' && r.tracks_head && r.tracks_head.length)
    parts.push(`<div class="tracks">${r.tracks_head.map(esc).join(' &middot; ')}</div>`);
  if(seg.type==='live' && r.url)
    parts.push(`<div class="detail">source: <a href="${esc(r.url)}" target="_blank">${esc(r.source_name||r.url)} ↗</a></div>`);
  if(seg.status==='ok' && seg.type==='tts')
    parts.push(`<audio controls preload="none" src="${BASE}/api/blocks/${esc(curBlock.id)}/audio/${esc(seg.id)}"></audio>`);
  parts.push(`<div class="detail">${mins?('~'+mins+' min &middot; '):''}status: ${esc(seg.status||'unresolved')}${r.track_count?(' &middot; '+r.track_count+' tracks'):''}</div>`);
  parts.push(`</div>
    <div class="addbar"><button class="mini" id="btnDetSave" type="button">Save block</button>
      <span class="sub">edits here save the whole block</span></div>`);
  box.innerHTML=parts.join('');
  wireFields(box, renderDetails);
  $('btnDetSave').onclick=saveBlock;
}

// Strip resolved/status on save so edited segments re-resolve fresh at air.
function cleanSegs(){
  return curBlock.segments.map(s=>({id:s.id, role:s.role||s.id, type:s.type, params:s.params}));
}
async function saveBlock(){
  const tick=tickerFor($('switchMsg'),20000); tick.set('saving');
  try{
    const r=await fetch(BASE+'/api/blocks/'+curBlock.id,{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({title:curBlock.title, segments:cleanSegs()}),signal:tick.signal});
    if(!r.ok) throw new Error((await r.text())||('HTTP '+r.status));
    tick.done('saved'); await inspect(curBlock.id);
  }catch(e){ tick.fail(e); }
}
async function saveAsBlock(){
  const tick=tickerFor($('switchMsg'),20000); tick.set('saving as new');
  try{
    const b=await (await fetch(BASE+'/api/blocks/save_as',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({title:curBlock.title+' (copy)', segments:cleanSegs()}),signal:tick.signal})).json();
    if(b.error) throw new Error(b.error);
    tick.done('created '+b.title); inspect(b.id);
  }catch(e){ tick.fail(e); }
}

$('btnNewBlock').onclick=async()=>{
  try{
    const b=await (await fetch(BASE+'/api/blocks',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({title:'New block'})})).json();
    if(b.id) setActive(b.id);
  }catch(e){}
};

// --- Generate tab (presets) ---
async function loadBuild(){
  const presets=await (await fetch(BASE+'/api/presets')).json();
  $('preset').innerHTML=presets.map(p=>`<option value="${esc(p.id)}">${esc(p.label)}</option>`).join('');
  try{
    const engines=await (await fetch(BASE+'/api/tts_engines')).json();
    const k=(engines||[]).find(e=>e.id==='kokoro');
    voiceOpts=(k&&k.voices)||[];
  }catch(e){}
  try{ sourceOpts=await (await fetch(BASE+'/api/live_sources')).json(); }catch(e){}
}
$('btnBuild').onclick=async()=>{
  const tick=tickerFor($('buildMsg'),25000); tick.set('creating block');
  try{
    const opts={genre_1:$('genre1').value, genre_2:$('genre2').value};
    const b=await (await fetch(BASE+'/api/blocks/preset',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({preset:$('preset').value, opts}),signal:tick.signal})).json();
    if(b.error) throw new Error(b.error);
    tick.done('created '+b.title); inspect(b.id); showTab('editor');
  }catch(e){ tick.fail(e); }
};

// Cut the station over to block `id` starting at segment `idx` (restart/scrub).
// The player keeps the Icecast source fed with a spoken filler across the
// air-time render, so a cast stays connected through the switch.
async function playFrom(id, idx){
  switching={id, idx, since:Date.now()};
  paintSwitching();
  const tick=tickerFor($('switchMsg'),20000);
  tick.set('cutting over to segment '+(idx+1));
  try{
    const r=await fetch(BASE+'/api/blocks/'+id+'/schedule',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({mode:'now',prerender:false,start_index:idx}),signal:tick.signal});
    if(!r.ok) throw new Error((await r.text())||('HTTP '+r.status));
    tick.done('switched — starts at segment '+(idx+1)+' after render');
  }catch(e){ switching=null; tick.fail(e); return; }
  // Only the LOCAL player reconnects to the freshly-switched stream; a cast
  // rides through the render on the filler.
  if(outputTarget==='local'){
    const a=$('player');
    setTimeout(()=>{ a.src='/stream?ts='+Date.now(); a.load(); a.play().catch(()=>{}); }, 5000);
  }
}
// Air the active block (the one loaded in the Editor) from the top.
$('btnAirActive').onclick=async()=>{
  if(!curBlock) return;
  const btn=$('btnAirActive'); btn.disabled=true; const t=btn.textContent; btn.textContent='⋯';
  try{ await playFrom(curBlock.id, 0); } finally{ btn.disabled=false; btn.textContent=t; }
};

function fmtElapsed(ms){
  if(!ms) return '';
  const s=Math.max(0,Math.round((Date.now()-ms)/1000));
  return (s>=60?(Math.floor(s/60)+'m '+(s%60)+'s'):(s+'s'));
}
// Repaint just the elapsed counter every second (poll is only every 4s).
function tickElapsed(){
  if(!airingStartedMs){ return; }
  const el=$('elapsed'); if(el) el.textContent=fmtElapsed(airingStartedMs);
}

function paintSwitching(){
  if(!switching) return;
  const card=$('now');
  card.className='nowcard on switching';
  card.innerHTML='<div class="line1"><span class="badge">switching</span>'
    +'<span class="segt">&rarr; segment '+(switching.idx+1)+'</span></div>'
    +'<div class="meta">cutting over &amp; rendering — audio resumes in a few seconds…</div>';
  $('btnPrev').disabled=true; $('btnNext').disabled=true; $('navMsg').textContent='switching…';
}

function setNav(idx,n){
  $('btnPrev').disabled = !(idx>0);
  $('btnNext').disabled = !(n && idx<n-1);
  $('navMsg').textContent = n ? ('segment '+(idx+1)+' / '+n) : '';
}
// Phase-driven: player_state.phase is the ground truth of what's on air right
// now -- airing (a track/segment), rendering (cutover render, air fill audible),
// or idle (between-blocks music). st.on_air is always the single audible label.
function renderNow(nowd){
  const card=$('now'), st=nowd.state||{}, live=(nowd.stream||{}).live, phase=st.phase;
  // Optimistic client 'switching' only bridges click -> server's first render
  // state; the server owns the truth as soon as it reports rendering/airing.
  if(switching){
    const owned = nowd.player_active && (phase==='rendering' || st.block_id===switching.id);
    if(owned || (Date.now()-switching.since)>40000) switching=null;
    else { paintSwitching(); setNav(-1,0); return; }
  }
  if(!nowd.player_active){
    card.className='nowcard';
    card.innerHTML='<span class="sub">'+esc(live?'Static fallback loop — no programmed block is airing.':'Stream offline — no source is connected.')+'</span>';
    setNav(-1,0); return;
  }
  if(phase==='rendering'){
    card.className='nowcard on switching';
    card.innerHTML=`<div class="line1"><span class="badge">preparing</span>
        <span class="segt">${esc(st.on_air||'Air fill')}</span></div>
      <div class="meta">rendering <b>${esc(st.title||st.block_id||'next block')}</b> &middot; <span id="elapsed">${fmtElapsed(airingStartedMs)}</span></div>`;
    setNav(-1,0); return;
  }
  if(phase==='idle' || st.idle || !st.block_id){
    card.className='nowcard';
    const named=st.track_count, ctx=named?(esc(st.mix||'Idle mix')+' &middot; track '+((st.track_index??0)+1)+' of '+st.track_count):'between blocks — queue a block or press ▶ on a segment';
    card.innerHTML=`<div class="line1"><span class="badge">idle</span> <span class="segt">${esc(st.on_air||'Idle music mix')}</span></div>
      <div class="meta">${ctx} &middot; <span id="elapsed">${fmtElapsed(airingStartedMs)}</span></div>`;
    setNav(-1,0); return;
  }
  // airing a segment
  const idx=st.segment_index??0, n=st.segment_count||0, isMusic=st.segment_type==='music';
  const onair = st.on_air || st.track_title || st.segment_title || st.segment_id || '';
  const trackline=(isMusic && st.track_count)?(' &middot; track '+((st.track_index??0)+1)+' of '+st.track_count):'';
  card.className='nowcard on';
  card.innerHTML=`<div class="line1">
      ${st.segment_role?('<span class="badge role">'+esc(st.segment_role)+'</span>'):''}
      ${st.segment_type?typeBadge(st.segment_type):''}
      <span class="segt">${esc(onair)}</span>
    </div>
    <div class="meta"><b class="blk" data-airblock="${esc(st.block_id)}">${esc(st.title||st.block_id)}</b> &middot; segment ${idx+1} of ${n}${trackline} &middot; <span id="elapsed">${fmtElapsed(airingStartedMs)}</span></div>
    <div class="prog"><i style="width:${n?Math.round((idx+1)/n*100):0}%"></i></div>`;
  const blk=card.querySelector('[data-airblock]');
  if(blk) blk.onclick=()=>{ inspect(st.block_id); showTab('editor'); };
  setNav(idx,n);
}

// Reconcile UI output state with the server's authoritative cast target.
function reconcileOutput(cast){
  const sel=$('target');
  if(cast && cast.uuid){
    castUuid=cast.uuid; castName=cast.name||cast.uuid;
    if(outputTarget!==cast.uuid){
      outputTarget=cast.uuid;
      $('player').pause();
      if(sel && [...sel.options].some(o=>o.value===cast.uuid)){ sel.value=cast.uuid; updateOutLabel(); }
      $('outMsg').textContent='';  // the cast-details panel already names the speaker
    }
  } else {
    castUuid='';
    if(outputTarget && outputTarget!=='local'){
      outputTarget=''; castName='';
      $('outMsg').textContent='not playing — choose an output';
    }
  }
}

// Only show the local <audio> when actually playing here -- during a cast it
// only controls local playback and misleads. Show cast details instead.
function updateOutputMode(n){
  const local = outputTarget==='local';
  const casting = outputTarget && !local;
  // Only show the local <audio> when we are actually listening HERE. When
  // casting -- or when no local playback is active -- hide it; its transport
  // only ever controlled local playback and is misleading otherwise.
  $('player').hidden = !local;
  $('outMsg').hidden = casting;  // cast-details already carries the cast state
  const cd=$('castDetails'); cd.hidden=!casting;
  if(casting){
    const s=n.stream||{};
    cd.innerHTML=`<b>Casting to ${esc(castName||'speaker')}</b><br>`
      +`Stream ${s.live?'live':'offline'} &middot; ${s.listeners||0} listening`
      +(s.title?` &middot; “${esc(s.title)}”`:'');
  }
}

function renderDiag(n){
  const st=n.state||{}, s=n.stream||{};
  const airing = n.player_active&&st.block_id
    ? esc(st.title||st.block_id)+' &middot; seg '+((st.segment_index??0)+1)+'/'+(st.segment_count||0)
    : '—';
  const out = outputTarget==='local'?'this device':(outputTarget?('cast: '+esc(castName)):'none');
  const rows=[
    ['Player', n.player_active?'running':'stopped'],
    ['Airing', airing],
    ['Queue', (n.queue&&n.queue.length)?(n.queue.length+' block(s)'):'empty'],
    ['Stream', (s.live?'live':'offline')+' &middot; '+(s.listeners||0)+' listening'],
    ['Output', out],
  ];
  $('diag').innerHTML=rows.map(r=>`<div>${r[0]}</div><div><b>${r[1]}</b></div>`).join('');
}

// How far a listener trails the monitor. The Icecast burst (server, s.buffer_s)
// is a floor; a listener's own player adds a jitter buffer. When we ARE playing
// locally we can read that client buffer straight off the <audio> element
// (received-but-not-yet-played = buffered.end - currentTime) for a real total;
// otherwise we can only show the server floor.
function behindLiveLabel(s){
  let secs = s.buffer_s || 0;
  const a=$('player');
  if(a && !a.hidden && !a.paused && a.buffered && a.buffered.length){
    const client = a.buffered.end(a.buffered.length-1) - a.currentTime;
    if(client > 0) secs += client;
  }
  return '≈'+Math.round(secs)+'s behind live';
}

function applyNow(n){
  reconcileOutput(n.cast);
  updateOutputMode(n);
  const s=n.stream||{};
  $('sstate').textContent=s.live?'live':'offline';
  $('sdot').className='dot '+(s.live?'live':'bad');
  $('listeners').textContent=s.live?('· '+(s.listeners||0)+' listening'):'';
  $('stitle').textContent=s.title?('“'+s.title+'”'):'';
  $('behind').textContent=s.live?('· '+behindLiveLabel(s)):'';
  const st=n.state||{};
  const prevA=airingId;
  airingId=n.player_active?(st.block_id||''):'';
  airingIdx=n.player_active&&st.segment_index!=null?st.segment_index:-1;
  airingCount=st.segment_count||0;
  // started_at marks the CURRENT on-air thing (track / segment / render / idle)
  // -> elapsed = how long that exact thing has been audible.
  airingStartedMs = (n.player_active && st.started_at) ? Date.parse(st.started_at) : 0;
  renderNow(n);
  renderDiag(n);
  lastNow=n;
  // refresh the block-list highlight when the airing block changes (never
  // reload the editor -- that would clobber in-progress edits).
  if(airingId!==prevA) loadList();
}
async function poll(){
  try{ applyNow(await (await fetch(BASE+'/api/now')).json()); }catch(e){}
}
// Live push via Server-Sent Events: the panel streams the now-payload on every
// player transition (render-start / segment / each track / idle) plus a 4s
// ambient refresh -- so /now updates within ~1s, no polling. EventSource
// auto-reconnects on drop; fall back to polling only if SSE is unavailable.
function startNowStream(){
  if(!window.EventSource){ setInterval(poll, 3000); return; }
  const es=new EventSource(BASE+'/api/now/stream');
  es.onmessage=e=>{ try{ applyNow(JSON.parse(e.data)); }catch(_){} };
}

$('btnPrev').onclick=()=>{ if(airingId && airingIdx>0) playFrom(airingId, airingIdx-1); };
$('btnNext').onclick=()=>{ if(airingId && airingCount && airingIdx<airingCount-1) playFrom(airingId, airingIdx+1); };

// --- Run log (recent player events) ---
function logClass(m){
  if(/-> (PLAYING|BUFFERING)/.test(m)) return 'k';
  if(/PAUSED|IDLE|failed|error|could not|not allowed/i.test(m)) return 'w';
  if(/cutover|render gap|idle|drain|exiting|sink/.test(m)) return 'w';
  if(/airing block|segment |^start |^stop /.test(m)) return 'k';
  return '';
}
async function loadLog(){
  try{
    const rows=await (await fetch(BASE+'/api/log')).json();
    const el=$('runlog');
    el.innerHTML = rows.length
      ? rows.map(r=>`<div class="${logClass(r.m)}"><span class="lt">${esc(r.t)}</span>${esc(r.m)}</div>`).join('')
      : '<span class="sub">no recent events</span>';
    el.scrollTop=el.scrollHeight;
  }catch(e){}
}

// --- Output (local OR one cast speaker, mutually exclusive) ---
async function loadTargets(force){
  const tick=tickerFor($('outMsg'),20000);
  tick.set(force?'rescanning for speakers':'loading speakers');
  try{
    const url=BASE+'/api/cast/devices'+(force?'?refresh=1':'');
    const list=await (await fetch(url,{signal:tick.signal})).json();
    if(list.error) throw new Error(list.error);
    const sel=$('target'); const prev=sel.value; sel.innerHTML='';
    const o0=document.createElement('option'); o0.value='local'; o0.textContent='This device (play here)';
    sel.appendChild(o0);
    list.forEach(d=>{
      const o=document.createElement('option'); o.value=d.uuid;
      o.textContent=d.name+' ('+(d.type==='group'?'group':d.type)+')'; sel.appendChild(o);
    });
    const casting = outputTarget && outputTarget!=='local';
    sel.value = casting ? outputTarget : (prev || 'local');
    updateOutLabel();
    if(casting) tick.done('casting to '+castName);
    else tick.done(list.length+' speakers + this device');
  }catch(e){ tick.fail(e); }
}

async function stopCast(uuid){
  if(!uuid) return;
  try{ await fetch(BASE+'/api/cast/stop',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({uuid})}); }catch(e){}
}

// Switch output to `v` ("local" or a cast uuid), stopping whatever was playing.
async function applyTarget(v){
  const a=$('player'), btn=$('btnOut'), sel=$('target');
  btn.disabled=true; sel.disabled=true;
  const restore=()=>{ btn.disabled=false; sel.disabled=false; updateOutLabel(); };
  if(v==='local'){
    btn.textContent='Starting…';
    if(castUuid){ stopCast(castUuid); castUuid=''; }
    outputTarget='local';
    $('player').hidden=false; $('castDetails').hidden=true;
    a.src='/stream?ts='+Date.now(); a.load(); a.play().catch(()=>{});
    $('outMsg').textContent='playing on this device';
    restore(); return;
  }
  btn.textContent='Connecting…';
  a.pause(); a.hidden=true; outputTarget='';  // leaving local -> remove local controls now
  if(castUuid && castUuid!==v){ stopCast(castUuid); }
  const tick=tickerFor($('outMsg'),90000); tick.set('connecting to speaker');
  try{
    const r=await (await fetch(BASE+'/api/cast/start',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({uuid:v}),signal:tick.signal})).json();
    if(r.error) throw new Error(r.error);
    if(r.state==='PLAYING'||r.state==='BUFFERING'){ outputTarget=v; castUuid=v;
      tick.done('casting to '+esc(r.name)+' ('+r.state.toLowerCase()+')'); }
    else { tick.done('could not cast'+(r.hint?': '+esc(r.hint):' (state '+esc(r.state||'?')+')')); }
  }catch(e){ tick.fail(e); }
  finally{ restore(); }
}

// The primary output button applies the SELECTED target, so its label must
// name it -- "Play here" for local, "Play on <speaker>" for a cast device.
function updateOutLabel(){
  const sel=$('target'); if(!sel||!sel.options.length) return;
  const v=sel.value, o=sel.selectedOptions[0];
  $('btnOut').textContent = (!v||v==='local') ? 'Play here'
    : ('Play on '+(o?o.textContent.replace(/\\s*\\(.*\\)\\s*$/,''):'speaker'));
}
$('target').onchange=updateOutLabel;
$('btnOut').onclick=()=>applyTarget($('target').value);
$('btnOutStop').onclick=async()=>{
  const a=$('player'); a.pause();
  if(castUuid){ const tick=tickerFor($('outMsg'),30000); tick.set('stopping'); await stopCast(castUuid); castUuid=''; tick.done('stopped'); }
  else { $('outMsg').textContent='stopped'; }
  outputTarget='';
};
$('btnRescan').onclick=()=>loadTargets(true);
// The native <audio> play control is also an output surface: starting local
// playback must stop any cast so only one destination is ever live.
$('player').addEventListener('play',()=>{
  if(castUuid){ stopCast(castUuid); castUuid=''; $('outMsg').textContent='playing on this device'; }
  outputTarget='local'; $('target').value='local'; $('castDetails').hidden=true;
});

document.querySelectorAll('.tab').forEach(t=>{ t.onclick=()=>showTab(t.dataset.tab); });

(async function init(){
  await loadBuild();
  await poll();
  if(airingId){ await inspect(airingId); } else { renderEditor(); }
  showTab('editor');
  loadTargets();  // cached device list -> instant; Rescan forces a fresh scan
  loadLog();
  startNowStream();  // live SSE push (falls back to polling if unsupported)
  setInterval(tickElapsed, 1000);
  setInterval(loadLog, 5000);
  setInterval(loadList, 20000);
})();
</script>
</body></html>"""
