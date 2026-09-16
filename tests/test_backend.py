import copy,json,os,sys,time,subprocess,threading
from pathlib import Path
import httpx,pytest
from langcas.config import Config
from langcas.db import APIError,Database,FINAL,validate_state
from langcas.runners import Decoder,build_command,redact
from conftest import Harness,ROOT

@pytest.mark.parametrize('path',['/api/state','/api/runners','/api/runs','/api/export','/api/search?q=test','/api/audit','/v1/models'])
def test_auth_required(server,path):
 with httpx.Client(base_url=server.url,trust_env=False) as c:
  r=c.get(path);assert r.status_code==401

def test_health_and_self_contained_html(server):
 r=server.client.get('/health');assert r.json()['status']=='ok'
 r=server.client.get('/');assert r.status_code==200 and 'LANGKAS' in r.text and 'liveBoot();' in r.text
 assert 'frame-ancestors' in r.headers['content-security-policy']
 assert 'access-token' not in r.text

@pytest.mark.parametrize('headers',[{'Host':'evil.example'},{'Origin':'https://evil.example'},{'Origin':'null'},{'Sec-Fetch-Site':'cross-site'}])
def test_origin_host_guard(server,headers):
 assert server.client.get('/api/state',headers=headers).status_code==403

@pytest.mark.parametrize('path',['/../../etc/passwd','/runners.json','/access-token','/web/seed.json','/api/runs/unknown','/api/collections/unknown'])
def test_private_paths_not_served(server,path):
 assert server.client.get(path).status_code==404

def test_login_logout_http_only_no_browser_secrets(server):
 with httpx.Client(base_url=server.url,trust_env=False) as c:
  assert c.post('/api/auth/login',json={'token':'wrong'}).status_code==401
  r=c.post('/api/auth/login',json={'token':server.app.config.token});assert r.status_code==200
  assert 'HttpOnly' in r.headers['set-cookie'] and 'SameSite=Strict' in r.headers['set-cookie']
  b=c.get('/api/bootstrap');assert b.status_code==200
  assert server.app.config.token not in b.text
  assert 'command' not in b.json()['runners'][0]
  assert b.json()['runners'][0]['authenticated'] is None
  assert not b.json()['features']['team_auth']
  assert c.post('/api/auth/logout',json={}).status_code==200
  assert c.get('/api/state').status_code==401

def test_bad_json_and_methods(server):
 assert server.client.post('/api/runs',content='{',headers={'Content-Type':'application/json'}).status_code==400
 assert server.client.post('/api/runs',content='{}',headers={'Content-Type':'text/plain'}).status_code==415
 assert server.client.post('/api/runs',json=[]).status_code==422
 assert server.client.post('/api/runs',content='{"prompt":NaN}',headers={'Content-Type':'application/json'}).status_code==400
 assert server.client.options('/api/runs').status_code==403
 assert server.client.put('/api/state',json={'state':{}}).status_code==428

def test_rate_limit(server):
 with httpx.Client(base_url=server.url,trust_env=False) as c:
  for _ in range(10): assert c.post('/api/auth/login',json={'token':'wrong'}).status_code==401
  assert c.post('/api/auth/login',json={'token':'wrong'}).status_code==429

def test_revision_compare_and_swap(server):
 s=server.client.get('/api/state').json();s['state']['profile']['name']='Test';r=server.client.put('/api/state',json=s)
 assert r.status_code==200 and r.json()['revision']==s['revision']+1
 assert server.client.put('/api/state',json=s).status_code==409
 assert server.client.get('/api/state').json()['state']['profile']['name']=='Test'

@pytest.mark.parametrize('alter',[
 lambda s:s['workspace'].update(accent='red;url(evil)'),
 lambda s:s.update(chats={}),lambda s:s['prefs'].update(theme='other'),
 lambda s:s.update(__proto__={'admin':True}),lambda s:s['agents'].append(copy.deepcopy(s['agents'][0])),
 lambda s:s['docs'].append({'id':'d_bad','name':'bad','kind':'image','data':'data:image/svg+xml;base64,PHN2Zz4='})])
