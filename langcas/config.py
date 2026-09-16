"""Local administrator configuration. Never accepts executable paths from HTTP."""
from __future__ import annotations
import json
import os
import re
import secrets
import shutil
import sys
from pathlib import Path

ID = re.compile(r'^[a-zA-Z0-9_-]{1,150}$')
RUNNER_ID = re.compile(r'^[a-z][a-z0-9_-]{0,39}$')
ROOT = Path(__file__).resolve().parent.parent


def data_directory() -> Path:
    if os.environ.get('LANGKAS_DATA_DIR'):
        return Path(os.environ['LANGKAS_DATA_DIR']).expanduser().resolve()
    if sys.platform == 'darwin':
        return Path.home() / 'Library/Application Support/LANGKAS'
    return Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'langkas'


def default_runners() -> list[dict]:
    return [
        {'id': 'agy', 'name': 'Antigravity (AGY)', 'command': 'agy', 'adapter': 'agy',
         'enabled': True, 'permission': 'read-only', 'timeout': 300, 'priority': 5,
         'note': 'Google Antigravity CLI · Höchste Priorität, Live-Streaming'},
        {'id': 'codex', 'name': 'Codex CLI', 'command': 'codex', 'adapter': 'codex',
         'enabled': False, 'permission': 'read-only', 'timeout': 180, 'priority': 10,
         'note': 'Vorsorglich deaktiviert. Erst lokal bewusst aktivieren (z. B. nach einem Wochenlimit).'},
        {'id': 'grok', 'name': 'Grok CLI', 'command': 'grok', 'adapter': 'grok',
         'enabled': True, 'permission': 'workspace-write', 'timeout': 180, 'priority': 15,
         'note': 'Grok Build CLI · Streaming mit Denkprozess'},
        {'id': 'opencode', 'name': 'OpenCode CLI', 'command': 'opencode', 'adapter': 'opencode',
         'enabled': True, 'permission': 'read-only', 'timeout': 180, 'priority': 20,
         'note': 'OpenCode Assistant'},
        {'id': 'claude', 'name': 'Claude Code', 'command': 'claude', 'adapter': 'claude',
         'enabled': True, 'permission': 'read-only', 'timeout': 180, 'priority': 25},
        {'id': 'gemini', 'name': 'Gemini CLI', 'command': 'gemini', 'adapter': 'gemini',
         'enabled': True, 'permission': 'workspace-write', 'timeout': 180, 'priority': 30,
         'note': 'Gemini Headless ist hier nicht als rein lesend freigegeben. Jeder Lauf benötigt deine explizite Zustimmung.'},
    ]


