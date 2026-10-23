import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

import test_server as fixture
app=fixture.app
import tool_runtime as runtime

class ProjectToolTests(unittest.TestCase):
    request=fixture.CharacterRoomTests.request
    chat=fixture.CharacterRoomTests.chat

    def setUp(self):
        fixture.CharacterRoomTests.setUp(self)
        work=Path(__file__).resolve().parents[3]/'work'
        self.folder=tempfile.TemporaryDirectory(dir=work)
        self.root=Path(self.folder.name)/'project';self.root.mkdir()
        self.outside=Path(self.folder.name)/'outside';self.outside.mkdir()
        (self.outside/'secret.txt').write_text('outside data',encoding='utf-8')
        self.person,self.chat_id=self.chat()
        self.request('/api/chats/'+self.chat_id,{'project_dir':str(self.root)})

    def tearDown(self):
        fixture.CharacterRoomTests.tearDown(self)
        self.folder.cleanup()

    def grant(self,*ids):
        c=dict(self.person);c['tool_ids']=list(ids)
        self.request('/api/characters/'+c['id'],c)
        self.person=c

    def dispatch(self,name,args):
        return app.TOOLS.dispatch(self.person['id'],{'id':self.chat_id,'project_dir':str(self.root)},name,args)

    def test_no_tools_without_permission_or_project(self):
        self.assertEqual(app.TOOLS.schemas(self.person['id'],{'project_dir':str(self.root)}),[])
        with self.assertRaises(ValueError):self.dispatch('files_write__write_text',{'path':'test.txt','content':'x'})
        self.grant('files_read','files_write')
        self.assertEqual(app.TOOLS.schemas(self.person['id'],{'project_dir':''}),[])

    def test_create_read_edit_and_concurrent_change_protection(self):
        self.grant('files_read','files_write')
        result=self.dispatch('files_write__write_text',{'path':'src/hello.py','content':'print("hello")\n'})
        read=self.dispatch('files_read__read_text',{'path':'src/hello.py'})
        self.assertEqual(read['sha256'],result['sha256'])
        with self.assertRaises(ValueError):self.dispatch('files_write__write_text',{'path':'src/hello.py','content':'lost'})
        self.dispatch('files_write__write_text',{'path':'src/hello.py','content':'print("updated")\n','expected_sha256':read['sha256']})
        with self.assertRaises(ValueError):self.dispatch('files_write__write_text',{'path':'src/hello.py','content':'stale','expected_sha256':read['sha256']})
        self.assertEqual((self.root/'src/hello.py').read_text(),'print("updated")\n')

    def test_traversal_absolute_paths_and_metadata_denied(self):
        self.grant('files_read','files_write')
        for path in ['../outside/secret.txt',str(self.outside/'secret.txt'),'C:relative.txt','C:/Windows/test.txt','//server/share/file','data.txt:stream','.git/config','.vscode/tasks.json','.env','NUL.txt','a/../b.txt']:
            with self.subTest(path=path),self.assertRaises(ValueError):self.dispatch('files_write__write_text',{'path':path,'content':'bad'})
        self.assertEqual((self.outside/'secret.txt').read_text(),'outside data')

    def test_hard_links_denied(self):
        self.grant('files_read','files_write')
        os.link(self.outside/'secret.txt',self.root/'linked.txt')
        with self.assertRaises(ValueError):self.dispatch('files_read__read_text',{'path':'linked.txt'})

    def test_junction_or_symlink_escape_denied(self):
        self.grant('files_read','files_write');link=self.root/'escape'
        if os.name=='nt':
            result=subprocess.run(['cmd.exe','/c','mklink','/J',str(link),str(self.outside)],capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
        else:link.symlink_to(self.outside,target_is_directory=True)
        with self.assertRaises(ValueError):self.dispatch('files_read__read_text',{'path':'escape/secret.txt'})
        with self.assertRaises(ValueError):self.dispatch('files_write__write_text',{'path':'escape/new.txt','content':'bad'})

    def test_global_disable_and_permission_revocation(self):
        self.grant('files_write')
        app.TOOLS.save_registry({'id':'files_write','name':'Write','adapter':'files_write','enabled':False})
        with self.assertRaises(ValueError):self.dispatch('files_write__write_text',{'path':'test.txt','content':'no'})
        app.TOOLS.save_registry({'id':'files_write','name':'Write','adapter':'files_write','enabled':True})
        self.grant()
        with self.assertRaises(ValueError):self.dispatch('files_write__write_text',{'path':'test.txt','content':'no'})

    def test_audited_retry_reuses_success_but_checks_current_permission(self):
        self.grant('files_write')
        handler=app.Handler.__new__(app.Handler);events=[]
        chat={'id':self.chat_id,'project_dir':str(self.root)}
        args={'path':'retry.txt','content':'only once'}
        first=handler.audited_tool(chat,self.person,'test-round','files_write__write_text',args,0,0,events.append)
        again=handler.audited_tool(chat,self.person,'test-round','files_write__write_text',args,0,0,events.append)
        self.assertEqual(first,again);self.assertTrue(events[-1]['cached'])
        self.grant()
        denied=handler.audited_tool(chat,self.person,'test-round','files_write__write_text',args,0,0,events.append)
        self.assertIn('error',denied)

    def test_paginated_reads_cover_complete_file(self):
        self.grant('files_read')
        (self.root/'long.txt').write_text(''.join(f'line {i}\n' for i in range(500)),encoding='utf-8')
        first=self.dispatch('files_read__read_text',{'path':'long.txt'})
        second=self.dispatch('files_read__read_text',{'path':'long.txt','start_line':first['next_line']})
        self.assertFalse(first['complete']);self.assertTrue(second['complete'])
        self.assertEqual(first['sha256'],second['sha256'])
        self.assertEqual(first['content']+second['content'],(self.root/'long.txt').read_bytes().decode('utf-8'))

    def test_native_model_tool_call_executes_and_is_audited(self):
        self.grant('files_read','files_write')
        original=app.urlopen;count=0
        def model(req,timeout=None):
            nonlocal count
            if isinstance(req,str):return original(req,timeout)
            payload=json.loads(req.data);count+=1
            if count==1:
                self.assertIn('files_write__write_text',[s['function']['name'] for s in payload['tools']])
                response={'message':{'content':'','tool_calls':[{'function':{'name':'files_write__write_text','arguments':{'path':'answer.txt','content':'Created through a model tool call.'}}}]},'done':True}
                return io.BytesIO((json.dumps(response)+'\n').encode())
            self.assertTrue(any(m['role']=='tool' and 'sha256' in m['content'] for m in payload['messages']))
            return original(req,timeout)
        app.urlopen=model
        events=self.request('/api/chats/'+self.chat_id+'/reply',{'message':'Create answer.txt'})
        self.assertEqual(events[-1]['type'],'done')
        self.assertEqual((self.root/'answer.txt').read_text(),'Created through a model tool call.')
        saved=self.request('/api/chats/'+self.chat_id)
        self.assertEqual(saved['tool_events'][0]['status'],'success')
        self.assertTrue(any(e['type']=='tool_start' for e in events))

    def test_ungranted_model_call_denied_even_if_model_requests_it(self):
        self.grant('files_read')
        original=app.urlopen;count=0
        def model(req,timeout=None):
            nonlocal count
            if isinstance(req,str):return original(req,timeout)
            count+=1
            if count==1:
                return io.BytesIO((json.dumps({'message':{'tool_calls':[{'function':{'name':'files_write__write_text','arguments':{'path':'bad.txt','content':'denied'}}}]},'done':True})+'\n').encode())
            return original(req,timeout)
        app.urlopen=model
        self.request('/api/chats/'+self.chat_id+'/reply',{'message':'Try a disallowed tool'})
        self.assertFalse((self.root/'bad.txt').exists())
        records=self.request('/api/chats/'+self.chat_id)['tool_events']
        self.assertTrue(any(r['operation']=='files_write__write_text' and r['status']=='failed' for r in records))

    def test_unsupported_native_model_uses_json_tools_and_project_prompt(self):
        self.grant('files_read','files_write')
        original=app.urlopen;requests=[]
        def model(req,timeout=None):
            if isinstance(req,str):return original(req,timeout)
            payload=json.loads(req.data);requests.append(payload)
            self.assertIn('not fictional roleplay',payload['messages'][0]['content'])
            self.assertIn('actual project read access',payload['messages'][0]['content'])
            if 'tools' in payload:
                raise urllib.error.HTTPError(req.full_url,400,'Bad Request',{},io.BytesIO(b'{"error":"model does not support tools"}'))
            self.assertEqual(payload['format']['type'],'object')
            self.assertFalse(any(m['role']=='tool' or 'tool_calls' in m for m in payload['messages']))
            envelope={'tool_calls':[{'name':'files_write__write_text','arguments':{'path':'compatible.txt','content':'Real file'}}],'reply':''} if len(requests)==2 else {'tool_calls':[],'reply':'Created the real file.'}
            return io.BytesIO((json.dumps({'message':{'content':json.dumps(envelope)},'done':True})+'\n').encode())
        app.urlopen=model
        events=self.request('/api/chats/'+self.chat_id+'/reply',{'message':'Create compatible.txt'})
        self.assertEqual(events[-1]['type'],'done')
        self.assertEqual((self.root/'compatible.txt').read_text(),'Real file')
        self.assertEqual(''.join(e.get('text','') for e in events if e['type']=='token'),'Created the real file.')
        self.assertTrue(any(e['type']=='tool_mode' for e in events))

    def test_ollama_http_errors_show_the_actual_model_error(self):
        self.grant('files_read')
        original=app.urlopen
        def model(req,timeout=None):
            if isinstance(req,str):return original(req,timeout)
            raise urllib.error.HTTPError(req.full_url,500,'Error',{},io.BytesIO(b'{"error":"model requires more system memory"}'))
        app.urlopen=model
        events=self.request('/api/chats/'+self.chat_id+'/reply',{'message':'Check files'})
        self.assertEqual(events[-1]['type'],'error')
        self.assertIn('model requires more system memory',events[-1]['error'])
        self.assertTrue(any(e['type']=='tool_result' and e['status']=='success' for e in events))

    def test_project_without_grants_uses_work_prompt_without_native_tools(self):
        self.request('/api/chats/'+self.chat_id+'/reply',{'message':'Check files'})
        payload=self.payloads[-1]
        self.assertNotIn('tools',payload)
        self.assertIn('not fictional roleplay',payload['messages'][0]['content'])
        self.assertIn('No project tools',payload['messages'][0]['content'])

    def test_git_local_workflow_and_hooks_disabled(self):
        location=shutil.which('git')
        if not location:self.skipTest('Git is not installed')
        app.TOOLS.save_registry({'id':'git','adapter':'git','name':'Git','location':location,'enabled':True});self.grant('git')
        self.dispatch('git__git',{'action':'init'})
        hook=self.root/'.git/hooks/pre-commit'
        marker=(self.outside/'hook-ran.txt').as_posix()
        hook.write_text('#!/bin/sh\necho unsafe > "'+marker+'"\n',encoding='utf-8');hook.chmod(0o755)
        (self.root/'notes.txt').write_text('project contents',encoding='utf-8')
        self.dispatch('git__git',{'action':'stage','paths':['notes.txt']})
        self.dispatch('git__git',{'action':'commit','message':'Scoped project commit'})
        self.assertFalse((self.outside/'hook-ran.txt').exists())
        self.assertIn('Scoped project commit',self.dispatch('git__git',{'action':'log'})['output'])
        for action in ['push','pull','clone','reset','checkout','shell']:
            with self.assertRaises(ValueError):self.dispatch('git__git',{'action':action})

    def test_parts_round_trip_and_invalid_hierarchy(self):
        app.TOOLS.save_registry({'id':'partmap','adapter':'partmap','name':'Parts','location':'','enabled':True})
        # A configured viewer location is required before its character adapter is exposed.
        source=Path(self.folder.name)/'partmap';source.mkdir()
        for name in ['index.html','app.js','style.css']:(source/name).write_text('test',encoding='utf-8')
        app.TOOLS.save_registry({'id':'partmap','adapter':'partmap','name':'Parts','location':str(source),'enabled':True});self.grant('partmap')
        project={'name':'Robot','nodes':[{'id':'board','name':'ESP32','category':'board','quantity':1,'parent':None}]}
        self.dispatch('partmap__parts_write',{'path':'parts.json','project':project})
        result=self.dispatch('partmap__parts_read',{'path':'parts.json'})
        self.assertEqual(result['project']['nodes'][0]['name'],'ESP32')
        project['nodes'][0]['parent']='board'
        with self.assertRaises(ValueError):self.dispatch('partmap__parts_write',{'path':'parts.json','project':project,'expected_sha256':result['sha256']})
        with self.assertRaises(ValueError):app.TOOLS.validate_project(str(source))

    def test_cad_declarative_validation_rejects_paths_and_code(self):
        for args in [{'output':'../outside/model','shapes':[{'type':'sphere','radius':5}]},{'output':'model','shapes':[{'type':'box','length':'__import__("os")','width':1,'height':1}]},{'output':'model','shapes':[{'type':'sphere','radius':-1}]},{'output':'model','shapes':[{'type':'sphere','radius':1,'operation':'cut'}]}]:
            with self.assertRaises(ValueError):runtime.cad_spec(self.root,args)
        outputs,shapes=runtime.cad_spec(self.root,{'output':'models/demo','shapes':[{'type':'box','length':20,'width':10,'height':4},{'type':'cylinder','radius':2,'height':6,'x':5,'y':5,'z':-1,'operation':'cut'}]})
        self.assertTrue(outputs['fcstd'].is_relative_to(self.root));self.assertEqual(shapes[1]['operation'],'cut')

    def test_pc_only_registry_and_project_changes(self):
        self.server.is_lan=True;app.NETWORK_CODE='TEST-CODE'
        token='test-session';app.NETWORK_SESSIONS.add(token)
        headers={'X-Character-Room':'1','Content-Type':'application/json','Cookie':'character_room_session='+token}
        try:
            for path,data in [('/api/tools',{'name':'bad','adapter':'files_write','enabled':True}),('/api/chats/'+self.chat_id,{'project_dir':str(self.outside)}),('/api/characters/'+self.person['id'],dict(self.person,tool_ids=['files_write']))]:
                with self.assertRaises(urllib.error.HTTPError) as error:self.request(path,data,headers)
                self.assertEqual(error.exception.code,403)
        finally:self.server.is_lan=False;app.NETWORK_SESSIONS.clear();app.NETWORK_CODE=''

if __name__=='__main__':unittest.main(verbosity=2)
