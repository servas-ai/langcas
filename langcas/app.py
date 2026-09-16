"""Same-origin, authenticated, local HTTP API and streaming UI server."""
from __future__ import annotations
import fcntl
import os
import hashlib
import hmac
import json
import logging
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit
from . import __version__
from .config import Config, ID, ROOT
from .db import APIError, COLLECTIONS, Database, FINAL, MAX_STATE, dumps, timestamp, uid
from .runners import Engine

LOG = logging.getLogger('langcas')
MAX_BODY = 8_000_000


def validate_messages(messages) -> list[dict]:
    if not isinstance(messages,list) or not 1<=len(messages)<=100:
        raise APIError(422,'messages muss 1–100 Textnachrichten enthalten.')
    result=[]
    for m in messages:
        if not isinstance(m,dict) or m.get('role') not in ('system','developer','user','assistant') or not isinstance(m.get('content'),str):
            raise APIError(422,'Nur Textnachrichten ohne Tool-Calls oder Bilder werden unterstützt.')
        if set(m)-{'role','content','name'}:
            raise APIError(422,'Nicht unterstützte Nachrichtenfelder.')
        result.append({'role':m['role'],'content':m['content']})
    if sum(len(m['content']) for m in result)>250000:
        raise APIError(413,'Nachrichtenkontext zu groß.')
    if not any(m['role']=='user' and m['content'].strip() for m in result):
        raise APIError(422,'Mindestens eine nichtleere Nutzernachricht ist erforderlich.')
    return result


