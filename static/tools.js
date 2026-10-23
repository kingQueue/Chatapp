'use strict';
globalThis.ToolUI=(()=>{
  const el=id=>document.getElementById(id), escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const action=fn=>(...args)=>{try{return Promise.resolve(fn(...args)).catch(e=>toast(e.message));}catch(e){toast(e.message);}};
  let registry=[],canManage=false,permissions=[],currentTool=null,requestIndex=0;
  async function refresh(){const result=await api('/api/tools');registry=result.tools;canManage=result.can_manage;return result;}
  function locationType(){return el('tool-adapter').value==='partmap'?'directory':'executable';}
  async function pick(target,mode='directory'){const button=document.activeElement;button.disabled=true;try{const result=await api('/api/pick-location',{mode});if(result.path)el(target).value=result.path;}finally{button.disabled=false;}}
  function permissionChoices(){
    el('character-tool-permissions').innerHTML=registry.map(tool=>`<label class="check-label"><input type="checkbox" data-character-tool="${tool.id}" ${permissions.includes(tool.id)?'checked':''} ${canManage?'':'disabled'}><span>${escape(tool.name)}${tool.enabled?'':' · disabled globally'}${!tool.location&&!tool.adapter.startsWith('files_')?' · location needed':''}</span></label>`).join('');
    document.querySelectorAll('[data-character-tool]').forEach(input=>input.onchange=()=>{permissions=[...document.querySelectorAll('[data-character-tool]:checked')].map(i=>i.dataset.characterTool);});
    el('character-tools-help').textContent=canManage?'Only checked tools are available to this character, and only when the chat has an assigned project directory.':'Tool permissions can be changed on the PC only.';
  }
  async function fillCharacter(c){
    permissions=(c?.tool_ids||[]).slice();const index=++requestIndex;
    el('character-tool-permissions').textContent='Loading tool permissions…';
    try{await refresh();if(index===requestIndex)permissionChoices();}catch(e){el('character-tool-permissions').textContent=e.message;}
  }
  function registryList(){
    el('tool-registry-list').innerHTML=registry.map(tool=>`<button type="button" class="registered-tool" data-edit-tool="${tool.id}"><strong>${escape(tool.name)}</strong><small>${escape(tool.adapter)} · ${tool.enabled?'enabled':'disabled'}${tool.location?' · '+escape(tool.location):tool.adapter.startsWith('files_')?' · built in':' · choose application location'}</small></button>`).join('');
    document.querySelectorAll('[data-edit-tool]').forEach(button=>button.onclick=()=>editTool(registry.find(t=>t.id===button.dataset.editTool)));
  }
  function editTool(tool=null){
    currentTool=tool;el('tool-form').reset();el('tool-name').value=tool?.name||'';el('tool-adapter').value=tool?.adapter||'files_read';el('tool-location').value=tool?.location||'';el('tool-enabled').checked=tool?!!tool.enabled:true;
    el('tool-location-label').hidden=el('tool-adapter').value.startsWith('files_');el('tool-form-title').textContent=tool?'Edit tool':'Add tool';
  }
  async function openRegistry(){
    const result=await refresh();el('tool-dialog').showModal();registryList();editTool();
    el('tool-admin-note').textContent=canManage?'Configure trusted adapters and installed application locations. Characters start with no tool grants.':'Open this screen on the PC to configure application locations.';
    for(const control of el('tool-form').elements)control.disabled=!canManage;
    el('tool-adapter').innerHTML=Object.entries(result.adapters).map(([key,name])=>`<option value="${key}">${escape(name)}</option>`).join('');editTool();
  }
  function initChat(chat){
    el('project-directory').value=chat.project_dir||'';
    const managed=!!state.can_manage_tools;
    el('project-directory').disabled=!managed;el('project-browse').disabled=!managed;el('project-save').disabled=!managed||busy;
    el('project-status').textContent=chat.project_dir?'Project work mode. Characters check actual read access before replying when permitted. File tools stay within this folder; character permissions still apply.':'No project selected. Characters cannot use project tools.';
    el('project-open-files').disabled=!chat.project_dir;el('project-open-parts').disabled=!chat.project_dir;
    el('tool-history-list').innerHTML=(chat.tool_events||[]).map(entry=>{
      let args={},result={};try{args=JSON.parse(entry.arguments);result=JSON.parse(entry.result);}catch{}
      const name=state.characters.find(c=>c.id===entry.character_id)?.name||'Character';
      return `<details class="tool-entry"><summary>${escape(name)} · ${escape(entry.operation)} · ${escape(entry.status)}</summary><pre>${escape(JSON.stringify({arguments:args,result},null,2).slice(0,30000))}</pre></details>`;
    }).join('')||'<p class="help">Tool activity will appear here when a permitted character uses a tool.</p>';
    el('tool-live').hidden=true;
  }
  function live(event){
    el('tool-live').hidden=false;
    el('tool-live').textContent=event.type==='tool_mode'?`${event.speaker_name} is using compatibility mode for this model’s tool requests…`:event.type==='tool_start'?`${event.speaker_name} is using ${event.name}…`:event.type==='tool_thinking'?`${event.speaker_name} is reviewing the tool result…`:`${event.name}: ${event.status}${event.result?.error?' · '+event.result.error:''}`;
  }
  async function showFiles(path='.'){const result=await api(`/api/project/${activeChat.id}/list?path=${encodeURIComponent(path)}`);el('project-files-dialog').showModal();el('project-files-path').value=path;
    el('project-file-list').innerHTML=result.entries.map(entry=>`<div class="project-file-row"><button class="text-button" data-project-path="${escape(entry.path)}" data-project-kind="${entry.type}">${entry.type==='directory'?'▸':'▤'} ${escape(entry.path)}</button>${entry.type==='file'?`<a href="/api/project/${activeChat.id}/download?path=${encodeURIComponent(entry.path)}" download>Download</a>`:''}</div>`).join('')||'<p class="help">This folder is empty.</p>';
    document.querySelectorAll('[data-project-path]').forEach(button=>button.onclick=action(async()=>{if(button.dataset.projectKind==='directory')return showFiles(button.dataset.projectPath);const value=await api(`/api/project/${activeChat.id}/read?path=${encodeURIComponent(button.dataset.projectPath)}`);el('project-file-preview').textContent=value.content;}));
  }
  async function openParts(){await refresh();const tool=registry.find(t=>t.adapter==='partmap'&&t.enabled&&t.location);if(!tool)throw new Error('Configure the Partmap source folder in Settings → Tools first.');const path=el('partmap-project-file').value.trim()||'parts.json';location.assign(`/partmap/${tool.id}/index.html?chat=${activeChat.id}&path=${encodeURIComponent(path)}`);}
  el('manage-tools').onclick=action(openRegistry);el('add-registered-tool').onclick=()=>editTool();
  el('tool-adapter').onchange=()=>{el('tool-location-label').hidden=el('tool-adapter').value.startsWith('files_');};
  el('browse-tool-location').onclick=action(()=>pick('tool-location',locationType()));
  el('detect-tool-location').onclick=action(async()=>{const result=await api('/api/tools',{action:'discover'});const location=result.locations[el('tool-adapter').value];if(location)el('tool-location').value=location;else toast('Choose this application’s installed location manually.');});
  el('tool-form').onsubmit=action(async event=>{event.preventDefault();const button=event.submitter;button.disabled=true;try{await api('/api/tools',{id:currentTool?.id,name:el('tool-name').value,adapter:el('tool-adapter').value,location:el('tool-location').value,enabled:el('tool-enabled').checked});await refresh();registryList();toast('Tool registration saved. Grant it to characters in Edit character.');}finally{button.disabled=false;}});
  el('project-browse').onclick=action(()=>pick('project-directory'));
  el('group-project-browse').onclick=action(()=>pick('group-project-directory'));
  el('project-save').onclick=action(async()=>{if(!canLeave())return;await api('/api/chats/'+activeChat.id,{project_dir:el('project-directory').value});activeChat=await api('/api/chats/'+activeChat.id);await loadState();initChat(activeChat);toast('Project directory saved.');});
  el('project-open-files').onclick=action(()=>showFiles());el('project-open-parts').onclick=action(openParts);
  el('project-files-go').onclick=action(()=>showFiles(el('project-files-path').value||'.'));
  return {fillCharacter,readPermissions:()=>permissions.slice(),initChat,live};
})();
