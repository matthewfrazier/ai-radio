#!/usr/bin/env python3
"""Programming-blocks admin UI. Same zero-framework convention as panel.py's
PAGE: one inline HTML/CSS/JS string, fetch()-based, no build step."""

BLOCKS_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Programming blocks</title>
<style>
:root{color-scheme:light dark}
body{font-family:system-ui,sans-serif;max-width:640px;margin:0 auto;padding:.9rem;line-height:1.4}
h1{font-size:1.2rem;margin:.2rem 0}
h2{font-size:.9rem;margin:0;text-transform:uppercase;letter-spacing:.02em;opacity:.6}
.sub{opacity:.7;font-size:.85rem;margin-bottom:1rem}
section{margin:0 0 1.4rem}
section>.hd2{border-bottom:1px solid #8883;padding-bottom:.4rem;margin-bottom:.6rem}
#editor{border:1px solid #3b82f666;border-radius:16px;padding:1rem;background:#3b82f60d}
#editor section{margin-bottom:1.2rem}
#editor section:last-child{margin-bottom:0}
label{display:block;font-size:.78rem;opacity:.75;margin:.55rem 0 .2rem}
input,select,textarea{width:100%;box-sizing:border-box;font:inherit;padding:.5rem .6rem;border:1px solid #8885;border-radius:10px;background:transparent;color:inherit}
textarea{min-height:4rem;resize:vertical}
.row{display:flex;gap:.7rem;flex-wrap:wrap;align-items:flex-end}
.row>div{flex:1;min-width:8rem}
button{font:inherit;padding:.5rem 1rem;border:1px solid transparent;border-radius:999px;background:#3b82f6;color:#fff;cursor:pointer;font-size:.85rem}
button.ghost{background:transparent;color:#3b82f6;border-color:#3b82f680}
button.danger{background:transparent;color:#ef4444;border-color:#ef444480}
button:disabled{opacity:.5;cursor:progress}
.actions{display:flex;gap:.5rem;flex-wrap:wrap;align-items:center;margin-top:.6rem}
.dot{display:inline-block;width:.6rem;height:.6rem;border-radius:50%;background:#888;margin-right:.35rem;vertical-align:middle}
.dot.ok{background:#22c55e}.dot.bad{background:#ef4444}
pre{white-space:pre-wrap;background:#8881;padding:.6rem;border-radius:10px;font-size:.78rem;max-height:16rem;overflow:auto}
audio{width:100%;margin-top:.5rem}
a{color:#3b82f6}
.seg{padding:.7rem .8rem;margin-bottom:.7rem;border-radius:12px;border:1px solid #8884;background:rgba(128,128,128,.08)}
.seg:last-child{margin-bottom:0}
.seg .hd{display:flex;justify-content:space-between;align-items:center;gap:.5rem}
.seg .hd .left{display:flex;align-items:center;gap:.4rem;flex-wrap:wrap;min-width:0}
.seg .hd .left .name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.seg .hd .move{display:flex;gap:.2rem}
.seg .hd .move button, .seg .hd .kill{padding:.3rem .55rem;font-size:.8rem}
.badge{font-size:.68rem;padding:.15rem .5rem;border-radius:999px;background:#8883;flex-shrink:0}
.testmsg{font-size:.8rem;opacity:.8}
.tracklist{max-height:8rem;overflow:auto;font-size:.8rem;margin-top:.4rem}
.tracklist div{display:flex;justify-content:space-between;gap:.4rem;padding:.15rem 0}
.blocklist div{display:flex;justify-content:space-between;gap:.5rem;padding:.5rem 0;border-bottom:1px solid #8882;cursor:pointer}
.blocklist div:last-child{border-bottom:none}
.blocklist div:active{opacity:.6}
.addtype{display:flex;gap:.5rem;flex-wrap:wrap}
.days{display:flex;gap:.3rem;flex-wrap:wrap;margin:.3rem 0}
.dayBtn{padding:.3rem .5rem;font-size:.78rem}
.dayBtn.on{background:#3b82f6;color:#fff;border-color:#3b82f6}
</style></head><body>
<h1>Programming blocks</h1>
<div class="sub"><a href="/admin">&larr; station control</a> &middot; ai-radio</div>

<section>
  <div class="hd2"><h2>Blocks</h2></div>
  <div class="blocklist" id="blockList"></div>
  <div class="actions">
    <button id="btnNew" type="button">+ New block</button>
  </div>
</section>

<div id="editor" hidden>
<section>
  <div class="hd2"><h2>Edit block</h2></div>
  <label>Title</label>
  <input id="title">
  <div id="segments"></div>
  <label style="margin-top:.9rem">Add segment</label>
  <div class="addtype">
    <button class="ghost" data-add="live" type="button">+ Live</button>
    <button class="ghost" data-add="tts" type="button">+ TTS</button>
    <button class="ghost" data-add="music" type="button">+ Music</button>
  </div>
  <div class="actions">
    <button id="btnSave" type="button">Save block</button>
    <button class="danger" id="btnDelete" type="button">Delete block</button>
    <span id="saveMsg" class="sub"></span>
  </div>
</section>

<section>
  <div class="hd2"><h2>Preview</h2></div>
  <div class="actions">
    <button class="ghost" id="btnBuildPreview" type="button">Build preview</button>
    <button class="ghost" id="btnPrev" type="button">&larr; Prev</button>
    <button class="ghost" id="btnNext" type="button">Next &rarr;</button>
  </div>
  <div class="sub" id="previewMsg"></div>
  <audio id="previewAudio" controls></audio>
</section>

<section>
  <div class="hd2"><h2>Schedule</h2></div>
  <div class="actions">
    <button id="btnPlayNow" type="button">Play now</button>
    <button class="ghost" id="btnQueue" type="button">Add to playlist</button>
    <button class="danger" id="btnStop" type="button">Stop programming</button>
  </div>
  <div class="sub" id="schedMsg"></div>
</section>

<section>
  <div class="hd2"><h2>Rundown</h2></div>
  <div class="actions"><button class="ghost" id="btnMd" type="button">View rundown</button></div>
  <pre id="mdBox"></pre>
</section>
</div>

<section>
  <div class="hd2"><h2>Scheduled blocks</h2></div>
  <div class="sub">Blocks queued automatically at a set time (checked every 30s).</div>
  <div id="schedList"></div>
  <div class="actions">
    <button class="ghost" id="btnAddSched" type="button">+ Add schedule</button>
    <button id="btnSaveSched" type="button">Save schedule</button>
    <span id="schedSaveMsg" class="sub"></span>
  </div>
</section>

<audio id="shared" controls style="width:100%;margin-top:1rem"></audio>

<script>
const $=id=>document.getElementById(id);
const BASE=location.pathname.replace(/\/+$/,'');
let block=null, liveSources=[], llmBackends=[], ttsEngines=[], previewQueue=[], previewIdx=0;
let allBlocks=[], schedEntries=[];
const DAY_LABELS=['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];

// Escape before interpolating any operator/Jellyfin-sourced text into
// innerHTML (block titles, queries, prompts, track names) -- otherwise a
// value like `"><script>` breaks out of the attribute/element. Persistent,
// since this data round-trips through block.json / the Jellyfin library.
function esc(s){
  return String(s==null?'':s).replace(/[&<>"']/g,
    c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

// Single persist path: acting on a block (preview, schedule) saves the
// on-screen edits first, so what airs is what the operator sees -- not the
// last-saved server copy.
async function persistBlock(signal){
  block.title=$('title').value;
  const resp=await fetch(BASE+'/api/blocks/'+block.id,{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({title:block.title,segments:block.segments}),signal});
  if(!resp.ok) throw new Error((await resp.text())||('HTTP '+resp.status));
  block=await resp.json();
}

// Every long-running action ticks its status message with elapsed seconds
// (a stuck request looks identical to a slow one otherwise) and aborts with
// a visible "timed out" after timeoutMs rather than hanging silently.
function tickerFor(el, timeoutMs){
  const t0=Date.now();
  let label='';
  const paint=()=>{ el.textContent=label+' ('+Math.round((Date.now()-t0)/1000)+'s)'; };
  const id=setInterval(paint,1000);
  const controller=new AbortController();
  const timer=setTimeout(()=>controller.abort(),timeoutMs);
  return {
    signal:controller.signal,
    set(l){ label=l; paint(); },
    done(finalText){ clearInterval(id); clearTimeout(timer); el.textContent=finalText; },
    fail(e){
      clearInterval(id); clearTimeout(timer);
      const s=Math.round((Date.now()-t0)/1000);
      el.textContent = e.name==='AbortError' ? ('timed out after '+s+'s') : ('error: '+(e.message||e)+' (after '+s+'s)');
    },
  };
}

function segTitle(seg){
  if(seg.type==='live') return seg.params.source_id||'(pick source)';
  if(seg.type==='music') return seg.params.query||'(shuffle all)';
  if(seg.type==='tts') return seg.params.topic||'weather';
  return '';
}

async function loadBlockList(){
  allBlocks=await (await fetch(BASE+'/api/blocks')).json();
  const el=$('blockList'); el.innerHTML='';
  allBlocks.forEach(b=>{
    const d=document.createElement('div');
    d.innerHTML=`<span>${esc(b.title)} &middot; ${b.segment_count} segments &middot; ${esc(b.schedule.state)}</span><span class="sub">${esc(b.id)}</span>`;
    d.onclick=()=>openBlock(b.id);
    el.appendChild(d);
  });
  renderSchedule();  // block dropdowns depend on the current block list
}

function blockOptions(sel){
  return allBlocks.map(b=>`<option value="${esc(b.id)}" ${b.id===sel?'selected':''}>${esc(b.title)}</option>`).join('');
}

function renderSchedule(){
  const el=$('schedList'); if(!el) return; el.innerHTML='';
  schedEntries.forEach((e,i)=>{
    const d=document.createElement('div'); d.className='seg';
    const days=e.days||[];
    const dayBtns=DAY_LABELS.map((lbl,di)=>
      `<button type="button" class="ghost dayBtn${days.includes(di)?' on':''}" data-day="${di}">${lbl}</button>`).join('');
    d.innerHTML=`<div class="row">
        <div><label>Block</label><select data-sf="block_id"><option value="">(pick block)</option>${blockOptions(e.block_id)}</select></div>
        <div style="max-width:7rem"><label>Time</label><input type="time" data-sf="time" value="${esc(e.time||'09:00')}"></div>
      </div>
      <label>Days (none = daily)</label><div class="days">${dayBtns}</div>
      <div class="actions"><label style="display:inline">Enabled <input type="checkbox" data-sf="enabled" ${e.enabled!==false?'checked':''} style="width:auto"></label>
        <button class="danger" type="button" data-srem="1">Remove</button></div>`;
    d.querySelector('[data-sf="block_id"]').onchange=ev=>e.block_id=ev.target.value;
    d.querySelector('[data-sf="time"]').onchange=ev=>e.time=ev.target.value;
    d.querySelector('[data-sf="enabled"]').onchange=ev=>e.enabled=ev.target.checked;
    d.querySelectorAll('.dayBtn').forEach(b=>b.onclick=()=>{
      const di=+b.dataset.day; e.days=e.days||[];
      const at=e.days.indexOf(di);
      if(at>=0) e.days.splice(at,1); else e.days.push(di);
      b.classList.toggle('on');
    });
    d.querySelector('[data-srem]').onclick=()=>{ schedEntries.splice(i,1); renderSchedule(); };
    el.appendChild(d);
  });
}

async function loadSchedule(){
  schedEntries=(await (await fetch(BASE+'/api/schedule')).json()).entries||[];
  renderSchedule();
}
$('btnAddSched').onclick=()=>{
  schedEntries.push({id:'sch-'+Date.now(), block_id:'', time:'09:00', days:[], enabled:true});
  renderSchedule();
};
$('btnSaveSched').onclick=async()=>{
  const tick=tickerFor($('schedSaveMsg'), 20000);
  tick.set('saving...');
  try{
    const r=await (await fetch(BASE+'/api/schedule',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({entries:schedEntries}),signal:tick.signal})).json();
    schedEntries=r.entries||schedEntries;
    tick.done(schedEntries.length+' entries saved');
  }catch(e){ tick.fail(e); }
};

async function openBlock(id){
  block=await (await fetch(BASE+'/api/blocks/'+id)).json();
  $('editor').hidden=false;
  $('title').value=block.title;
  renderSegments();
  $('editor').scrollIntoView({behavior:'smooth',block:'start'});
}

function renderSegments(){
  const el=$('segments'); el.innerHTML='';
  block.segments.forEach((seg,i)=>{
    const d=document.createElement('div'); d.className='seg';
    d.innerHTML=segForm(seg,i);
    el.appendChild(d);
  });
  wireSegHandlers();
}

function segForm(seg,i){
  let body='';
  if(seg.type==='live'){
    const opts=liveSources.map(s=>`<option value="${esc(s.id)}" ${s.id===seg.params.source_id?'selected':''}>${esc(s.name)}</option>`).join('');
    body=`<label>Source</label><select data-f="source_id">${opts}</select>
      <label>Duration (s)</label><input type="number" data-f="duration_s" value="${seg.params.duration_s||300}">`;
  } else if(seg.type==='music'){
    body=`<label>Playlist name / search term (blank = shuffle all)</label><input data-f="query" value="${esc(seg.params.query||'')}">
      <label>Duration (s)</label><input type="number" data-f="duration_s" value="${seg.params.duration_s||900}">`;
  } else if(seg.type==='tts'){
    const isWeather=(seg.params.topic||'weather')==='weather';
    body=`<label>Topic</label><select data-f="topic"><option value="weather" ${isWeather?'selected':''}>weather</option><option value="freeform" ${!isWeather?'selected':''}>freeform</option></select>
      <label>Voice</label><select data-f="voice" class="voiceSelect"></select>
      <div class="wxOnly" ${!isWeather?'hidden':''}><label>Location (zip or city)</label><input data-f="location" value="${esc(seg.params.location||'')}"></div>
      <div class="ffOnly" ${isWeather?'hidden':''}>
        <label>Prompt</label><textarea data-f="prompt">${esc(seg.params.prompt||'')}</textarea>
        <div class="row">
          <div><label>LLM backend</label><select data-f="llm_backend" class="llmBackend"></select></div>
          <div><label>Model</label><select data-f="llm_model" class="llmModel"></select></div>
        </div>
      </div>
      <label>TTL before re-render (s)</label><input type="number" data-f="ttl_s" value="${seg.params.ttl_s||1800}">`;
  }
  const dotClass = seg.status==='ok' ? 'ok' : (seg.status==='error' ? 'bad' : '');
  return `<div class="hd">
      <span class="left"><span class="dot ${dotClass}" data-role="statusdot" title="${esc(seg.status||'unresolved')}"></span><span class="badge">${esc(seg.type)}</span><span class="name">${esc(segTitle(seg))}</span></span>
      <span class="move"><button class="ghost" data-act="up">&uarr;</button><button class="ghost" data-act="down">&darr;</button><button class="danger kill" data-act="remove">&times;</button></span></div>
    ${body}
    <div class="actions"><button class="ghost" data-act="test">Test</button><span class="testmsg" data-role="testmsg"></span></div>
    ${seg.type==='music'?'<div class="tracklist"></div>':''}`;
}

function setSegDot(el, state){
  // state: 'ok' | 'bad' | '' (unresolved/untested) -- attached directly to
  // the segment card it describes, and updated live by Test/edits rather
  // than only reflecting whatever was true at the last full save.
  const dot=el.querySelector('[data-role=statusdot]');
  dot.className='dot'+(state?' '+state:'');
  dot.title=state==='ok'?'ok':(state==='bad'?'error':'unresolved');
}

function wireSegHandlers(){
  document.querySelectorAll('#segments .seg').forEach((el,i)=>{
    el.querySelectorAll('[data-f]').forEach(inp=>{
      inp.onchange=()=>{ block.segments[i].params[inp.dataset.f]=inp.type==='number'?parseFloat(inp.value):inp.value;
        // editing invalidates whatever was last resolved/tested for this segment
        block.segments[i].status=undefined;
        setSegDot(el,'');
        if(inp.dataset.f==='topic') renderSegments(); };
    });
    el.querySelectorAll('[data-act]').forEach(btn=>{
      btn.onclick=()=>segAction(i,btn.dataset.act,el);
    });
    if(el.querySelector('.llmBackend')) loadLlmPickers(el, block.segments[i]);
    if(el.querySelector('.voiceSelect')) loadVoicePicker(el, block.segments[i]);
  });
}

async function loadVoicePicker(el,seg){
  if(!ttsEngines.length) ttsEngines=await (await fetch(BASE+'/api/tts_engines')).json();
  const vsel=el.querySelector('.voiceSelect');
  const voices=(ttsEngines.find(e=>e.id==='kokoro')||{}).voices||[];
  vsel.innerHTML='<option value="">(station default)</option>'
    +voices.map(v=>`<option value="${v}" ${v===seg.params.voice?'selected':''}>${v}</option>`).join('');
}

async function loadLlmPickers(el,seg){
  if(!llmBackends.length) llmBackends=await (await fetch(BASE+'/api/llm_backends')).json();
  const bsel=el.querySelector('.llmBackend'), msel=el.querySelector('.llmModel');
  bsel.innerHTML=llmBackends.map(b=>`<option value="${b.id}" ${b.id===seg.params.llm_backend?'selected':''}>${b.label}</option>`).join('');
  function fillModels(){
    const b=llmBackends.find(x=>x.id===bsel.value)||llmBackends[0];
    msel.innerHTML=(b.models||[]).map(m=>`<option value="${m}" ${m===seg.params.llm_model?'selected':''}>${m}</option>`).join('');
    // populating options doesn't fire 'change', so the visually-shown default
    // would otherwise never land in seg.params until the user manually
    // re-picks it -- write it through explicitly so Test works on first click.
    seg.params.llm_backend=bsel.value;
    seg.params.llm_model=msel.value;
  }
  bsel.onchange=fillModels; fillModels();
}

function segAction(i,act,el){
  const seg=block.segments[i];
  if(act==='remove'){ block.segments.splice(i,1); renderSegments(); return; }
  if(act==='up'&&i>0){ [block.segments[i-1],block.segments[i]]=[block.segments[i],block.segments[i-1]]; renderSegments(); return; }
  if(act==='down'&&i<block.segments.length-1){ [block.segments[i+1],block.segments[i]]=[block.segments[i],block.segments[i+1]]; renderSegments(); return; }
  if(act==='test'){ testSegment(seg,el); return; }
}

async function testSegment(seg,el){
  const msg=el.querySelector('[data-role=testmsg]');
  const btn=el.querySelector('[data-act=test]');
  const shared=$('shared');
  const isTts=seg.type==='tts';
  const tick=tickerFor(msg, isTts?90000:20000);
  btn.disabled=true;
  try{
    if(seg.type==='live'){
      tick.set('resolving stream...');
      const r=await (await fetch(BASE+'/api/live_test?source_id='+encodeURIComponent(seg.params.source_id),{signal:tick.signal})).json();
      if(r.error) throw new Error(r.error);
      shared.src=r.url; shared.play();
      seg.status='ok'; setSegDot(el,'ok');
      tick.done('playing: '+r.title);
    } else if(seg.type==='music'){
      tick.set('resolving tracks...');
      const r=await (await fetch(BASE+'/api/music_test?q='+encodeURIComponent(seg.params.query||''),{signal:tick.signal})).json();
      if(r.error) throw new Error(r.error);
      seg.status='ok'; setSegDot(el,'ok');
      tick.done(r.track_count+' tracks ('+r.title+')');
      const tl=el.querySelector('.tracklist'); tl.innerHTML='';
      r.tracks.slice(0,30).forEach(t=>{
        const d=document.createElement('div');
        d.innerHTML=`<span>${esc(t.name)}</span><button class="ghost" type="button">play</button>`;
        d.querySelector('button').onclick=()=>{shared.src=t.url; shared.play();};
        tl.appendChild(d);
      });
    } else if(seg.type==='tts'){
      const isFreeform=(seg.params.topic||'weather')==='freeform';
      tick.set(isFreeform?('generating via '+(seg.params.llm_backend||'llm')+'...'):'fetching weather...');
      const q=new URLSearchParams({topic:seg.params.topic||'weather'});
      if(seg.params.location) q.set('location',seg.params.location);
      if(seg.params.prompt) q.set('prompt',seg.params.prompt);
      if(seg.params.llm_backend) q.set('llm_backend',seg.params.llm_backend);
      if(seg.params.llm_model) q.set('llm_model',seg.params.llm_model);
      if(seg.params.voice) q.set('voice',seg.params.voice);
      const resp=await fetch(BASE+'/api/tts_test?'+q.toString(),{signal:tick.signal});
      if(!resp.ok){ throw new Error((await resp.text())||('HTTP '+resp.status)); }
      tick.set('rendering audio...');
      const blob=await resp.blob();
      shared.src=URL.createObjectURL(blob); shared.play();
      seg.status='ok'; setSegDot(el,'ok');
      tick.done('playing');
    }
  }catch(e){
    seg.status='error'; setSegDot(el,'bad');
    tick.fail(e);
  }finally{
    btn.disabled=false;
  }
}

$('btnNew').onclick=async()=>{
  const b=await (await fetch(BASE+'/api/blocks',{method:'POST',headers:{'Content-Type':'application/json'},
    body:'{}'})).json();
  await loadBlockList(); openBlock(b.id);
};

document.querySelectorAll('[data-add]').forEach(btn=>{
  btn.onclick=()=>{
    const type=btn.dataset.add;
    const defaults={
      live:{source_id:liveSources[0]?liveSources[0].id:'npr', duration_s:300},
      music:{query:'', duration_s:900},
      tts:{topic:'weather', location:'', ttl_s:1800},
    }[type];
    block.segments.push({id:'seg-'+Date.now(), type, params:defaults});
    renderSegments();
  };
});

$('btnSave').onclick=async()=>{
  const tick=tickerFor($('saveMsg'), 20000);
  tick.set('saving...');
  try{
    await persistBlock(tick.signal);
    tick.done('saved');
    await loadBlockList();
  }catch(e){ tick.fail(e); }
};

function stopAllPlayback(){
  [$('shared'),$('previewAudio')].forEach(a=>{ a.pause(); a.removeAttribute('src'); a.load(); });
  previewQueue=[]; previewIdx=0; $('previewMsg').textContent='';
}

$('btnDelete').onclick=async()=>{
  if(!confirm('Delete "'+block.title+'"? This cannot be undone.')) return;
  const tick=tickerFor($('saveMsg'), 20000);
  tick.set('deleting...');
  try{
    const resp=await fetch(BASE+'/api/blocks/'+block.id,{method:'DELETE',signal:tick.signal});
    if(!resp.ok) throw new Error((await resp.text())||('HTTP '+resp.status));
    tick.done('deleted');
    stopAllPlayback();
    $('editor').hidden=true;
    block=null;
    await loadBlockList();
  }catch(e){ tick.fail(e); }
};

$('btnBuildPreview').onclick=async()=>{
  const tick=tickerFor($('previewMsg'), 90000);
  tick.set('saving...');
  try{
    await persistBlock(tick.signal);  // preview what's on screen, not the last-saved copy
    tick.set('rendering (only stale/missing assets)...');
    const resp=await fetch(BASE+'/api/blocks/'+block.id+'/render',{method:'POST',headers:{'Content-Type':'application/json'},body:'{"force":false}',signal:tick.signal});
    if(!resp.ok) throw new Error((await resp.text())||('HTTP '+resp.status));
    block=await (await fetch(BASE+'/api/blocks/'+block.id)).json();
    renderSegments();
    tick.set('resolving preview tracks...');
    previewQueue=[];
    for(const seg of block.segments){
      const r=seg.resolved||{};
      if(seg.type==='tts'&&r.audio_path) previewQueue.push({label:'tts: '+(r.title||''), url:BASE+'/api/blocks/'+block.id+'/audio/'+seg.id});
      else if(seg.type==='live'&&r.url) previewQueue.push({label:'live: '+(r.title||''), url:r.url});
      else if(seg.type==='music'&&r.playlist_path){
        try{
          // Preview the ACTUAL rendered playlist (the URLs that will air),
          // not a fresh random music_test roll -- otherwise the preview and
          // the broadcast share little overlap. Capped at 10 for stepping.
          const tr=await (await fetch(BASE+'/api/blocks/'+block.id+'/tracks/'+seg.id)).json();
          (tr.urls||[]).slice(0,10).forEach((u,i)=>previewQueue.push({label:'music: '+(r.title||'')+' ['+(i+1)+']', url:u}));
        }catch(e){}
      }
    }
    previewIdx=0;
    tick.done(previewQueue.length+' segments ready');
    playPreview();
  }catch(e){ tick.fail(e); }
};
function playPreview(){
  if(!previewQueue.length) return;
  const item=previewQueue[previewIdx];
  const a=$('previewAudio'); a.src=item.url; a.play();
  $('previewMsg').textContent=(previewIdx+1)+'/'+previewQueue.length+' · '+item.label;
}
$('previewAudio').onended=()=>{ if(previewIdx<previewQueue.length-1){ previewIdx++; playPreview(); } };
$('btnPrev').onclick=()=>{ if(previewIdx>0){ previewIdx--; playPreview(); } };
$('btnNext').onclick=()=>{ if(previewIdx<previewQueue.length-1){ previewIdx++; playPreview(); } };

const schedBtns=['btnPlayNow','btnQueue','btnStop'];
async function schedule(mode){
  const tick=tickerFor($('schedMsg'), 90000);
  schedBtns.forEach(b=>$(b).disabled=true);  // no double-click double-spawn
  tick.set('saving...');
  try{
    await persistBlock(tick.signal);  // air what's on screen, not the last-saved copy
    tick.set('working...');
    const resp=await fetch(BASE+'/api/blocks/'+block.id+'/schedule',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({mode}),signal:tick.signal});
    const r=await resp.json();
    tick.done(r.ok?('queue: '+JSON.stringify(r.queue)):('error: '+r.error));
  }catch(e){ tick.fail(e); }
  finally{ schedBtns.forEach(b=>$(b).disabled=false); }
}
$('btnPlayNow').onclick=()=>schedule('now');
$('btnQueue').onclick=()=>schedule('queue');
$('btnStop').onclick=async()=>{
  const tick=tickerFor($('schedMsg'), 20000);
  tick.set('stopping...');
  try{
    const resp=await fetch(BASE+'/api/blocks/stop',{method:'POST',signal:tick.signal});
    if(!resp.ok) throw new Error((await resp.text())||('HTTP '+resp.status));
    tick.done('stopped, static loop resumed');
  }catch(e){ tick.fail(e); }
};

$('btnMd').onclick=async()=>{
  const r=await fetch(BASE+'/api/blocks/'+block.id+'/markdown');
  $('mdBox').textContent=await r.text();
};

(async function init(){
  liveSources=await (await fetch(BASE+'/api/live_sources')).json();
  await loadBlockList();  // populates allBlocks (schedule block dropdowns need it)
  await loadSchedule();
})();
</script>
</body></html>"""
