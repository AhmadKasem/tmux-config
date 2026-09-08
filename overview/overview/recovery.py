"""Snapshot-bound manifests and explicit, non-destructive conversation recovery."""
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import time
import uuid
from .tmux import command, launcher, process_identity

VENDOR = Path(__file__).resolve().parents[1] / 'vendor'


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temp.open('x') as file:
            os.chmod(temp, 0o600)
            json.dump(value, file, indent=2)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


@contextlib.contextmanager
def lock(store):
    with (store.directory / 'recovery.lock').open('a') as file:
        deadline = time.monotonic() + 2
        while True:
            try:
                fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() > deadline:
                    raise RuntimeError('Another recovery operation is in progress')
                time.sleep(.05)
        yield


def snapshot_locations(path):
    locations = []
    for line in path.read_text().splitlines():
        fields = line.split('\t')
        if fields[0] == 'pane' and len(fields) >= 11:
            locations.append(([fields[1], fields[2], fields[5]], fields[7].removeprefix(':')))
    return locations


def snapshot_digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(store, tmux):
    with lock(store):
        directory = Path(tmux.option('@resurrect-dir'))
        deadline = time.monotonic() + 2
        while (directory / time.strftime('tmux_resurrect_%Y%m%dT%H%M%S.txt')).exists():
            if time.monotonic() > deadline:
                raise RuntimeError('Snapshot timestamp collision; retry save')
            time.sleep(.05)
        before = tmux.panes()
        conversations = store.rows('SELECT * FROM conversations')
        pending = {'runtime': tmux.identity(), 'panes': before, 'conversations': conversations, 'at': time.time()}
        # Per-server pending data; hook called synchronously by resurrect.
        store.meta('pending-save:' + tmux.identity(), pending)
        result = subprocess.run([str(VENDOR / 'tmux-resurrect/scripts/save.sh')], env=tmux.environment(), capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise RuntimeError('Resurrect save failed: ' + result.stderr[-300:])
        last = Path(tmux.option('@resurrect-dir')) / 'last'
        if not last.exists() or not last.with_name(last.resolve().name + '.overview.json').exists():
            raise RuntimeError('Snapshot has no paired manifest; run overview doctor')
        path, manifest = load_manifest(tmux)
        paired = store.meta('paired-save:' + tmux.identity())
        if not paired or paired['at'] < pending['at'] or paired['snapshot'] != str(path) or paired['digest'] != manifest['digest']:
            raise RuntimeError('Latest save did not complete snapshot pairing')
        store.meta('last-save', {'at': time.time(), 'snapshot': str(path), 'digest': manifest['digest'], 'warnings': manifest.get('warnings', [])})
        return str(last.resolve())


def pair(store, tmux, snapshot):
    path = Path(snapshot).resolve()
    pending = store.meta('pending-save:' + tmux.identity())
    if not pending or time.time() - pending['at'] > 65:
        raise RuntimeError('Save was not started through overview; refusing an inferred manifest')
    current = {p['pane_id']: p for p in tmux.panes()}
    entries, warnings = [], []
    repair_empty_title_records(path, pending['panes'], current)
    for location, cwd in snapshot_locations(path):
        before = [p for p in pending['panes'] if location in p['locations'] and p['pane_current_path'] == cwd]
        if len(before) != 1:
            warnings.append({'location': location, 'reason': 'Pane moved or snapshot location is ambiguous'})
            continue
        p = before[0]
        now = current.get(p['pane_id'])
        if not now or location not in now['locations'] or now['pane_pid'] != p['pane_pid'] or now['pane_current_path'] != cwd:
            continue
        matches = [c for c in pending['conversations'] if c['runtime'] == p['runtime'] and c['pane'] == p['pane_id'] and c['status'] != 'Interrupted/disconnected' and (not c['instance_pid'] or process_identity(c['instance_pid'].split(':')[0]) == c['instance_pid'])]
        # Preserve prior recovery mapping when the pane is still an untouched placeholder.
        if not matches and p['@overview_placeholder']:
            ids = store.rows('SELECT conversation FROM recoveries WHERE runtime=? AND pane=? AND token=?', (p['runtime'], p['pane_id'], p['@overview_placeholder']))
            matches = [c for c in pending['conversations'] if c['id'] in [i['conversation'] for i in ids]]
        if len(matches) > 1:
            warnings.append({'location': location, 'reason': 'Multiple conversation references; resume individually in a new pane', 'conversations': [c['id'] for c in matches]})
        if len(matches) == 1:
            c = matches[0]
            entries.append({'location': location, 'conversation': c['id'], 'cwd': c['cwd']})
    digest = snapshot_digest(path)
    manifest = {'version': 1, 'digest': digest, 'created_at': time.time(), 'entries': entries, 'warnings': warnings}
    atomic_json(Path(str(path) + '.overview.json'), manifest)
    # Force resurrect to retain a new layout file when only conversation mapping changed.
    # Its comment parser ignores this line. Hash includes the manifest-binding marker.
    with path.open('a') as file:
        file.write('\n# overview-manifest ' + uuid.uuid4().hex + '\n')
    manifest['digest'] = snapshot_digest(path)
    atomic_json(Path(str(path) + '.overview.json'), manifest)
    store.meta('paired-save:' + tmux.identity(), {'at': time.time(), 'snapshot': str(path), 'digest': manifest['digest']})


def load_manifest(tmux):
    path = (Path(tmux.option('@resurrect-dir')) / 'last').resolve()
    data = json.loads(Path(str(path) + '.overview.json').read_text())
    if data.get('version') != 1 or data.get('digest') != snapshot_digest(path):
        raise RuntimeError('Missing, mismatched or unsupported snapshot manifest')
    return path, data


def pre_restore(store, tmux):
    path, manifest = load_manifest(tmux)
    token = uuid.uuid4().hex
    state = {'snapshot': str(path), 'manifest': manifest, 'token': token, 'default_command': tmux.option('default-command'), 'before': [p['pane_id'] for p in tmux.panes()]}
    state['placeholder_command'] = command('placeholder', token)
    store.meta('restore:' + tmux.identity(), state)
    tmux.option('default-command', state['placeholder_command'])


def post_restore(store, tmux):
    state = store.meta('restore:' + tmux.identity())
    if not state:
        return
    if tmux.option('default-command') == state['placeholder_command']:
        tmux.option('default-command', state['default_command'])
    panes = tmux.panes()
    with store.transaction():
        for entry in state['manifest']['entries']:
            matches = [p for p in panes if entry['location'] in p['locations'] and p['pane_id'] not in state['before'] and started_as(p, state['placeholder_command'])]
            if len(matches) != 1:
                continue
            p = matches[0]
            tmux.run('set-option', '-p', '-t', p['pane_id'], '@overview_placeholder', state['token'])
            store.db.execute('INSERT INTO recoveries VALUES (?,?,?,?,?) ON CONFLICT(conversation,runtime) DO UPDATE SET snapshot=excluded.snapshot,pane=excluded.pane,token=excluded.token', (entry['conversation'], state['snapshot'], p['runtime'], p['pane_id'], state['token']))
    store.meta('last-restore', {'at': time.time(), 'snapshot': state['snapshot']})


def restore(store, tmux):
    with lock(store):
        load_manifest(tmux)  # Fail before changing any tmux state.
        try:
            pre_restore(store, tmux)
            result = subprocess.run([str(VENDOR / 'tmux-resurrect/scripts/restore.sh')], env=tmux.environment(), capture_output=True, text=True, timeout=60)
            if result.returncode:
                raise RuntimeError('Resurrect restore failed: ' + result.stderr[-300:])
        finally:
            post_restore(store, tmux)


def placeholder(store, tmux, token):
    pane = os.environ.get('TMUX_PANE')
    tmux.run('set-option', '-p', '-t', pane, '@overview_placeholder', token)
    print('Recovered layout. Resume a conversation from overview.\nPress Enter to use this pane as a shell.', flush=True)
    try:
        input()
    except EOFError:
        pass
    # Clear ownership before starting an interactive shell, even if it looks idle later.
    with lock(store):
        tmux.run('set-option', '-p', '-t', pane, '-u', '@overview_placeholder')
        shell = tmux.option('default-shell') or '/bin/sh'
        os.execv(shell, [shell, '-l'])


def resume(store, tmux, key):
    with lock(store):
        rows = store.rows('SELECT * FROM conversations WHERE id=?', (key,))
        if not rows:
            raise ValueError('Unknown conversation')
        c = rows[0]
        if not Path(c['cwd']).is_dir():
            raise RuntimeError(f"Missing directory: {c['cwd']}; restore it or use project notes to record recovery")
        binary = shutil.which(c['agent'])
        if not binary:
            raise RuntimeError(f"Missing executable: {c['agent']}")
        panes = tmux.panes()
        live = next((p for p in panes if p['runtime'] == c['runtime'] and p['pane_id'] == c['pane'] and p['pane_dead'] != '1' and c['status'] != 'Interrupted/disconnected' and (not c['instance_pid'] or process_identity(c['instance_pid'].split(':')[0]) == c['instance_pid'])), None)
        if live:
            return live['pane_id']
        mappings = store.rows('SELECT * FROM recoveries WHERE conversation=? AND runtime=?', (key, tmux.identity()))
        match = next((p for p in panes for m in mappings if p['pane_id'] == m['pane'] and p['@overview_placeholder'] == m['token'] and started_as(p, command('placeholder', m['token'])) and p['pane_dead'] != '1'), None)
        # tmux executes argv directly when more than one command argument is supplied.
        args = [command('run-conversation', key)]
        if match:
            # The placeholder process cooperates through the same lock before releasing
            # ownership; verify its live executable as a final check before respawn.
            if not placeholder_alive(match):
                match = None
        if match:
            pane = match['pane_id']
            tmux.run('respawn-pane', '-k', '-t', pane, '-c', c['cwd'], *args)
            tmux.run('set-option', '-p', '-t', pane, '-u', '@overview_placeholder')
        else:
            pane = tmux.run('new-window', '-d', '-P', '-F', '#{pane_id}', '-n', c['label'][:30] or c['agent'], '-c', c['cwd'], *args)
        row = next(p for p in tmux.panes() if p['pane_id'] == pane)
        with store.transaction():
            store.db.execute("UPDATE conversations SET runtime=?,pane=?,instance_pid=?,status='Unknown',observed_at=? WHERE id=?", (row['runtime'], pane, process_identity(row['pane_pid']), time.time(), key))
        return pane


def placeholder_alive(pane):
    try:
        args = Path(f"/proc/{pane['pane_pid']}/cmdline").read_bytes().split(b'\0')
        return b'placeholder' in args and pane['@overview_placeholder'].encode() in args
    except OSError:
        return False


def run_conversation(store, tmux, key):
    """Keep an agent's recovery failure visible without reading its private history."""
    with lock(store):
        c = store.rows('SELECT * FROM conversations WHERE id=?', (key,))[0]
    argv = [c['agent'], 'resume', c['session_id']] if c['agent'] == 'codex' else [c['agent'], '--resume', c['session_id']]
    try:
        code = subprocess.call(argv, cwd=c['cwd'])
    except OSError as error:
        print(str(error), flush=True)
        code = 127
    with store.transaction():
        store.db.execute("UPDATE conversations SET status='Interrupted/disconnected',observed_at=? WHERE id=? AND pane=? AND runtime=?", (time.time(), key, os.environ.get('TMUX_PANE', ''), tmux.identity()))
    print(f'\n{key} exited with status {code}. If history is missing, restore the agent history backup.\nConversation ID and directory remain in overview. Press Enter for a shell.', flush=True)
    try:
        input()
    except EOFError:
        pass
    shell = tmux.option('default-shell') or '/bin/sh'
    os.execv(shell, [shell, '-l'])


def started_as(pane, expected):
    raw = pane['pane_start_command']
    try:
        actual = shlex.split(raw)
        if len(actual) == 1:
            actual = shlex.split(actual[0])
        wanted = shlex.split(expected)
        return (bool(actual) and bool(wanted) and actual[1:] == wanted[1:]
                and Path(actual[0]).is_absolute()
                and Path(actual[0]).resolve() == Path(wanted[0]).resolve())
    except ValueError:
        return False


def repair_empty_title_records(path, before, current):
    """Resurrect's shell tab-reader collapses empty titles; repair from live facts.

    Only use a pre/post-stable runtime pane at its exact saved location. This
    repairs layout fields, never infers a conversation from a directory.
    """
    lines = []
    for line in path.read_text().splitlines():
        fields = line.split('\t')
        if fields[0] == 'pane' and len(fields) >= 6:
            location = [fields[1], fields[2], fields[5]]
            candidates = [p for p in before if location in p['locations']]
            if len(candidates) == 1:
                p = candidates[0]
                now = current.get(p['pane_id'])
                stable = now and location in now['locations'] and now['pane_pid'] == p['pane_pid'] and now['pane_current_path'] == p['pane_current_path']
                malformed = len(fields) != 11 or not fields[7].startswith(':') or fields[8] not in ('0', '1')
                if stable and malformed:
                    # A single blank is nonempty to the upstream tab parser and
                    # visually preserves an empty title. No program is replayed.
                    fields = fields[:6] + [' ', ':' + p['pane_current_path'], p['pane_active'], p['pane_current_command'] or 'sh', ':']
                    line = '\t'.join(fields)
        lines.append(line)
    path.write_text('\n'.join(lines) + '\n')