def test_invalid_import_atomic(server,alter):
 s=server.client.get('/api/state').json();rev=s['revision'];alter(s['state'])
 r=server.client.post('/api/import',json=s);assert r.status_code==422,r.text
 assert server.client.get('/api/state').json()['revision']==rev

def test_collections_crud(server):
 state=server.client.get('/api/state').json()
 prompt={'id':'p_test','name':'Testprompt','text':'Servas','category':'Produktivität','visibility':'private','star':False}
 r=server.client.post('/api/collections/prompts',json={'revision':state['revision'],'data':prompt});assert r.status_code==200
 r=server.client.patch('/api/collections/prompts/p_test',json={'revision':r.json()['revision'],'data':{'name':'Neu'}});assert r.status_code==200
 v=server.client.get('/api/collections/prompts/p_test').json();assert v['data']['name']=='Neu'
 r=server.client.request('DELETE','/api/collections/prompts/p_test',json={'revision':v['revision']});assert r.status_code==200
 assert server.client.get('/api/collections/prompts/p_test').status_code==404

def test_real_process_unicode_stream_persistence(server):
 r=server.submit('Servas öäü 🧀');done=server.wait(r['id']);assert done['status']=='succeeded',done
 assert 'Servas öäü 🧀' in done['output'] and done['usage']['fixture'] is True
 events=server.app.db.events(r['id']);assert any(e['type']=='process' for e in events)
 assert ''.join(e['data']['text'] for e in events if e['type']=='delta')==done['output']
 assert [e['seq'] for e in events]==list(range(1,len(events)+1))
 c=server.client.get('/api/state').json()['state']['chats'][0];assert c['messages'][-1]['text']==done['output']
 assert c['messages'][-1]['status']=='succeeded'
 assert 'payload' not in done

def test_sse_replay_last_event_id(server):
 r=server.submit();server.wait(r['id'])
 full=server.client.get('/api/runs/'+r['id']+'/events').text
 assert 'event: done' in full and 'event: delta' in full
 subset=server.client.get('/api/runs/'+r['id']+'/events',headers={'Last-Event-ID':'2'}).text
 assert '\nid: 1\n' not in '\n'+subset and '\nid: 2\n' not in '\n'+subset
 assert full.endswith('}\n\n')

def test_history_and_model_switch(server):
 one=server.submit('FIRST_SECRET_CONTEXT');server.wait(one['id'])
 two=server.submit('[CONTEXT] second',chat_id=one['chat_id']);done=server.wait(two['id'])
 assert 'FIRST_SECRET_CONTEXT' in done['output']
 assert len(server.app.db.state()['state']['chats'][0]['messages'])==4

def test_agent_project_documents_skills_context(server):
 def setup(s):
  s['projects']=[{'id':'p','name':'Project','description':'','color':'blue','instructions':'PROJECT_RULE','knowledge':['d1']}]
  s['agents'][0].update(instructions='AGENT_RULE',knowledge=['d2'])
  s['docs']=[{'id':'d1','name':'project.md','text':'PROJECT_DOCUMENT','kind':'text','size':16,'created':0},
             {'id':'d2','name':'agent.md','text':'AGENT_DOCUMENT','kind':'text','size':14,'created':0}]
  s['skills']=[{'id':'s1','name':'Skill','text':'SKILL_RULE','enabled':True,'category':'Allgemein'}]
 server.edit(setup);agent=server.app.db.state()['state']['agents'][0]['id']
 r=server.submit('[CONTEXT]',agent=agent,project='p');done=server.wait(r['id'])
 assert done['status']=='succeeded'
 for token in ['PROJECT_RULE','AGENT_RULE','PROJECT_DOCUMENT','AGENT_DOCUMENT','SKILL_RULE']:assert token in done['output']

def test_text_upload_search_download(server):
 r=server.client.post('/api/files',json={'name':'Geheim ö.md','text':'ATTACHMENT_DATA'});assert r.status_code==201
 d=r.json()['file'];assert len(d['sha256'])==64
 assert server.client.get('/api/files/'+d['id']+'/download').text=='ATTACHMENT_DATA'
 assert server.client.get('/api/search?q=ATTACHMENT_DATA').json()['results'][0]['id']==d['id']
 run=server.submit('[CONTEXT]',files=[d['id']]);assert 'ATTACHMENT_DATA' in server.wait(run['id'])['output']

