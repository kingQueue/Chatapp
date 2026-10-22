import importlib.util
import base64
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.request
import urllib.error
import sqlite3

SOURCE = Path(__file__).resolve().parents[1] / 'server.py'
spec = importlib.util.spec_from_file_location('character_room', SOURCE)
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)

class CharacterRoomTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        app.DB_PATH = Path(self.temp.name) / 'library.sqlite3'
        app.initialize()
        self.payloads = []
        self.fail = False
        self.fail_on = None
        self.available = ['qwen3:8b', 'specialist:local']
        self.reply_text = 'A distinctive reply.'
        def fake_open(req, timeout=None):
            if isinstance(req, str) and req.endswith('/api/tags'):
                return io.BytesIO(json.dumps({'models':[{'name':name} for name in self.available + ['private-cloud']]}).encode())
            self.payloads.append(json.loads(req.data))
            if self.fail or len(self.payloads) == self.fail_on:
                raise urllib.error.URLError('offline')
            return io.BytesIO((json.dumps({'message':{'content':self.reply_text},'done':True})+'\n').encode())
        app.urlopen = fake_open
        self.server = app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, path, data=None, headers=None):
        opts = {'Content-Type':'application/json','X-Character-Room':'1'} if headers is None else headers
        req = urllib.request.Request(self.base+path, None if data is None else json.dumps(data).encode(),opts)
        with urllib.request.urlopen(req,timeout=5) as response:
            raw=response.read().decode()
            if response.headers['Content-Type'].startswith('application/x-ndjson'):
                return [json.loads(line) for line in raw.splitlines()]
            return json.loads(raw)

    def chat(self):
        c=self.request('/api/state')['characters'][0]
        return c,self.request('/api/chats',{'character_id':c['id']})['id']

    def test_persona_memory_stream_and_persistence(self):
        c,chat_id=self.chat()
        self.request('/api/chats/'+chat_id,{'memory':'My name is Jun. I love foxes.'})
        result=self.request('/api/chats/'+chat_id+'/reply',{'message':'Hello there'})
        self.assertEqual(result[-1]['type'],'done')
        payload=self.payloads[-1]
        self.assertIn(c['background'],payload['messages'][0]['content'])
        self.assertIn(', '.join(c['tags']),payload['messages'][0]['content'])
        self.assertIn('My name is Jun',payload['messages'][0]['content'])
        self.assertEqual(payload['messages'][-1],{'role':'user','content':'Hello there'})
        app.initialize() # reopen database without reseeding or losing records
        chat=self.request('/api/chats/'+chat_id)
        self.assertEqual(chat['messages'][-1]['content'],'A distinctive reply.')
        self.assertEqual(chat['title'],'Hello there')
        self.assertEqual(len(self.request('/api/state')['characters']),3)

    def test_failure_and_retry_do_not_duplicate_user(self):
        c,chat_id=self.chat();self.fail=True
        result=self.request('/api/chats/'+chat_id+'/reply',{'message':'Remember this'})
        self.assertEqual(result[-1]['type'],'error')
        self.fail=False
        self.request('/api/chats/'+chat_id+'/reply',{'message':''})
        chat=self.request('/api/chats/'+chat_id)
        self.assertEqual([m['content'] for m in chat['messages'] if m['role']=='user'],['Remember this'])

    def test_character_crud_and_cascade(self):
        data=dict(app.DEFAULTS[0]);data['name']='Test <script>';data['tags']=['patient','patient']
        c_id=self.request('/api/characters',data)['id']
        data['name']='Updated';self.request('/api/characters/'+c_id,data)
        chat_id=self.request('/api/chats',{'character_id':c_id})['id']
        self.assertEqual(self.request('/api/state')['characters'][0]['name'],'Updated')
        self.request('/api/characters/'+c_id,{'delete':True})
        with self.assertRaises(urllib.error.HTTPError) as ctx:self.request('/api/chats/'+chat_id)
        self.assertEqual(ctx.exception.code,404)
        with app.db() as con:self.assertEqual(con.execute('SELECT COUNT(*) FROM messages WHERE chat_id=?',(chat_id,)).fetchone()[0],0)

    def test_validation_and_origin_protection(self):
        for data,headers in [({'name':'x'},None), ({},{'Content-Type':'application/json'}), ({},{'X-Character-Room':'1','Origin':'https://untrusted.example'})]:
            with self.assertRaises(urllib.error.HTTPError) as ctx:self.request('/api/characters',data,headers)
            self.assertIn(ctx.exception.code,(400,403))
        for path in ['/data/character-room.sqlite3','/server.py','/../server.py']:
            with self.assertRaises(urllib.error.HTTPError) as ctx:self.request(path)
            self.assertEqual(ctx.exception.code,404)

    def test_export_is_complete_and_cloud_models_excluded(self):
        c,chat_id=self.chat()
        export=self.request('/api/export')
        self.assertEqual(export['format'],'character-room-v1')
        self.assertEqual(export['chats'][0]['id'],chat_id)
        self.assertEqual(len(export['messages']),1)
        self.assertEqual(self.request('/api/models')['models'],['qwen3:8b','specialist:local'])

    def test_separate_conversations_and_renaming(self):
        c,first=self.chat()
        second=self.request('/api/chats',{'character_id':c['id']})['id']
        self.request('/api/chats/'+first,{'memory':'first only','title':'Private story'})
        self.assertEqual(self.request('/api/chats/'+second)['memory'],'')
        self.assertEqual(self.request('/api/chats/'+first)['title'],'Private story')
        self.request('/api/chats/'+first,{'delete':True})
        self.assertEqual(self.request('/api/chats/'+second)['id'],second)

    def test_images_and_voice_settings_round_trip(self):
        data=dict(app.DEFAULTS[0])
        image='data:image/jpeg;base64,'+base64.b64encode(b'\xff\xd8\xfftest\xff\xd9').decode()
        data.update(image_data=image,voice_uri='Windows test voice',speech_rate=1.25,auto_read=True)
        record_id=self.request('/api/characters',data)['id']
        saved=next(c for c in self.request('/api/state')['characters'] if c['id']==record_id)
        self.assertEqual(saved['image_data'],image)
        self.assertEqual(saved['voice_uri'],'Windows test voice')
        self.assertEqual(saved['speech_rate'],1.25)
        self.assertEqual(saved['auto_read'],1)
        app.initialize()
        saved=next(c for c in self.request('/api/export')['characters'] if c['id']==record_id)
        self.assertEqual(saved['image_data'],image)
        # Legacy clients editing the story must not erase media fields.
        self.request('/api/characters/'+record_id,dict(app.DEFAULTS[0]))
        saved=next(c for c in self.request('/api/state')['characters'] if c['id']==record_id)
        self.assertEqual(saved['voice_uri'],'Windows test voice')
        data.update(image_data='',auto_read=False)
        self.request('/api/characters/'+record_id,data)
        saved=next(c for c in self.request('/api/state')['characters'] if c['id']==record_id)
        self.assertEqual(saved['image_data'],'')

    def test_invalid_media_and_voice_values_rejected(self):
        for field,value in [('image_data','data:image/svg+xml;base64,PHN2Zz4='),('image_data','data:image/jpeg;base64,bad!'),('image_data','https://example.com/photo.jpg'),('speech_rate',0),('speech_rate',True),('auto_read','yes')]:
            with self.subTest(field=field,value=value):
                data=dict(app.DEFAULTS[0]);data[field]=value
                with self.assertRaises(urllib.error.HTTPError) as ctx:self.request('/api/characters',data)
                self.assertEqual(ctx.exception.code,400)

    def test_old_database_migration_preserves_existing_records(self):
        app.DB_PATH=Path(self.temp.name)/'old.sqlite3'
        with sqlite3.connect(app.DB_PATH) as con:
            con.executescript('''CREATE TABLE characters(id TEXT PRIMARY KEY,name TEXT NOT NULL,subtitle TEXT NOT NULL,avatar TEXT NOT NULL,color TEXT NOT NULL,tags TEXT NOT NULL,background TEXT NOT NULL,style TEXT NOT NULL,scenario TEXT NOT NULL,greeting TEXT NOT NULL,updated REAL NOT NULL);
              INSERT INTO characters VALUES ('old','Existing character','','*','plum','[]','Original background','','','',0);
              CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
              INSERT INTO settings VALUES ('initialized','true');
              INSERT INTO settings VALUES ('model','qwen3:8b');''')
        app.initialize();app.initialize()
        records=self.request('/api/state')['characters']
        self.assertEqual(len(records),1)
        self.assertEqual(records[0]['background'],'Original background')
        self.assertEqual(records[0]['image_data'],'')
        self.assertEqual(records[0]['speech_rate'],1)

    def test_phone_login_and_remote_management_restrictions(self):
        lan=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);lan.daemon_threads=True;lan.is_lan=True
        thread=threading.Thread(target=lan.serve_forever,daemon=True);thread.start()
        original_base=self.base;self.base=f'http://127.0.0.1:{lan.server_port}'
        app.NETWORK_CODE='A1B2C3-D4E5F6'
        try:
            with self.assertRaises(urllib.error.HTTPError) as ctx:self.request('/api/state')
            self.assertEqual(ctx.exception.code,401)
            with urllib.request.urlopen(self.base) as response:self.assertIn('access code',response.read().decode())
            with self.assertRaises(urllib.error.HTTPError) as ctx:self.request('/api/login',{'code':'wrong'})
            self.assertEqual(ctx.exception.code,401)
            req=urllib.request.Request(self.base+'/api/login',json.dumps({'code':app.NETWORK_CODE}).encode(),{'X-Character-Room':'1','Content-Type':'application/json'})
            with urllib.request.urlopen(req) as response:
                cookie=response.headers['Set-Cookie']
                self.assertIn('HttpOnly',cookie)
                self.assertIn('SameSite=Strict',cookie)
            headers={'Cookie':cookie.split(';')[0],'X-Character-Room':'1','Content-Type':'application/json'}
            self.assertEqual(len(self.request('/api/state',headers=headers)['characters']),3)
            network=self.request('/api/network',headers=headers)
            self.assertFalse(network['can_manage']);self.assertEqual(network['code'],'')
            for path in ['/api/network','/api/shutdown']:
                with self.assertRaises(urllib.error.HTTPError) as ctx:self.request(path,{'enabled':False},headers)
                self.assertEqual(ctx.exception.code,403)
        finally:
            self.base=original_base;lan.shutdown();lan.server_close();thread.join()
            app.NETWORK_CODE='';app.NETWORK_SESSIONS.clear();app.LOGIN_ATTEMPTS.clear()

    def test_phone_listener_binds_only_to_selected_interface(self):
        with patch.object(app,'local_addresses',return_value=['192.168.50.20']), patch.object(app,'ThreadingHTTPServer') as factory, patch.object(app.threading,'Thread'):
            factory.return_value.server_address=('192.168.50.20',8766)
            try:
                result=app.set_network(True,persist=False,address='192.168.50.20')
                factory.assert_called_once_with(('192.168.50.20',8766),app.Handler)
                self.assertEqual(factory.return_value.allowed_hosts,['192.168.50.20'])
                self.assertEqual(result['urls'],['http://192.168.50.20:8766'])
                self.assertNotEqual(result['code'],'')
            finally:
                app.set_network(False,persist=False)
            with self.assertRaises(ValueError):app.set_network(True,persist=False,address='0.0.0.0')

    def team(self):
        characters=self.request('/api/state')['characters'][:2]
        second=dict(characters[1]);second.update(model='specialist:local',specialty='Review plans for missing requirements.')
        self.request('/api/characters/'+second['id'],second)
        chat_id=self.request('/api/groups',{'title':'Project team','memory':'Design a small garden. Budget: 200 dollars.','member_ids':[c['id'] for c in characters]})['id']
        return characters,chat_id

    def test_character_model_override_and_default(self):
        c,chat_id=self.chat();data=dict(c);data.update(model='specialist:local',specialty='Find practical solutions.')
        self.request('/api/characters/'+c['id'],data)
        self.request('/api/chats/'+chat_id+'/reply',{'message':'Help me plan'})
        self.assertEqual(self.payloads[-1]['model'],'specialist:local')
        self.assertIn('Find practical solutions.',self.payloads[-1]['messages'][0]['content'])
        data.update(model='');self.request('/api/characters/'+c['id'],data)
        self.request('/api/chats/'+chat_id+'/reply',{'message':'And now?'})
        self.assertEqual(self.payloads[-1]['model'],'qwen3:8b')

    def test_group_uses_each_model_and_shares_previous_contributions(self):
        people,chat_id=self.team()
        events=self.request('/api/chats/'+chat_id+'/reply',{'message':'Make a concrete plan together.'})
        self.assertEqual(events[-1]['type'],'done')
        self.assertEqual([p['model'] for p in self.payloads],['qwen3:8b','specialist:local'])
        self.assertIn('Budget: 200 dollars',self.payloads[1]['messages'][0]['content'])
        self.assertIn('Review plans for missing requirements.',self.payloads[1]['messages'][0]['content'])
        self.assertTrue(any(people[0]['name'] in m['content'] and 'A distinctive reply.' in m['content'] for m in self.payloads[1]['messages'][1:]))
        saved=self.request('/api/chats/'+chat_id)
        self.assertEqual(saved['kind'],'group')
        self.assertEqual(saved['pending_round'],'')
        self.assertEqual([m['character_id'] for m in saved['messages'][1:]],[c['id'] for c in people])
        self.assertEqual([m['model'] for m in saved['messages'][1:]],['qwen3:8b','specialist:local'])
        self.assertEqual(len(self.request('/api/export')['rounds']),1)

    def test_group_retry_resumes_after_completed_member_without_duplicates(self):
        people,chat_id=self.team();self.fail_on=2
        events=self.request('/api/chats/'+chat_id+'/reply',{'message':'Start the task.'})
        self.assertEqual(events[-1]['type'],'error')
        saved=self.request('/api/chats/'+chat_id)
        self.assertNotEqual(saved['pending_round'],'')
        self.assertEqual(len(saved['messages']),2)
        with self.assertRaises(urllib.error.HTTPError):self.request('/api/chats/'+chat_id+'/reply',{'message':'A conflicting task'})
        app.initialize();self.fail_on=None
        events=self.request('/api/chats/'+chat_id+'/reply',{'message':''})
        self.assertEqual(events[-1]['type'],'done')
        self.assertEqual(self.payloads[-1]['model'],'specialist:local')
        saved=self.request('/api/chats/'+chat_id)
        self.assertEqual(len(saved['messages']),3)
        self.assertEqual(len([m for m in saved['messages'] if m['role']=='user']),1)
        self.assertEqual(len([m for m in saved['messages'] if m['character_id']==people[0]['id']]),1)
        self.assertEqual(saved['pending_round'],'')

    def test_group_validation_and_character_deletion_protection(self):
        people,chat_id=self.team()
        for ids in [[],[people[0]['id']],[people[0]['id']]*2,['missing',people[0]['id']]]:
            with self.assertRaises(urllib.error.HTTPError):self.request('/api/groups',{'title':'Bad team','member_ids':ids})
        with self.assertRaises(urllib.error.HTTPError) as ctx:self.request('/api/characters/'+people[1]['id'],{'delete':True})
        self.assertEqual(ctx.exception.code,400)
        self.assertEqual(self.request('/api/chats/'+chat_id)['member_ids'],[c['id'] for c in people])
        self.request('/api/chats/'+chat_id,{'delete':True})
        self.request('/api/characters/'+people[1]['id'],{'delete':True})

    def test_missing_member_model_keeps_progress_and_allows_reassignment(self):
        people,chat_id=self.team();self.available=['qwen3:8b']
        events=self.request('/api/chats/'+chat_id+'/reply',{'message':'Start a plan.'})
        self.assertEqual(events[-1]['type'],'error')
        self.assertIn('specialist:local',events[-1]['error'])
        self.assertEqual(len(self.payloads),1)
        c=next(c for c in self.request('/api/state')['characters'] if c['id']==people[1]['id'])
        c['model']='';self.request('/api/characters/'+c['id'],c)
        events=self.request('/api/chats/'+chat_id+'/reply',{'message':''})
        self.assertEqual(events[-1]['type'],'done')
        self.assertEqual(len(self.request('/api/chats/'+chat_id)['messages']),3)

    def test_long_group_round_keeps_current_user_task_in_context(self):
        people=self.request('/api/state')['characters'][:3]
        chat_id=self.request('/api/groups',{'title':'Long round','member_ids':[c['id'] for c in people]})['id']
        self.reply_text='Detailed contribution. '*450
        task='The active task must remain visible to every participant.'
        self.request('/api/chats/'+chat_id+'/reply',{'message':task})
        self.assertTrue(any(m['content']==task for m in self.payloads[-1]['messages'][1:]))

if __name__=='__main__':unittest.main(verbosity=2)

