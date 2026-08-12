#!/usr/bin/env python3
"""/browse -- the Music view. Find music three ways -- instant search (grouped
by artist), facet-first Browse (mood/era/theme/sort, no seed needed), or
similar-to-seed with per-axis vibe nudging -- and queue any track into a named
playlist with one click. Playlists are server-persisted (playlists.json),
mirror to Jellyfin on demand, go on air as a block, or cast to a Chromecast
(the panel sequences track-by-track). Zero-framework, CSP-safe; wrapped in the
shared web.page shell. Inline `style` only for dynamic feature-bar widths."""

import web

CSS = """
.chips{display:flex;gap:var(--s1);flex-wrap:wrap;margin-top:var(--s2)}
.chip{font-size:var(--fs-xs);padding:.3rem .55rem;border-radius:var(--r-pill);background:var(--surface-2);border:1px solid var(--border);color:var(--muted);cursor:pointer}
.chip.on{background:var(--primary-weak);border-color:var(--primary);color:var(--primary)}
.cbx{width:auto;min-height:0;margin-right:.4em}
.grow{flex:1;min-width:0}
#searchResults{display:flex;flex-direction:column;gap:var(--s1);margin-top:var(--s2);max-height:22rem;overflow:auto}
.gart{font-size:var(--fs-xs);color:var(--muted);margin-top:var(--s2);text-transform:uppercase;letter-spacing:.04em}
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
.selgrp{display:flex;gap:var(--s1);align-items:center;flex-wrap:wrap}
.selgrp select{min-width:9rem}
#castStatus{font-variant-numeric:tabular-nums}
"""

BODY = """
<section>
  <div class="row">
    <input id="q" placeholder="type to search songs / artists / albums" autocomplete="off">
    <button class="ghost mini" id="btnSurprise" type="button">🎲 Surprise</button>
    <button class="ghost mini" id="btnBrowse" type="button">☰ Browse all</button>
  </div>
  <div id="searchResults"></div>
</section>

<section id="filterSection">
  <div class="hd2"><h2>Filters</h2><span class="spacer"></span>
    <label class="sub"><input type="checkbox" id="incLive" class="cbx">include live versions</label>
  </div>
  <div class="sub">Era</div><div id="eraChips" class="chips"></div>
  <div class="sub mt3">Moods</div><div id="moodChips" class="chips"></div>
  <div class="sub mt3">Themes</div><div id="themeChips" class="chips"></div>
</section>

<section id="browseSection" hidden>
  <div class="hd2"><h2>Browse</h2><span class="spacer sub" id="brCount"></span>
    <span class="selgrp"><label class="sub" for="brSort">sort</label>
      <select id="brSort">
        <option value="">random</option><option value="energy">energy</option>
        <option value="valence">valence</option><option value="danceability">dance</option>
        <option value="tempo_norm">tempo</option><option value="acousticness">acoustic</option>
        <option value="name">name</option>
      </select>
      <select id="brDir"><option value="desc">high→low</option><option value="asc">low→high</option></select>
      <button class="ghost mini" id="brReroll" type="button">↻</button></span>
  </div>
  <div id="brResults" class="reslist"></div>
</section>

<section id="seedSection" hidden>
  <div class="hd2"><h2>Seed</h2><span class="spacer"></span><button class="ghost mini" id="btnReset" type="button">reset vibe</button></div>
  <div class="card" id="seedCard"></div>
</section>

<section id="navSection" hidden>
  <div class="hd2"><h2>Navigate the vibe</h2></div>
  <div id="axes"></div>
</section>

<section id="resSection" hidden>
  <div class="hd2"><h2>Similar tracks</h2><span class="spacer sub" id="resCount"></span></div>
  <div id="results" class="reslist"></div>
</section>

<section id="plSection">
  <div class="hd2"><h2>Playlists</h2><span class="spacer sub" id="plInfo"></span></div>
  <div class="row selgrp">
    <select id="plSelect"></select>
    <input id="plName" class="grow" placeholder="new playlist name" autocomplete="off">
    <button class="mini" id="plNew" type="button">New</button>
    <button class="ghost mini" id="plRename" type="button">Rename</button>
    <button class="danger mini" id="plDelete" type="button">Delete</button>
  </div>
  <div id="plTracks" class="crate mt3"></div>
  <div class="row">
    <button class="mini" id="plQueue" type="button">Queue on air</button>
    <button class="mini" id="plNow" type="button">On air now</button>
    <button class="ghost mini" id="plSync" type="button">Sync to Jellyfin</button>
  </div>
  <div class="row mt2 selgrp">
    <select id="castSelect"><option value="">cast to…</option></select>
    <button class="mini" id="plCast" type="button">Cast</button>
    <button class="ghost mini" id="plCastStop" type="button">Stop</button>
    <span class="sub" id="castStatus"></span>
  </div>
  <div class="msg" id="plMsg"></div>
</section>

<audio id="audio" controls preload="none" hidden></audio>
"""

