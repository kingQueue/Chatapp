// The configured Partmap app shares a JSON file with Character Room, not browser-only storage.
(()=>{
  const query=new URLSearchParams(location.search), chat=query.get('chat'), path=query.get('path')||'parts.json';
  let hash='',ready=false,dirty=false,saving=false,conflict=false,timer,revision=0;
  const bar=document.createElement('div');bar.className='room-bridge-bar';
  const label=document.createElement('span');label.textContent='Connecting to the assigned project…';
  const save=document.createElement('button');save.textContent='Save project';
  const reload=document.createElement('button');reload.textContent='Reload latest';
  const back=document.createElement('a');back.href='/';back.textContent='← Back to chat';back.style.color='white';
  bar.append(back,label,save,reload);document.body.prepend(bar);
  const style=document.createElement('style');style.textContent='.room-bridge-bar{position:sticky;top:0;z-index:1000;background:#244339;color:white;padding:12px 20px;display:flex;align-items:center;gap:12px;font:12px Segoe UI,Arial}.room-bridge-bar span{flex:1}.room-bridge-bar button{background:#e8f0db;border:0;border-radius:5px;padding:7px 10px;color:#244339;cursor:pointer}';document.head.append(style);
  async function request(action,data){const response=await fetch(`/api/project/${encodeURIComponent(chat)}/${action}${data?'':'?path='+encodeURIComponent(path)}`,data?{method:'POST',headers:{'Content-Type':'application/json','X-Character-Room':'1'},body:JSON.stringify(data)}:{});const value=await response.json();if(!response.ok)throw new Error(value.error);return value;}
  async function load(initial=false){
    if(!chat){label.textContent='Open Partmap from a Character Room chat with an assigned project.';save.disabled=true;return;}
    try{const result=await request('parts');if(!dirty&&result.sha256!==hash){project=validate(result.project);selected=project.nodes[0]?.id;hash=result.sha256;render();}ready=true;conflict=false;label.textContent=`Project file: ${path} · synced`;}catch(e){
      if(initial&&/does not exist/.test(e.message)){project=validate({name:'Hardware project',nodes:[]});selected=null;hash='';ready=true;render();label.textContent=`New project file: ${path}`;}
      else label.textContent=e.message;
    }
  }
  async function flush(){
    if(!ready||saving||conflict)return;saving=true;const sentRevision=revision;
    try{const result=await request('parts',{path,project:exportObject(),expected_sha256:hash});hash=result.sha256;dirty=revision!==sentRevision;label.textContent=dirty?'Saving project file…':`Project file: ${path} · synced`;}
    catch(e){label.textContent=e.message+' Use Reload latest to review the current file.';conflict=true;}
    finally{saving=false;if(dirty&&!conflict){clearTimeout(timer);timer=setTimeout(flush,500);}}
  }
  persist=function(){if(!ready)return;revision++;dirty=true;label.textContent='Saving project file…';clearTimeout(timer);timer=setTimeout(flush,500);};
  save.onclick=()=>{dirty=true;conflict=false;flush();};
  reload.onclick=()=>{if(dirty&&!confirm('Discard unsaved Partmap edits and reload the project file?'))return;dirty=false;conflict=false;load();};
  window.addEventListener('beforeunload',event=>{if(dirty){event.preventDefault();event.returnValue='';}});
  load(true);setInterval(()=>{if(ready&&!dirty&&!saving)load();},5000);
})();
