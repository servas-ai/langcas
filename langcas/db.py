"""SQLite persistence, optimistic concurrency and durable ordered run events."""
from __future__ import annotations
import contextlib
import copy
import hashlib
import json
import re
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from .config import ID, ROOT

COLLECTIONS = ('chats', 'projects', 'agents', 'folders', 'docs', 'prompts', 'skills',
               'workflows', 'tasks', 'members', 'groups', 'apiKeys', 'memories', 'audit')
ACTIVE = ('queued', 'running', 'awaiting_approval')
FINAL = ('succeeded', 'failed', 'cancelled', 'interrupted')
MAX_STATE = 7_000_000


class APIError(Exception):
    def __init__(self, status: int, message: str, code: str = 'invalid_request'):
        super().__init__(message)
        self.status, self.code = status, code


def uid(prefix: str) -> str:
    return prefix + '_' + uuid.uuid4().hex


def timestamp() -> int:
    return int(time.time() * 1000)


def dumps(data) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def validate_state(state: dict) -> None:
    if not isinstance(state, dict):
        raise APIError(422, 'Workspace muss ein Objekt sein.')
    try:
        raw = dumps(state)
    except (ValueError, TypeError):
        raise APIError(422, 'Ungültiger JSON-Zustand.') from None
    if len(raw.encode()) > MAX_STATE:
        raise APIError(413, 'Workspace überschreitet das 7-MB-Limit.')
    if re.search(r'"(?:__proto__|prototype|constructor)"\s*:', raw):
        raise APIError(422, 'Unsichere Objektstruktur.')
    for key in ('profile','prefs','workspace','capabilities','models','roles','connections','canvas','usage','billing','security'):
        if not isinstance(state.get(key),dict): raise APIError(422,'Ungültige Einstellungen: '+key)
    if state.get('version') != 3: raise APIError(422,'Unbekannte Workspace-Version.')
    if not re.fullmatch(r'#[a-fA-F0-9]{6}', str(state.get('workspace', {}).get('accent', ''))):
        raise APIError(422, 'Ungültige Markenfarbe.')
    for key in COLLECTIONS:
        values = state.get(key)
        if not isinstance(values, list) or len(values) > 10000:
            raise APIError(422, 'Ungültige Liste: ' + key)
        seen = set()
        for value in values:
            if not isinstance(value, dict) or not ID.fullmatch(str(value.get('id', ''))) or value['id'] in seen:
                raise APIError(422, 'Ungültige oder doppelte ID: ' + key)
            seen.add(value['id'])
    for c in state['chats']:
        if not isinstance(c.get('title'), str) or not isinstance(c.get('messages'), list):
            raise APIError(422, 'Ungültiger Chat.')
        seen = set()
        for m in c['messages']:
            if not isinstance(m, dict) or not ID.fullmatch(str(m.get('id', ''))) or m['id'] in seen or m.get('role') not in ('user', 'assistant') or not isinstance(m.get('text'), str):
                raise APIError(422, 'Ungültige Nachricht.')
            seen.add(m['id'])
    for key in ('profile', 'prefs', 'workspace', 'capabilities', 'models', 'roles', 'connections', 'canvas', 'usage', 'billing', 'security'):
        if not isinstance(state.get(key), dict):
            raise APIError(422, 'Ungültige Einstellungen: ' + key)
    for d in state['docs']:
        if not isinstance(d.get('name'), str) or d.get('kind') not in ('text', 'image', 'metadata'):
            raise APIError(422, 'Ungültige Datei.')
        if d['kind'] == 'text' and not isinstance(d.get('text'), str):
            raise APIError(422, 'Dateitext fehlt.')
        if d['kind'] == 'image' and not re.fullmatch(r'data:image/(?:png|jpeg|webp);base64,[A-Za-z0-9+/=]+', str(d.get('data', ''))):
            raise APIError(422, 'Ungültige Bilddaten.')
    required_text = {'agents':('name','description','instructions','model','category','icon','color','owner','visibility'),
                     'projects':('name','description','instructions'), 'prompts':('name','text','category'),
                     'skills':('name','text'), 'workflows':('name','description'), 'memories':('text',)}
    for group, fields in required_text.items():
        for item in state[group]:
            if any(not isinstance(item.get(f), str) for f in fields):
                raise APIError(422, 'Pflichttext fehlt in '+group)
            for field in ('knowledge','capabilities','integrations','subagents','starters'):
                if field in item and (not isinstance(item[field],list) or not all(isinstance(v,str) for v in item[field])):
                    raise APIError(422,'Ungültige Liste in '+group+'/'+field)
            if 'color' in item and item['color'] not in ('blue','peach','green','pink','gold','gray'):
                raise APIError(422,'Ungültige Symbolfarbe.')
            if 'icon' in item and not re.fullmatch(r'[a-zA-Z0-9_-]{1,40}',item['icon']):
                raise APIError(422,'Ungültiges Symbol.')
    for flow in state['workflows']:
        if not isinstance(flow.get('nodes'),list) or not isinstance(flow.get('runs'),list):
            raise APIError(422,'Workflow-Schritte und Verlauf erforderlich.')
        node_ids=set()
        for node in flow['nodes']:
            if not isinstance(node,dict) or not ID.fullmatch(str(node.get('id',''))) or node['id'] in node_ids:
                raise APIError(422,'Ungültige Workflow-Schritt-ID.')
            node_ids.add(node['id'])
            if not all(isinstance(node.get(k),str) for k in ('name','type','config')):
                raise APIError(422,'Ungültiger Workflow-Schritt.')
    for group, fields in {'profile':('name','fullName','email','job','avatar'),
                          'prefs':('instructions','about','defaultModel'),
                          'workspace':('name','welcome','description','disclaimer'),
                          'canvas':('title','text')}.items():
        if any(not isinstance(state[group].get(f),str) for f in fields):
            raise APIError(422,'Ungültige Textfelder: '+group)
    if state['prefs'].get('theme') not in ('light', 'dark', 'system'):
        raise APIError(422, 'Ungültiges Theme.')


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.RLock()
        self.connection = sqlite3.connect(path, check_same_thread=False, timeout=10)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript('''
          PRAGMA journal_mode=WAL;
          PRAGMA foreign_keys=ON;
          PRAGMA busy_timeout=10000;
          CREATE TABLE IF NOT EXISTS schema_version(version INTEGER PRIMARY KEY);
          INSERT OR IGNORE INTO schema_version VALUES(1);
          CREATE TABLE IF NOT EXISTS state(id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL, data TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS sessions(digest TEXT PRIMARY KEY, expires REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS runs(
            id TEXT PRIMARY KEY, chat_id TEXT, message_id TEXT, kind TEXT NOT NULL,
            provider TEXT NOT NULL, model TEXT, status TEXT NOT NULL, created INTEGER NOT NULL,
            updated INTEGER NOT NULL, output TEXT NOT NULL DEFAULT '', error TEXT,
            usage TEXT NOT NULL DEFAULT '{}', payload TEXT NOT NULL, exit_code INTEGER,
            idempotency_key TEXT UNIQUE, request_hash TEXT, approval TEXT);
          CREATE INDEX IF NOT EXISTS runs_created ON runs(created DESC);
          CREATE TABLE IF NOT EXISTS events(
            run_id TEXT NOT NULL REFERENCES runs(id), seq INTEGER NOT NULL, type TEXT NOT NULL,
            data TEXT NOT NULL, at INTEGER NOT NULL, PRIMARY KEY(run_id,seq));
          CREATE TABLE IF NOT EXISTS audit(
            id INTEGER PRIMARY KEY AUTOINCREMENT, at INTEGER NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL);
        ''')
        import os
        os.chmod(path, 0o600)
        if not self.connection.execute('SELECT 1 FROM state').fetchone():
            seed = json.loads((ROOT / 'web/seed.json').read_text())
            validate_state(seed)
            self.connection.execute('INSERT INTO state VALUES(1,1,?)', (dumps(seed),))
        self.connection.commit()

    @contextlib.contextmanager
    def transaction(self):
        with self.lock:
            self.connection.execute('BEGIN IMMEDIATE')
            try:
                yield self.connection
                self.connection.commit()
            except BaseException:
                self.connection.rollback()
                raise

    def state(self) -> dict:
        with self.lock:
            row = self.connection.execute('SELECT revision,data FROM state WHERE id=1').fetchone()
            return {'revision': row['revision'], 'state': json.loads(row['data'])}

    @staticmethod
    def _write_state(conn, state) -> int:
        conn.execute('UPDATE state SET data=?,revision=revision+1 WHERE id=1', (dumps(state),))
        return conn.execute('SELECT revision FROM state WHERE id=1').fetchone()[0]

    def update_state(self, state, expected: int) -> dict:
        validate_state(state)
        with self.transaction() as conn:
            row = conn.execute('SELECT revision,data FROM state WHERE id=1').fetchone()
            if expected != row['revision']:
                raise APIError(409, 'Der Workspace wurde inzwischen geändert. Neu laden oder lokale Änderungen exportieren.', 'revision_conflict')
            # A stale tab may never overwrite/delete messages owned by an active run.
            old = json.loads(row['data'])
            active = conn.execute("SELECT chat_id FROM runs WHERE status IN ('queued','running','awaiting_approval')").fetchall()
            for r in active:
                if not r['chat_id']:
                    continue
                before = next((c for c in old['chats'] if c['id'] == r['chat_id']), None)
                after = next((c for c in state['chats'] if c['id'] == r['chat_id']), None)
                if before and (not after or after['messages'] != before['messages']):
                    raise APIError(409, 'Ein laufender Chat darf nicht überschrieben werden.', 'run_active')
            revision = self._write_state(conn, state)
        return {'revision': revision}

    def mutate(self, fn):
        with self.transaction() as conn:
            state = json.loads(conn.execute('SELECT data FROM state WHERE id=1').fetchone()[0])
            result = fn(state)
            validate_state(state)
            revision = self._write_state(conn, state)
        return {'revision': revision, 'result': result}

    def audit(self, action: str, detail: str = '') -> None:
        with self.transaction() as conn:
            conn.execute('INSERT INTO audit(at,action,detail) VALUES(?,?,?)', (timestamp(), action, detail[:2000]))

    def audit_list(self) -> list:
        with self.lock:
            return [dict(r) for r in self.connection.execute('SELECT * FROM audit ORDER BY id DESC LIMIT 200')]

    def session(self, token: str, lifetime: int = 86400) -> None:
        with self.transaction() as conn:
            conn.execute('DELETE FROM sessions WHERE expires<?', (time.time(),))
            conn.execute('INSERT INTO sessions VALUES(?,?)', (hashlib.sha256(token.encode()).hexdigest(), time.time()+lifetime))

    def valid_session(self, token: str) -> bool:
        with self.lock:
            return bool(self.connection.execute('SELECT 1 FROM sessions WHERE digest=? AND expires>?',
                        (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone())

    def remove_session(self, token: str) -> None:
        with self.transaction() as conn:
            conn.execute('DELETE FROM sessions WHERE digest=?', (hashlib.sha256(token.encode()).hexdigest(),))

    def run(self, run_id: str, private: bool = False) -> dict:
        with self.lock:
            row = self.connection.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone()
        if not row:
            raise APIError(404, 'Lauf nicht gefunden.', 'not_found')
        result = dict(row)
        result['usage'] = json.loads(result['usage'])
        result['approval'] = json.loads(result['approval']) if result['approval'] else None
        if private:
            result['payload'] = json.loads(result['payload'])
        else:
            for key in ('payload', 'request_hash', 'idempotency_key'):
                result.pop(key)
        return result

    def runs(self, limit: int = 100) -> list:
        with self.lock:
            ids = [r[0] for r in self.connection.execute('SELECT id FROM runs ORDER BY created DESC LIMIT ?', (limit,))]
        return [self.run(i) for i in ids]

    def create_run(self, payload: dict, provider: str, status: str, key: str | None, request_hash: str) -> tuple[dict, bool]:
        with self.transaction() as conn:
            if key:
                old = conn.execute('SELECT id,request_hash FROM runs WHERE idempotency_key=?', (key,)).fetchone()
                if old:
                    if old['request_hash'] != request_hash:
                        raise APIError(409, 'Idempotenz-Schlüssel wurde für eine andere Anfrage verwendet.', 'idempotency_conflict')
                    return self.run(old['id']), False
            state = json.loads(conn.execute('SELECT data FROM state WHERE id=1').fetchone()[0])
            chat_id = payload.get('chat_id') or uid('c')
            chat = next((c for c in state['chats'] if c['id'] == chat_id), None)
            if conn.execute("SELECT 1 FROM runs WHERE chat_id=? AND status IN ('queued','running','awaiting_approval')", (chat_id,)).fetchone():
                raise APIError(409, 'In diesem Chat läuft bereits eine Anfrage.', 'run_active')
            now = timestamp()
            if not chat:
                chat = {'id': chat_id, 'title': payload['prompt'][:80] or 'Workflow', 'created': now, 'updated': now,
                        'model': provider, 'agent': payload.get('agent'), 'project': payload.get('project'),
                        'pinned': False, 'messages': []}
                state['chats'].insert(0, chat)
            message_id, run_id = uid('m'), uid('run')
            chat['model'] = provider
            chat['updated'] = now
            if 'api_messages' in payload:
                chat['messages'] = [{'id': uid('m'), 'role': m['role'], 'text': m['content'], 'at': now}
                                    for m in payload['api_messages'] if m['role'] in ('user', 'assistant')]
            else:
                chat['messages'].append({'id': uid('m'), 'role': 'user', 'text': payload['prompt'],
                                         'files': payload.get('files', []), 'at': now})
            chat['messages'].append({'id': message_id, 'role': 'assistant', 'text': '', 'model': provider,
                                    'demo': False, 'at': now, 'runId': run_id, 'status': status})
            payload = copy.deepcopy(payload)
            payload['chat_id'] = chat_id
            payload['history'] = copy.deepcopy(chat)
            payload['context'] = {k: copy.deepcopy(state[k]) for k in ('workspace','prefs','agents','projects','docs','skills','memories')}
            if payload.get('workflow'):
                w = next((w for w in state['workflows'] if w['id'] == payload['workflow']), None)
                if not w:
                    raise APIError(404, 'Workflow nicht gefunden.')
                payload['nodes'] = copy.deepcopy(w['nodes'])
            validate_state(state)
            self._write_state(conn, state)
            conn.execute('''INSERT INTO runs(id,chat_id,message_id,kind,provider,model,status,created,updated,payload,idempotency_key,request_hash)
                            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
                         (run_id,chat_id,message_id,'workflow' if payload.get('workflow') else 'chat',provider,payload.get('model',''),status,now,now,dumps(payload),key,request_hash))
            self._event(conn, run_id, 'status', {'status': status, 'provider': provider})
            conn.execute('INSERT INTO audit(at,action,detail) VALUES(?,?,?)', (now,'run.created',run_id+' / '+provider))
        return self.run(run_id), True

    @staticmethod
    def _event(conn, run_id: str, kind: str, data: dict) -> int:
        seq = conn.execute('SELECT COALESCE(MAX(seq),0)+1 FROM events WHERE run_id=?', (run_id,)).fetchone()[0]
        conn.execute('INSERT INTO events VALUES(?,?,?,?,?)', (run_id,seq,kind,dumps(data),timestamp()))
        return seq

    def event(self, run_id: str, kind: str, data: dict) -> int:
        with self.transaction() as conn:
            return self._event(conn,run_id,kind,data)

    def events(self, run_id: str, since: int = 0, limit: int = 500) -> list:
        with self.lock:
            rows = self.connection.execute('SELECT seq,type,data,at FROM events WHERE run_id=? AND seq>? ORDER BY seq LIMIT ?', (run_id,since,limit)).fetchall()
        return [{'seq': r['seq'], 'type': r['type'], 'data': json.loads(r['data']), 'at': r['at']} for r in rows]

    def progress(self, run_id: str, text: str) -> None:
        if not text:
            return
        with self.transaction() as conn:
            row = conn.execute('SELECT status,length(output) FROM runs WHERE id=?', (run_id,)).fetchone()
            if row[0] in FINAL:
                return
            if row[1] + len(text) > 2_000_000:
                raise APIError(413, 'Ausgabe überschreitet das 2-MB-Limit.', 'output_limit')
            conn.execute('UPDATE runs SET output=output||?,updated=? WHERE id=?', (text,timestamp(),run_id))
            self._event(conn,run_id,'delta',{'text': text})

    def set_status(self, run_id: str, status: str, error: str | None = None, exit_code: int | None = None,
                   usage: dict | None = None, approval: dict | None = None) -> None:
        with self.transaction() as conn:
            row = conn.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone()
            if row['status'] in FINAL:
                return
            conn.execute('UPDATE runs SET status=?,error=?,exit_code=?,updated=?,usage=?,approval=? WHERE id=?',
                         (status,error,exit_code,timestamp(),dumps(usage or {}),dumps(approval) if approval else None,run_id))
            self._event(conn,run_id,'status',{'status':status,'error':error,'exit_code':exit_code,'approval':approval})
            if status in FINAL:
                state = json.loads(conn.execute('SELECT data FROM state WHERE id=1').fetchone()[0])
                chat = next((c for c in state['chats'] if c['id']==row['chat_id']), None)
                if chat:
                    message = next((m for m in chat['messages'] if m['id']==row['message_id']), None)
                    if message:
                        message.update(text=row['output'],status=status,error=bool(error),stopped=status=='cancelled',
                                       runError=error,usage=usage or {})
                    chat['updated'] = timestamp()
                self._write_state(conn, state)
                self._event(conn,run_id,'done',{'status':status,'error':error})
                conn.execute('INSERT INTO audit(at,action,detail) VALUES(?,?,?)', (timestamp(),'run.'+status,run_id))

    def recover(self) -> int:
        with self.lock:
            ids = [r[0] for r in self.connection.execute("SELECT id FROM runs WHERE status IN ('queued','running','awaiting_approval')")]
        for i in ids:
            self.set_status(i,'interrupted','Server wurde neu gestartet. Es wird nichts automatisch erneut ausgeführt.')
        return len(ids)

    def close(self):
        with self.lock:
            self.connection.close()
