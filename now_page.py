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
.seg .detail{font-size:.82rem;opacity:.9;margin-top:.35rem}
.seg .quote{border-left:3px solid #8886;padding-left:.6rem;margin:.4rem 0;font-style:italic;opacity:.85}
.tracks{font-size:.8rem;opacity:.85;margin-top:.3rem}
pre{white-space:pre-wrap;background:#8881;padding:.6rem;border-radius:8px;font-size:.72rem;max-height:16rem;overflow:auto;margin-top:.4rem}
.dbg{font-size:.75rem;cursor:pointer;color:#3b82f6;margin-top:.3rem;display:inline-block}
.now{font-size:.9rem}
.now b{font-weight:600}
</style></head><body>
<h1>ai-radio &middot; now</h1>
<div class="sub"><a href="/admin">station</a> &middot; <a href="/blocks">blocks</a> &middot; <a href="/day">24-hour day</a></div>

<section>
  <div class="hd2"><h2>Listen</h2></div>
  <audio id="player" src="/stream" controls preload="none"></audio>
  <div class="status">
    <span><span id="sdot" class="dot"></span>Stream <span id="sstate">?</span> <span id="listeners"></span></span>
    <span id="stitle"></span>
    <span><a id="surl" href="/stream" target="_blank">open /stream</a></span>
  </div>
</section>

<section>
  <div class="hd2"><h2>Cast to a speaker</h2></div>
  <div class="row" style="display:flex;gap:.5rem;flex-wrap:wrap;align-items:center">
    <select id="castPick" style="flex:1;min-width:10rem"></select>
    <button id="btnCast" type="button">Cast</button>
    <button class="ghost" id="btnCastStop" type="button">Stop</button>
    <button class="ghost" id="btnCastRescan" type="button">Rescan</button>
  </div>
  <div class="sub" id="castMsg">scanning for devices…</div>
</section>

<section>
  <div class="hd2"><h2>Now airing</h2></div>
  <div class="now" id="now">loading…</div>
  <div class="sub" id="queue"></div>
</section>

<section>
  <div class="hd2"><h2>Switch block</h2></div>
  <div class="sub" style="margin:0 0 .4rem">Selecting a block cuts the station over to it now.</div>
  <select id="pick"></select>
  <div id="blockView" style="margin-top:.6rem"></div>
</section>

<script>
const $=id=>document.getElementById(id);
const BASE=location.pathname.replace(/\/+$/,'');
let picked="", airingId="", airingIdx=-1;

function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}

function statusDot(st){return st==='ok'?'ok':(st==='error'?'bad':'');}

function segEntity(seg, blockId, airing){
  const r=seg.resolved||{}, p=seg.params||{};
  let detail='';
  if(seg.type==='live'){
    detail=`source: ${esc(r.source_id||p.source_id)} &middot; ${esc(p.duration_s||0)}s`
      +(r.url?`<br><a href="${esc(r.url)}" target="_blank">stream url</a> &middot; ${esc(r.title||'')}`:'');
  } else if(seg.type==='music'){
    detail=`${esc(r.title||p.query||'shuffle')} &middot; ${esc(r.track_count||0)} tracks &middot; ${esc(p.duration_s||0)}s`
      +(r.tracks_head&&r.tracks_head.length?`<div class="tracks">${esc(r.tracks_head.slice(0,8).join(' &middot; '))}${r.tracks_head.length>8?' …':''}</div>`:'');
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
  $('blockView').innerHTML = head + b.segments.map((s,i)=>segEntity(s, b.id, airing && i===airingIdx)).join('');
  $('blockView').querySelectorAll('[data-dbg]').forEach(el=>{
    el.onclick=()=>{const pre=el.nextElementSibling; pre.hidden=!pre.hidden; el.textContent=pre.hidden?'debug ⌄':'debug ⌃';};
  });
}

async function loadPicker(){
  const list=await (await fetch(BASE+'/api/blocks')).json();
  const sel=$('pick'); const prev=sel.value;
  sel.innerHTML='<option value="">— pick a block —</option>'
    + list.map(b=>`<option value="${esc(b.id)}">${esc(b.title)} (${b.segment_count} seg &middot; ${esc(b.schedule.state)})</option>`).join('');
  if(prev) sel.value=prev;
}
// Selecting a block SWITCHES the station to it (play-now) and reconnects the
// player to the newly-switched live source. Only fires on a real user pick --
// the poll sets the dropdown's value programmatically, which does not trigger
// onchange, so auto-reflecting the airing block never causes a cutover.
async function switchTo(id){
  picked=id;
  if(!id){ loadBlock(''); return; }
  loadBlock(id);
  if(id===airingId) return;  // already airing -> just inspect, don't re-cut
  $('now').innerHTML='<span class="sub">switching to <b>'+esc(id)+'</b>… (the new hour renders for a few seconds before audio resumes)</span>';
  // fire-and-forget with prerender:false so the POST returns immediately; the
  // player does the single air-time render and the poll shows it airing.
  fetch(BASE+'/api/blocks/'+id+'/schedule',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:'now',prerender:false})})
    .catch(e=>{ $('now').innerHTML='<span class="sub">switch failed: '+esc(e)+'</span>'; });
  // reconnect the audio to the switched stream (cache-buster forces a fresh
  // connection so it picks up the new source once its sink is airing).
  const a=$('player');
  setTimeout(()=>{ a.src='/stream?ts='+Date.now(); a.load(); a.play().catch(()=>{}); }, 5000);
}
$('pick').onchange=()=>switchTo($('pick').value);

