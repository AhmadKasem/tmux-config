"""Private, transactional state. No transcripts or scrollback are read."""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import time


def state_dir():
    return Path(os.environ.get('OVERVIEW_STATE_DIR', str(Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'tmux-overview')))


def excerpt(value, limit=400):
    return ' '.join(''.join(c if c.isprintable() else ' ' for c in str(value or '')).split())[:limit]


def repository(cwd):
    path = Path(cwd).expanduser().resolve()
    try:
        result = subprocess.run(['git', '-C', str(path), 'rev-parse', '--path-format=absolute', '--git-common-dir'], capture_output=True, text=True, timeout=2)
        if result.returncode == 0:
            common = Path(result.stdout.strip()).resolve()
            return str(common.parent if common.name == '.git' else common)
    except (OSError, subprocess.TimeoutExpired):
        pass
    return str(path)


class Store:
    def __init__(self, directory=None):
        self.directory = Path(directory) if directory else state_dir()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory.chmod(0o700)
        self.db = sqlite3.connect(self.directory / 'overview.sqlite3', timeout=2, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA busy_timeout=2000')
        self.db.execute('PRAGMA foreign_keys=ON')
        with self.transaction():
            version = self.db.execute('PRAGMA user_version').fetchone()[0]
            if version > 1:
                raise ValueError('State is newer than this overview version')
            if version == 0:
                for sql in SCHEMA:
                    self.db.execute(sql)
                self.db.execute('PRAGMA user_version=1')
        (self.directory / 'overview.sqlite3').chmod(0o600)

    @contextlib.contextmanager
    def transaction(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def rows(self, sql, args=()):
        return [dict(r) for r in self.db.execute(sql, args)]

    def project(self, cwd, registered=False, ignored=False, name=None, note=None):
        root = repository(cwd)
        with self.transaction():
            self.db.execute('INSERT OR IGNORE INTO projects(root,name) VALUES (?,?)', (root, Path(root).name or root))
            if registered or ignored:
                self.db.execute('UPDATE projects SET registered=?,ignored=? WHERE root=?', (int(registered), int(ignored), root))
            if name is not None:
                self.db.execute('UPDATE projects SET name=? WHERE root=?', (excerpt(name, 100), root))
            if note is not None:
                self.db.execute('UPDATE projects SET note=? WHERE root=?', (excerpt(note, 1000), root))
        return root

    def meta(self, key, value=None):
        if value is not None:
            with self.transaction():
                self.db.execute('INSERT INTO meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, json.dumps(value)))
            return value
        row = self.db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def event(self, event):
        agent, sid, kind = event['agent'], event['session_id'], event['kind']
        if agent not in ('codex', 'claude') or kind not in ('start', 'prompt', 'tool', 'waiting', 'response', 'interrupt', 'end'):
            raise ValueError('Unsupported agent or event kind')
        if not isinstance(sid, str) or not sid or len(sid) > 200 or sid.startswith('-') or any(not c.isalnum() and c not in '_-.' for c in sid):
            raise ValueError('Invalid conversation ID')
        if event.get('child'):
            return False
        stamp = float(event.get('observed_at', time.time()))
        if not 0 < stamp <= time.time() + 60:
            raise ValueError('Invalid observation time')
        root = self.project(event.get('cwd') or os.getcwd())
        key = agent + ':' + sid
        event_id = event.get('event_id') or hashlib.sha256(json.dumps(event, sort_keys=True).encode()).hexdigest()
        with self.transaction():
            if self.db.execute('SELECT 1 FROM events WHERE id=?', (str(event_id),)).fetchone():
                return False
            self.db.execute('INSERT INTO events VALUES (?,?,?)', (str(event_id), key, stamp))
            old = self.db.execute('SELECT * FROM conversations WHERE id=?', (key,)).fetchone()
            if old and stamp <= old['observed_at']:
                return False
            turn = str(event.get('turn_id') or '')
            if old and turn and kind not in ('start', 'prompt') and old['turn_id'] and turn != old['turn_id']:
                return False
            prompt = excerpt(event.get('prompt'))
            label = old['label'] if old else ''
            if not label and prompt and not (old and old['label_edited']):
                label = prompt[:120]
            status = {'start': 'Unknown', 'prompt': 'Working', 'tool': 'Working', 'waiting': 'Waiting', 'response': 'Response ready', 'interrupt': 'Interrupted/disconnected', 'end': 'Interrupted/disconnected'}[kind]
            response = excerpt(event.get('response')) if kind == 'response' else (old['response'] if old else '')
            ready = stamp if kind == 'response' else (0 if kind == 'prompt' else (old['ready_at'] if old else 0))
            self.db.execute('''INSERT INTO conversations(id,agent,session_id,root,cwd,label,label_edited,status,observed_at,response,ready_at,ack_at,turn_id,runtime,pane,instance_pid)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                root=excluded.root,cwd=excluded.cwd,label=excluded.label,status=excluded.status,observed_at=excluded.observed_at,
                response=excluded.response,ready_at=excluded.ready_at,turn_id=excluded.turn_id,runtime=excluded.runtime,pane=excluded.pane,instance_pid=excluded.instance_pid''',
                (key, agent, sid, root, str(Path(event.get('cwd') or os.getcwd()).resolve()), label, old['label_edited'] if old else 0,
                 status, stamp, response, ready, old['ack_at'] if old else 0, turn or (old['turn_id'] if old else ''),
                 event.get('runtime', old['runtime'] if old else ''), event.get('pane', old['pane'] if old else ''), event.get('instance_pid', old['instance_pid'] if old else '')))
        return True

    def acknowledge(self, key):
        with self.transaction():
            self.db.execute('UPDATE conversations SET ack_at=ready_at WHERE id=?', (key,))

    def label(self, key, value):
        with self.transaction():
            self.db.execute('UPDATE conversations SET label=?,label_edited=1 WHERE id=?', (excerpt(value, 120), key))

    def reviewed(self, root):
        with self.transaction():
            self.db.execute('UPDATE projects SET reviewed_at=? WHERE root=?', (time.time(), root))


SCHEMA = [
    '''CREATE TABLE projects(root TEXT PRIMARY KEY,name TEXT NOT NULL,note TEXT NOT NULL DEFAULT '',registered INTEGER NOT NULL DEFAULT 0,ignored INTEGER NOT NULL DEFAULT 0,reviewed_at REAL NOT NULL DEFAULT 0)''',
    '''CREATE TABLE conversations(id TEXT PRIMARY KEY,agent TEXT NOT NULL,session_id TEXT NOT NULL,root TEXT REFERENCES projects(root),cwd TEXT NOT NULL,label TEXT NOT NULL DEFAULT '',label_edited INTEGER NOT NULL DEFAULT 0,status TEXT NOT NULL,observed_at REAL NOT NULL,response TEXT NOT NULL DEFAULT '',ready_at REAL NOT NULL DEFAULT 0,ack_at REAL NOT NULL DEFAULT 0,turn_id TEXT NOT NULL DEFAULT '',runtime TEXT NOT NULL DEFAULT '',pane TEXT NOT NULL DEFAULT '',instance_pid TEXT NOT NULL DEFAULT '')''',
    'CREATE TABLE events(id TEXT PRIMARY KEY,conversation TEXT NOT NULL,observed_at REAL NOT NULL)',
    'CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)',
    '''CREATE TABLE recoveries(conversation TEXT NOT NULL,snapshot TEXT NOT NULL,runtime TEXT NOT NULL,pane TEXT NOT NULL,token TEXT NOT NULL,PRIMARY KEY(conversation,runtime))''',
]
