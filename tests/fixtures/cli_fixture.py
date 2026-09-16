#!/usr/bin/env python3
"""Deterministic process fixture. It is NOT an AI model. Tests only; never a default runner."""
import json,os,sys,time,subprocess
raw=sys.stdin.read()
try:
 data=json.loads(raw);messages=data.get('messages',data) if isinstance(data,dict) else data
except ValueError:
 messages=[{'role':'user','content':raw}]
prompt=next((m['content'] for m in reversed(messages) if m['role']=='user'),'')
context='\n'.join(m['content'] for m in messages)
def event(obj): print(json.dumps(obj,ensure_ascii=False),flush=True)
if '[FAIL]' in prompt:
 print('fixture failed',file=sys.stderr,flush=True);sys.exit(7)
if '[ERROR]' in prompt:
 event({'type':'error','message':'explicit fixture error'});sys.exit(0)
if '[EMPTY]' in prompt: sys.exit(0)
if '[MALFORMED]' in prompt:
 print('not-json',flush=True);sys.exit(0)
if '[CWD]' in prompt:
 event({'type':'delta','text':os.getcwd()});sys.exit(0)
if '[ENV]' in prompt:
 event({'type':'delta','text':json.dumps(sorted(k for k in os.environ if k.startswith('LANGKAS_')))});sys.exit(0)
if '[HUGE]' in prompt:
 for i in range(500): event({'type':'delta','text':'X'*10000})
 sys.exit(0)
if '[SLEEP]' in prompt:
 event({'type':'delta','text':'Fixture gestartet. '});time.sleep(30)
if '[CLOSED_PIPES]' in prompt:
 os.close(1);os.close(2);time.sleep(30)
if '[CHILD]' in prompt:
 child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'])
 event({'type':'delta','text':f'child={child.pid}'});time.sleep(30)
if '[DELAY]' in prompt: time.sleep(.7)
if '[CONTEXT]' in prompt: answer='KONTEXT:\n'+context
elif '[SIZE]' in prompt: answer='bytes='+str(len(raw.encode()))
else: answer='CLI-Testprozess (keine KI): '+prompt+' · Servas 🧀'
for chunk in [answer[i:i+23] for i in range(0,len(answer),23)]:
 event({'type':'delta','text':chunk});time.sleep(.005)
event({'type':'result','text':answer,'usage':{'fixture':True}})
