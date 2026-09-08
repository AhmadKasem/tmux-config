"""tmux protocol access; runtime identities never survive a server restart."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import time
from .state import excerpt, repository

FIELDS = ['socket_path', 'start_time', 'pid', 'pane_id', 'pane_pid', 'session_id', 'session_name', 'window_id', 'window_index', 'pane_index', 'pane_current_path', 'pane_current_command', 'pane_start_command', '@overview', '@overview_placeholder', 'pane_dead', 'pane_active']


def process_identity(pid):
    try:
        data = Path(f'/proc/{int(pid)}/stat').read_text().rsplit(')', 1)[1].split()
        return f'{pid}:{data[19]}'
    except (OSError, ValueError, IndexError):
        return ''


class Tmux:
    def __init__(self, socket=None):
        self.socket = socket or os.environ.get('OVERVIEW_SOCKET') or (os.environ.get('TMUX', '').split(',')[0] or None)

    def run(self, *args, check=True):
        command = ['tmux'] + (['-S', self.socket] if self.socket else []) + list(args)
        result = subprocess.run(command, capture_output=True, text=True, timeout=8)
        if check and result.returncode:
            raise RuntimeError(excerpt(result.stderr) or 'tmux command failed')
        return result.stdout.strip()

    def identity(self):
        raw = self.run('display-message', '-p', '#{socket_path}\t#{start_time}\t#{pid}')
        socket, start, pid = raw.split('\t')
        # Kernel boot ID and PID birth tick disambiguate same-second server restarts.
        boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        return json.dumps([socket, start, process_identity(pid), boot], separators=(',', ':'))

    def panes(self):
        runtime = self.identity()
        rows = self.run('list-panes', '-a', '-F', '\t'.join('#{' + f + '}' for f in FIELDS))
        result = {}
        for line in rows.splitlines():
            parts = line.split('\t')
            if len(parts) != len(FIELDS):
                continue  # tabs/newlines cannot be safely represented by tmux's format protocol
            row = dict(zip(FIELDS, parts))
            if row['@overview'] == '1':
                continue
            row['runtime'] = runtime
            row['location'] = [row['session_name'], row['window_index'], row['pane_index']]
            if row['pane_id'] in result:
                result[row['pane_id']]['locations'].append(row['location'])
            else:
                row['locations'] = [row['location']]
                result[row['pane_id']] = row
        return list(result.values())

    def jump(self, runtime, pane_id, client=None):
        row = next((r for r in self.panes() if r['runtime'] == runtime and r['pane_id'] == pane_id), None)
        if not row:
            raise RuntimeError('Pane is no longer available')
        # Prefer the client's existing linked-window location to preserve shared navigation.
        current = self.run('display-message', *( ['-c', client] if client else []), '-p', '#{session_name}')
        loc = next((loc for loc in row['locations'] if loc[0] == current), row['location'])
        self.run('select-window', '-t', f'{loc[0]}:{loc[1]}')
        self.run('select-pane', '-t', pane_id)
        if current != loc[0]:
            self.run('switch-client', *( ['-c', client] if client else []), '-t', '=' + loc[0])

    def option(self, key, value=None):
        if value is None:
            return self.run('show-options', '-gqv', key)
        return self.run('set-option', '-g', key, value)

    def environment(self):
        raw = self.run('display-message', '-p', '#{socket_path},#{pid},0')
        return dict(os.environ, TMUX=raw)


def observe(store, tmux):
    panes = tmux.panes()
    for pane in panes:
        pane['root'] = store.project(pane['pane_current_path'])
    return panes


def display_status(conversation, panes, now=None):
    now = now or time.time()
    live = next((p for p in panes if p['runtime'] == conversation['runtime'] and p['pane_id'] == conversation['pane']), None)
    if not conversation['runtime'] or not conversation['pane']:
        return 'Unknown' if conversation['status'] != 'Interrupted/disconnected' else 'Interrupted/disconnected'
    if conversation['status'] == 'Interrupted/disconnected' or not live or live['pane_dead'] == '1':
        return 'Interrupted/disconnected'
    identity = conversation['instance_pid']
    if identity and process_identity(identity.split(':')[0]) != identity:
        return 'Interrupted/disconnected'
    if conversation['status'] == 'Waiting':
        return 'Waiting'
    if conversation['ready_at'] > conversation['ack_at']:
        return 'Response ready'
    if conversation['status'] == 'Working' and now - conversation['observed_at'] <= 120:
        return 'Working'
    return 'Unknown'


def launcher():
    return str(Path(__file__).resolve().parents[1] / 'bin/overview')


def command(*args):
    return shlex.join([launcher(), *args])


def open_window(tmux, client=None):
    rows = tmux.run('list-windows', '-F', '#{window_id}\t#{@overview_window}').splitlines()
    window = next((r.split('\t')[0] for r in rows if r.endswith('\t1')), None)
    if not window:
        window = tmux.run('new-window', '-d', '-P', '-F', '#{window_id}', '-n', 'overview', command('ui', *(['--client', client] if client else [])))
        tmux.run('set-option', '-w', '-t', window, '@overview_window', '1')
    if client:
        tmux.run('set-option', '-w', '-t', window, '@overview_client', client)
    tmux.run('select-window', '-t', window)