JS = r"""
const $=id=>document.getElementById(id);
const BASE=location.pathname.replace(/\/(browse)\/?$/,'').replace(/\/+$/,'');
const API=p=>BASE+'/api/'+p;
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
async function jget(p){const r=await fetch(API(p));if(!r.ok)throw new Error(await r.text());return r.json();}
async function jpost(p,body){const r=await fetch(API(p),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})});if(!r.ok)throw new Error(await r.text());return r.json();}
const AXES=[{k:'energy',n:'Energy'},{k:'valence',n:'Valence'},{k:'acousticness',n:'Acoustic'},
  {k:'danceability',n:'Dance'},{k:'instrumental',n:'Instrum.'},{k:'tempo_norm',n:'Tempo'}];
const STEP=0.08;
let seed=null, target=[0,0,0,0,0,0], facets={moods:[],themes:[],eras:[]};
let fEra=null, fMoods=new Set(), fThemes=new Set(), incLive=false, qTimer=null, sTimer=null;
let pls=[], curPl=null, devices=[];

function label(r){return (r.artist? r.artist+' — ':'')+(r.name||r.id);}
function bpmOf(r){return Math.round(r.bpm||(40+ (r.vec?r.vec[5]:0)*160));}
function play(url){const a=$('audio');a.hidden=false;a.src=url;a.play().catch(()=>{});}
function fmtDur(s){s=Math.round(s||0);return Math.floor(s/60)+':'+String(s%60).padStart(2,'0');}
function filters(){return {studio_only:!incLive,era:fEra,moods:[...fMoods],themes:[...fThemes]};}
function filterQS(){const p=new URLSearchParams();p.set('studio',incLive?'0':'1');
  if(fEra)p.set('era',fEra);if(fMoods.size)p.set('moods',[...fMoods].join(','));
  if(fThemes.size)p.set('themes',[...fThemes].join(','));return p;}

async function loadMeta(){
  try{ facets=await jget('browse/meta'); }catch(e){}
  $('eraChips').innerHTML=(facets.eras||[]).map(e=>`<span class="chip" data-era="${esc(e)}">${esc(e)}</span>`).join('');
  $('moodChips').innerHTML=(facets.moods||[]).map(m=>`<span class="chip" data-mood="${esc(m)}">${esc(m)}</span>`).join('');
  $('themeChips').innerHTML=(facets.themes||[]).map(t=>`<span class="chip" data-theme="${esc(t)}">${esc(t)}</span>`).join('');
  $('eraChips').querySelectorAll('[data-era]').forEach(el=>el.onclick=()=>{const v=el.dataset.era;fEra=(fEra===v?null:v);el.parentElement.querySelectorAll('.chip').forEach(c=>c.classList.toggle('on',c===el&&fEra));onFilter();});
  const tog=(set,key)=>el=>el.onclick=()=>{const v=el.dataset[key];if(set.has(v))set.delete(v);else set.add(v);el.classList.toggle('on');onFilter();};
  $('moodChips').querySelectorAll('[data-mood]').forEach(tog(fMoods,'mood'));
  $('themeChips').querySelectorAll('[data-theme]').forEach(tog(fThemes,'theme'));
}
function onFilter(){
  if(!$('browseSection').hidden)doBrowse();
  if(seed)requery();
  if($('browseSection').hidden&&!seed)doBrowse();  // facet-first: touching a filter starts browsing
}

// one row renderer for Browse + Similar results
function resRow(r,{score}={}){
  const mb=AXES.map((a,i)=>`<i><b style="width:${Math.round((r.vec?r.vec[i]:0)*100)}%"></b></i>`).join('');
  const dup=r.dupes>1?`<span class="badge" title="${r.dupes} copies in library">×${r.dupes}</span>`:'';
  const sc=score&&r.score!=null?`<span class="score">${Math.round(r.score*100)}</span>`:'';
  return `<div class="res" data-id="${esc(r.id)}">
    <div class="hd">${sc}
      <span class="who"><span class="title">${esc(r.name||r.id)}</span> <span class="sub">${esc(r.artist||'')}</span></span>${dup}
      <span class="ctl">
        <button class="ghost icon-btn" data-play type="button" title="preview">▶</button>
        <button class="ghost icon-btn" data-seed type="button" title="explore from here">↻</button>
        <button class="mini" data-add type="button" title="add to playlist">+</button>
      </span></div>
    <div class="mini-bars">${mb}</div></div>`;
}
function wireRows(container,res){
  container.querySelectorAll('.res').forEach(el=>{
    const r=res.find(x=>x.id===el.dataset.id); if(!r)return;
    el.querySelector('[data-play]').onclick=()=>r.url&&play(r.url);
    el.querySelector('[data-seed]').onclick=()=>setSeed(r);
    el.querySelector('[data-add]').onclick=()=>addToPl(r);
  });
}

// --- facet-first browse ------------------------------------------------------
async function doBrowse(){
  $('browseSection').hidden=false;
  const p=filterQS(); p.set('k','60');
  const sort=$('brSort').value; if(sort){p.set('sort',sort);p.set('dir',$('brDir').value);}
  let d={total:0,results:[]};
  try{ d=await jget('browse/list?'+p.toString()); }catch(e){}
  $('brCount').textContent=d.results.length+' of '+d.total;
  $('brResults').innerHTML=d.results.map(r=>resRow(r)).join('')||'<span class="sub">nothing matches — loosen the filters</span>';
  wireRows($('brResults'),d.results);
}

// --- seed + similar ----------------------------------------------------------
function bar(v){return `<div class="track"><i style="width:${Math.round((v||0)*100)}%"></i></div>`;}
function renderSeed(){
  if(!seed){$('seedSection').hidden=true;return;}
  $('seedSection').hidden=false;
  const chips=[].concat((seed.moods||[]),(seed.themes||[])).map(m=>`<span class="chip">${esc(m)}</span>`).join('');
  const badges=`<span class="badge badge--music">♫ ${esc(seed.era||'—')}</span>`+(seed.live?'<span class="badge badge--live">live</span>':'');
  const rows=AXES.map((a,i)=>`<div class="lab">${a.n}</div>${bar(seed.vec[i])}<div class="val">${a.k==='tempo_norm'?bpmOf(seed):Math.round(seed.vec[i]*100)}</div>`).join('');
  $('seedCard').innerHTML=`<div class="row"><div class="grow"><div class="title">${esc(seed.name||seed.id)}</div><div class="who">${esc(seed.artist||'unknown artist')}${seed.album?' · '+esc(seed.album):''}</div></div>
      <button class="ghost mini" id="seedPlay" type="button">▶</button>
      <button class="mini" id="seedAdd" type="button" title="add to playlist">+</button></div>
    <div class="row mt2">${badges}</div>
    <div class="chips">${chips}</div><div class="bars">${rows}</div>`;
  $('seedPlay').onclick=()=>seed.url&&play(seed.url);
  $('seedAdd').onclick=()=>addToPl(seed);
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
  $('browseSection').hidden=true;
  $('navSection').hidden=false; $('resSection').hidden=false;
  $('searchResults').innerHTML=''; $('q').value='';
  renderSeed(); renderAxes(); requery();
}
function resetTarget(){ if(!seed)return; target=seed.vec.slice(); renderAxes(); requery(); }

function requery(){ clearTimeout(qTimer); qTimer=setTimeout(doQuery,160); }
async function doQuery(){
  const exclude=(curPl?curPl.track_ids.slice():[]); if(seed)exclude.push(seed.id);
  const body={vec:target,k:40,filters:filters(),exclude};
  let res=[];
  try{ res=(await jpost('browse/navigate',body)).results||[]; }catch(e){}
  $('resCount').textContent=res.length+' shown';
  $('results').innerHTML=res.map(r=>resRow(r,{score:true})).join('') || '<span class="sub">no matches — loosen the filters</span>';
  wireRows($('results'),res);
}

// --- instant search, grouped by artist --------------------------------------
function doSearch(){
  const q=$('q').value.trim(); if(!q){$('searchResults').innerHTML='';return;}
  jget('browse/search?q='+encodeURIComponent(q)).then(d=>{
    const res=d.results||[], groups=[];
    res.forEach(r=>{const a=r.artist||'unknown artist';let g=groups.find(x=>x.a===a);if(!g)groups.push(g={a,rs:[]});g.rs.push(r);});
    $('searchResults').innerHTML=groups.map(g=>`<div class="gart">${esc(g.a)}</div>`+g.rs.map(r=>`<div class="sr" data-id="${esc(r.id)}">
      <span class="t"><span class="title">${esc(r.name||r.id)}</span>${r.album?` <span class="who">${esc(r.album)}</span>`:''}</span>
      ${r.dupes>1?`<span class="badge" title="${r.dupes} copies">×${r.dupes}</span>`:''}
      <button class="ghost icon-btn" data-play type="button" title="preview">▶</button>
      <button class="mini" data-add type="button" title="add to playlist">+</button></div>`).join('')).join('')||'<span class="sub">no matches</span>';
    $('searchResults').querySelectorAll('.sr').forEach(el=>{const r=res.find(x=>x.id===el.dataset.id);
      el.querySelector('[data-play]').onclick=(e)=>{e.stopPropagation();r.url&&play(r.url);};
      el.querySelector('[data-add]').onclick=(e)=>{e.stopPropagation();addToPl(r);};
      el.onclick=()=>setSeed(r);});
  }).catch(()=>{});
}
async function surprise(){ try{const r=await jget('browse/random'); if(r)setSeed(r);}catch(e){} }

// --- playlists ---------------------------------------------------------------
function msg(t){$('plMsg').textContent=t||'';}
function renderPlSelect(){
  $('plSelect').innerHTML=pls.map(p=>`<option value="${esc(p.id)}"${curPl&&p.id===curPl.id?' selected':''}>${esc(p.title)} (${p.track_count})</option>`).join('')||'<option value="">— no playlists —</option>';
}
function renderPl(){
  renderPlSelect();
  if(!curPl){$('plInfo').textContent='';$('plTracks').innerHTML='<span class="sub">create a playlist, then + any track into it</span>';return;}
  const t=curPl.tracks||[];
  $('plInfo').textContent=curPl.title+' · '+t.length+' track'+(t.length===1?'':'s')+(curPl.duration_s?' · '+fmtDur(curPl.duration_s):'')+(curPl.jellyfin_id?' · synced':'');
  $('plTracks').innerHTML=t.map((c,i)=>`<div class="ci" data-i="${i}">
    <span class="badge">${i+1}</span><span class="t"><span class="title">${esc(c.name||c.id)}</span> <span class="sub">${esc(c.artist||'')}${c.duration_s?' · '+fmtDur(c.duration_s):''}</span></span>
    <button class="ghost icon-btn" data-up type="button" title="earlier">↑</button>
    <button class="ghost icon-btn" data-dn type="button" title="later">↓</button>
    <button class="ghost icon-btn" data-p type="button" title="preview">▶</button>
    <button class="danger icon-btn" data-x type="button" title="remove">✕</button></div>`).join('')||'<span class="sub">empty — + any track above to queue it here</span>';
  $('plTracks').querySelectorAll('.ci').forEach(el=>{const i=+el.dataset.i;
    el.querySelector('[data-p]').onclick=()=>t[i].url&&play(t[i].url);
    el.querySelector('[data-x]').onclick=()=>plOp({op:'remove',index:i});
    el.querySelector('[data-up]').onclick=()=>i>0&&plOp({op:'move',index:i,to:i-1});
    el.querySelector('[data-dn]').onclick=()=>i<t.length-1&&plOp({op:'move',index:i,to:i+1});});
}
async function loadPls(keepId){
  try{ pls=(await jget('playlists')).playlists||[]; }catch(e){ pls=[]; }
  const want=keepId||(curPl&&curPl.id)||(pls[0]&&pls[0].id);
  curPl=null;
  if(want&&pls.some(p=>p.id===want)){ try{ curPl=await jget('playlists/'+want); }catch(e){} }
  renderPl();
}
async function plOp(body){
  if(!curPl)return;
  try{ curPl=await jpost('playlists/'+curPl.id,body); await loadPls(curPl.id); }catch(e){ msg('error: '+e.message); }
}
async function addToPl(r){
  try{
    if(!curPl){ const p=await jpost('playlists',{title:$('plName').value||'New playlist'}); await loadPls(p.id); }
    curPl=await jpost('playlists/'+curPl.id,{op:'add',track_ids:[r.id]});
    await loadPls(curPl.id);
    msg('queued: '+label(r));
  }catch(e){ msg('error: '+e.message); }
}
async function newPl(){
  try{ const p=await jpost('playlists',{title:$('plName').value}); $('plName').value=''; await loadPls(p.id); }
  catch(e){ msg('error: '+e.message); }
}
async function delPl(){
  if(!curPl)return;
  try{ await fetch(API('playlists/'+curPl.id),{method:'DELETE'}); curPl=null; await loadPls(); msg('deleted'); }
  catch(e){ msg('error: '+e.message); }
}
async function airPl(air){
  if(!curPl)return; msg('building…');
  try{ const r=await jpost('playlists/'+curPl.id+'/air',{air});
    msg('"'+(r.block&&r.block.title||'block')+'" '+(air==='now'?'on air now':'queued')); }
  catch(e){ msg('error: '+e.message); }
}
async function syncPl(){
  if(!curPl)return; msg('syncing…');
  try{ await jpost('playlists/'+curPl.id+'/sync'); await loadPls(curPl.id); msg('synced to Jellyfin'); }
  catch(e){ msg('error: '+e.message); }
}

// --- casting -----------------------------------------------------------------
async function loadDevices(){
  try{ devices=await jget('cast/devices'); }catch(e){ devices=[]; }
  if(!Array.isArray(devices))devices=[];
  $('castSelect').innerHTML='<option value="">cast to…</option>'+devices.map(d=>`<option value="${esc(d.uuid)}">${esc(d.name)}${d.type==='group'?' (group)':''}</option>`).join('');
}
async function castPl(){
  const uuid=$('castSelect').value;
  if(!curPl||!uuid){msg(uuid?'no playlist':'pick a device first');return;}
  msg('casting…');
  try{ const st=await jpost('playlists/'+curPl.id+'/cast',{uuid}); msg('casting to '+(st.device||'device')); pollCast(); }
  catch(e){ msg('error: '+e.message); }
}
async function stopCast(){
  try{ await jpost('playlist_cast/stop',{}); $('castStatus').textContent=''; msg('cast stopped'); }
  catch(e){ msg('error: '+e.message); }
}
let castTimer=null;
async function pollCast(){
  clearTimeout(castTimer);
  let st=null;
  try{ st=await jget('playlist_cast'); }catch(e){}
  if(st&&st.state){
    const tr=st.track?(' · '+(st.track.artist?st.track.artist+' — ':'')+st.track.name):'';
    $('castStatus').textContent=st.state==='playing'
      ?('▶ '+st.title+' '+(st.index+1)+'/'+st.count+tr+' on '+st.device)
      :(st.state+' · '+st.title+' on '+st.device);
    castTimer=setTimeout(pollCast,st.state==='playing'?5000:15000);
  }else{ $('castStatus').textContent=''; castTimer=setTimeout(pollCast,15000); }
}

$('q').addEventListener('input',()=>{clearTimeout(sTimer);sTimer=setTimeout(doSearch,200);});
$('q').addEventListener('keydown',e=>{if(e.key==='Enter')doSearch();});
$('btnSurprise').onclick=surprise;
$('btnBrowse').onclick=doBrowse;
$('brSort').onchange=doBrowse; $('brDir').onchange=doBrowse; $('brReroll').onclick=doBrowse;
$('btnReset').onclick=resetTarget;
$('incLive').onchange=()=>{incLive=$('incLive').checked;onFilter();};
$('plSelect').onchange=()=>loadPls($('plSelect').value);
$('plNew').onclick=newPl;
$('plRename').onclick=()=>{const t=$('plName').value.trim();if(t){plOp({op:'rename',title:t});$('plName').value='';}};
$('plDelete').onclick=delPl;
$('plQueue').onclick=()=>airPl('queue');
$('plNow').onclick=()=>airPl('now');
$('plSync').onclick=syncPl;
$('plCast').onclick=castPl;
$('plCastStop').onclick=stopCast;

(async function init(){
  await loadMeta(); loadPls(); loadDevices(); pollCast();
  const seedId=new URLSearchParams(location.search).get('seed');
  if(seedId){ try{const r=await jget('browse/track/'+seedId); if(r&&r.id)return setSeed(r);}catch(e){} }
  doBrowse();
})();
"""

BROWSE_PAGE = web.page("music", "music", BODY, css=CSS, js=JS)
