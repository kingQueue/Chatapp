"""Project-scoped tool adapters. No shell commands or model-written code execution."""
import hashlib
import json
import math
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import stat
import subprocess
import threading
import uuid

ADAPTERS = {
    'files_read': ('Read project files', [('list_files', 'List files in the assigned project directory.', {'path': 'string'}),
                                         ('read_text', 'Read UTF-8 text in pages and its full-file SHA-256 before editing. start_line is 1-based, line_count up to 300; read remaining pages before replacing a file.', {'path': 'string','start_line':'integer','line_count':'integer'})]),
    'files_write': ('Write project files', [('write_text', 'Create or replace UTF-8 text/code. For existing files, expected_sha256 must match a preceding read.', {'path': 'string', 'content': 'string', 'expected_sha256': 'string'})]),
    'vscode': ('Visual Studio Code', [('open_editor', 'Open an existing project file in VS Code. Code editing uses write_text.', {'path': 'string'})]),
    'git': ('Local Git', [('git', 'Local project Git only. Actions: status, diff, log, init, stage, commit. Stage requires explicit file paths; commit requires a message. No remote, hooks, shell, checkout, or delete actions.', {'action': 'string', 'paths': 'array', 'message': 'string'})]),
    'partmap': ('Partmap hardware studio', [('parts_read', 'Read a project-local Partmap JSON file; includes parts, hierarchy and wiring.', {'path': 'string'}),
                                          ('parts_write', 'Create/update a Partmap project JSON with name and nodes. Existing files require expected_sha256 from parts_read. Categories: board,sensor,motor,power,peripheral,printed,fastener,mechanical.', {'path': 'string', 'project': 'object', 'expected_sha256': 'string'})]),
    'freecad': ('FreeCAD modeling', [('cad_create', 'Create parametric FreeCAD, STEP and STL models from a declarative shape list. Shapes: box(length,width,height), cylinder(radius,height), sphere(radius), cone(radius,radius2,height). Optional x,y,z,rx,ry,rz; operation add or cut. Units mm/degrees. First shape must add. Output is a new relative stem, e.g. models/bracket. Never pass Python code.', {'output': 'string', 'shapes': 'array'})]),
}
BLOCKED = {'.git', '.hg', '.svn', '.vscode', '.idea', '.ssh', '.aws', '.codex', '.agents', '__pycache__', '.character-room'}
PROJECT_LOCKS = {}
GUARD = threading.Lock()

def project_lock(root):
    with GUARD:
        return PROJECT_LOCKS.setdefault(str(root), threading.RLock())

def reparse(path):
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)

def project_directory(value, app_root=None):
    if not isinstance(value, str) or len(value) > 1000:
        raise ValueError('Enter an existing absolute project directory.')
    if not value.strip():
        return ''
    path = Path(value.strip()).expanduser()
    if not path.is_absolute() or not path.is_dir():
        raise ValueError('Choose an existing absolute project folder on this PC.')
    path = path.resolve()
    forbidden = [Path.home().resolve(), Path(path.anchor)]
    forbidden_subtrees=[]
    for key in ('WINDIR', 'PROGRAMFILES', 'PROGRAMFILES(X86)', 'APPDATA', 'LOCALAPPDATA'):
        if os.environ.get(key):
            forbidden_subtrees.append(Path(os.environ[key]).resolve())
    if path in forbidden or any(path.is_relative_to(item) for item in forbidden_subtrees):
        raise ValueError('Choose a specific work project, not a drive, home, system, or application-data folder.')
    if app_root:
        app_root = Path(app_root).resolve()
        if path == app_root or path.is_relative_to(app_root) or app_root.is_relative_to(path):
            raise ValueError('Choose a project folder separate from Character Room and its private data.')
    return str(path)

