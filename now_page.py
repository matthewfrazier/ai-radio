#!/usr/bin/env python3
"""/now -- listen + monitor. Embeds the live Icecast stream and shows what is
airing right now plus a rich, debug-expandable view of every block and segment
as a rendered entity (resolved URLs, tracklists, the actual spoken recap/
weather text, statuses, timings, raw JSON). Same zero-framework convention."""

NOW_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ai-radio &middot; now</title>
<style>
:root{color-scheme:light dark}
body{font-family:system-ui,sans-serif;max-width:760px;margin:0 auto;padding:.9rem;line-height:1.4}
h1{font-size:1.2rem;margin:.2rem 0}
h2{font-size:.9rem;margin:0;text-transform:uppercase;letter-spacing:.02em;opacity:.6}
.sub{opacity:.7;font-size:.85rem;margin-bottom:1rem}
section{margin:0 0 1.3rem}
section>.hd2{border-bottom:1px solid #8883;padding-bottom:.4rem;margin-bottom:.6rem}
audio{width:100%;margin:.3rem 0}
select{width:100%;box-sizing:border-box;font:inherit;padding:.5rem .6rem;border:1px solid #8885;border-radius:10px;background:transparent;color:inherit}
a{color:#3b82f6}
.status{display:flex;gap:1.2rem;flex-wrap:wrap;font-size:.85rem;align-items:center}
.dot{display:inline-block;width:.6rem;height:.6rem;border-radius:50%;background:#888;margin-right:.35rem;vertical-align:middle}
.dot.ok{background:#22c55e}.dot.bad{background:#ef4444}.dot.live{background:#22c55e}
.badge{font-size:.68rem;padding:.15rem .5rem;border-radius:999px;background:#8883;margin-right:.3rem}
.badge.role{background:#3b82f633;color:#3b82f6}
.seg{border:1px solid #8884;border-radius:12px;padding:.55rem .7rem;margin-bottom:.5rem;background:rgba(128,128,128,.05)}
.seg.airing{border-color:#22c55e;background:rgba(34,197,94,.10)}
.seg .hd{display:flex;align-items:center;gap:.4rem;flex-wrap:wrap}
.seg .name{font-weight:600;overflow:hidden;text-overflow:ellipsis}
.seg .play{margin-left:auto;font:inherit;font-size:.8rem;padding:.2rem .6rem;border:1px solid #3b82f680;border-radius:999px;background:transparent;color:#3b82f6;cursor:pointer}
.seg.airing .play{border-color:#22c55e;color:#22c55e}
.seg .detail{font-size:.82rem;opacity:.9;margin-top:.35rem}
.seg .quote{border-left:3px solid #8886;padding-left:.6rem;margin:.4rem 0;font-style:italic;opacity:.85}
.tracks{font-size:.8rem;opacity:.85;margin-top:.3rem}
pre{white-space:pre-wrap;background:#8881;padding:.6rem;border-radius:8px;font-size:.72rem;max-height:16rem;overflow:auto;margin-top:.4rem}
.dbg{font-size:.75rem;cursor:pointer;color:#3b82f6;margin-top:.3rem;display:inline-block}
.now{font-size:.9rem}
.now b{font-weight:600}
button{font:inherit;padding:.4rem .9rem;border:1px solid transparent;border-radius:999px;background:#3b82f6;color:#fff;cursor:pointer;font-size:.85rem}
button.ghost{background:transparent;color:#3b82f6;border-color:#3b82f680}
button:disabled{opacity:.4;cursor:not-allowed}
.nowcard{border:1px solid #8884;border-radius:12px;padding:.7rem .8rem;background:rgba(128,128,128,.05)}
.nowcard.on{border-color:#22c55e;background:rgba(34,197,94,.08)}
.nowcard .line1{display:flex;align-items:center;gap:.4rem;flex-wrap:wrap}
.nowcard .segt{font-weight:600;font-size:1rem}
.nowcard .meta{font-size:.82rem;opacity:.8;margin-top:.35rem}
.nowcard .prog{height:.3rem;border-radius:999px;background:#8883;margin-top:.5rem;overflow:hidden}
.nowcard .prog>i{display:block;height:100%;background:#22c55e;width:0}
.segnav{display:flex;align-items:center;gap:.6rem;margin-top:.5rem}
.segnav .sub{flex:1;text-align:center;margin:0}
.row{display:flex;gap:.5rem;flex-wrap:wrap;align-items:center}
#target{flex:1;min-width:11rem}
.mb4{margin:0 0 .4rem}
.runlog{font:.72rem/1.55 ui-monospace,SFMono-Regular,Menlo,monospace;background:#8881;border-radius:8px;padding:.5rem .6rem;max-height:14rem;overflow:auto}
.runlog .lt{opacity:.55;margin-right:.5rem}
.runlog .k{color:#3b82f6}
.runlog .w{color:#f59e0b}
.nowcard.switching{border-color:#f59e0b;background:rgba(245,158,11,.10)}
</style></head><body>
<h1>ai-radio &middot; now</h1>
<div class="sub"><a href="/admin">station</a> &middot; <a href="/blocks">blocks</a> &middot; <a href="/day">24-hour day</a></div>

<section>
  <div class="hd2"><h2>Output</h2></div>
  <div class="sub mb4">Play on this device <b>or</b> cast to one speaker — one at a time.</div>
  <div class="row">
    <select id="target"></select>
    <button id="btnOut" type="button">Play</button>
    <button class="ghost" id="btnOutStop" type="button">Stop</button>
    <button class="ghost" id="btnRescan" type="button">Rescan</button>
  </div>
  <audio id="player" src="/stream" controls preload="none"></audio>
  <div class="status">
    <span><span id="sdot" class="dot"></span>Stream <span id="sstate">?</span> <span id="listeners"></span></span>
    <span id="stitle"></span>
    <span><a id="surl" href="/stream" target="_blank">open /stream</a></span>
  </div>
  <div class="sub" id="outMsg">scanning for speakers…</div>
</section>

<section>
  <div class="hd2"><h2>Now airing</h2></div>
  <div class="now" id="now">loading…</div>
  <div class="segnav">
    <button class="ghost" id="btnPrev" type="button" disabled>◀ prev segment</button>
    <span class="sub" id="navMsg"></span>
    <button class="ghost" id="btnNext" type="button" disabled>next segment ▶</button>
  </div>
  <div class="sub" id="queue"></div>
</section>

<section>
  <div class="hd2"><h2>Blocks</h2></div>
  <div class="sub mb4">Pick a block to inspect; press ▶ on any segment to cut the station over and start from there (restart &amp; scrub).</div>
  <select id="pick"></select>
  <div class="sub" id="switchMsg"></div>
  <div id="blockView" style="margin-top:.6rem"></div>
</section>

<section>
  <div class="hd2"><h2>Run log</h2></div>
  <div class="sub mb4">Recent player events — why the stream did what it did (cutovers, render/filler, idle, drain).</div>
  <div id="runlog" class="runlog">loading…</div>
</section>

<script>
const $=id=>document.getElementById(id);
const BASE=location.pathname.replace(/\/+$/,'');
let picked="", airingId="", airingIdx=-1, airingCount=0, airingStartedMs=0;
// Output is one-at-a-time: "" none, "local" this device's <audio>, or a cast
// device uuid. castUuid tracks the speaker we told to play (to stop it).
// The server persists the active cast target, so poll() can restore this state
// on a page refresh instead of forgetting it and defaulting to local.
let outputTarget="", castUuid="", castName="";
// When a cutover is in flight (▶ / prev / next), the player takes several
// seconds to render before the new segment airs. Track it so the now-card
// shows an explicit "switching → segment N" state instead of looking dead.
let switching=null; // {id, idx, since}

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

function segEntity(seg, blockId, airing, idx){
  const r=seg.resolved||{}, p=seg.params||{};
  let detail='';
  if(seg.type==='live'){
    detail=`source: ${esc(r.source_id||p.source_id)} &middot; ${esc(p.duration_s||0)}s`
      +(r.url?`<br><a href="${esc(r.url)}" target="_blank">stream url</a> &middot; ${esc(r.title||'')}`:'');
  } else if(seg.type==='music'){
    detail=`${esc(r.title||p.query||'shuffle')} &middot; ${esc(r.track_count||0)} tracks &middot; ${esc(p.duration_s||0)}s`
      +(r.tracks_head&&r.tracks_head.length?`<div class="tracks">${r.tracks_head.slice(0,8).map(esc).join(' &middot; ')}${r.tracks_head.length>8?' …':''}</div>`:'');
  } else if(seg.type==='tts'){
    detail=`topic: ${esc(p.topic||'?')}${r.duration_s?(' &middot; '+esc(Math.round(r.duration_s))+'s'):''}${r.rendered_at?(' &middot; rendered '+esc(r.rendered_at.slice(11,19))):''}`
      +(r.text?`<div class="quote">${esc(r.text)}</div>`:'')
      +(r.audio_path?`<a href="${BASE}/api/blocks/${esc(blockId)}/audio/${esc(seg.id)}" target="_blank">audio</a>`:'');
  }
  const title = r.title || p.topic || p.query || p.source_id || seg.id;
  return `<div class="seg${airing?' airing':''}">
      <div class="hd">
        <span class="dot ${statusDot(seg.status)}" title="${esc(seg.status||'unresolved')}"></span>
        ${seg.role?`<span class="badge role">${esc(seg.role)}</span>`:''}
        <span class="badge">${esc(seg.type)}</span>
        <span class="name">${esc(title)}</span>
        ${airing?'<span class="badge" style="background:#22c55e33;color:#22c55e">▶ airing</span>':''}
        <button class="play" data-play="${idx}" title="cut over &amp; start from this segment">▶ play</button>
      </div>
      <div class="detail">${detail}</div>
      ${seg.error?`<div class="detail" style="color:#ef4444">error: ${esc(seg.error)}</div>`:''}
      <span class="dbg" data-dbg>debug ⌄</span>
      <pre hidden>${esc(JSON.stringify(seg,null,2))}</pre>
    </div>`;
}

async function loadBlock(id){
  if(!id){ $('blockView').innerHTML=''; return; }
  let b;
  try{ b=await (await fetch(BASE+'/api/blocks/'+id)).json(); }
  catch(e){ $('blockView').textContent='load failed'; return; }
  const head=`<div class="sub">${esc(b.title)} &middot; ${esc(b.id)} &middot; ${b.segments.length} segments &middot; ${esc(b.schedule?b.schedule.state:'')}</div>`;
  const airing = (b.id===airingId);
  $('blockView').innerHTML = head + b.segments.map((s,i)=>segEntity(s, b.id, airing && i===airingIdx, i)).join('');
  $('blockView').querySelectorAll('[data-dbg]').forEach(el=>{
    el.onclick=()=>{const pre=el.nextElementSibling; pre.hidden=!pre.hidden; el.textContent=pre.hidden?'debug ⌄':'debug ⌃';};
  });
  $('blockView').querySelectorAll('[data-play]').forEach(el=>{
    el.onclick=()=>playFrom(b.id, parseInt(el.dataset.play,10));
  });
}

async function loadPicker(){
  const list=await (await fetch(BASE+'/api/blocks')).json();
  const sel=$('pick'); const prev=sel.value;
  sel.innerHTML='<option value="">— pick a block —</option>'
    + list.map(b=>`<option value="${esc(b.id)}">${esc(b.title)} (${b.segment_count} seg &middot; ${esc(b.schedule.state)})</option>`).join('');
  if(prev) sel.value=prev;
}
// Picking a block only INSPECTS it now -- the actual cutover is per-segment
// via the ▶ buttons (playFrom). The poll sets the dropdown value
// programmatically, which does not fire onchange, so auto-reflecting the
// airing block never triggers a load loop.
function inspect(id){ picked=id; loadBlock(id); }
$('pick').onchange=()=>inspect($('pick').value);

// Cut the station over to block `id` starting at segment `idx` (restart/scrub).
// The player keeps the Icecast source fed with a spoken filler across the
// air-time render, so a cast stays connected through the switch.
async function playFrom(id, idx){
  // Reflect the intermediate state immediately -- the cutover renders for a
  // few seconds before the new segment airs, so without this the UI looks
  // like the button did nothing.
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
  // Only the LOCAL player needs to reconnect to the freshly-switched stream
  // (cache-buster forces a new connection). A cast is independent and rides
  // through the render on the filler, so leave it alone -- reconnecting local
  // audio while casting is what used to yank output back to this device.
  if(outputTarget==='local'){
    const a=$('player');
    setTimeout(()=>{ a.src='/stream?ts='+Date.now(); a.load(); a.play().catch(()=>{}); }, 5000);
  }
}

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

function renderNow(nowd){
  const card=$('now'), st=nowd.state||{}, live=(nowd.stream||{}).live;
  // Clear the switching state once the target segment is actually airing (or
  // after a 35s guard, in case the target errored/was skipped).
  if(switching){
    const arrived = nowd.player_active && st.block_id===switching.id && (st.segment_index??-1)===switching.idx;
    if(arrived || (Date.now()-switching.since)>35000) switching=null;
    else { paintSwitching(); return; }
  }
  if(!(nowd.player_active && st.block_id)){
    // No block airing -- say exactly which source is holding the stream.
    let msg;
    if(nowd.player_active && st.idle)
      msg='Idle music — the player is holding the stream between blocks. Queue a block or press ▶ on a segment.';
    else if(nowd.player_active)
      msg='Player running, starting up…';
    else if(live)
      msg='Static fallback loop — no programmed block is airing.';
    else
      msg='Stream offline — no source is connected.';
    card.className='nowcard';
    card.innerHTML='<span class="sub">'+esc(msg)+'</span>';
    $('btnPrev').disabled=true; $('btnNext').disabled=true; $('navMsg').textContent='';
    return;
  }
  const idx=st.segment_index??0, n=st.segment_count||0;
  card.className='nowcard on';
  card.innerHTML=`<div class="line1">
      ${st.segment_role?('<span class="badge role">'+esc(st.segment_role)+'</span>'):''}
      <span class="badge">${esc(st.segment_type||'')}</span>
      <span class="segt">${esc(st.segment_title||st.segment_id||'')}</span>
    </div>
    <div class="meta"><b>${esc(st.title||st.block_id)}</b> &middot; segment ${idx+1} of ${n} &middot; <span id="elapsed">${fmtElapsed(airingStartedMs)}</span> elapsed</div>
    <div class="prog"><i style="width:${n?Math.round((idx+1)/n*100):0}%"></i></div>`;
  $('btnPrev').disabled = !(idx>0);
  $('btnNext').disabled = !(n && idx<n-1);
  $('navMsg').textContent = 'segment '+(idx+1)+' / '+n;
}

// Reconcile UI output state with the server's authoritative cast target (set
// when a cast succeeds, cleared on stop). On refresh this restores "casting to
// X" instead of resetting to local; if a cast ended elsewhere it drops back to
// no-selection rather than falsely showing a speaker.
function reconcileOutput(cast){
  const sel=$('target');
  if(cast && cast.uuid){
    castUuid=cast.uuid; castName=cast.name||cast.uuid;
    if(outputTarget!==cast.uuid){
      outputTarget=cast.uuid;
      $('player').pause();
      if(sel && [...sel.options].some(o=>o.value===cast.uuid)) sel.value=cast.uuid;
      $('outMsg').textContent='casting to '+castName;
    }
  } else {
    castUuid='';
    if(outputTarget && outputTarget!=='local'){
      outputTarget=''; castName='';
      $('outMsg').textContent='not playing — choose an output';
    }
  }
}

async function poll(){
  try{
    const n=await (await fetch(BASE+'/api/now')).json();
    reconcileOutput(n.cast);
    const s=n.stream||{};
    $('sstate').textContent=s.live?'live':'offline';
    $('sdot').className='dot '+(s.live?'live':'bad');
    $('listeners').textContent=s.live?('· '+(s.listeners||0)+' listening'):'';
    $('stitle').textContent=s.title?('“'+s.title+'”'):'';
    const st=n.state||{};
    const prevIdx=airingIdx;
    airingId=n.player_active?(st.block_id||''):'';
    airingIdx=n.player_active&&st.segment_index!=null?st.segment_index:-1;
    airingCount=st.segment_count||0;
    // reset the elapsed anchor when the airing segment changes
    if(airingIdx!==prevIdx || !airingStartedMs){
      airingStartedMs = st.started_at?Date.parse(st.started_at):(n.player_active?Date.now():0);
    }
    if(!n.player_active || !st.block_id) airingStartedMs=0;
    renderNow(n);
    $('queue').textContent = (n.queue&&n.queue.length)?('Queue: '+n.queue.join(', ')):'Queue empty.';
    // if a block is airing and nothing is picked, show it
    if(airingId && !picked){ $('pick').value=airingId; picked=airingId; loadBlock(picked); }
    else if(picked===airingId) loadBlock(picked); // refresh airing highlight
  }catch(e){}
}

$('btnPrev').onclick=()=>{ if(airingId && airingIdx>0) playFrom(airingId, airingIdx-1); };
$('btnNext').onclick=()=>{ if(airingId && airingCount && airingIdx<airingCount-1) playFrom(airingId, airingIdx+1); };

// --- Run log (recent player events) ---
function logClass(m){
  if(/-> (PLAYING|BUFFERING)/.test(m)) return 'k';                       // cast ok
  if(/PAUSED|IDLE|failed|error|could not|not allowed/i.test(m)) return 'w'; // trouble
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
async function loadTargets(){
  const tick=tickerFor($('outMsg'),20000); tick.set('scanning for speakers');
  try{
    const list=await (await fetch(BASE+'/api/cast/devices',{signal:tick.signal})).json();
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
    if(casting) tick.done('casting to '+castName);
    else tick.done(list.length+' speakers + this device');
  }catch(e){ tick.fail(e); }
}

async function stopCast(uuid){
  if(!uuid) return;
  try{ await fetch(BASE+'/api/cast/stop',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({uuid})}); }catch(e){}
}

// Switch output to `v` ("local" or a cast uuid), stopping whatever was playing
// before -- only one destination is ever active.
async function applyTarget(v){
  const a=$('player');
  if(v==='local'){
    if(castUuid){ stopCast(castUuid); castUuid=''; }
    outputTarget='local';
    a.src='/stream?ts='+Date.now(); a.load(); a.play().catch(()=>{});
    $('outMsg').textContent='playing on this device';
    return;
  }
  // casting: stop local audio + any previous speaker, then cast to v
  a.pause();
  if(castUuid && castUuid!==v){ stopCast(castUuid); }
  const tick=tickerFor($('outMsg'),40000); tick.set('casting');
  try{
    const r=await (await fetch(BASE+'/api/cast/start',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({uuid:v}),signal:tick.signal})).json();
    if(r.error) throw new Error(r.error);
    if(r.state==='PLAYING'||r.state==='BUFFERING'){ outputTarget=v; castUuid=v;
      tick.done('casting to '+esc(r.name)+' ('+r.state.toLowerCase()+')'); }
    else { tick.done('could not cast'+(r.hint?': '+esc(r.hint):' (state '+esc(r.state||'?')+')')); }
  }catch(e){ tick.fail(e); }
}

$('btnOut').onclick=()=>applyTarget($('target').value);
$('btnOutStop').onclick=async()=>{
  const a=$('player'); a.pause();
  if(castUuid){ const tick=tickerFor($('outMsg'),30000); tick.set('stopping'); await stopCast(castUuid); castUuid=''; tick.done('stopped'); }
  else { $('outMsg').textContent='stopped'; }
  outputTarget='';
};
$('btnRescan').onclick=loadTargets;
// The native <audio> play control is also an output surface: starting local
// playback must stop any cast so only one destination is ever live.
$('player').addEventListener('play',()=>{
  if(castUuid){ stopCast(castUuid); castUuid=''; $('outMsg').textContent='playing on this device'; }
  outputTarget='local'; $('target').value='local';
});

(async function init(){
  await loadPicker();
  await poll();
  loadTargets();  // slow (~8s discovery); runs in the background
  loadLog();
  setInterval(poll, 4000);
  setInterval(tickElapsed, 1000);
  setInterval(loadLog, 5000);
  setInterval(loadPicker, 20000);
})();
</script>
</body></html>"""
