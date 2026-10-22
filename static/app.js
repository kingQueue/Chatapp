'use strict';
const $ = id => document.getElementById(id);
let state = {characters: [], chats: [], settings: {}}, activeChat = null, editingId = null, busy = false, toastTimer, editorImage='', imageLoading=false, imageSequence=0, networkEnabled=false, selectedGroup=[], modelLoadSequence=0;
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const imageMarkup = c => c.image_data?.startsWith('data:image/jpeg;base64,') ? `<img src="${esc(c.image_data)}" alt="">` : esc(c.avatar);
const avatar = (c, size='') => `<div class="avatar ${esc(c.color)} ${size}" aria-hidden="true">${imageMarkup(c)}</div>`;
const speech = new RoomSpeech(window.speechSynthesis, window.SpeechSynthesisUtterance, status => {
  $('speech-player').hidden=['stopped','error'].includes(status.state);
  $('speech-status').textContent=status.state==='paused' ? 'Playback paused' : `Reading ${status.name || 'character'}’s reply…`;
  $('pause-speech').textContent=status.state==='paused' ? 'Resume' : 'Pause';
  $('voice-preview-status').textContent=['loading','speaking'].includes(status.state) ? 'Playing voice preview…' : status.state==='paused' ? 'Playback paused.' : '';
  if(status.state==='error')toast(status.message);
});
const tags = c => c.tags.map(t => `<span class="tag">${esc(t)}</span>`).join('');
function toast(message) { const target=document.querySelector('dialog[open]')||document.body;target.append($('toast'));$('toast').textContent = message; $('toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => $('toast').hidden = true, 5000); }
function action(fn) { return (...args) => { try { return Promise.resolve(fn(...args)).catch(e => toast(e.message)); } catch(e) { toast(e.message); } }; }
async function api(path, data) {
  const res = await fetch(path, data === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json','X-Character-Room':'1'},body:JSON.stringify(data)});
  const result = await res.json();
  if (!res.ok) throw new Error(result.error || 'The request failed.');
  return result;
}
function canLeave() { if (busy) { toast('Let the character finish replying first.'); return false; } return true; }
async function loadState() { state = await api('/api/state'); renderLibrary(); renderRecent(); }
function currentCharacter() { return state.characters.find(c => c.id === activeChat?.character_id); }
function chatIdentity(chat=activeChat){
  if(chat?.kind==='group')return {name:chat.title,subtitle:(chat.member_ids||[]).map(id=>state.characters.find(c=>c.id===id)?.name||'Character').join(' · '),avatar:'◉',color:'blue',tags:[]};
  return state.characters.find(c=>c.id===chat?.character_id);
}
function messageCharacter(message){return state.characters.find(c=>c.id===message.character_id)||{...(currentCharacter()||{}),name:message.speaker_name||currentCharacter()?.name||'Character'};}
function groupProfile(){return `<div class="group-profile-intro"><div class="avatar blue">◉</div><h2>Your team</h2><p class="subtitle">Each member builds on the shared conversation.</p></div>`+activeChat.member_ids.map((id,index)=>{const c=state.characters.find(c=>c.id===id);return c?`<section class="group-member">${avatar(c,'small')}<div><h3>${index+1}. ${esc(c.name)}</h3><p class="model-badge">${esc(c.model||state.settings.model)}${c.model?'':' · default'}</p><p class="help">${esc(c.specialty||c.subtitle)}</p><button class="text-button" data-member-edit="${c.id}">Edit ${esc(c.name)}</button></div></section>`:'';}).join('');}

function renderLibrary() {
  $('character-count').textContent = state.characters.length;
  $('collection-count').textContent = state.characters.length;
  const query = $('search').value.toLowerCase().trim();
  const characters = state.characters.filter(c => [c.name,c.subtitle,...c.tags].join(' ').toLowerCase().includes(query));
  $('character-grid').innerHTML = characters.map(c => `<article class="character-card ${esc(c.color)}"><div class="card-art">${avatar(c)}</div><div class="card-body"><div class="card-title"><h3>${esc(c.name)}</h3><button class="card-edit" data-edit="${c.id}" aria-label="Edit ${esc(c.name)}">✎</button></div><p class="card-subtitle">${esc(c.subtitle || 'A story waiting to happen')}</p><div class="tags">${tags(c)}</div><p class="card-description">${esc(c.background)}</p><button class="card-chat" data-chat="${c.id}"><span>${state.chats.some(chat => chat.kind!=='group' && chat.character_id === c.id) ? 'Continue conversation' : 'Start a conversation'}</span><span>↗</span></button></div></article>`).join('') + `<button class="create-card" id="grid-create"><span>＋</span><strong>${query && !characters.length ? 'No matches. Create someone new?' : 'Someone only you can imagine'}</strong><small>Give them a story.<br>Let the conversation begin.</small></button>`;
  document.querySelectorAll('[data-edit]').forEach(b => b.onclick = () => openEditor(b.dataset.edit));
  document.querySelectorAll('[data-chat]').forEach(b => b.onclick = action(() => openCharacter(b.dataset.chat)));
  $('grid-create').onclick = () => openEditor();
  const groups=state.chats.filter(chat=>chat.kind==='group');$('saved-groups').hidden=!groups.length;
  $('group-list').innerHTML=groups.map(chat=>`<button class="saved-group" data-open-group="${chat.id}"><span class="avatar blue tiny">◉</span><span><strong>${esc(chat.title)}</strong><small>${esc(chatIdentity(chat).subtitle)}${chat.pending_round?' · unfinished round':''}</small></span><span>↗</span></button>`).join('');
  document.querySelectorAll('[data-open-group]').forEach(button=>button.onclick=action(()=>openChat(button.dataset.openGroup)));

}
function renderRecent() {
  const chats = state.chats.slice(0,30);
  $('recent-list').innerHTML = chats.length ? chats.map(chat => {
    const c = chatIdentity(chat);
    return c ? `<button class="recent-item ${activeChat?.id === chat.id ? 'selected' : ''}" data-recent="${chat.id}">${avatar(c,'tiny')}<span class="recent-copy"><strong>${esc(c.name)}</strong><small>${esc(chat.kind==='group' ? c.subtitle : chat.title)}</small></span></button>` : '';
  }).join('') : '<p class="empty-recent">Your conversations will find a home here.</p>';
  document.querySelectorAll('[data-recent]').forEach(b => b.onclick = action(() => openChat(b.dataset.recent)));
}
function showLibrary() {
  if (!canLeave()) return;
  speech.stop();
  $('library').hidden = false; $('chat-view').hidden = true;
  activeChat = null;
  localStorage.removeItem('character-room-active-chat');
  renderRecent();
}
async function openCharacter(id, forceNew=false) {
  if (!canLeave()) return;
  const latest = state.chats.find(c => c.kind!=='group' && c.character_id === id);
  const chatId = !forceNew && latest ? latest.id : (await api('/api/chats', {character_id:id})).id;
  await loadState();
  await openChat(chatId);
}
async function openChat(id) {
  if (!canLeave()) return;
  speech.stop();
  activeChat = await api('/api/chats/' + id);
  localStorage.setItem('character-room-active-chat', id);
  $('library').hidden = true; $('chat-view').hidden = false;
  renderChat(); renderRecent();
  $('message-input').focus();
}
function renderChat() {
  const c = chatIdentity(); if (!c) return showLibrary();
  const group=activeChat.kind==='group';
  $('chat-name').textContent = c.name; $('chat-subtitle').textContent = c.subtitle;
  $('chat-title').textContent = activeChat.title;
  $('chat-avatar').className = 'avatar small ' + c.color; $('chat-avatar').innerHTML = imageMarkup(c);
  $('mobile-chat-picker').innerHTML=state.chats.map(chat=>`<option value="${chat.id}">${esc(chatIdentity(chat)?.name)} · ${esc(chat.title)}</option>`).join('');
  $('mobile-chat-picker').value=activeChat.id;
  $('message-input').placeholder = group?'Give the team a task or respond…':`Message ${c.name}…`;
  $('profile-button').textContent=group?'Team details':'Character details';
  $('edit-character').hidden=group;
  $('continue-group').hidden=!group;
  $('continue-group').textContent=activeChat.messages.some(m=>m.role==='user')?'↻ Continue round':'▶ Start round';
  $('continue-group').disabled=!!activeChat.pending_round;
  $('memory-label').textContent=group?'Shared task & memory':'Pinned memory';
  $('memory-help').textContent=group?'Goals, requirements, and facts every member sees on each turn.':'Facts and preferences this character should always remember in this conversation.';
  $('profile-content').innerHTML = group ? groupProfile() : `${avatar(c)}<h2>${esc(c.name)}</h2><p class="subtitle">${esc(c.subtitle)}</p><div class="tags">${tags(c)}</div><h3>Their story</h3><p class="bio">${esc(c.background)}</p><p class="model-badge">${esc(c.model||state.settings.model)}${c.model?'':' · default'}</p>${c.specialty?`<h3>Task specialty</h3><p class="bio">${esc(c.specialty)}</p>`:''}${c.style ? `<h3>Their voice</h3><p class="bio">${esc(c.style)}</p>` : ''}${c.scenario ? `<h3>The scene</h3><p class="bio">${esc(c.scenario)}</p>` : ''}`;
  document.querySelectorAll('[data-member-edit]').forEach(b=>b.onclick=()=>openEditor(b.dataset.memberEdit));
  $('memory-input').value = activeChat.memory;
  renderMessages();
  const unanswered = !!activeChat.pending_round || activeChat.messages.at(-1)?.role === 'user';
  $('reply-error').hidden = !unanswered;
  $('reply-error-text').textContent = unanswered ? (group?'This round is unfinished. Retry to continue with the next character; saved contributions are kept.':'Your last message is saved and waiting for a reply.') : '';
  $('message-input').disabled = unanswered;
  $('send-button').disabled = unanswered;
}
function formatMessage(text) { return esc(text).replace(/\*([^*\n]+)\*/g, '<em>$1</em>'); }
function messageHTML(message, index) {
  const c = messageCharacter(message), user = message.role === 'user';
  return `<div class="message ${user ? 'user' : ''}">${user ? '' : avatar(c,'tiny')}<div class="message-body"><p class="message-label">${user ? 'You' : esc(message.speaker_name||c.name)}${!user&&message.model?`<span class="message-model">${esc(message.model)}</span>`:''}</p><div class="message-text">${formatMessage(message.content)}</div>${user ? '' : `<button class="text-button read-aloud" data-read="${index}" aria-label="Read reply ${index+1} aloud">▷ Read aloud</button>`}</div></div>`;
}
function renderMessages() { $('messages').innerHTML = activeChat.messages.map(messageHTML).join(''); document.querySelectorAll('[data-read]').forEach(button=>button.onclick=action(()=>speech.speak(activeChat.messages[Number(button.dataset.read)].content,messageCharacter(activeChat.messages[Number(button.dataset.read)])))); scrollMessages(); }
function scrollMessages() { $('messages').scrollTop = $('messages').scrollHeight; }
async function sendMessage(retry=false, override=null) {
  if (busy || !activeChat) return;
  const text = retry ? '' : override ?? $('message-input').value.trim();
  if (!retry && !text) return;
  const chatId = activeChat.id;
  speech.stop();
  busy = true;
  $('send-button').disabled = true; $('message-input').disabled = true; $('retry-button').disabled = true;
  $('reply-error').hidden = true;
  if (!retry) { activeChat.messages.push({role:'user',content:text}); if(override===null)$('message-input').value=''; renderMessages(); }
  let pending = document.createElement('div'); pending.className='message';
  pending.innerHTML = `${avatar(chatIdentity(),'tiny')}<div class="message-body"><p class="message-label">${esc(chatIdentity().name)}</p><div class="message-text waiting">Thinking of a reply… The first response may take a moment.</div></div>`;
  $('messages').append(pending); scrollMessages();
  let error = null, complete = false, reply = '', completedTurns=[];
  try {
    const response = await fetch(`/api/chats/${chatId}/reply`, {method:'POST',headers:{'Content-Type':'application/json','X-Character-Room':'1'},body:JSON.stringify({message:text})});
    if (!response.ok) { const data = await response.json(); throw new Error(data.error); }
    const reader = response.body.getReader(), decoder = new TextDecoder(); let buffer = '';
    function consume(line) {
      if (!line.trim()) return;
      const event = JSON.parse(line);
      if(event.type==='speaker'){
        if(!pending){pending=document.createElement('div');pending.className='message';$('messages').append(pending);}
        reply='';const c=state.characters.find(c=>c.id===event.character_id)||chatIdentity();
        pending.innerHTML=`${avatar(c,'tiny')}<div class="message-body"><p class="message-label">${esc(event.speaker_name)} <span class="message-model">${esc(event.model)} · ${event.position}/${event.total}</span></p><div class="message-text waiting">Preparing a contribution…</div></div>`;scrollMessages();
      }
      if(event.type==='turn_done'){completedTurns.push(event.message_id);pending=null;}
      if (event.type === 'token') { reply += event.text; const el = pending.querySelector('.message-text'); el.classList.remove('waiting'); el.innerHTML = formatMessage(reply); scrollMessages(); }
      if (event.type === 'error') error = event.error;
      if (event.type === 'done') complete = true;
    }
    for (;;) { const {done,value} = await reader.read(); if (done) break; buffer += decoder.decode(value,{stream:true}); let index; while ((index=buffer.indexOf('\n')) >= 0) { consume(buffer.slice(0,index)); buffer=buffer.slice(index+1); } }
    buffer += decoder.decode(); if (buffer.trim()) consume(buffer);
    if (!complete && !error) error = 'The connection ended before the reply finished. You can retry your saved message.';
  } catch (e) { error = e.message || 'Could not connect. Check that the local app is still running.'; }
  finally {
    busy = false; $('retry-button').disabled = false;
    try { await loadState(); activeChat = await api('/api/chats/' + chatId); renderChat(); renderRecent(); }
    catch (e) { pending?.remove(); if (!retry) $('message-input').value=text; toast('Could not refresh saved history. Reload after restarting the app.'); }
    if (error) { $('reply-error').hidden = false; $('reply-error-text').textContent=error; }
    if (!$('message-input').disabled) $('message-input').focus();
    if(complete&&!error){const entries=activeChat.messages.filter(m=>completedTurns.includes(m.id)&&messageCharacter(m).auto_read).map(m=>({text:m.content,character:messageCharacter(m)}));if(entries.length)speech.speakSequence(entries);}
  }
}
function openEditor(id=null) {
  if (!canLeave()) return;
  speech.stop(); imageSequence++; imageLoading=false;
  editingId = id;
  $('character-form').reset();
  $('editor-title').textContent = id ? 'Edit character' : 'Create a character';
  $('delete-character').hidden = !id;
  if (id) { const c=state.characters.find(c=>c.id===id); for (const key of ['name','subtitle','avatar','color','background','style','scenario','greeting']) $('character-form').elements.namedItem(key).value=c[key]; $('character-form').elements.namedItem('tags').value=c.tags.join(', '); }
  const c=state.characters.find(c=>c.id===id);
  editorImage=c?.image_data||''; renderImagePreview();
  $('speech-rate').value=c?.speech_rate||1; $('speech-rate-value').textContent=Number($('speech-rate').value).toFixed(2)+'×';
  $('auto-read').checked=!!c?.auto_read;
  populateVoices(c?.voice_uri||'');
  $('character-form').elements.namedItem('specialty').value=c?.specialty||'';
  loadCharacterModels(c?.model||'');
  $('character-dialog').showModal();
}
async function saveCharacter(event) {
  event.preventDefault(); const button = event.submitter; button.disabled=true;
  try {
    if(imageLoading)throw new Error('Wait for the image preview before saving.');
    const data=Object.fromEntries(new FormData($('character-form'))); data.tags=data.tags.split(',').map(s=>s.trim()).filter(Boolean);
    data.image_data=editorImage;data.speech_rate=Number(data.speech_rate);data.auto_read=$('auto-read').checked;
    await api('/api/characters' + (editingId ? '/' + editingId : ''),data);
    await loadState(); speech.stop(); $('character-dialog').close(); if (activeChat) renderChat(); toast('Character saved.');
  } finally { button.disabled=false; }
}
function confirmAction(title, message, label='Delete') {
  $('confirm-title').textContent=title; $('confirm-message').textContent=message; $('confirm-ok').textContent=label;
  $('confirm-dialog').showModal();
  return new Promise(resolve=>{
    const finish=value=>{ $('confirm-dialog').close(); $('confirm-dialog').oncancel=null; resolve(value); };
    $('confirm-ok').onclick=()=>finish(true); $('confirm-cancel').onclick=()=>finish(false);
    $('confirm-dialog').oncancel=e=>{e.preventDefault();finish(false);};
  });
}
async function refreshModels() {
  $('model-status').textContent='Checking Ollama…';
  const data=await api('/api/models');
  $('model-select').innerHTML=data.models.length ? data.models.map(name=>`<option value="${esc(name)}">${esc(name)}</option>`).join('') : '<option value="">No local models found</option>';
  if (data.models.includes(state.settings.model)) $('model-select').value=state.settings.model;
  $('save-model').disabled=!data.models.length;
  $('model-status').textContent=data.error || (data.models.length ? `Connected to Ollama · Current model: ${state.settings.model}` : 'Download a model in Ollama, then click Refresh. For example: ollama pull qwen3:8b');
}
function download(name, contents, mime) {
  const url=URL.createObjectURL(new Blob([contents],{type:mime}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);
}
async function loadCharacterModels(selected=$('character-model').value){
  const sequence=++modelLoadSequence;
  $('character-model').innerHTML=`<option value="">Use app default (${esc(state.settings.model)})</option>${selected?`<option value="${esc(selected)}">${esc(selected)}</option>`:''}`;
  $('character-model').value=selected;$('character-model-status').textContent='Checking downloaded models…';
  try{
    const result=await api('/api/models');if(sequence!==modelLoadSequence)return;
    const value=$('character-model').value;
    $('character-model').innerHTML=`<option value="">Use app default (${esc(state.settings.model)})</option>`+result.models.map(model=>`<option value="${esc(model)}">${esc(model)}</option>`).join('');
    if(value&&!result.models.includes(value))$('character-model').insertAdjacentHTML('beforeend',`<option value="${esc(value)}">${esc(value)} · currently unavailable</option>`);
    $('character-model').value=value;
    $('character-model-status').textContent=result.error||`${result.models.length} local models available. Your choice is saved per character.`;
  }catch(e){if(sequence===modelLoadSequence)$('character-model-status').textContent=e.message;}
}
function openGroupEditor(ids=[], title='', memory=''){
  if(!canLeave())return;speech.stop();selectedGroup=ids.slice();$('group-form').reset();
  $('group-form').elements.namedItem('title').value=title;
  $('group-form').elements.namedItem('memory').value=memory;
  renderGroupChoices();$('group-dialog').showModal();
}
function renderGroupChoices(){
  $('group-options').innerHTML=state.characters.map(c=>`<label class="group-choice"><input type="checkbox" data-group-member="${c.id}" ${selectedGroup.includes(c.id)?'checked':''}>${avatar(c,'tiny')}<span><strong>${esc(c.name)}</strong><small>${esc(c.model||state.settings.model)} · ${esc(c.specialty||c.subtitle)}</small></span></label>`).join('');
  document.querySelectorAll('[data-group-member]').forEach(input=>input.onchange=()=>{if(input.checked){if(selectedGroup.length>=6){input.checked=false;toast('Choose at most six characters.');return;}selectedGroup.push(input.dataset.groupMember);}else selectedGroup=selectedGroup.filter(id=>id!==input.dataset.groupMember);renderGroupChoices();});
  $('group-order').innerHTML=selectedGroup.length?selectedGroup.map((id,index)=>{const c=state.characters.find(c=>c.id===id);return `<div class="group-order-row"><span>${index+1}. ${esc(c.name)}</span><button type="button" class="text-button" data-order="${index}" data-move="-1" aria-label="Move ${esc(c.name)} earlier" ${index===0?'disabled':''}>↑</button><button type="button" class="text-button" data-order="${index}" data-move="1" aria-label="Move ${esc(c.name)} later" ${index===selectedGroup.length-1?'disabled':''}>↓</button></div>`;}).join(''):'<p class="help">Select characters above. Put a reviewer or coordinator last to bring the work together.</p>';
  document.querySelectorAll('[data-order]').forEach(button=>button.onclick=()=>{const a=Number(button.dataset.order),b=a+Number(button.dataset.move);[selectedGroup[a],selectedGroup[b]]=[selectedGroup[b],selectedGroup[a]];renderGroupChoices();});
}
$('group-nav').onclick=()=>openGroupEditor();$('group-button').onclick=()=>openGroupEditor();
$('group-form').onsubmit=action(async event=>{
  event.preventDefault();if(selectedGroup.length<2)throw new Error('Choose at least two characters.');
  const button=event.submitter;button.disabled=true;
  try{const data=Object.fromEntries(new FormData($('group-form')));data.member_ids=selectedGroup;
    const result=await api('/api/groups',data);await loadState();$('group-dialog').close();await openChat(result.id);
  }finally{button.disabled=false;}
});
$('refresh-character-models').onclick=()=>loadCharacterModels();
$('continue-group').onclick=action(()=>sendMessage(false,activeChat.messages.some(m=>m.role==='user')?'Continue collaborating on the shared task. Build on the team’s previous contributions, resolve open questions, and improve the result.':'Work together on the shared task. Make concrete contributions using your individual specialties and build on each other’s ideas.'));
function renderImagePreview(){ $('image-preview').innerHTML=editorImage ? `<img src="${esc(editorImage)}" alt="Character image preview">` : '<span>✧</span>'; $('remove-image').disabled=!editorImage; }
async function chooseImage(){
  const file=$('character-image').files[0];if(!file)return;
  if(!['image/jpeg','image/png','image/webp'].includes(file.type)||file.size>10*1024*1024){$('character-image').value='';throw new Error('Choose a PNG, JPG, or WebP image under 10 MB.');}
  const sequence=++imageSequence;imageLoading=true;
  try{
    const source=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(new Error('Could not read that image.'));reader.readAsDataURL(file);});
    const image=await new Promise((resolve,reject)=>{const img=new Image();img.onload=()=>resolve(img);img.onerror=()=>reject(new Error('That file could not be opened as an image.'));img.src=source;});
    if(image.naturalWidth*image.naturalHeight>40000000)throw new Error('Choose an image smaller than 40 megapixels.');
    const canvas=document.createElement('canvas');canvas.width=512;canvas.height=512;
    const ctx=canvas.getContext('2d');ctx.fillStyle='#211e29';ctx.fillRect(0,0,512,512);
    const side=Math.min(image.naturalWidth,image.naturalHeight);
    ctx.drawImage(image,(image.naturalWidth-side)/2,(image.naturalHeight-side)/2,side,side,0,0,512,512);
    if(sequence===imageSequence){editorImage=canvas.toDataURL('image/jpeg',0.85);renderImagePreview();}
  }finally{if(sequence===imageSequence)imageLoading=false;$('character-image').value='';}
}
function populateVoices(selected=$('character-voice').value){
  const voices=speech.voices();
  $('character-voice').innerHTML='<option value="">Default local voice</option>'+voices.map(v=>`<option value="${esc(v.voiceURI)}">${esc(v.name)} · ${esc(v.lang)}</option>`).join('');
  if(selected&&!voices.some(v=>v.voiceURI===selected))$('character-voice').insertAdjacentHTML('beforeend',`<option value="${esc(selected)}">Saved voice · unavailable on this device</option>`);
  $('character-voice').value=selected;
  $('preview-voice').disabled=!voices.length;
  $('voice-availability').textContent=voices.length ? `${voices.length} installed local voices available. Choose a different voice for each character.` : 'No local voices found yet. Try Chrome or Edge with an installed Windows speech voice. Chat and images still work.';
}
async function refreshNetwork(){
  const network=await api('/api/network');networkEnabled=network.enabled;
  $('network-status').textContent=network.enabled ? (network.can_manage?'Phone access is on. Use the same Wi-Fi as this PC.':'You are connected to this PC over the local network.') : 'Phone access is off. Only this PC can open the app.';
  $('network-details').hidden=!network.enabled||!network.can_manage;
  $('network-toggle').disabled=!network.can_manage;
  $('network-toggle').textContent=network.enabled?'Turn off phone access':'Enable phone access';
  $('network-firewall-help').hidden=!network.can_manage;
  $('network-addresses').innerHTML=network.urls.length ? network.urls.map(url=>`<p><a href="${esc(url)}" target="_blank" rel="noopener">${esc(url)}</a></p>`).join('') : '<p class="help">No home-network address found. Connect the PC to your Wi-Fi, then turn phone access off and on.</p>';
  $('network-code').value=network.code;
  const selected=$('network-interface').value;
  $('network-interface').innerHTML=network.addresses.map(address=>`<option value="${esc(address)}">${esc(address)}</option>`).join('');
  $('network-interface').value=network.address|| (network.addresses.includes(selected)?selected:network.addresses.find(ip=>ip.startsWith('192.168.'))||network.addresses[0]||'');
  $('network-interface').disabled=network.enabled||!network.can_manage;
  $('network-interface-label').hidden=!network.can_manage;
}
$('character-image').onchange=action(chooseImage);
$('remove-image').onclick=()=>{imageSequence++;imageLoading=false;editorImage='';$('character-image').value='';renderImagePreview();};
$('speech-rate').oninput=()=>$('speech-rate-value').textContent=Number($('speech-rate').value).toFixed(2)+'×';
$('preview-voice').onclick=action(()=>speech.speak(`Hello, I’m ${$('character-form').elements.namedItem('name').value.trim()||'your character'}. This is how my replies will sound.`,{name:'voice preview',voice_uri:$('character-voice').value,speech_rate:Number($('speech-rate').value)}));
$('stop-preview').onclick=()=>speech.stop();$('stop-speech').onclick=()=>speech.stop();$('pause-speech').onclick=()=>speech.pause();
$('character-dialog').addEventListener('close',()=>{speech.stop();imageSequence++;imageLoading=false;});
if(window.speechSynthesis)window.speechSynthesis.addEventListener('voiceschanged',()=>populateVoices());
$('network-toggle').onclick=action(async()=>{const button=$('network-toggle');button.disabled=true;try{await api('/api/network',{enabled:!networkEnabled,address:$('network-interface').value});await refreshNetwork();}finally{button.disabled=false;}});
$('mobile-chat-picker').onchange=action(()=>openChat($('mobile-chat-picker').value));
window.addEventListener('pagehide',()=>speech.stop());
$('search').addEventListener('input',renderLibrary);
for (const id of ['create-nav','create-button','feature-create']) $(id).onclick=()=>openEditor();
$('home-button').onclick=showLibrary; $('back-button').onclick=showLibrary;
document.querySelector('.brand').onclick=e=>{e.preventDefault();showLibrary();};
document.querySelectorAll('.close-dialog').forEach(b=>b.onclick=()=>b.closest('dialog').close());
$('character-form').onsubmit=action(saveCharacter);
$('message-form').onsubmit=action(e=>{e.preventDefault();return sendMessage();});
$('message-input').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();action(()=>sendMessage())();}};
$('retry-button').onclick=action(()=>sendMessage(true));
$('new-chat').onclick=action(()=>activeChat.kind==='group'?openGroupEditor(activeChat.member_ids,activeChat.title,activeChat.memory):openCharacter(activeChat.character_id,true));
$('profile-button').onclick=()=>$('profile-panel').classList.toggle('visible');
$('edit-character').onclick=()=>openEditor(activeChat.character_id);
$('save-memory').onclick=action(async()=>{if(!canLeave())return;await api('/api/chats/'+activeChat.id,{memory:$('memory-input').value});activeChat.memory=$('memory-input').value;toast('Memory saved for this conversation.');});
$('rename-chat').onclick=()=>{if(!canLeave())return;$('rename-input').value=activeChat.title;$('rename-dialog').showModal();};
$('rename-form').onsubmit=action(async e=>{e.preventDefault();await api('/api/chats/'+activeChat.id,{title:$('rename-input').value});activeChat.title=$('rename-input').value;await loadState();renderChat();$('rename-dialog').close();});
$('delete-chat').onclick=action(async()=>{if(!canLeave())return;if(!await confirmAction('Delete this conversation?','All messages and pinned memories in this conversation will be permanently deleted.'))return;await api('/api/chats/'+activeChat.id,{delete:true});showLibrary();await loadState();toast('Conversation deleted.');});
$('delete-character').onclick=action(async()=>{if(!await confirmAction('Delete this character?', 'This deletes individual chats with this character. A character in a group cannot be deleted until its group conversations have been deleted. Export a backup first to keep your history.'))return;await api('/api/characters/'+editingId,{delete:true});$('character-dialog').close();if(activeChat?.character_id===editingId)showLibrary();await loadState();toast('Character deleted.');});
$('settings-button').onclick=action(async()=>{$('settings-dialog').showModal();await Promise.all([refreshModels(),refreshNetwork()]);});
$('refresh-models').onclick=action(refreshModels);
$('save-model').onclick=action(async()=>{await api('/api/settings',{model:$('model-select').value});await loadState();toast('Local model selected.');await refreshModels();});
$('backup-button').onclick=action(async()=>{download('character-room-backup.json',JSON.stringify(await api('/api/export'),null,2),'application/json');toast('Backup exported.');});
$('export-chat').onclick=()=>{const c=chatIdentity();download(`${c.name.replace(/[^a-z0-9_-]/gi,'_')}-conversation.txt`,`${c.name} — ${activeChat.title}\n\nPinned memory: ${activeChat.memory || '(none)'}\n\n`+activeChat.messages.map(m=>`${m.role==='user'?'You':m.speaker_name||messageCharacter(m).name}${m.model?' ['+m.model+']':''}:\n${m.content}`).join('\n\n'),'text/plain;charset=utf-8');};
window.addEventListener('beforeunload',e=>{if(busy){e.preventDefault();e.returnValue='';}});
action(async()=>{await loadState();const saved=localStorage.getItem('character-room-active-chat');if(saved&&state.chats.some(c=>c.id===saved))await openChat(saved);}) ();