@pytest.mark.parametrize('patch,status',[{'provider':'missing'},{'provider':'disabled'}] if False else [({'provider':'missing'},503),({'provider':'disabled'},503),({'provider':'bogus'},503),({'command':'sh'},422),({'args':['-c','whoami']},422),({'workspace':'/etc'},422),({'workspace':'not_registered'},422),({'model':'--dangerous'},422),({'files':['absent']},404),({'agent':'absent'},404),({'prompt':''},422),({'prompt':'a'*50001},422)])
def test_bad_runs_fail_explicitly(server,patch,status):
 r=server.client.post('/api/runs',json={'prompt':'test',**patch});assert r.status_code==status,r.text
 assert server.client.get('/api/runs').json()['runs']==[]

def test_idempotent_submission(server):
 payload={'prompt':'[DELAY] test'};headers={'Idempotency-Key':'same_request'}
 a=server.client.post('/api/runs',json=payload,headers=headers).json()
 b=server.client.post('/api/runs',json=payload,headers=headers).json();assert a['id']==b['id']
 assert server.client.post('/api/runs',json={'prompt':'other'},headers=headers).status_code==409
 assert server.wait(a['id'])['status']=='succeeded'
 assert len(server.client.get('/api/runs').json()['runs'])==1

def test_same_chat_lock_and_active_state_protection(server):
 r=server.submit('[DELAY] one');s=server.app.db.state()
 assert server.client.post('/api/runs',json={'prompt':'second','chat_id':r['chat_id']}).status_code==409
 s['state']['chats'][0]['messages']=[];assert server.client.put('/api/state',json=s).status_code==409
 assert server.wait(r['id'])['status']=='succeeded'

def test_concurrency_bounded_two(server):
 runs=[server.submit('[DELAY] job '+str(i)) for i in range(5)]
 max_count=0;end=time.monotonic()+8
 while time.monotonic()<end:
  with server.app.engine.lock: count=len(server.app.engine.processes)
  max_count=max(max_count,count);assert count<=2
  if all(server.app.db.run(r['id'])['status'] in FINAL for r in runs):break
  time.sleep(.01)
 assert max_count==2
 assert all(server.app.db.run(r['id'])['status']=='succeeded' for r in runs)

@pytest.mark.parametrize('prompt,error',[('[FAIL]','Exit 7'),('[ERROR]','explicit fixture error'),('[EMPTY]','keinen Antworttext'),('[MALFORMED]','keinen Antworttext'),('[SLEEP]','Zeitlimit'),('[CLOSED_PIPES]','Pipes geschlossen')])
def test_failure_modes_not_fake_success(server,prompt,error):
 r=server.submit(prompt);done=server.wait(r['id']);assert done['status']=='failed',done
 assert error in done['error'],done

def test_cancel_kills_process_and_releases_worker(server):
 r=server.submit('[SLEEP]');server.wait(r['id'],'running')
 end=time.monotonic()+2
 while r['id'] not in server.app.engine.processes and time.monotonic()<end:time.sleep(.01)
 proc=server.app.engine.processes[r['id']]
 assert server.client.post('/api/runs/'+r['id']+'/cancel',json={}).json()['status']=='cancelled'
 end=time.monotonic()+2
 while proc.poll() is None and time.monotonic()<end:time.sleep(.02)
 assert proc.poll() is not None
 assert server.app.db.run(r['id'])['status']=='cancelled'

def test_cancel_closed_pipes_fast(server):
 r=server.submit('[CLOSED_PIPES]');server.wait(r['id'],'running');time.sleep(.2)
 proc=server.app.engine.processes[r['id']];server.client.post('/api/runs/'+r['id']+'/cancel',json={})
 end=time.monotonic()+1.5
 while proc.poll() is None and time.monotonic()<end:time.sleep(.02)
 assert proc.poll() is not None

