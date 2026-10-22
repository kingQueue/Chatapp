'use strict';
const $ = id => document.getElementById(id);
let state = {characters: [], chats: [], settings: {}}, activeChat = null, editingId = null, busy = false, toastTimer;
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const avatar = (c, size='') => `<div class="avatar ${esc(c.color)} ${size}" aria-hidden="true">${esc(c.avatar)}</div>`;
const tags = c => c.tags.map(t => `<span class="tag">${esc(t)}</span>`).join('');
function toast(message) { $('toast').textContent = message; $('toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => $('toast').hidden = true, 5000); }
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
function renderLibrary() {
  $('character-count').textContent = state.characters.length;
  $('collection-count').textContent = state.characters.length;
  const query = $('search').value.toLowerCase().trim();
  const characters = state.characters.filter(c => [c.name,c.subtitle,...c.tags].join(' ').toLowerCase().includes(query));
  $('character-grid').innerHTML = characters.map(c => `<article class="character-card ${esc(c.color)}"><div class="card-art">${avatar(c)}</div><div class="card-body"><div class="card-title"><h3>${esc(c.name)}</h3><button class="card-edit" data-edit="${c.id}" aria-label="Edit ${esc(c.name)}">✎</button></div><p class="card-subtitle">${esc(c.subtitle || 'A story waiting to happen')}</p><div class="tags">${tags(c)}</div><p class="card-description">${esc(c.background)}</p><button class="card-chat" data-chat="${c.id}"><span>${state.chats.some(chat => chat.character_id === c.id) ? 'Continue conversation' : 'Start a conversation'}</span><span>↗</span></button></div></article>`).join('') + `<button class="create-card" id="grid-create"><span>＋</span><strong>${query && !characters.length ? 'No matches. Create someone new?' : 'Someone only you can imagine'}</strong><small>Give them a story.<br>Let the conversation begin.</small></button>`;
  document.querySelectorAll('[data-edit]').forEach(b => b.onclick = () => openEditor(b.dataset.edit));
  document.querySelectorAll('[data-chat]').forEach(b => b.onclick = action(() => openCharacter(b.dataset.chat)));
  $('grid-create').onclick = () => openEditor();
}
function renderRecent() {
  const chats = state.chats.slice(0,30);
  $('recent-list').innerHTML = chats.length ? chats.map(chat => {
    const c = state.characters.find(c => c.id === chat.character_id);
    return c ? `<button class="recent-item ${activeChat?.id === chat.id ? 'selected' : ''}" data-recent="${chat.id}">${avatar(c,'tiny')}<span class="recent-copy"><strong>${esc(c.name)}</strong><small>${esc(chat.title)}</small></span></button>` : '';
  }).join('') : '<p class="empty-recent">Your conversations will find a home here.</p>';
  document.querySelectorAll('[data-recent]').forEach(b => b.onclick = action(() => openChat(b.dataset.recent)));
}
function showLibrary() {
  if (!canLeave()) return;
  $('library').hidden = false; $('chat-view').hidden = true;
  activeChat = null;
  localStorage.removeItem('character-room-active-chat');
  renderRecent();
}
async function openCharacter(id, forceNew=false) {
  if (!canLeave()) return;
  const latest = state.chats.find(c => c.character_id === id);
  const chatId = !forceNew && latest ? latest.id : (await api('/api/chats', {character_id:id})).id;
  await loadState();
  await openChat(chatId);
}
async function openChat(id) {
  if (!canLeave()) return;
  activeChat = await api('/api/chats/' + id);
  localStorage.setItem('character-room-active-chat', id);
  $('library').hidden = true; $('chat-view').hidden = false;
  renderChat(); renderRecent();
  $('message-input').focus();
}
function renderChat() {
  const c = currentCharacter(); if (!c) return showLibrary();
  $('chat-name').textContent = c.name; $('chat-subtitle').textContent = c.subtitle;
  $('chat-title').textContent = activeChat.title;
  $('chat-avatar').className = 'avatar small ' + c.color; $('chat-avatar').textContent = c.avatar;
  $('message-input').placeholder = `Message ${c.name}…`;
  $('profile-content').innerHTML = `${avatar(c)}<h2>${esc(c.name)}</h2><p class="subtitle">${esc(c.subtitle)}</p><div class="tags">${tags(c)}</div><h3>Their story</h3><p class="bio">${esc(c.background)}</p>${c.style ? `<h3>Their voice</h3><p class="bio">${esc(c.style)}</p>` : ''}${c.scenario ? `<h3>The scene</h3><p class="bio">${esc(c.scenario)}</p>` : ''}`;
  $('memory-input').value = activeChat.memory;
  renderMessages();
  const unanswered = activeChat.messages.at(-1)?.role === 'user';
  $('reply-error').hidden = !unanswered;
  $('reply-error-text').textContent = unanswered ? 'Your last message is saved and waiting for a reply.' : '';
  $('message-input').disabled = unanswered;
  $('send-button').disabled = unanswered;
}
function formatMessage(text) { return esc(text).replace(/\*([^*\n]+)\*/g, '<em>$1</em>'); }
function messageHTML(message) {
  const c = currentCharacter(), user = message.role === 'user';
  return `<div class="message ${user ? 'user' : ''}">${user ? '' : avatar(c,'tiny')}<div class="message-body"><p class="message-label">${user ? 'You' : esc(c.name)}</p><div class="message-text">${formatMessage(message.content)}</div></div></div>`;
}
function renderMessages() { $('messages').innerHTML = activeChat.messages.map(messageHTML).join(''); scrollMessages(); }
function scrollMessages() { $('messages').scrollTop = $('messages').scrollHeight; }
async function sendMessage(retry=false) {
  if (busy || !activeChat) return;
  const text = retry ? '' : $('message-input').value.trim();
  if (!retry && !text) return;
  const chatId = activeChat.id;
  busy = true;
  $('send-button').disabled = true; $('message-input').disabled = true; $('retry-button').disabled = true;
  $('reply-error').hidden = true;
  if (!retry) { activeChat.messages.push({role:'user',content:text}); $('message-input').value=''; renderMessages(); }
  const pending = document.createElement('div'); pending.className='message';
  pending.innerHTML = `${avatar(currentCharacter(),'tiny')}<div class="message-body"><p class="message-label">${esc(currentCharacter().name)}</p><div class="message-text waiting">Thinking of a reply… The first response may take a moment.</div></div>`;
  $('messages').append(pending); scrollMessages();
  let error = null, complete = false, reply = '';
  try {
    const response = await fetch(`/api/chats/${chatId}/reply`, {method:'POST',headers:{'Content-Type':'application/json','X-Character-Room':'1'},body:JSON.stringify({message:text})});
    if (!response.ok) { const data = await response.json(); throw new Error(data.error); }
    const reader = response.body.getReader(), decoder = new TextDecoder(); let buffer = '';
    function consume(line) {
      if (!line.trim()) return;
      const event = JSON.parse(line);
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
    catch (e) { pending.remove(); if (!retry) $('message-input').value=text; toast('Could not refresh saved history. Reload after restarting the app.'); }
    if (error) { $('reply-error').hidden = false; $('reply-error-text').textContent=error; }
    if (!$('message-input').disabled) $('message-input').focus();
  }
}
function openEditor(id=null) {
  if (!canLeave()) return;
  editingId = id;
  $('character-form').reset();
  $('editor-title').textContent = id ? 'Edit character' : 'Create a character';
  $('delete-character').hidden = !id;
  if (id) { const c=state.characters.find(c=>c.id===id); for (const key of ['name','subtitle','avatar','color','background','style','scenario','greeting']) $('character-form').elements.namedItem(key).value=c[key]; $('character-form').elements.namedItem('tags').value=c.tags.join(', '); }
  $('character-dialog').showModal();
}
async function saveCharacter(event) {
  event.preventDefault(); const button = event.submitter; button.disabled=true;
  try {
    const data=Object.fromEntries(new FormData($('character-form'))); data.tags=data.tags.split(',').map(s=>s.trim()).filter(Boolean);
    await api('/api/characters' + (editingId ? '/' + editingId : ''),data);
    await loadState(); $('character-dialog').close(); if (activeChat) renderChat(); toast('Character saved.');
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
$('search').addEventListener('input',renderLibrary);
for (const id of ['create-nav','create-button','feature-create']) $(id).onclick=()=>openEditor();
$('home-button').onclick=showLibrary; $('back-button').onclick=showLibrary;
document.querySelector('.brand').onclick=e=>{e.preventDefault();showLibrary();};
document.querySelectorAll('.close-dialog').forEach(b=>b.onclick=()=>b.closest('dialog').close());
$('character-form').onsubmit=action(saveCharacter);
$('message-form').onsubmit=action(e=>{e.preventDefault();return sendMessage();});
$('message-input').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();action(()=>sendMessage())();}};
$('retry-button').onclick=action(()=>sendMessage(true));
$('new-chat').onclick=action(()=>openCharacter(activeChat.character_id,true));
$('profile-button').onclick=()=>$('profile-panel').classList.toggle('visible');
$('edit-character').onclick=()=>openEditor(activeChat.character_id);
$('save-memory').onclick=action(async()=>{if(!canLeave())return;await api('/api/chats/'+activeChat.id,{memory:$('memory-input').value});activeChat.memory=$('memory-input').value;toast('Memory saved for this conversation.');});
$('rename-chat').onclick=()=>{if(!canLeave())return;$('rename-input').value=activeChat.title;$('rename-dialog').showModal();};
$('rename-form').onsubmit=action(async e=>{e.preventDefault();await api('/api/chats/'+activeChat.id,{title:$('rename-input').value});activeChat.title=$('rename-input').value;await loadState();renderChat();$('rename-dialog').close();});
$('delete-chat').onclick=action(async()=>{if(!canLeave())return;if(!await confirmAction('Delete this conversation?','All messages and pinned memories in this conversation will be permanently deleted.'))return;await api('/api/chats/'+activeChat.id,{delete:true});showLibrary();await loadState();toast('Conversation deleted.');});
$('delete-character').onclick=action(async()=>{if(!await confirmAction('Delete this character?', 'This also permanently deletes all conversations with this character. Export a backup first if you want to keep them.'))return;await api('/api/characters/'+editingId,{delete:true});$('character-dialog').close();if(activeChat?.character_id===editingId)showLibrary();await loadState();toast('Character deleted.');});
$('settings-button').onclick=action(async()=>{$('settings-dialog').showModal();await refreshModels();});
$('refresh-models').onclick=action(refreshModels);
$('save-model').onclick=action(async()=>{await api('/api/settings',{model:$('model-select').value});await loadState();toast('Local model selected.');await refreshModels();});
$('backup-button').onclick=action(async()=>{download('character-room-backup.json',JSON.stringify(await api('/api/export'),null,2),'application/json');toast('Backup exported.');});
$('export-chat').onclick=()=>{const c=currentCharacter();download(`${c.name.replace(/[^a-z0-9_-]/gi,'_')}-conversation.txt`,`${c.name} — ${activeChat.title}\n\nPinned memory: ${activeChat.memory || '(none)'}\n\n`+activeChat.messages.map(m=>`${m.role==='user'?'You':c.name}:\n${m.content}`).join('\n\n'),'text/plain;charset=utf-8');};
window.addEventListener('beforeunload',e=>{if(busy){e.preventDefault();e.returnValue='';}});
action(async()=>{await loadState();const saved=localStorage.getItem('character-room-active-chat');if(saved&&state.chats.some(c=>c.id===saved))await openChat(saved);}) ();
