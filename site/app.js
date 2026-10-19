const messages = document.getElementById('messages');
const promptBox = document.getElementById('prompt');
const send = document.getElementById('send');
const todayLabel = document.getElementById('todayLabel');
const pickCount = document.getElementById('pickCount');
todayLabel.textContent = new Intl.DateTimeFormat('en-GB',{day:'2-digit',month:'short',year:'numeric'}).format(new Date()).toUpperCase();

function addMessage(text, role='assistant', picks=[]) {
  const wrap=document.createElement('div'); wrap.className=`message ${role}`;
  const avatar=document.createElement('div'); avatar.className='avatar'; avatar.textContent=role==='assistant'?'L':'Y';
  const bubble=document.createElement('div'); bubble.className='bubble';
  const p=document.createElement('p'); p.textContent=text; bubble.appendChild(p);
  picks.forEach(pick => bubble.appendChild(pickCard(pick)));
  wrap.append(avatar,bubble); messages.appendChild(wrap); messages.scrollTop=messages.scrollHeight;
}
function pickCard(p){
  const card=document.createElement('article'); card.className='pick-card';
  const likelihood=(Number(p.blended_prob)*100).toFixed(1)+'%';
  card.innerHTML=`<div class="pick-head"><div><div class="match">${esc(p.home_team)} <span class="muted">v</span> ${esc(p.away_team)}</div><div class="selection">${esc(p.display_selection||p.selection)} @ ${Number(p.odds).toFixed(2)}</div></div><span class="likelihood">${likelihood} likely</span></div><div class="pick-grid"><div class="metric"><label>CONFIDENCE</label><strong>${esc(p.confidence||'Medium')}</strong></div><div class="metric"><label>MARKET SAYS</label><strong>${(Number(p.market_prob)*100).toFixed(1)}%</strong></div><div class="metric"><label>MODEL SAYS</label><strong>${(Number(p.model_prob)*100).toFixed(1)}%</strong></div></div><div class="pick-copy"><b>Why:</b> ${esc(p.rationale||'Market and model support this outcome.')}</div><div class="pick-copy risk"><b>Risk:</b> ${esc(p.risks||'Check team news before staking.')}</div><div class="pick-copy debate"><b>Debate:</b> ${esc(p.alternatives||'Challenge the assumptions.')}</div>`;
  return card;
}
function esc(value){return String(value??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));}
async function ask(text){
  if(!text.trim()) return;
  addMessage(text,'user'); promptBox.value=''; send.disabled=true; send.textContent='…';
  try { const res=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:text})}); const data=await res.json(); pickCount.textContent=data.count??'—'; addMessage(data.reply||'I could not read the desk response.', 'assistant', data.picks||[]); }
  catch(e){ addMessage('The desk is offline. Start the local server and try again.', 'assistant'); }
  finally{send.disabled=false;send.textContent='↗';}
}
send.addEventListener('click',()=>ask(promptBox.value));
promptBox.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();ask(promptBox.value)}});
document.querySelectorAll('[data-prompt]').forEach(el=>el.addEventListener('click',()=>ask(el.dataset.prompt)));