def test_shell_metacharacters_are_data(server,tmp_path):
 target=tmp_path/'owned';prompt=f'; touch {target}; $(whoami) `id` "quoted"'
 r=server.submit(prompt);done=server.wait(r['id']);assert done['status']=='succeeded'
 assert prompt in done['output'];assert not target.exists()

def test_server_secret_env_not_forwarded(server,monkeypatch):
 monkeypatch.setenv('LANGKAS_TEST_SECRET','must-not-leak')
 r=server.submit('[ENV]');assert server.wait(r['id'])['output']=='[]'

def test_long_stdin_written_completely(server):
 payload='[SIZE]'+'ö'*49000
 args,stdin,_=build_command(server.app.config.runners['fixture'],[{'role':'user','content':payload}])
 r=server.client.post('/v1/chat/completions',json={'model':'fixture','messages':[{'role':'user','content':payload}]})
 assert r.status_code==200,r.text
 assert r.json()['choices'][0]['message']['content']=='bytes='+str(len(stdin))

def test_output_limit(server):
 r=server.submit('[HUGE]');done=server.wait(r['id']);assert done['status']=='failed'
 assert len(done['output'])<=2000000 and ('Limit' in done['error'] or 'limit' in done['error'])

def test_write_approval_and_reject(server):
 r=server.submit('change something',provider='writer');assert r['status']=='awaiting_approval'
 assert not any(e['type']=='process' for e in server.app.db.events(r['id']))
 rr=server.client.post('/api/runs/'+r['id']+'/approve',json={'approve':True});assert rr.status_code==200
 assert server.wait(r['id'])['status']=='succeeded'
 r=server.submit('reject',provider='writer');assert server.client.post('/api/runs/'+r['id']+'/approve',json={'approve':False}).json()['status']=='cancelled'
 assert server.client.post('/api/runs/'+r['id']+'/approve',json={'approve':True}).status_code==409
 assert not any(e['type']=='process' for e in server.app.db.events(r['id']))

def test_workflow_local_real_artifact(server):
 r=server.client.post('/api/workflows/w_notes/run',json={'prompt':'One\nTwo'});assert r.status_code==202
 done=server.wait(r.json()['id']);assert done['status']=='succeeded'
 assert done['output']=='- One\n- Two'
 docs=server.app.db.state()['state']['docs'];assert docs[-1]['text']==done['output']
 assert docs[-1]['runId']==done['id']

def test_workflow_cli_and_approval(server):
 r=server.client.post('/api/workflows/w_review/run',json={'prompt':'REVIEW_ME','provider':'fixture'}).json()
 waiting=server.wait(r['id'],'awaiting_approval');assert 'REVIEW_ME' in waiting['approval']['preview']
 assert server.app.db.state()['state']['docs']==[]
 assert server.client.post('/api/runs/'+r['id']+'/approve',json={'approve':True}).status_code==200
 done=server.wait(r['id']);assert done['status']=='succeeded'
 assert 'REVIEW_ME' in server.app.db.state()['state']['docs'][-1]['text']

def test_workflow_http_rejected(server):
 server.edit(lambda s:s['workflows'][0]['nodes'].append({'id':'n_http','type':'http','name':'Request','config':'http://localhost'}))
 r=server.client.post('/api/workflows/w_notes/run',json={'prompt':'test'});assert r.status_code==501

def test_openai_compatible_nonstream(server):
 r=server.client.post('/v1/chat/completions',json={'model':'fixture','messages':[{'role':'system','content':'RULE'},{'role':'user','content':'[CONTEXT] API'}]})
 assert r.status_code==200,r.text
 obj=r.json();assert obj['object']=='chat.completion' and 'RULE' in obj['choices'][0]['message']['content']
 assert 'usage' not in obj # Never fabricate vendor-compatible token counts.

def test_openai_compatible_stream(server):
 r=server.client.post('/v1/chat/completions',json={'model':'fixture','messages':[{'role':'user','content':'API_STREAM'}],'stream':True})
 assert r.status_code==200 and r.headers['content-type'].startswith('text/event-stream')
 chunks=[json.loads(l[6:]) for l in r.text.splitlines() if l.startswith('data: ') and l!='data: [DONE]']
 assert chunks[-1]['choices'][0]['finish_reason']=='stop'
 assert 'API_STREAM' in ''.join(c['choices'][0]['delta'].get('content','') for c in chunks)
 assert r.text.endswith('data: [DONE]\n\n')

