#!/usr/bin/env python3
"""24-hour day programming UI, served at /day (sibling to /blocks, same
zero-framework inline-HTML/fetch convention). Generate a day, edit each hour's
music/weather/factoid by role without hand-building segments, bulk-edit, and
deep-link into /blocks for full per-segment editing. Wrapped in the shared
web.page shell so it inherits the universal design system + nav + error banner."""

import web

CSS = """
.row>div{flex:1;min-width:8rem}
.row .noflex{flex:0 0 auto}
.actions{display:flex;gap:var(--s2);flex-wrap:wrap;align-items:center;margin-top:var(--s2)}
.hour{border:1px solid var(--border);border-radius:var(--r-md);padding:var(--s2) var(--s3);margin-bottom:var(--s2);background:var(--surface)}
.hour .top{display:flex;justify-content:space-between;align-items:center;gap:var(--s2);cursor:pointer}
.hour .hr{font-weight:var(--fw-med);min-width:3.2rem}
.hour .meta{flex:1;font-size:var(--fs-sm);color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.hour .edit{margin-top:var(--s2)}
.hour.empty{opacity:.5}
.dot.gen{background:var(--success)}
"""

BODY = """
<section>
  <div class="hd2"><h2>Day</h2></div>
  <div class="row">
    <div><label>Date</label><input type="date" id="date"></div>
    <div class="noflex"><button id="btnGen" type="button">Generate day</button></div>
    <div class="noflex"><button class="ghost" id="btnReload" type="button">Reload</button></div>
    <div class="noflex"><button class="danger" id="btnDelete" type="button">Delete day</button></div>
  </div>
  <div class="sub" id="dayMsg"></div>
</section>

<section>
  <div class="hd2"><h2>Bulk edit</h2></div>
  <div class="row">
    <div><label>Weather location &rarr; all hours</label><input id="bulkLoc" placeholder="zip or city"></div>
    <div class="noflex"><button class="ghost" id="btnBulkLoc" type="button">Apply to all</button></div>
  </div>
  <div class="sub" id="bulkMsg"></div>
</section>

<section>
  <div class="hd2"><h2>Hours</h2></div>
  <div id="hours"></div>
</section>
"""

JS = r"""
const $=id=>document.getElementById(id);
const BASE=location.pathname.replace(/\/+$/,'');
let curDate="", summary=null;

function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function fmtDur(s){const m=Math.round((s||0)/60);return m+'m';}
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

async function loadDay(){
  curDate=$('date').value;
  if(!curDate) return;
  summary=await (await fetch(BASE+'/api/day/'+curDate)).json();
  renderHours();
}

function renderHours(){
  const el=$('hours');el.innerHTML='';
  (summary?summary.hours:[]).forEach(h=>{
    const d=document.createElement('div');
    d.className='hour'+(h.generated?'':' empty');
    if(!h.generated){
      d.innerHTML=`<div class="top"><span class="hr">${String(h.hour).padStart(2,'0')}:00</span>`
        +`<span class="meta">not generated</span></div>`;
      el.appendChild(d);return;
    }
    d.innerHTML=`<div class="top">
        <span class="hr">${String(h.hour).padStart(2,'0')}:00</span>
        <span class="meta">${esc((h.music||[]).filter(Boolean).join(' / ')||'shuffle')} &middot; `
        +`${esc((h.news||[]).join(', '))} &middot; ${fmtDur(h.est_duration_s)}</span>
        <span class="dot ${h.generated?'gen':''}" title="${esc(h.state||'')}"></span></div>
      <div class="edit" hidden>
        <div class="row">
          <div><label>Music 1</label><input data-f="m1" value="${esc((h.music||[])[0]||'')}"></div>
          <div><label>Music 2</label><input data-f="m2" value="${esc((h.music||[])[1]||'')}"></div>
        </div>
        <div class="row">
          <div><label>Weather location</label><input data-f="loc" value="${esc(h.weather_location||'')}"></div>
          <div><label>Factoid seed (optional)</label><input data-f="seed" placeholder="e.g. 1970s soul"></div>
        </div>
        <div class="actions">
          <button data-a="save" type="button">Save hour</button>
          <a href="${BASE.replace(/\/day$/,'')}/blocks" title="deep edit in blocks">Edit segments &rarr;</a>
          <span class="sub" data-role="msg"></span>
        </div>
      </div>`;
    const top=d.querySelector('.top'), edit=d.querySelector('.edit');
    top.onclick=()=>{edit.hidden=!edit.hidden;};
    d.querySelector('[data-a="save"]').onclick=()=>saveHour(h.hour,d);
    el.appendChild(d);
  });
}

async function saveHour(hour,d){
  const msg=d.querySelector('[data-role="msg"]');
  const tick=tickerFor(msg,20000);tick.set('saving...');
  const patch={
    music:[d.querySelector('[data-f="m1"]').value, d.querySelector('[data-f="m2"]').value],
    weather_location:d.querySelector('[data-f="loc"]').value,
  };
  const seed=d.querySelector('[data-f="seed"]').value;
  if(seed) patch.factoid_seed=seed;
  try{
    const r=await fetch(BASE+'/api/day/'+curDate+'/hour/'+hour,{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify(patch),signal:tick.signal});
    if(!r.ok) throw new Error((await r.text())||('HTTP '+r.status));
    tick.done('saved');
    await loadDay();
  }catch(e){tick.fail(e);}
}

$('btnGen').onclick=async()=>{
  const tick=tickerFor($('dayMsg'),60000);tick.set('generating 24 hours...');
  try{
    const r=await fetch(BASE+'/api/day/'+$('date').value+'/generate',{method:'POST',
      headers:{'Content-Type':'application/json'},body:'{"template":"standard_hour"}',signal:tick.signal});
    const j=await r.json();
    tick.done((j.blocks?j.blocks.length:0)+' hours generated'+(j.warnings&&j.warnings.length?(' ('+j.warnings.join('; ')+')'):''));
    await loadDay();
  }catch(e){tick.fail(e);}
};
$('btnReload').onclick=loadDay;
$('btnDelete').onclick=async()=>{
  if(!confirm('Delete the whole day '+$('date').value+'?')) return;
  const tick=tickerFor($('dayMsg'),30000);tick.set('deleting...');
  try{
    const r=await (await fetch(BASE+'/api/day/'+$('date').value,{method:'DELETE',signal:tick.signal})).json();
    tick.done((r.removed?r.removed.length:0)+' hours removed');
    await loadDay();
  }catch(e){tick.fail(e);}
};
$('btnBulkLoc').onclick=async()=>{
  const tick=tickerFor($('bulkMsg'),30000);tick.set('applying...');
  try{
    const r=await (await fetch(BASE+'/api/day/'+curDate+'/bulk',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({field:'weather_location',value:$('bulkLoc').value}),signal:tick.signal})).json();
    tick.done((r.changed?r.changed.length:0)+' hours updated');
    await loadDay();
  }catch(e){tick.fail(e);}
};

(function init(){
  $('date').value=new Date().toISOString().slice(0,10);
  loadDay();
})();
"""

DAY_PAGE = web.page("day", "day", BODY, css=CSS, js=JS)