def private_write(path: Path, value: str) -> None:
    tmp = path.with_suffix(path.suffix + '.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(value)
    os.replace(tmp, path)
    os.chmod(path, 0o600)


class Config:
    def __init__(self, directory: Path | None = None):
        self.directory = (directory or data_directory()).resolve()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.directory, 0o700)
        self.scratch = self.directory / 'workspaces'
        self.scratch.mkdir(exist_ok=True, mode=0o700)
        self.path = self.directory / 'runners.json'
        self.token_path = self.directory / 'access-token'
        if not self.token_path.exists():
            private_write(self.token_path, secrets.token_urlsafe(36))
        self.token = self.token_path.read_text().strip()
        if len(self.token) < 32:
            raise ValueError('Der lokale Zugriffsschlüssel muss mindestens 32 Zeichen haben.')
        if not self.path.exists():
            self.save({'version': 1, 'max_concurrency': 2, 'runners': default_runners(), 'workspaces': []})
        self.reload()

    def save(self, data: dict) -> None:
        self.validate(data)
        private_write(self.path, json.dumps(data, ensure_ascii=False, indent=2) + '\n')

    def reload(self) -> None:
        data = json.loads(self.path.read_text())
        self.validate(data)
        self.raw = data
        self.runners = {r['id']: r.copy() for r in data['runners']}
        self.workspaces = {w['id']: w.copy() for w in data.get('workspaces', [])}
        self.max_concurrency = data.get('max_concurrency', 2)

    @staticmethod
    def validate(data: dict) -> None:
        if not isinstance(data, dict) or data.get('version') != 1:
            raise ValueError('Unbekannte Runner-Konfiguration.')
        if type(data.get('max_concurrency', 2)) is not int or not 1 <= data.get('max_concurrency', 2) <= 2:
            raise ValueError('max_concurrency muss 1 oder 2 sein.')
        runners = data.get('runners')
        if not isinstance(runners, list) or len(runners) > 64:
            raise ValueError('Ungültige Runner-Liste.')
        seen = set()
        for r in runners:
            if not isinstance(r, dict) or not RUNNER_ID.fullmatch(str(r.get('id', ''))) or r['id'] in seen:
                raise ValueError('Ungültige oder doppelte Runner-ID.')
            seen.add(r['id'])
            if type(r.get('priority',100)) is not int:
                raise ValueError('priority muss eine ganze Zahl sein.')
            if not isinstance(r.get('name',r['id']),str):
                raise ValueError('Runner-Name muss Text sein.')
            if r.get('adapter') not in ('claude', 'gemini', 'codex', 'agy', 'grok', 'opencode', 'generic'):
                raise ValueError('Adapter nicht unterstützt.')
            if r.get('permission', 'read-only') not in ('read-only', 'workspace-write'):
                raise ValueError('Ungültiger Berechtigungsmodus.')
            if r['adapter']=='gemini' and r.get('permission','read-only')!='workspace-write':
                raise ValueError('Gemini Headless benötigt workspace-write mit Freigabe. Plan-Modus ist kein verlässlicher Nur-Lesen-Schutz.')
            if type(r.get('enabled', True)) is not bool:
                raise ValueError('enabled muss ein Boolean sein.')
            if not isinstance(r.get('command'), str) or not r['command'] or '\x00' in r['command']:
                raise ValueError('Ein ausführbarer Befehl fehlt.')
            if not isinstance(r.get('args', []), list) or not all(isinstance(a, str) and '\x00' not in a for a in r.get('args', [])):
                raise ValueError('args muss ein Array einzelner Argumente sein, keine Shell-Zeile.')
            if type(r.get('timeout', 180)) not in (int, float) or not 1 <= r.get('timeout', 180) <= 3600:
                raise ValueError('Timeout außerhalb 1–3600 Sekunden.')
            if r.get('output', 'text') not in ('text', 'jsonl'):
                raise ValueError('Generische Ausgabe muss text oder jsonl sein.')
            if r.get('input', 'text') not in ('text', 'json'):
                raise ValueError('Generische Eingabe muss text oder json sein.')
        workspaces = data.get('workspaces', [])
        if not isinstance(workspaces, list) or len(workspaces) > 128:
            raise ValueError('Ungültige Workspace-Liste.')
        workspace_ids = set()
        for w in data.get('workspaces', []):
            if not isinstance(w, dict) or not RUNNER_ID.fullmatch(str(w.get('id', ''))) or w['id'] in workspace_ids:
                raise ValueError('Ungültige oder doppelte Workspace-ID.')
            workspace_ids.add(w['id'])
            if not isinstance(w.get('path'), str) or not Path(w['path']).expanduser().is_absolute():
                raise ValueError('Workspaces benötigen einen absoluten lokalen Pfad.')

    def public_runners(self) -> list[dict]:
        result = []
        for r in self.runners.values():
            executable = shutil.which(r['command'])
            result.append({'id': r['id'], 'name': r.get('name', r['id']),
                           'adapter': r['adapter'], 'enabled': r.get('enabled', True),
                           'available': bool(executable), 'authenticated': None,
                           'permission': r.get('permission', 'read-only'),
                           'timeout': r.get('timeout', 180), 'note': r.get('note', ''),
                           'status': 'disabled' if not r.get('enabled', True) else ('detected' if executable else 'not_installed')})
        return result

    def public_workspaces(self) -> list[dict]:
        return [{'id': w['id'], 'name': w.get('name', w['id'])} for w in self.workspaces.values()]

    def select(self, selected: str = 'auto') -> dict:
        if selected == 'auto':
            options = sorted(self.runners.values(), key=lambda r: r.get('priority', 100))
        else:
            if selected not in self.runners:
                raise ValueError('Runner unbekannt. Konfiguriere ihn lokal in runners.json.')
            options = [self.runners[selected]]
        for r in options:
            if r.get('enabled', True) and shutil.which(r['command']):
                return r.copy()
        raise ValueError('Kein aktivierter CLI-Runner gefunden. CLI auf diesem Rechner installieren/anmelden oder einen lokalen Adapter konfigurieren. Keine Demo-Antwort erzeugt.')

    def cwd(self, workspace: str | None, run_id: str) -> Path:
        if workspace:
            if workspace not in self.workspaces:
                raise ValueError('Workspace ist nicht lokal freigegeben.')
            path = Path(self.workspaces[workspace]['path']).expanduser().resolve()
            if not path.is_dir():
                raise ValueError('Der freigegebene Workspace existiert nicht.')
            return path
        path = self.scratch / run_id
        path.mkdir(mode=0o700, exist_ok=True)
        return path