@pytest.mark.parametrize('body,status',[
 ({'messages':[]},422),({'messages':[{'role':'user','content':[{'type':'text','text':'Hi'}]}]},422),
 ({'messages':[{'role':'user','content':'hello'}],'tools':[]},422),
 ({'messages':[{'role':'user','content':'hello'}],'model':'writer'},403),
 ({'messages':[{'role':'user','content':'[FAIL]'}]},502)])
def test_openai_unsupported_explicit(server,body,status):
 assert server.client.post('/v1/chat/completions',json=body).status_code==status

def test_models_list_truthful(server):
 models=server.client.get('/v1/models').json()['data'];assert any(x['id']=='fixture' for x in models)
 assert not any('gpt-5.6' in x['id'] for x in models)

def test_restart_persistence_and_recovery(tmp_path):
 h=Harness(tmp_path/'persistent')
 r=h.submit('Persist');done=h.wait(r['id']);h.close()
 h=Harness(tmp_path/'persistent')
 try:
  assert h.app.db.run(r['id'])['output']==done['output']
  assert h.app.db.state()['state']['chats'][0]['messages'][-1]['text']==done['output']
  pending,created=h.app.db.create_run({'prompt':'do not reexecute','runner':{}},'fixture','queued',None,'hash')
  assert h.app.db.recover()==1
  assert h.app.db.run(pending['id'])['status']=='interrupted'
 finally:h.close()

def test_cli_ask_end_to_end(server):
 env=dict(os.environ,LANGKAS_DATA_DIR=str(server.path))
 p=subprocess.run([sys.executable,'-m','langcas','ask','CLI_COMMAND','--runner','fixture','--port',str(server.server.server_address[1])],cwd=ROOT,env=env,capture_output=True,text=True,timeout=10)
 assert p.returncode==0,p.stderr;assert 'CLI_COMMAND' in p.stdout

def test_config_private_and_registration(tmp_path):
 c=Config(tmp_path/'private');assert c.token_path.stat().st_mode&0o777==0o600
 assert c.directory.stat().st_mode&0o777==0o700
 assert len(c.token)>32
 assert not next(r for r in c.raw['runners'] if r['id']=='codex')['enabled']
 for bad in [{'version':1,'runners':[],'max_concurrency':3},{'version':1,'runners':[{'id':'bad','command':'sh','adapter':'shell'}]}]:
  with pytest.raises(ValueError):c.validate(bad)

def test_vendor_command_permissions_and_no_shell():
 for name in ['claude','gemini','codex']:
  args,stdin,protocol=build_command({'adapter':name,'command':name,'permission':'read-only'},[{'role':'user','content':'$(rm nope)'}])
  assert protocol==name and b'$(rm nope)' in stdin
  assert not any('dangerously' in a or a=='--yolo' for a in args)
  assert ('plan' in args) if name!='codex' else ('read-only' in args)
 args,stdin,proto=build_command({'adapter':'generic','command':'custom','args':['--prompt','{prompt}'],'output':'jsonl'},[{'role':'user','content':'a; b'}])
 assert len(args)==3 and 'a; b' in args[-1] and stdin==b'' and proto=='jsonl'

