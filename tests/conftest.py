from pathlib import Path
import json,sys,threading,time
import httpx,pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from langcas.config import Config
from langcas.app import App,Server
from langcas.db import FINAL
FIXTURE=ROOT/'tests/fixtures/cli_fixture.py'

def configured(directory):
 c=Config(directory)
 c.raw['runners']=[{'id':'fixture','name':'Testprozess (keine KI)','adapter':'generic','command':sys.executable,
  'args':[str(FIXTURE)],'enabled':True,'permission':'read-only','timeout':4,'input':'json','output':'jsonl','priority':1},
  {'id':'writer','name':'Freigabe-Testprozess','adapter':'generic','command':sys.executable,'args':[str(FIXTURE)],
   'enabled':True,'permission':'workspace-write','timeout':4,'input':'json','output':'jsonl'},
  {'id':'missing','name':'Fehlend','adapter':'generic','command':'langkas-this-executable-does-not-exist','enabled':True},
  {'id':'disabled','name':'Deaktiviert','adapter':'generic','command':sys.executable,'enabled':False}]
 c.save(c.raw);return c

class Harness:
 def __init__(self,path):
  configured(path);self.path=path;self.app=App(path);self.server=Server(('127.0.0.1',0),self.app)
  self.url=f'http://127.0.0.1:{self.server.server_address[1]}'
  self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
  self.client=httpx.Client(base_url=self.url,headers={'Authorization':'Bearer '+self.app.config.token},timeout=15,trust_env=False)
 def close(self):
  self.client.close();self.server.shutdown();self.server.server_close();self.app.close();self.thread.join(2)
 def submit(self,prompt='Servas',**kw):
  r=self.client.post('/api/runs',json={'prompt':prompt,**kw});assert r.status_code==202,r.text;return r.json()
 def wait(self,rid,expected=None,seconds=8):
  end=time.monotonic()+seconds
  while time.monotonic()<end:
   r=self.client.get('/api/runs/'+rid).json()
   if (expected and r['status']==expected) or (not expected and r['status'] in FINAL): return r
   time.sleep(.02)
  raise AssertionError('timeout '+str(r))
 def edit(self,fn):
  s=self.client.get('/api/state').json();fn(s['state']);r=self.client.put('/api/state',json=s);assert r.status_code==200,r.text;return r.json()

@pytest.fixture
def server(tmp_path):
 h=Harness(tmp_path/'data')
 yield h
 h.close()