def scoped(root, relative='.', allow_directory=False):
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError('The project directory no longer exists.')
    if not isinstance(relative, str) or len(relative) > 500 or '\x00' in relative:
        raise ValueError('Use a relative project path.')
    normalized = relative.replace('\\', '/')
    windows = PureWindowsPath(relative)
    if normalized.startswith('/') or windows.drive or ':' in normalized or '..' in normalized.split('/'):
        raise ValueError('Paths must stay inside the assigned project directory.')
    parts = [p for p in normalized.split('/') if p not in ('', '.')]
    for part in parts:
        base = part.split('.')[0].upper()
        if part.lower() in BLOCKED or part.lower().startswith('.env') or part.endswith((' ', '.')) or part.lower().endswith('.code-workspace') or part.lower() in ('.gitattributes', '.gitmodules') or base in {'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(1,10)],*[f'LPT{i}' for i in range(1,10)]}:
            raise ValueError('That path is protected project metadata or an unsafe filename.')
    target = root.joinpath(*parts)
    current = root
    for part in parts:
        current = current / part
        if current.exists() or current.is_symlink():
            if reparse(current):
                raise ValueError('Symbolic links and Windows junctions are not available to characters.')
            if current.is_file() and current.stat().st_nlink > 1:
                raise ValueError('Hard-linked files are not available to characters.')
    resolved = target.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError('The path leaves the assigned project directory.')
    if not allow_directory and (not parts or resolved.is_dir()):
        raise ValueError('Choose a project file, not a directory.')
    return resolved

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def read_text(root, path, start_line=1, line_count=300, whole=False):
    target = scoped(root, path)
    if not target.is_file():
        raise ValueError('That project file does not exist.')
    if target.stat().st_size > 300000:
        raise ValueError('Text tools support files up to 300 KB. Split this file into smaller files.')
    raw = target.read_bytes()
    if b'\0' in raw:
        raise ValueError('This is a binary file. Use the project file download action instead.')
    try:
        content = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise ValueError('Text tools read UTF-8 files only.')
    if whole:
        return {'path':str(target.relative_to(root)),'content':content,'sha256':digest(raw)}
    if type(start_line) is not int or type(line_count) is not int or start_line<1 or not 1<=line_count<=300:
        raise ValueError('Use a positive start_line and 1–300 lines per page.')
    lines=content.splitlines(keepends=True);page=[];size=0
    for line in lines[start_line-1:start_line-1+line_count]:
        if size+len(line)>24000:break
        page.append(line);size+=len(line)
    if not page and start_line<=len(lines):raise ValueError('A line exceeds the text tool limit. Split long generated lines before using this reader.')
    next_line=start_line+len(page)
    return {'path': str(target.relative_to(root)), 'content': ''.join(page), 'sha256': digest(raw),
            'start_line':start_line,'total_lines':len(lines),'next_line':next_line if next_line<=len(lines) else None,
            'complete':next_line>len(lines)}

def write_text(root, path, content, expected=''):
    if not isinstance(content, str) or len(content.encode('utf-8')) > 300000 or '\0' in content:
        raise ValueError('Write UTF-8 text/code up to 300 KB.')
    target = scoped(root, path)
    if target.exists() and (not expected or digest(target.read_bytes()) != expected):
        raise ValueError('File changed or was not read first. Read it again and provide its SHA-256 before replacing it.')
    target.parent.mkdir(parents=True, exist_ok=True)
    # Recheck after making directories; character APIs cannot create links.
    target = scoped(root, path)
    raw = content.encode('utf-8')
    temporary = target.parent / ('.room-write-' + uuid.uuid4().hex)
    try:
        temporary.write_bytes(raw)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return {'path': str(target.relative_to(root)), 'bytes': len(raw), 'sha256': digest(raw)}

def list_files(root, path='.'):
    folder = scoped(root, path, True)
    if not folder.is_dir():
        raise ValueError('Choose an existing project subdirectory.')
    entries = []
    for item in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
        if len(entries) >= 500:
            break
        try:
            checked = scoped(root, str(item.relative_to(root)), True)
            entries.append({'path': str(checked.relative_to(root)), 'type': 'directory' if checked.is_dir() else 'file', 'bytes': checked.stat().st_size if checked.is_file() else None})
        except (ValueError, OSError):
            continue
    return {'entries': entries, 'limit': 500}

def validate_parts(project):
    if not isinstance(project, dict) or not isinstance(project.get('name'), str) or not isinstance(project.get('nodes'), list) or len(project['nodes']) > 300:
        raise ValueError('Partmap needs a name and up to 300 nodes.')
    project = json.loads(json.dumps(project))
    ids = set()
    categories = {'board','sensor','motor','power','peripheral','printed','fastener','mechanical'}
    for n in project['nodes']:
        if not isinstance(n, dict) or not isinstance(n.get('id'), str) or not n['id'] or n['id'] in ids or not isinstance(n.get('name'), str) or not n['name'].strip() or n.get('category') not in categories:
            raise ValueError('Each part needs a unique ID, name, and supported category.')
        ids.add(n['id'])
        q = n.get('quantity', 1)
        if type(q) is not int or not 1 <= q <= 100000:
            raise ValueError('Part quantities must be positive integers.')
        n.update(quantity=q, parent=n.get('parent') or None, ready=bool(n.get('ready', False)))
        for key in ('connections','pins','attachments'):
            if not isinstance(n.get(key, []), list):
                raise ValueError(f'Part {key} must be a list.')
            n.setdefault(key, [])
        # Exported attachments can be imported by the user; bots exchange project files, not embedded payloads.
        if n['attachments']:
            raise ValueError('Keep attachment files separately in the project directory; embedded attachments are not supported by this bridge.')
    lookup = {n['id']: n for n in project['nodes']}
    for n in project['nodes']:
        seen = {n['id']}; parent = n['parent']
        while parent:
            if parent not in ids or parent in seen:
                raise ValueError('Part parents must form a valid tree without cycles.')
            seen.add(parent); parent = lookup[parent]['parent']
        if len(n['pins']) > 100 or any(not isinstance(p, dict) or not isinstance(p.get('name'), str) or not p['name'].strip() for p in n['pins']):
            raise ValueError('Use up to 100 named pins per component.')
        for c in n['connections']:
            if not isinstance(c, dict) or c.get('target') not in ids or c['target'] == n['id'] or not isinstance(c.get('local'), str) or not isinstance(c.get('remote'), str):
                raise ValueError('Part wiring must reference valid components and named pins.')
    project['schemaVersion'] = '1.0'
    project.setdefault('baseline', None); project.setdefault('history', [])
    if len(json.dumps(project).encode()) > 300000:
        raise ValueError('Partmap project must fit within 300 KB.')
    return project

def executable(location):
    path = Path(location)
    if not path.is_absolute() or not path.is_file() or (os.name == 'nt' and path.suffix.lower() != '.exe'):
        raise ValueError('Configure the absolute path to the installed executable (.exe), not a shell script or command line.')
    return str(path.resolve())

def run(command, cwd, timeout=30, env=None):
    result = subprocess.run(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            timeout=timeout, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    output = result.stdout.decode('utf-8', 'replace')
    if result.returncode:
        raise ValueError('Program returned an error: ' + output[-5000:])
    return output[:30000]

def git_action(root, location, args, private):
    action = args.get('action')
    if action not in ('status','diff','log','init','stage','commit'):
        raise ValueError('Choose status, diff, log, init, stage, or commit. Remote and shell commands are unavailable.')
    gitdir = root / '.git'
    if gitdir.exists():
        if not gitdir.is_dir() or reparse(gitdir):
            raise ValueError('Linked worktrees and external Git directories are not supported by the scoped adapter.')
        for folder, dirs, files in os.walk(gitdir, followlinks=False):
            for name in dirs + files:
                p = Path(folder) / name
                if reparse(p) or (p.is_file() and p.stat().st_nlink > 1):
                    raise ValueError('Git metadata cannot contain links outside the project.')
        config = (gitdir / 'config').read_text(encoding='utf-8', errors='replace') if (gitdir / 'config').exists() else ''
        if re.search(r'^\s*\[\s*(filter|include|includeIf|alias|extensions|submodule)\b', config, re.I | re.M):
            raise ValueError('This repository uses configuration that can run external programs or reference other directories. Use standard Git manually for this repository.')
        alternate = gitdir / 'objects/info/alternates'
        if alternate.exists() and alternate.read_text().strip():
            raise ValueError('External Git object stores are not supported.')
    elif action != 'init':
        raise ValueError('Initialize a project-local Git repository first.')
    hooks = private / 'empty-hooks'; hooks.mkdir(parents=True, exist_ok=True)
    env = {k:v for k,v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull, GIT_ATTR_NOSYSTEM='1',
               GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='Never', GIT_AUTHOR_NAME='Character Room', GIT_AUTHOR_EMAIL='character-room@localhost',
               GIT_COMMITTER_NAME='Character Room', GIT_COMMITTER_EMAIL='character-room@localhost')
    prefix = [executable(location), '--no-pager', '--literal-pathspecs', '-c', 'core.hooksPath='+str(hooks), '-c', 'core.fsmonitor=false',
              '-c', 'core.attributesFile='+os.devnull, '-c', 'core.quotePath=false', '-c', 'commit.gpgsign=false',
              '--git-dir='+str(gitdir), '--work-tree='+str(root)]
    if action == 'init':
        return {'output': run(prefix + ['init'], root, env=env)}
    if action == 'status': command = ['status', '--short', '--untracked-files=normal']
    elif action == 'diff': command = ['diff', '--no-ext-diff', '--no-textconv', '--', '.']
    elif action == 'log': command = ['log', '-10', '--format=%h %s']
    elif action == 'stage':
        paths = args.get('paths')
        if not isinstance(paths, list) or not 1 <= len(paths) <= 50:
            raise ValueError('Stage 1–50 explicit project files.')
        checked = [str(scoped(root, p).relative_to(root)) for p in paths]
        command = ['add', '--'] + checked
    else:
        message = args.get('message')
        if not isinstance(message, str) or not 1 <= len(message.strip()) <= 1000:
            raise ValueError('Supply a commit message of 1–1000 characters.')
        staged = run(prefix + ['diff','--cached','--name-only','-z','--no-ext-diff'], root, env=env)
        for name in staged.split('\0'):
            if name: scoped(root, name)
        command = ['commit', '--no-verify', '-m', message]
    return {'output': run(prefix + command, root, env=env)}

def cad_spec(root, args):
    stem = args.get('output', '')
    if not isinstance(stem, str) or not stem or Path(stem).suffix:
        raise ValueError('Choose a new output stem without an extension, such as models/bracket.')
    outputs = {key: scoped(root, stem+ext) for key,ext in [('fcstd','.FCStd'),('step','.step'),('stl','.stl'),('spec','.cad.json')]}
    if any(p.exists() for p in outputs.values()):
        raise ValueError('Model output already exists. Choose a new output stem to preserve it.')
    shapes = args.get('shapes')
    if not isinstance(shapes, list) or not 1 <= len(shapes) <= 32:
        raise ValueError('Use 1–32 declarative shapes.')
    result = []
    for index, shape in enumerate(shapes):
        if not isinstance(shape, dict) or shape.get('type') not in ('box','cylinder','sphere','cone'):
            raise ValueError('Supported shapes: box, cylinder, sphere, cone.')
        kind = shape['type']; op = shape.get('operation', 'add')
        if op not in ('add','cut') or (index == 0 and op != 'add'):
            raise ValueError('Use add/cut operations, with an additive first shape.')
        item = {'type':kind,'operation':op}
        required = {'box':['length','width','height'],'cylinder':['radius','height'],'sphere':['radius'],'cone':['radius','radius2','height']}[kind]
        for key in required + ['x','y','z','rx','ry','rz']:
            value = shape.get(key, 0)
            if type(value) not in (int,float) or not math.isfinite(value) or abs(value)>10000 or (key in required and value <= 0):
                raise ValueError('Supply finite positive dimensions and bounded positions (mm) and rotations (degrees).')
            item[key]=value
        result.append(item)
    return outputs, result

CAD_RUNNER = '''import json, os
import FreeCAD as App
import Part, Mesh
spec=json.load(open(SPEC_PATH, encoding="utf-8"))
doc=App.newDocument("CharacterRoomModel")
current=None
for i,s in enumerate(spec["shapes"]):
    kind=s["type"]
    feature=doc.addObject({"box":"Part::Box","cylinder":"Part::Cylinder","sphere":"Part::Sphere","cone":"Part::Cone"}[kind],"Primitive"+str(i))
    if kind=="box": feature.Length=s["length"]; feature.Width=s["width"]; feature.Height=s["height"]
    elif kind=="cylinder": feature.Radius=s["radius"]; feature.Height=s["height"]
    elif kind=="sphere": feature.Radius=s["radius"]
    else: feature.Radius1=s["radius"]; feature.Radius2=s["radius2"]; feature.Height=s["height"]
    feature.Placement=App.Placement(App.Vector(s["x"],s["y"],s["z"]),App.Rotation(s["rz"],s["ry"],s["rx"]))
    if current is None: current=feature
    else:
        combined=doc.addObject("Part::Cut" if s["operation"]=="cut" else "Part::Fuse","Result"+str(i))
        combined.Base=current; combined.Tool=feature
        current=combined
    doc.recompute()
if current.Shape.isNull() or not current.Shape.isValid(): raise ValueError("The resulting CAD shape is empty or invalid.")
current.Label="Final model"
doc.recompute()
doc.saveAs(spec["outputs"]["fcstd"])
Part.export([current],spec["outputs"]["step"])
Mesh.export([current],spec["outputs"]["stl"])
print("CHARACTER_ROOM_CAD_OK", flush=True)
App.closeDocument(doc.Name)
'''

def cad_create(root, location, args, private):
    outputs, shapes = cad_spec(root, args)
    outputs['fcstd'].parent.mkdir(parents=True, exist_ok=True)
    for path in outputs.values(): scoped(root, str(path.relative_to(root)))
    job = private / 'cad-jobs' / uuid.uuid4().hex; job.mkdir(parents=True)
    spec = {'shapes': shapes, 'outputs':{key:str(value) for key,value in outputs.items()}}
    specfile=job/'spec.json'; specfile.write_text(json.dumps(spec), encoding='utf-8')
    runner=job/'run.py'; runner.write_text('SPEC_PATH='+repr(str(specfile))+'\n'+CAD_RUNNER, encoding='utf-8')
    env={k:v for k,v in os.environ.items() if not k.startswith('PYTHON')}
    output=run([executable(location), str(runner)], job, timeout=120, env=env)
    if 'CHARACTER_ROOM_CAD_OK' not in output or not all(outputs[key].is_file() for key in ('fcstd','step','stl')):
        raise ValueError('FreeCAD did not produce all requested model files: '+output[-3000:])
    write_text(root, str(outputs['spec'].relative_to(root)), json.dumps({'shapes':shapes}, indent=2))
    return {'files':[str(p.relative_to(root)) for p in outputs.values()], 'units':'mm', 'output':output[-2000:]}

def discover():
    local = Path(os.environ.get('LOCALAPPDATA',''))
    vscode = local/'Programs/Microsoft VS Code/Code.exe'
    freecad = next((p/'bin/freecadcmd.exe' for p in sorted(Path(os.environ.get('PROGRAMFILES','C:/Program Files')).glob('FreeCAD*'), reverse=True) if (p/'bin/freecadcmd.exe').exists()), None)
    return {'vscode':str(vscode) if vscode.exists() else '', 'git':shutil.which('git') or '', 'freecad':str(freecad) if freecad else ''}

class ToolService:
    def __init__(self, db, app_root, private):
        self.db=db; self.app_root=Path(app_root).resolve(); self.private=Path(private)

    def initialize(self):
        with self.db() as con:
            con.executescript('''CREATE TABLE IF NOT EXISTS registered_tools(id TEXT PRIMARY KEY,name TEXT NOT NULL,adapter TEXT NOT NULL,location TEXT NOT NULL,enabled INTEGER NOT NULL);
              CREATE TABLE IF NOT EXISTS character_tools(character_id TEXT NOT NULL REFERENCES characters(id) ON DELETE CASCADE,tool_id TEXT NOT NULL REFERENCES registered_tools(id) ON DELETE CASCADE,PRIMARY KEY(character_id,tool_id));
              CREATE TABLE IF NOT EXISTS tool_events(id TEXT PRIMARY KEY,chat_id TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,character_id TEXT NOT NULL,round_id TEXT NOT NULL,call_key TEXT NOT NULL UNIQUE,operation TEXT NOT NULL,arguments TEXT NOT NULL,status TEXT NOT NULL,result TEXT NOT NULL,created REAL NOT NULL);''')
            for adapter,(name,_) in ADAPTERS.items():
                con.execute('INSERT OR IGNORE INTO registered_tools VALUES (?,?,?,?,1)', (adapter,name,adapter,''))

    def registry(self):
        with self.db() as con:
            return [dict(r) for r in con.execute('SELECT * FROM registered_tools ORDER BY name')]

    def save_registry(self, data):
        adapter=data.get('adapter'); name=data.get('name'); location=data.get('location','')
        if adapter not in ADAPTERS or not isinstance(name,str) or not 1<=len(name.strip())<=100 or not isinstance(location,str) or len(location)>1000:
            raise ValueError('Choose an adapter, a name, and an absolute application location.')
        if adapter in ('vscode','git','freecad') and location:
            location=executable(location)
        if adapter=='partmap' and location:
            directory=Path(location).resolve()
            if not directory.is_dir() or not all((directory/f).is_file() for f in ('index.html','app.js','style.css')):
                raise ValueError('Choose the Partmap dist folder containing index.html, app.js, and style.css.')
            location=str(directory)
            with self.db() as con:
                for row in con.execute("SELECT project_dir FROM chats WHERE project_dir!=''"):
                    root=Path(row['project_dir']).resolve()
                    if directory.is_relative_to(root) or root.is_relative_to(directory):
                        raise ValueError('Keep the Partmap application source separate from bot project directories.')
        if adapter in ('files_read','files_write'): location=''
        record_id=data.get('id') or uuid.uuid4().hex[:12]
        if not isinstance(record_id,str) or not re.fullmatch(r'[a-zA-Z0-9_]{1,40}',record_id):
            raise ValueError('Invalid tool ID.')
        with self.db() as con:
            con.execute('INSERT INTO registered_tools VALUES (?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,adapter=excluded.adapter,location=excluded.location,enabled=excluded.enabled',
                        (record_id,name.strip(),adapter,location,int(data.get('enabled') is True)))
        return record_id

    def validate_project(self, value):
        value=project_directory(value,self.app_root)
        if value:
            root=Path(value)
            for tool in self.registry():
                if tool['adapter']=='partmap' and tool['location']:
                    source=Path(tool['location']).resolve()
                    if source.is_relative_to(root) or root.is_relative_to(source):
                        raise ValueError('Choose a work folder separate from the Partmap application source.')
        return value

    def permissions(self, con, character_id):
        return [r['tool_id'] for r in con.execute('SELECT tool_id FROM character_tools WHERE character_id=? ORDER BY tool_id',(character_id,))]

    def set_permissions(self, con, character_id, ids):
        if not isinstance(ids,list) or len(ids)>50 or any(not isinstance(value,str) for value in ids):
            raise ValueError('Select valid tool permissions.')
        existing={r['id'] for r in con.execute('SELECT id FROM registered_tools')}
        if not set(ids)<=existing: raise ValueError('One or more selected tools no longer exist.')
        con.execute('DELETE FROM character_tools WHERE character_id=?',(character_id,))
        con.executemany('INSERT INTO character_tools VALUES (?,?)',[(character_id,record_id) for record_id in set(ids)])

    def available(self, character_id, chat):
        if not chat.get('project_dir'): return []
        with self.db() as con:
            return [dict(r) for r in con.execute('SELECT t.* FROM registered_tools t JOIN character_tools p ON p.tool_id=t.id WHERE p.character_id=? AND t.enabled=1',(character_id,)) if r['adapter'] in ('files_read','files_write') or r['location']]

    def schemas(self, character_id, chat):
        result=[]
        for tool in self.available(character_id,chat):
            for operation,description,args in ADAPTERS[tool['adapter']][1]:
                properties={key:{'type':value} for key,value in args.items()}
                for key in ('paths',):
                    if key in properties: properties[key]['items']={'type':'string'}
                if 'shapes' in properties: properties['shapes']['items']={'type':'object'}
                required={'list_files':[], 'read_text':['path'], 'write_text':['path','content'], 'open_editor':['path'], 'git':['action'], 'parts_read':['path'], 'parts_write':['path','project'], 'cad_create':['output','shapes']}[operation]
                result.append({'type':'function','function':{'name':tool['id']+'__'+operation,'description':description,'parameters':{'type':'object','properties':properties,'required':required,'additionalProperties':False}}})
        return result

    def dispatch(self, character_id, chat, name, args):
        if not isinstance(args,dict): raise ValueError('Tool arguments must be an object.')
        if not isinstance(name,str) or '__' not in name: raise ValueError('Unknown tool.')
        tool_id,operation=name.split('__',1)
        tool=next((t for t in self.available(character_id,chat) if t['id']==tool_id),None)
        if not tool or operation not in [op[0] for op in ADAPTERS[tool['adapter']][1]]:
            raise ValueError('This character does not have permission to use that tool.')
        root=Path(self.validate_project(chat['project_dir']))
        with project_lock(root):
            if operation=='list_files': return list_files(root,args.get('path','.'))
            if operation=='read_text': return read_text(root,args.get('path'),args.get('start_line',1),args.get('line_count',300))
            if operation=='write_text': return write_text(root,args.get('path'),args.get('content'),args.get('expected_sha256',''))
            if operation=='open_editor':
                target=scoped(root,args.get('path'))
                if not target.is_file(): raise ValueError('Create the project file before opening it in VS Code.')
                env={k:v for k,v in os.environ.items() if k!='ELECTRON_RUN_AS_NODE'}
                subprocess.Popen([executable(tool['location']),'--reuse-window',str(target)],cwd=root,env=env,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                return {'opened':str(target.relative_to(root)), 'application':'VS Code'}
            if operation=='git': return git_action(root,tool['location'],args,self.private)
            if operation=='parts_read':
                result=read_text(root,args.get('path'),whole=True);result['project']=validate_parts(json.loads(result.pop('content')));return result
            if operation=='parts_write':
                if not str(args.get('path','')).lower().endswith('.json'):raise ValueError('Use a .json file for Partmap projects.')
                project=validate_parts(args.get('project'));return write_text(root,args.get('path'),json.dumps(project,indent=2),args.get('expected_sha256',''))
            if operation=='cad_create':return cad_create(root,tool['location'],args,self.private)
        raise ValueError('Unknown tool operation.')
