#!/usr/bin/env python3
"""/browse -- the music browser. Explore the library through the feature overlay:
search or surprise a seed track, walk a target point through feature space with
per-axis nudges/sliders, filter by era/mood/theme + studio/live, preview, and
collect picks into a crate to build a block and put it on air. Zero-framework,
CSP-safe; same design tokens as /now."""

BROWSE_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ai-radio &middot; browse</title>
<style>
:root{
  color-scheme:light dark;
  --bg:#0d1117;--surface:#161b22;--surface-2:#1c2431;--surface-3:#232d3b;
  --border:#2a3644;--border-strong:#3a4757;
  --text:#e6edf3;--muted:#93a1b0;--faint:#7f8c9b;
  --primary:#4c8dfb;--primary-fg:#0b1220;--primary-weak:#4c8dfb26;
  --success:#2fbf6b;--success-weak:#2fbf6b1f;--warn:#f0a935;--warn-weak:#f0a9351f;
  --danger:#f26d6d;--danger-weak:#f26d6d1f;
  --live:#2dd4bf;--live-weak:#2dd4bf24;--music:#a78bfa;--music-weak:#a78bfa24;
  --font:system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  --mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  --fs-xs:.72rem;--fs-sm:.82rem;--fs-md:.92rem;--fs-lg:1.1rem;--fs-xl:1.35rem;
  --lh:1.45;--fw-med:600;--fw-bold:700;--track-caps:.04em;
  --s1:.25rem;--s2:.5rem;--s3:.75rem;--s4:1rem;--s5:1.5rem;--s6:2rem;--s7:3rem;
  --r-sm:8px;--r-md:12px;--r-lg:16px;--r-pill:999px;
  --tap:44px;--ctl-h:44px;--ctl-h-sm:40px;--ctl-pad-x:.85rem;
  --sh-1:0 1px 2px rgba(0,0,0,.35);--focus:0 0 0 2px var(--bg),0 0 0 4px var(--primary);--maxw:760px;
}
@media (prefers-color-scheme:light){:root:not([data-theme="dark"]){
  --bg:#f5f7fa;--surface:#fff;--surface-2:#eef2f7;--surface-3:#e4eaf1;
  --border:#d7dee7;--border-strong:#c2ccd8;--text:#141c26;--muted:#586573;--faint:#707b89;
  --primary:#2563eb;--primary-fg:#fff;--primary-weak:#2563eb14;
  --success:#15a34a;--success-weak:#15a34a17;--warn:#c2790a;--warn-weak:#c2790a17;
  --danger:#dc2626;--danger-weak:#dc262617;
  --live:#0d9488;--live-weak:#0d948817;--music:#7c3aed;--music-weak:#7c3aed17;
  --sh-1:0 1px 2px rgba(16,24,40,.08);
}}
:root[data-theme="light"]{
  --bg:#f5f7fa;--surface:#fff;--surface-2:#eef2f7;--surface-3:#e4eaf1;
  --border:#d7dee7;--border-strong:#c2ccd8;--text:#141c26;--muted:#586573;--faint:#707b89;
  --primary:#2563eb;--primary-fg:#fff;--primary-weak:#2563eb14;
  --success:#15a34a;--success-weak:#15a34a17;--warn:#c2790a;--warn-weak:#c2790a17;
  --danger:#dc2626;--danger-weak:#dc262617;
  --live:#0d9488;--live-weak:#0d948817;--music:#7c3aed;--music-weak:#7c3aed17;
  --sh-1:0 1px 2px rgba(16,24,40,.08);
}
*{box-sizing:border-box}html,body{margin:0}
body{font-family:var(--font);color:var(--text);background:var(--bg);max-width:var(--maxw);margin:0 auto;padding:var(--s3) var(--s3) var(--s7);line-height:var(--lh);font-size:var(--fs-md);-webkit-text-size-adjust:100%}
a{color:var(--primary);text-decoration:none}a:hover{text-decoration:underline}
:focus-visible{outline:none;box-shadow:var(--focus);border-radius:var(--r-sm)}
h1{font-size:var(--fs-xl);margin:var(--s1) 0;letter-spacing:-.01em}
h2{font-size:var(--fs-sm);margin:0 0 var(--s2);text-transform:uppercase;letter-spacing:var(--track-caps);color:var(--muted);font-weight:var(--fw-med)}
.sub{color:var(--muted);font-size:var(--fs-sm)}
.appbar{margin-bottom:var(--s2)}
.nav{display:flex;gap:var(--s1);flex-wrap:wrap;align-items:center;font-size:var(--fs-sm);margin-bottom:var(--s4)}
.nav a{color:var(--muted);padding:var(--s1) var(--s2);border-radius:var(--r-pill);min-height:var(--tap);display:inline-flex;align-items:center}
.nav a:hover{background:var(--surface-2);color:var(--text);text-decoration:none}
.nav a[aria-current="page"]{background:var(--primary-weak);color:var(--primary)}
section{margin:0 0 var(--s5)}
button{font:inherit;font-size:var(--fs-sm);font-weight:var(--fw-med);min-height:var(--ctl-h);padding:0 var(--ctl-pad-x);border:1px solid transparent;border-radius:var(--r-pill);background:var(--primary);color:var(--primary-fg);cursor:pointer;display:inline-flex;align-items:center;justify-content:center;gap:var(--s1);white-space:nowrap}
button:hover{filter:brightness(1.06)}button:active{transform:translateY(1px)}
button.ghost{background:transparent;color:var(--primary);border-color:var(--border-strong)}
button.ghost:hover{background:var(--primary-weak)}
button.danger{background:transparent;color:var(--danger);border-color:var(--danger)}
button:disabled{opacity:.4;cursor:not-allowed}
.mini{min-height:var(--ctl-h-sm);padding:0 var(--s3);font-size:var(--fs-sm)}
.icon-btn{min-width:var(--ctl-h-sm);padding:0 var(--s2)}
select,input{width:100%;font:inherit;font-size:var(--fs-md);min-height:var(--ctl-h);padding:var(--s2) var(--s3);border:1px solid var(--border-strong);border-radius:var(--r-md);background:var(--surface-2);color:var(--text)}
input:focus,select:focus{border-color:var(--primary);outline:none}
.row{display:flex;gap:var(--s2);flex-wrap:wrap;align-items:center}
.mt2{margin-top:var(--s2)}.mt3{margin-top:var(--s3)}
.cbx{width:auto;min-height:0;margin-right:.4em}
.grow{flex:1;min-width:0}
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--r-lg);padding:var(--s4);box-shadow:var(--sh-1)}
.badge{display:inline-flex;align-items:center;gap:.3em;font-size:var(--fs-xs);font-weight:var(--fw-med);line-height:1;padding:.32rem .55rem;border-radius:var(--r-pill);background:var(--surface-3);color:var(--muted)}
.badge--live{background:var(--live-weak);color:var(--live)}
.badge--music{background:var(--music-weak);color:var(--music)}
.chips{display:flex;gap:var(--s1);flex-wrap:wrap;margin-top:var(--s2)}
.chip{font-size:var(--fs-xs);padding:.3rem .55rem;border-radius:var(--r-pill);background:var(--surface-2);border:1px solid var(--border);color:var(--muted);cursor:pointer}
.chip.on{background:var(--primary-weak);border-color:var(--primary);color:var(--primary)}
#searchResults{display:flex;flex-direction:column;gap:var(--s1);margin-top:var(--s2);max-height:16rem;overflow:auto}
.sr{display:flex;align-items:center;gap:var(--s2);padding:var(--s2);border:1px solid var(--border);border-radius:var(--r-md);background:var(--surface);cursor:pointer}
.sr:hover{border-color:var(--border-strong)}
.sr .t{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.title{font-weight:var(--fw-med)}
.who{color:var(--muted);font-size:var(--fs-sm)}
/* feature bars + axis navigators */
.bars{display:grid;grid-template-columns:5.2rem 1fr 2.4rem;gap:var(--s1) var(--s2);align-items:center;margin-top:var(--s3)}
.bars .lab{font-size:var(--fs-xs);color:var(--muted)}
.bars .val{font-size:var(--fs-xs);color:var(--muted);text-align:right;font-variant-numeric:tabular-nums}
.track{height:8px;border-radius:var(--r-pill);background:var(--surface-3);overflow:hidden}
.track>i{display:block;height:100%;background:var(--primary)}
.axis{display:grid;grid-template-columns:5.2rem auto 1fr auto 2.6rem;gap:var(--s2);align-items:center;margin-bottom:var(--s2)}
.axis .lab{font-size:var(--fs-sm);color:var(--muted)}
.axis input[type=range]{width:100%;min-height:var(--ctl-h-sm);accent-color:var(--primary)}
.axis .val{font-size:var(--fs-xs);color:var(--muted);text-align:right;font-variant-numeric:tabular-nums}
.reslist{display:flex;flex-direction:column;gap:var(--s2)}
.res{border:1px solid var(--border);border-radius:var(--r-md);padding:var(--s3);background:var(--surface)}
.res .hd{display:flex;align-items:center;gap:var(--s2);flex-wrap:wrap}
.res .score{font-variant-numeric:tabular-nums;font-size:var(--fs-xs);color:var(--success);font-weight:var(--fw-med)}
.res .who{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.res .mini-bars{display:flex;gap:3px;margin-top:var(--s2)}
.res .mini-bars>i{height:5px;border-radius:2px;background:var(--surface-3);flex:1;position:relative;overflow:hidden}
.res .mini-bars>i>b{position:absolute;left:0;top:0;bottom:0;background:var(--primary)}
.res .ctl{margin-left:auto;display:flex;gap:var(--s1)}
.crate{display:flex;flex-direction:column;gap:var(--s1);margin-bottom:var(--s3)}
.crate .ci{display:flex;align-items:center;gap:var(--s2);padding:var(--s2);border:1px solid var(--border);border-radius:var(--r-md);background:var(--surface)}
.crate .ci .t{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
audio{width:100%;margin-top:var(--s3);border-radius:var(--r-md)}
.msg{font-size:var(--fs-sm);color:var(--warn);min-height:1.2em}
.hd2{border-bottom:1px solid var(--border);padding-bottom:var(--s2);margin-bottom:var(--s3);display:flex;align-items:center;gap:var(--s2)}
.hd2 h2{margin:0}.hd2 .spacer{margin-left:auto}
</style></head><body>
<div class="appbar"><h1>WRIT-FM &middot; browse</h1></div>
<div class="nav"><a href="/admin">station</a><a href="/blocks">blocks</a><a href="/day">24-hour day</a><a href="/now">now</a><a href="/browse" aria-current="page">browse</a></div>

<section>
  <div class="row">
    <input id="q" placeholder="search a song / artist to start" autocomplete="off">
    <button class="mini" id="btnSearch" type="button">Search</button>
    <button class="ghost mini" id="btnSurprise" type="button">🎲 Surprise</button>
  </div>
  <div id="searchResults"></div>
</section>

<section id="seedSection" hidden>
  <div class="hd2"><h2>Seed</h2><span class="spacer"></span><button class="ghost mini" id="btnReset" type="button">reset vibe</button></div>
  <div class="card" id="seedCard"></div>
</section>

<section id="navSection" hidden>
  <div class="hd2"><h2>Navigate the vibe</h2></div>
  <div id="axes"></div>
  <div class="row mt2">
    <label class="sub"><input type="checkbox" id="incLive" class="cbx">include live versions</label>
  </div>
  <div class="sub mt3">Era</div><div id="eraChips" class="chips"></div>
  <div class="sub mt3">Moods</div><div id="moodChips" class="chips"></div>
  <div class="sub mt3">Themes</div><div id="themeChips" class="chips"></div>
</section>

<section id="resSection" hidden>
  <div class="hd2"><h2>Similar tracks</h2><span class="spacer sub" id="resCount"></span></div>
  <div id="results" class="reslist"></div>
</section>

<section id="crateSection" hidden>
  <div class="hd2"><h2>Crate</h2><span class="spacer sub" id="crateInfo"></span></div>
  <div id="crate" class="crate"></div>
  <div class="row">
    <input id="crateTitle" placeholder="block title (optional)">
  </div>
  <div class="row mt2">
    <button class="mini" id="btnQueue" type="button">Build &amp; queue</button>
    <button class="mini" id="btnNow" type="button">Build &amp; play now</button>
    <button class="ghost mini" id="btnSave" type="button">Build &amp; save</button>
    <button class="ghost mini" id="btnClear" type="button">Clear</button>
  </div>
  <div class="msg" id="crateMsg"></div>
</section>

<audio id="audio" controls preload="none" hidden></audio>

<script>
const $=id=>document.getElementById(id);
const BASE=location.pathname.replace(/\\/(browse)\\/?$/,'').replace(/\\/+$/,'');
const API=p=>BASE+'/api/'+p;
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
const AXES=[{k:'energy',n:'Energy'},{k:'valence',n:'Valence'},{k:'acousticness',n:'Acoustic'},
  {k:'danceability',n:'Dance'},{k:'instrumental',n:'Instrum.'},{k:'tempo_norm',n:'Tempo'}];
const STEP=0.08;
let seed=null, target=[0,0,0,0,0,0], crate=[], facets={moods:[],themes:[],eras:[]};
let fEra=null, fMoods=new Set(), fThemes=new Set(), incLive=false, qTimer=null;

function label(r){return (r.artist? r.artist+' — ':'')+(r.name||r.id);}
function bpmOf(r){return Math.round(r.bpm||(40+ (r.vec?r.vec[5]:0)*160));}
function play(url){const a=$('audio');a.hidden=false;a.src=url;a.play().catch(()=>{});}

async function loadMeta(){
  try{ facets=await (await fetch(API('browse/meta'))).json(); }catch(e){}
  $('eraChips').innerHTML=(facets.eras||[]).map(e=>`<span class="chip" data-era="${esc(e)}">${esc(e)}</span>`).join('');
  $('moodChips').innerHTML=(facets.moods||[]).map(m=>`<span class="chip" data-mood="${esc(m)}">${esc(m)}</span>`).join('');
  $('themeChips').innerHTML=(facets.themes||[]).map(t=>`<span class="chip" data-theme="${esc(t)}">${esc(t)}</span>`).join('');
  $('eraChips').querySelectorAll('[data-era]').forEach(el=>el.onclick=()=>{const v=el.dataset.era;fEra=(fEra===v?null:v);el.parentElement.querySelectorAll('.chip').forEach(c=>c.classList.toggle('on',c===el&&fEra));requery();});
  const tog=(set,key)=>el=>el.onclick=()=>{const v=el.dataset[key];if(set.has(v))set.delete(v);else set.add(v);el.classList.toggle('on');requery();};
  $('moodChips').querySelectorAll('[data-mood]').forEach(tog(fMoods,'mood'));
  $('themeChips').querySelectorAll('[data-theme]').forEach(tog(fThemes,'theme'));
}

function bar(v){return `<div class="track"><i style="width:${Math.round((v||0)*100)}%"></i></div>`;}
function renderSeed(){
  if(!seed){$('seedSection').hidden=true;return;}
  $('seedSection').hidden=false;
  const chips=[].concat((seed.moods||[]),(seed.themes||[])).map(m=>`<span class="chip">${esc(m)}</span>`).join('');
  const badges=`<span class="badge badge--music">♫ ${esc(seed.era||'—')}</span>`+(seed.live?'<span class="badge badge--live">live</span>':'');
  const rows=AXES.map((a,i)=>`<div class="lab">${a.n}</div>${bar(seed.vec[i])}<div class="val">${a.k==='tempo_norm'?bpmOf(seed):Math.round(seed.vec[i]*100)}</div>`).join('');
  $('seedCard').innerHTML=`<div class="row"><div class="grow"><div class="title">${esc(seed.name||seed.id)}</div><div class="who">${esc(seed.artist||'unknown artist')}${seed.album?' · '+esc(seed.album):''}</div></div>
      <button class="ghost mini" id="seedPlay" type="button">▶</button></div>
    <div class="row mt2">${badges}</div>
    <div class="chips">${chips}</div><div class="bars">${rows}</div>`;
  $('seedPlay').onclick=()=>seed.url&&play(seed.url);
}

function renderAxes(){
  $('axes').innerHTML=AXES.map((a,i)=>`<div class="axis">
    <div class="lab">${a.n}</div>
    <button class="ghost icon-btn" data-nudge="${i}" data-d="-1" type="button" title="less">◀</button>
    <input type="range" min="0" max="1" step="0.01" data-ax="${i}" value="${target[i]}">
    <button class="ghost icon-btn" data-nudge="${i}" data-d="1" type="button" title="more">▶</button>
    <div class="val" id="axv${i}">${a.k==='tempo_norm'?Math.round(40+target[i]*160):Math.round(target[i]*100)}</div>
  </div>`).join('');
  $('axes').querySelectorAll('[data-ax]').forEach(el=>el.oninput=()=>{const i=+el.dataset.ax;target[i]=+el.value;paintAxVal(i);requery();});
  $('axes').querySelectorAll('[data-nudge]').forEach(el=>el.onclick=()=>{const i=+el.dataset.nudge;target[i]=Math.max(0,Math.min(1,target[i]+(+el.dataset.d)*STEP));$('axes').querySelector('[data-ax="'+i+'"]').value=target[i];paintAxVal(i);requery();});
}
function paintAxVal(i){$('axv'+i).textContent=AXES[i].k==='tempo_norm'?Math.round(40+target[i]*160):Math.round(target[i]*100);}

function setSeed(rec){
  seed=rec; target=rec.vec.slice();
  $('navSection').hidden=false; $('resSection').hidden=false;
  $('searchResults').innerHTML=''; $('q').value='';
  renderSeed(); renderAxes(); requery();
}
function resetTarget(){ if(!seed)return; target=seed.vec.slice(); renderAxes(); requery(); }

function requery(){ clearTimeout(qTimer); qTimer=setTimeout(doQuery,160); }
async function doQuery(){
  const exclude=crate.map(c=>c.id); if(seed)exclude.push(seed.id);
  const body={vec:target,k:40,filters:{studio_only:!incLive,era:fEra,
    moods:[...fMoods],themes:[...fThemes]},exclude};
  let res=[];
  try{ res=(await (await fetch(API('browse/navigate'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})).json()).results||[]; }catch(e){}
  $('resCount').textContent=res.length+' shown';
  $('results').innerHTML=res.map(r=>{
    const mb=AXES.map((a,i)=>`<i><b style="width:${Math.round(r.vec[i]*100)}%"></b></i>`).join('');
    const dup=r.dupes>1?`<span class="badge" title="${r.dupes} copies in library">×${r.dupes}</span>`:'';
    return `<div class="res" data-id="${esc(r.id)}">
      <div class="hd"><span class="score">${Math.round(r.score*100)}</span>
        <span class="who"><span class="title">${esc(r.name||r.id)}</span> <span class="sub">${esc(r.artist||'')}</span></span>${dup}
        <span class="ctl">
          <button class="ghost icon-btn" data-play type="button" title="preview">▶</button>
          <button class="ghost icon-btn" data-seed type="button" title="explore from here">↻</button>
          <button class="mini" data-add type="button">+</button>
        </span></div>
      <div class="mini-bars">${mb}</div></div>`;
  }).join('') || '<span class="sub">no matches — loosen the filters</span>';
  $('results').querySelectorAll('.res').forEach(el=>{
    const r=res.find(x=>x.id===el.dataset.id);
    el.querySelector('[data-play]').onclick=()=>r.url&&play(r.url);
    el.querySelector('[data-seed]').onclick=()=>setSeed(r);
    el.querySelector('[data-add]').onclick=()=>addCrate(r);
  });
}

function fmtDur(s){s=Math.round(s||0);return Math.floor(s/60)+':'+String(s%60).padStart(2,'0');}
function renderCrate(){
  $('crateSection').hidden = crate.length===0;
  const total=crate.reduce((a,c)=>a+(c.duration_s||0),0);
  $('crateInfo').textContent=crate.length+' track'+(crate.length===1?'':'s')+(total?' · '+fmtDur(total):'');
  $('crate').innerHTML=crate.map((c,i)=>`<div class="ci" data-i="${i}">
    <span class="badge">${i+1}</span><span class="t"><span class="title">${esc(c.name||c.id)}</span> <span class="sub">${esc(c.artist||'')}</span></span>
    <button class="ghost icon-btn" data-p type="button">▶</button>
    <button class="danger icon-btn" data-x type="button">✕</button></div>`).join('');
  $('crate').querySelectorAll('.ci').forEach(el=>{const i=+el.dataset.i;
    el.querySelector('[data-p]').onclick=()=>crate[i].url&&play(crate[i].url);
    el.querySelector('[data-x]').onclick=()=>{crate.splice(i,1);renderCrate();requery();};});
}
const dkey=r=>r.dkey||r.id;
function addCrate(r){ if(!crate.some(c=>dkey(c)===dkey(r))){crate.push(r);renderCrate();requery();} }

async function build(air){
  if(!crate.length)return;
  const btns=$('crateSection').querySelectorAll('button'); btns.forEach(b=>b.disabled=true);
  $('crateMsg').textContent='building…';
  try{
    const r=await (await fetch(API('browse/build'),{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({title:$('crateTitle').value||undefined,track_ids:crate.map(c=>c.id),air})})).json();
    if(r.error)throw new Error(r.error);
    $('crateMsg').textContent='built "'+(r.block&&r.block.title||'block')+'"'+(air?(' — '+(air==='now'?'on air now':'queued')):' — saved');
  }catch(e){ $('crateMsg').textContent='error: '+(e.message||e); }
  finally{ btns.forEach(b=>b.disabled=false); }
}

function doSearch(){
  const q=$('q').value.trim(); if(!q){$('searchResults').innerHTML='';return;}
  fetch(API('browse/search?q='+encodeURIComponent(q))).then(r=>r.json()).then(d=>{
    $('searchResults').innerHTML=(d.results||[]).map(r=>`<div class="sr" data-id="${esc(r.id)}">
      <span class="t"><span class="title">${esc(r.name||r.id)}</span> <span class="who">${esc(r.artist||'')}</span></span>
      ${r.dupes>1?`<span class="badge" title="${r.dupes} copies">×${r.dupes}</span>`:''}
      <button class="ghost icon-btn" data-play type="button">▶</button></div>`).join('')||'<span class="sub">no matches</span>';
    $('searchResults').querySelectorAll('.sr').forEach(el=>{const r=(d.results||[]).find(x=>x.id===el.dataset.id);
      el.querySelector('[data-play]').onclick=(e)=>{e.stopPropagation();r.url&&play(r.url);};
      el.onclick=()=>setSeed(r);});
  }).catch(()=>{});
}
async function surprise(){ try{const r=await (await fetch(API('browse/random'))).json(); if(r)setSeed(r);}catch(e){} }

$('btnSearch').onclick=doSearch;
$('q').addEventListener('input',()=>{clearTimeout(qTimer);qTimer=setTimeout(doSearch,250);});
$('q').addEventListener('keydown',e=>{if(e.key==='Enter')doSearch();});
$('btnSurprise').onclick=surprise;
$('btnReset').onclick=resetTarget;
$('incLive').onchange=()=>{incLive=$('incLive').checked;requery();};
$('btnQueue').onclick=()=>build('queue');
$('btnNow').onclick=()=>build('now');
$('btnSave').onclick=()=>build(null);
$('btnClear').onclick=()=>{crate=[];renderCrate();requery();};

(async function init(){
  await loadMeta();
  const seedId=new URLSearchParams(location.search).get('seed');
  if(seedId){ try{const r=await (await fetch(API('browse/track/'+seedId))).json(); if(r&&r.id)return setSeed(r);}catch(e){} }
  surprise();
})();
</script>
</body></html>"""
