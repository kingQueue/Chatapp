import importlib.util
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.request
import urllib.error

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
        def fake_open(req, timeout=None):
            if isinstance(req, str) and req.endswith('/api/tags'):
                return io.BytesIO(json.dumps({'models':[{'name':'qwen3:8b'},{'name':'private-cloud'}]}).encode())
            self.payloads.append(json.loads(req.data))
            if self.fail:
                raise urllib.error.URLError('offline')
            return io.BytesIO(b'{"message":{"content":"A distinctive "}}\n{"message":{"content":"reply."},"done":true}\n')
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
        self.assertEqual(self.request('/api/models')['models'],['qwen3:8b'])

    def test_separate_conversations_and_renaming(self):
        c,first=self.chat()
        second=self.request('/api/chats',{'character_id':c['id']})['id']
        self.request('/api/chats/'+first,{'memory':'first only','title':'Private story'})
        self.assertEqual(self.request('/api/chats/'+second)['memory'],'')
        self.assertEqual(self.request('/api/chats/'+first)['title'],'Private story')
        self.request('/api/chats/'+first,{'delete':True})
        self.assertEqual(self.request('/api/chats/'+second)['id'],second)

if __name__=='__main__':unittest.main(verbosity=2)