async function poll(){
  try{
    const n=await (await fetch(BASE+'/api/now')).json();
    const s=n.stream||{};
    $('sstate').textContent=s.live?'live':'offline';
    $('sdot').className='dot '+(s.live?'live':'bad');
    $('listeners').textContent=s.live?('· '+(s.listeners||0)+' listening'):'';
    $('stitle').textContent=s.title?('“'+s.title+'”'):'';
    const st=n.state||{};
    airingId=n.player_active?(st.block_id||''):'';
    airingIdx=n.player_active&&st.segment_index!=null?st.segment_index:-1;
    if(n.player_active && st.block_id){
      $('now').innerHTML=`<b>${esc(st.title||st.block_id)}</b> — segment ${(st.segment_index??0)+1}/${st.segment_count||'?'}: `
        +`${st.segment_role?('<span class="badge role">'+esc(st.segment_role)+'</span>'):''}<span class="badge">${esc(st.segment_type||'')}</span> ${esc(st.segment_title||'')}`;
    } else {
      $('now').innerHTML='<span class="sub">No programmed block airing — the static music loop is on.</span>';
    }
    $('queue').textContent = (n.queue&&n.queue.length)?('Queue: '+n.queue.join(', ')):'Queue empty.';
    // if a block is airing and nothing is picked, show it
    if(airingId && !picked){ $('pick').value=airingId; picked=airingId; loadBlock(picked); }
    else if(picked===airingId) loadBlock(picked); // refresh airing highlight
  }catch(e){}
}

// --- Cast ---
async function loadCastDevices(){
  const tick=tickerFor($('castMsg'),20000); tick.set('scanning for devices');
  try{
    const list=await (await fetch(BASE+'/api/cast/devices')).json();
    if(list.error) throw new Error(list.error);
    const sel=$('castPick'); const prev=sel.value; sel.innerHTML='';
    list.forEach(d=>{
      const o=document.createElement('option');
      o.value=d.uuid;
      o.textContent=d.name+' ('+(d.type==='group'?'group':d.type)+')';
      sel.appendChild(o);
    });
    if(prev) sel.value=prev;
    tick.done(list.length+' devices/groups');
  }catch(e){ tick.fail(e); }
}
$('btnCast').onclick=async()=>{
  const uuid=$('castPick').value; if(!uuid) return;
  const tick=tickerFor($('castMsg'),40000); tick.set('casting');
  try{
    const r=await (await fetch(BASE+'/api/cast/start',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({uuid}),signal:tick.signal})).json();
    if(r.error) throw new Error(r.error);
    if(r.state==='PLAYING'||r.state==='BUFFERING') tick.done('casting to '+esc(r.name)+' ('+r.state.toLowerCase()+')');
    else tick.done('could not cast'+(r.hint?': '+esc(r.hint):' (state '+esc(r.state||'?')+')'));
  }catch(e){ tick.fail(e); }
};
$('btnCastStop').onclick=async()=>{
  const uuid=$('castPick').value; if(!uuid) return;
  const tick=tickerFor($('castMsg'),30000); tick.set('stopping');
  try{
    await fetch(BASE+'/api/cast/stop',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({uuid}),signal:tick.signal});
    tick.done('stopped');
  }catch(e){ tick.fail(e); }
};
$('btnCastRescan').onclick=loadCastDevices;

(async function init(){
  await loadPicker();
  await poll();
  loadCastDevices();  // slow (~8s discovery); runs in the background
  setInterval(poll, 4000);
  setInterval(loadPicker, 20000);
})();
</script>
</body></html>"""