class App:
    def __init__(self, directory: Path | None = None):
        self.config=Config(directory)
        # A second server must never recover/interrupt the first server's live jobs.
        self._closed=False
        fd=os.open(self.config.directory/'server.lock',os.O_RDWR|os.O_CREAT,0o600)
        self._file_lock=os.fdopen(fd,'r+')
        try:
            fcntl.flock(self._file_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            self._file_lock.close()
            raise ValueError('Für diesen Datenordner läuft bereits ein LANGKAS-Server.') from None
        try:
            self.db=Database(self.config.directory/'langkas.sqlite3')
            self.engine=Engine(self.config,self.db)
        except Exception:
            if hasattr(self,'db'): self.db.close()
            self._file_lock.close()
            raise
        self.started=time.monotonic()
        self.login_attempts=defaultdict(deque)
        self.auth_lock=threading.Lock()

    def login_allowed(self,ip):
        with self.auth_lock:
            times=self.login_attempts[ip]
            while times and times[0]<time.monotonic()-60: times.popleft()
            if len(times)>=10: return False
            times.append(time.monotonic())
            return True

    def bootstrap(self):
        return {**self.db.state(),'runners':self.config.public_runners(),'workspaces':self.config.public_workspaces(),
                'version':__version__,'mode':'local-single-user',
                'limits':{'concurrency':len(self.engine.workers),'state_bytes':MAX_STATE,'text_only':True},
                'features':{'chat':True,'streaming':True,'state':True,'agents':True,'workflows':True,
                            'approval':True,'openai_text_api':True,'sso':False,'billing':False,
                            'team_auth':False,'oauth_integrations':False,'scheduler':False,'browser_harness':False}}

    def close(self):
        if self._closed: return
        self._closed=True
        try:
            self.engine.close()
            self.db.close()
        finally:
            self._file_lock.close()


class Server(ThreadingHTTPServer):
    daemon_threads=True
    request_queue_size=32
    allow_reuse_address=True

    def __init__(self,address,app):
        self.app=app
        self.slots=threading.BoundedSemaphore(32)
        super().__init__(address,Handler)
        port=self.server_address[1]
        self.allowed_hosts={f'localhost:{port}',f'127.0.0.1:{port}'}

    def process_request(self,request,client_address):
        if not self.slots.acquire(blocking=False):
            try: request.sendall(b'HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
            finally: self.shutdown_request(request)
            return
        try: super().process_request(request,client_address)
        except BaseException:
            self.slots.release(); raise

    def process_request_thread(self,request,client_address):
        try: super().process_request_thread(request,client_address)
        finally: self.slots.release()


class Handler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    server_version='LANGKAS/'+__version__
    sys_version=''

    @property
    def app(self): return self.server.app

    def setup(self):
        super().setup()
        self.connection.settimeout(30)

    def log_message(self,format,*args):
        # Never log headers, query strings, request bodies or access tokens.
        LOG.debug('%s %s',self.command,urlsplit(self.path).path)

    def headers_common(self):
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        self.send_header('Permissions-Policy','camera=(), microphone=(self), geolocation=()')

    def send_bytes(self,status,body,kind='application/json; charset=utf-8',extra=None):
        self.send_response(status)
        self.send_header('Content-Type',kind)
        self.send_header('Content-Length',str(len(body)))
        if self.close_connection: self.send_header('Connection','close')
        self.headers_common()
        for k,v in (extra or {}).items(): self.send_header(k,v)
        self.end_headers()
        if self.command!='HEAD': self.wfile.write(body)

    def send_json(self,status,data,extra=None): self.send_bytes(status,dumps(data).encode(),'application/json; charset=utf-8',extra)

    def body(self):
        if self.headers.get('Transfer-Encoding'):
            raise APIError(400,'Chunked Request-Bodies werden nicht unterstützt.')
        if self.headers.get_content_type()!='application/json': raise APIError(415,'Content-Type application/json erforderlich.')
        try: size=int(self.headers.get('Content-Length','0'))
        except ValueError: raise APIError(400,'Ungültige Inhaltslänge.') from None
        if not 0<size<=MAX_BODY: raise APIError(413,'Anfrage leer oder größer als 8 MB.')
        raw=self.rfile.read(size)
        if len(raw)!=size: raise APIError(400,'Unvollständige Anfrage.')
        try:
            def no_constant(x): raise ValueError('Ungültige Zahl')
            data=json.loads(raw,parse_constant=no_constant)
        except (ValueError,UnicodeDecodeError,RecursionError): raise APIError(400,'Ungültiges JSON.') from None
        if not isinstance(data,dict): raise APIError(422,'JSON-Objekt erforderlich.')
        return data

    def session_token(self):
        cookies=SimpleCookie()
        try: cookies.load(self.headers.get('Cookie',''))
        except Exception: return ''
        return cookies['langkas_session'].value if 'langkas_session' in cookies else ''

    def authenticated(self):
        auth=self.headers.get('Authorization','')
        if auth.startswith('Bearer ') and hmac.compare_digest(auth[7:].encode(),self.app.config.token.encode()): return True
        token=self.session_token()
        return bool(token and self.app.db.valid_session(token))

    def guard(self):
        if self.headers.get('Host','') not in self.server.allowed_hosts:
            raise APIError(403,'Unzulässiger Host. Verwende localhost oder 127.0.0.1.','invalid_host')
        origin=self.headers.get('Origin')
        if origin:
            parsed=urlsplit(origin)
            if parsed.scheme!='http' or parsed.netloc!=self.headers.get('Host') or parsed.path not in ('','/'):
                raise APIError(403,'Fremde Origin nicht zugelassen.','invalid_origin')
        if self.headers.get('Sec-Fetch-Site')=='cross-site':
            raise APIError(403,'Cross-Site-Anfragen sind gesperrt.','cross_site')

    def do_GET(self): self.dispatch()
    def do_POST(self): self.dispatch()
    def do_PUT(self): self.dispatch()
    def do_PATCH(self): self.dispatch()
    def do_DELETE(self): self.dispatch()
    def do_HEAD(self): self.dispatch()
    def do_OPTIONS(self): self.dispatch()

    def dispatch(self):
        try:
            self.guard()
            path=urlsplit(self.path).path
            query=parse_qs(urlsplit(self.path).query)
            method=self.command
            if method=='OPTIONS': raise APIError(403,'Keine Cross-Origin-Freigaben.')
            if method in ('GET','HEAD') and path in ('/','/index.html','/favicon.ico'):
                if path=='/favicon.ico': self.send_bytes(204,b''); return
                self.send_bytes(200,(ROOT/'web/index.html').read_bytes(),'text/html; charset=utf-8'); return
            if method=='GET' and path=='/health':
                self.send_json(200,{'status':'ok','version':__version__,'service':'LANGKAS'}); return
            if method=='POST' and path=='/api/auth/login':
                if not self.app.login_allowed(self.client_address[0]): raise APIError(429,'Zu viele Anmeldeversuche. Eine Minute warten.','rate_limit')
                data=self.body()
                token=data.get('token','')
                if not isinstance(token,str) or not hmac.compare_digest(token.encode(),self.app.config.token.encode()):
                    raise APIError(401,'Zugriffsschlüssel ungültig.','unauthorized')
                session=secrets.token_urlsafe(36)
                self.app.db.session(session)
                self.app.db.audit('auth.login','Lokaler Browser angemeldet')
                self.send_json(200,{'ok':True},{'Set-Cookie':'langkas_session='+session+'; Path=/; HttpOnly; SameSite=Strict; Max-Age=86400'})
                return
            if not self.authenticated(): raise APIError(401,'Lokaler Zugriffsschlüssel erforderlich.','unauthorized')
            if method=='POST' and path=='/api/auth/logout':
                self.body()
                self.app.db.remove_session(self.session_token())
                self.send_json(200,{'ok':True},{'Set-Cookie':'langkas_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0'}); return
            if method=='GET' and path=='/api/bootstrap': self.send_json(200,self.app.bootstrap()); return
            if method=='GET' and path=='/api/state': self.send_json(200,self.app.db.state()); return
            if method in ('PUT','POST') and path in ('/api/state','/api/import'):
                data=self.body()
                if type(data.get('revision')) is not int: raise APIError(428,'Aktuelle Workspace-Revision erforderlich.','precondition_required')
                result=self.app.db.update_state(data.get('state'),data['revision'])
                if path=='/api/import': self.app.db.audit('state.import','Validierte Sicherung importiert')
                self.send_json(200,result); return
            if method=='GET' and path=='/api/export':
                self.send_json(200,self.app.db.state(),{'Content-Disposition':'attachment; filename="langkas-workspace.json"'}); return
            if method=='GET' and path=='/api/runners':
                self.send_json(200,{'runners':self.app.config.public_runners(),'workspaces':self.app.config.public_workspaces()}); return
            if method=='POST' and path=='/api/config/reload':
                self.body()
                try: self.app.config.reload()
                except ValueError as e: raise APIError(422,str(e)) from None
                self.app.db.audit('config.reload','Lokale Konfiguration neu eingelesen')
                self.send_json(200,{'runners':self.app.config.public_runners(), 'restart_required':self.app.config.max_concurrency!=len(self.app.engine.workers)}); return
            if method=='GET' and path=='/api/runs': self.send_json(200,{'runs':self.app.db.runs(50)}); return
            if method=='POST' and path=='/api/runs':
                data=self.body()
                if 'api_messages' in data: data['api_messages']=validate_messages(data['api_messages'])
                self.send_json(202,self.app.engine.submit(data,self.headers.get('Idempotency-Key'))); return
            match=re.fullmatch(r'/api/runs/([A-Za-z0-9_-]+)(?:/(events|cancel|approve))?',path)
            if match:
                rid,action=match.groups()
                self.app.db.run(rid)
                if method=='GET' and not action: self.send_json(200,self.app.db.run(rid)); return
                if method=='GET' and action=='events':
                    try: since=int(self.headers.get('Last-Event-ID',query.get('since',['0'])[0]))
                    except ValueError: raise APIError(422,'Ungültige Ereignis-ID.') from None
                    if since<0: raise APIError(422,'Ereignis-ID muss nichtnegativ sein.')
                    if query.get('format')==['json']:
                        self.send_json(200,{'events':self.app.db.events(rid,since),'run':self.app.db.run(rid)}); return
                    self.run_events(rid,since); return
                if method=='POST' and action=='cancel':
                    self.body(); self.send_json(200,self.app.engine.cancel(rid)); return
                if method=='POST' and action=='approve':
                    data=self.body()
                    if type(data.get('approve')) is not bool: raise APIError(422,'approve muss true oder false sein.')
                    self.send_json(200,self.app.engine.approve(rid,data['approve'])); return
            match=re.fullmatch(r'/api/(agents|workflows)/([A-Za-z0-9_-]+)/run',path)
            if match and method=='POST':
                group,item_id=match.groups(); data=self.body()
                data['agent' if group=='agents' else 'workflow']=item_id
                self.send_json(202,self.app.engine.submit(data,self.headers.get('Idempotency-Key'))); return
            if method=='GET' and path=='/api/audit': self.send_json(200,{'events':self.app.db.audit_list()}); return
            if method=='GET' and path=='/api/stats':
                runs=self.app.db.runs(10000)
                self.send_json(200,{'runs':len(runs),'succeeded':sum(r['status']=='succeeded' for r in runs),
                                   'failed':sum(r['status']=='failed' for r in runs),'active':sum(r['status'] not in FINAL for r in runs),
                                   'uptime_seconds':round(time.monotonic()-self.app.started),'cost_usd':None,
                                   'note':'Keine geschätzten Kosten oder erfundenen Token-Zähler.'}); return
            if method=='GET' and path=='/api/search':
                term=query.get('q',[''])[0].strip().lower()
                if not 1<=len(term)<=200: raise APIError(422,'Suchtext muss 1–200 Zeichen enthalten.')
                state=self.app.db.state()['state']; results=[]
                for collection in ('chats','docs','agents','projects','prompts'):
                    for item in state[collection]:
                        text=dumps(item)
                        pos=text.lower().find(term)
                        if pos>=0:
                            results.append({'collection':collection,'id':item['id'],'name':item.get('title',item.get('name','')),
                                            'snippet':text[max(0,pos-60):pos+180]})
                            if len(results)>=100: break
                self.send_json(200,{'results':results[:100]}); return
            match=re.fullmatch(r'/api/collections/([a-zA-Z]+)(?:/([A-Za-z0-9_-]+))?',path)
            if match:
                collection,item_id=match.groups()
                if collection not in COLLECTIONS: raise APIError(404,'Bereich nicht gefunden.')
                state=self.app.db.state()
                item=next((x for x in state['state'][collection] if x['id']==item_id),None)
                if method=='GET':
                    if item_id and not item: raise APIError(404,'Eintrag nicht gefunden.')
                    self.send_json(200,{'revision':state['revision'],'data':item if item_id else state['state'][collection]}); return
                data=self.body()
                if type(data.get('revision')) is not int: raise APIError(428,'Revision fehlt.')
                if data['revision']!=state['revision']: raise APIError(409,'Veraltete Revision.','revision_conflict')
                if method=='POST' and not item_id:
                    value=data.get('data')
                    if not isinstance(value,dict): raise APIError(422,'data muss ein Objekt sein.')
                    value={**value,'id':value.get('id') or uid(collection[:2])}
                    state['state'][collection].append(value)
                elif method=='PATCH' and item:
                    value=data.get('data')
                    if not isinstance(value,dict) or ('id' in value and value['id']!=item_id): raise APIError(422,'ID darf nicht geändert werden.')
                    item.update(value)
                elif method=='DELETE' and item:
                    state['state'][collection]=[x for x in state['state'][collection] if x['id']!=item_id]
                else: raise APIError(404,'Eintrag nicht gefunden.')
                self.send_json(200,self.app.db.update_state(state['state'],state['revision'])); return
            if method=='POST' and path=='/api/files':
                data=self.body(); name=data.get('name'); text=data.get('text')
                if not isinstance(name,str) or not 1<=len(name)<=150 or not isinstance(text,str): raise APIError(422,'Dateiname und Text sind erforderlich.')
                if len(text.encode())>3_000_000: raise APIError(413,'Datei größer als 3 MB.')
                doc={'id':uid('d'),'name':name,'kind':'text','text':text,'type':'text/plain','folder':None,
                     'size':len(text.encode()),'created':timestamp(),'sha256':hashlib.sha256(text.encode()).hexdigest()}
                result=self.app.db.mutate(lambda state: state['docs'].append(doc))
                self.send_json(201,{'revision':result['revision'],'file':doc}); return
            match=re.fullmatch(r'/api/files/([A-Za-z0-9_-]+)/download',path)
            if method=='GET' and match:
                doc=next((d for d in self.app.db.state()['state']['docs'] if d['id']==match[1]),None)
                if not doc: raise APIError(404,'Datei nicht gefunden.')
                if doc['kind']!='text': raise APIError(422,'Kein Textdownload für diesen Dateityp.')
                self.send_bytes(200,doc['text'].encode(),'text/plain; charset=utf-8',
                                {'Content-Disposition':"attachment; filename*=UTF-8''"+quote(doc['name'],safe='')}); return
            if method=='GET' and path=='/v1/models':
                self.send_json(200,{'object':'list','data':[{'id':r['id'],'object':'model','created':0,'owned_by':'local-cli',
                                                          'available':r['available'],'enabled':r['enabled']} for r in self.app.config.public_runners()]}); return
            if method=='POST' and path=='/v1/chat/completions': self.completion(self.body()); return
            raise APIError(404,'Endpunkt nicht gefunden.','not_found')
        except APIError as exc:
            self.close_connection=True
            self.send_json(exc.status,{'error':{'message':str(exc),'type':exc.code,'code':exc.code}})
        except (BrokenPipeError,ConnectionResetError,TimeoutError):
            self.close_connection=True
        except Exception:
            LOG.exception('Interner Fehler bei %s',urlsplit(self.path).path)
            self.close_connection=True
            self.send_json(500,{'error':{'message':'Interner Serverfehler. Siehe lokale Serverprotokolle.','code':'internal_error'}})

    def stream_headers(self):
        self.send_response(200)
        self.send_header('Content-Type','text/event-stream; charset=utf-8')
        self.send_header('Connection','close')
        self.send_header('X-Accel-Buffering','no')
        self.headers_common()
        self.end_headers()
        self.close_connection=True

    def sse(self,event=None,data=None,seq=None):
        value=('id: '+str(seq)+'\n' if seq is not None else '')
        value+=('event: '+event+'\n' if event else '')
        value+='data: '+(data if isinstance(data,str) else dumps(data))+'\n\n'
        self.wfile.write(value.encode()); self.wfile.flush()

    def run_events(self,run_id,since):
        self.stream_headers()
        beat=time.monotonic()
        while True:
            events=self.app.db.events(run_id,since)
            for event in events:
                self.sse(event['type'],event['data'],event['seq']); since=event['seq']
            status=self.app.db.run(run_id)['status']
            if status in FINAL and not events:
                break
            if time.monotonic()-beat>8:
                self.wfile.write(b': heartbeat\n\n'); self.wfile.flush(); beat=time.monotonic()
            time.sleep(.08)

    def completion(self,data):
        allowed={'model','messages','stream','user'}
        if set(data)-allowed: raise APIError(422,'Dieser lokale API-Adapter unterstützt model, messages und stream. Tools, Bilder und Sampling-Parameter sind nicht implementiert.')
        messages=validate_messages(data.get('messages'))
        model=data.get('model','auto')
        if not isinstance(model,str): raise APIError(422,'model muss Text sein.')
        if type(data.get('stream',False)) is not bool: raise APIError(422,'stream muss ein Boolean sein.')
        provider,sep,provider_model=model.partition('/')
        try:
            selected=self.app.config.select(provider)
            if selected.get('permission')=='workspace-write': raise APIError(403,'Schreibende Runner benötigen eine UI-Freigabe. Verwende /api/runs.')
        except ValueError as exc: raise APIError(503,str(exc),'runner_unavailable') from None
        prompt=next(m['content'] for m in reversed(messages) if m['role']=='user')
        run=self.app.engine.submit({'provider':provider,'model':provider_model,'prompt':prompt,
                                   'api_messages':messages},self.headers.get('Idempotency-Key'))
        rid=run['id']; completion_id='chatcmpl-'+rid; created=run['created']//1000
        base={'id':completion_id,'created':created,'model':model}
        if not data.get('stream'):
            while run['status'] not in FINAL:
                time.sleep(.05); run=self.app.db.run(rid)
            if run['status']!='succeeded': raise APIError(502,run['error'] or run['status'],'provider_error')
            self.send_json(200,{**base,'object':'chat.completion','choices':[{'index':0,'message':{'role':'assistant','content':run['output']},'finish_reason':'stop'}]})
            return
        self.stream_headers(); since=0; done=False; beat=time.monotonic()
        chunk=lambda delta,finish=None:{**base,'object':'chat.completion.chunk','choices':[{'index':0,'delta':delta,'finish_reason':finish}]}
        try:
            self.sse(data=chunk({'role':'assistant'}))
            while True:
                events=self.app.db.events(rid,since)
                for event in events:
                    since=event['seq']
                    if event['type']=='delta': self.sse(data=chunk({'content':event['data']['text']}))
                run=self.app.db.run(rid)
                if run['status'] in FINAL and not events: break
                if time.monotonic()-beat>8:
                    self.wfile.write(b': heartbeat\n\n'); self.wfile.flush(); beat=time.monotonic()
                time.sleep(.05)
            if run['status']=='succeeded': self.sse(data=chunk({},'stop'))
            else: self.sse(data={'error':{'message':run['error'] or run['status'],'type':'provider_error'}})
            self.sse(data='[DONE]'); done=True
        finally:
            if not done:
                self.app.engine.cancel(rid)