@pytest.mark.parametrize('protocol,events,expected',[
 ('claude',[{'type':'stream_event','event':{'type':'content_block_delta','delta':{'type':'text_delta','text':'Hello'}}},{'type':'assistant','message':{'content':[{'type':'text','text':'Hello'}]}},{'type':'result','result':'Hello','usage':{'input_tokens':2}}],'Hello'),
 ('claude',[{'type':'assistant','message':{'content':[{'type':'text','text':'Full'}]}},{'type':'result','result':'Full'}],'Full'),
 ('gemini',[{'type':'message','role':'assistant','content':'Gemi'},{'type':'message','role':'assistant','content':'ni'},{'type':'result','status':'success','stats':{}}],'Gemini'),
 ('codex',[{'type':'item.updated','item':{'type':'agent_message','id':'i','text':'Hi'}},{'type':'item.completed','item':{'type':'agent_message','id':'i','text':'Hi world'}}],'Hi world'),
 ('agy',[{'event':'init','conversation_id':'cid'},{'event':'step_update','step_update':{'step_type':'agent_response','text_delta':'Agy '}},{'event':'step_update','step_update':{'step_type':'agent_response','text_delta':'Live'}},{'event':'result','result':{'response':'Agy Live','status':'SUCCESS'}}],'Agy Live'),
 ('opencode',[{'type':'step_start'},{'type':'text','part':{'text':'Open'}},{'type':'text','part':{'text':'Code'}},{'type':'step_finish','part':{}}],'OpenCode'),
 ('jsonl',[{'type':'delta','text':'A'},{'type':'result','text':'A'}],'A')])
def test_vendor_decoders_no_duplicates(protocol,events,expected):
 d=Decoder(protocol);text=''.join(data['text'] for e in events for t,data in d.decode(json.dumps(e)) if t=='delta');assert text==expected

def test_redaction():
 s=redact('Bearer abc.secret sk-123456789012345 ghp_123456789012345 ownersecret','ownersecret')
 assert all(x not in s for x in ['abc.secret','123456789012345','ownersecret'])

# Regressions found during the final production pass.
def test_attachment_available_in_followup(server):
 d=server.client.post('/api/files',json={'name':'persistent.md','text':'FOLLOWUP_FILE_SECRET'}).json()['file']
 r=server.submit('Read my file.',files=[d['id']]);server.wait(r['id'])
 r2=server.submit('[CONTEXT] What was in that file?',chat_id=r['chat_id'])
 assert 'FOLLOWUP_FILE_SECRET' in server.wait(r2['id'])['output']

def test_workspace_context_in_prompt(server):
 server.edit(lambda s:s['workspace'].update(description='WORKSPACE_PERSISTENT_RULE'))
 r=server.submit('[CONTEXT]');assert 'WORKSPACE_PERSISTENT_RULE' in server.wait(r['id'])['output']

def test_event_polling_matches_sse_storage(server):
 r=server.submit();server.wait(r['id']);events=server.app.db.events(r['id'],2)
 result=server.client.get('/api/runs/'+r['id']+'/events?format=json&since=2').json()
 assert result['events']==events and result['run']['status']=='succeeded'

@pytest.mark.parametrize('key,value',[('agents',None),('workspace',None),('prefs',None)])
def test_reject_missing_required_structures(server,key,value):
 s=server.client.get('/api/state').json();s['state'][key]=value
 assert server.client.put('/api/state',json=s).status_code==422

def test_reload_reports_real_worker_count(server):
 cfg=server.app.config;cfg.raw['max_concurrency']=1;cfg.save(cfg.raw)
 r=server.client.post('/api/config/reload',json={});assert r.json()['restart_required'] is True
 assert server.client.get('/api/bootstrap').json()['limits']['concurrency']==2

def test_local_workspace_cwd_and_path_with_spaces(server,tmp_path):
 path=tmp_path/'my actual workspace';path.mkdir()
 cfg=server.app.config;cfg.raw['workspaces']=[{'id':'work','path':str(path)}];cfg.save(cfg.raw);cfg.reload()
 r=server.submit('[CWD]',workspace='work');assert str(path) in server.wait(r['id'])['output']

@pytest.mark.parametrize('field,value',[('workspaces',{}),('workspaces',None),('max_concurrency',3)])
def test_invalid_local_configuration(field,value,tmp_path):
 c=Config(tmp_path/'config');data=copy.deepcopy(c.raw);data[field]=value
 with pytest.raises(ValueError):c.save(data)


def test_second_server_cannot_interrupt_live_jobs(server):
 from langcas.app import App
 r=server.submit('[SLEEP]');server.wait(r['id'],'running')
 with pytest.raises(ValueError,match='bereits'):App(server.path)
 assert server.app.db.run(r['id'])['status']=='running'
 server.app.engine.cancel(r['id'])
