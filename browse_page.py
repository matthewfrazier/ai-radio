#!/usr/bin/env python3
"""/browse -- the Music view. Explore the library through the feature overlay:
search or surprise a seed track, walk a target point through feature space with
per-axis nudges/sliders, filter by era/mood/theme + studio/live, preview, and
collect picks into a crate to build a block and put it on air. Zero-framework,
CSP-safe; wrapped in the shared web.page shell (design system + nav + errors).
Inline `style` is used only for the dynamic feature-bar widths."""

import web

CSS = """
.chips{display:flex;gap:var(--s1);flex-wrap:wrap;margin-top:var(--s2)}
.chip{font-size:var(--fs-xs);padding:.3rem .55rem;border-radius:var(--r-pill);background:var(--surface-2);border:1px solid var(--border);color:var(--muted);cursor:pointer}
.chip.on{background:var(--primary-weak);border-color:var(--primary);color:var(--primary)}
.cbx{width:auto;min-height:0;margin-right:.4em}
.grow{flex:1;min-width:0}
#searchResults{display:flex;flex-direction:column;gap:var(--s1);margin-top:var(--s2);max-height:16rem;overflow:auto}
.sr{display:flex;align-items:center;gap:var(--s2);padding:var(--s2);border:1px solid var(--border);border-radius:var(--r-md);background:var(--surface);cursor:pointer}
.sr:hover{border-color:var(--border-strong)}
.sr .t{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.title{font-weight:var(--fw-med)}
.who{color:var(--muted);font-size:var(--fs-sm)}
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
.msg{font-size:var(--fs-sm);color:var(--warn);min-height:1.2em}
"""

BODY = """
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
"""

JS = r"""
const $=id=>document.getElementById(id);
const BASE=location.pathname.replace(/\/(browse)\/?$/,'').replace(/\/+$/,'');
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
"""

BROWSE_PAGE = web.page("music", "music", BODY, css=CSS, js=JS)
