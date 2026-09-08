"""Command-line surface. Hooks never print output to the agent."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
from .state import Store
from .tmux import Tmux, observe, open_window


def parser():
    p = argparse.ArgumentParser(prog='overview', description='Persistent projects, agent attention, and tmux recovery')
    p.add_argument('--socket', help='tmux socket path (default: current server)')
    sub = p.add_subparsers(dest='command', required=True)
    for name in ('open', 'ui'):
        sub.add_parser(name).add_argument('--client')
    for name in ('status', 'save', 'restore', 'doctor', 'list', 'bootstrap', 'configure-status'):
        sub.add_parser(name)
    for name in ('install', 'uninstall'):
        sub.add_parser(name).add_argument('--home', type=Path)
    project = sub.add_parser('project')
    project.add_argument('action', choices=['register', 'ignore', 'edit', 'review', 'list'])
    project.add_argument('path', nargs='?', default='.')
    project.add_argument('--name')
    project.add_argument('--note')
    for name in ('ack', 'resume', 'run-conversation'):
        sub.add_parser(name).add_argument('conversation', help='agent:conversation-id')
    label = sub.add_parser('label')
    label.add_argument('conversation')
    label.add_argument('text')
    sub.add_parser('event', help='Read a normalized observational event from stdin')
    sub.add_parser('hook').add_argument('agent', choices=['codex', 'claude'])
    sub.add_parser('hooks-config').add_argument('agent', choices=['codex', 'claude'])
    sub.add_parser('pair').add_argument('snapshot')
    sub.add_parser('placeholder').add_argument('token')
    return p


def read_payload():
    raw = sys.stdin.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError('Hook payload exceeds 1 MiB limit')
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError('Expected a JSON object')
    return data


def doctor(store, tmux):
    from .recovery import VENDOR, load_manifest
    report = {'python': sys.version.split()[0], 'state': str(store.directory), 'sqlite': store.db.execute('PRAGMA integrity_check').fetchone()[0], 'executables': {name: shutil.which(name) for name in ('tmux', 'codex', 'claude')}, 'plugins': {name: (VENDOR / name).exists() for name in ('tmux-resurrect', 'tmux-continuum')}, 'last_save': store.meta('last-save'), 'last_restore': store.meta('last-restore'), 'last_error': store.meta('last-error'), 'limitations': ['Hooks require activation/trust; unknown status means observation is unavailable or stale.', 'Retained conversation history is checked by the agent on explicit resume.', 'Continuum saves require a rendering tmux status bar and may disable itself with multiple servers.']}
    try:
        report['runtime'] = tmux.identity()
        report['panes'] = len(tmux.panes())
        report['continuum_active'] = 'continuum_save.sh' in tmux.option('status-right')
        report['program_replay_disabled'] = tmux.option('@resurrect-processes') == 'false'
        try:
            path, manifest = load_manifest(tmux)
            report['snapshot'] = str(path)
            report['paired_conversations'] = len(manifest['entries'])
            report['mapping_warnings'] = manifest.get('warnings', [])
        except (OSError, ValueError, RuntimeError) as e:
            report['snapshot_warning'] = str(e)
    except (RuntimeError, OSError) as e:
        report['tmux_warning'] = str(e)
    return report


def main():
    os.umask(0o077)
    args = parser().parse_args()
    tmux = Tmux(args.socket)
    try:
        store = Store()
        cmd = args.command
        if cmd == 'open':
            open_window(tmux, args.client)
        elif cmd == 'ui':
            from .ui import run
            run(store, tmux, args.client)
        elif cmd == 'project':
            if args.action == 'list':
                print(json.dumps(store.rows('SELECT * FROM projects ORDER BY name'), indent=2))
            else:
                root = store.project(args.path, registered=args.action == 'register', ignored=args.action == 'ignore', name=args.name, note=args.note)
                if args.action == 'review':
                    store.reviewed(root)
                print(root)
        elif cmd == 'label':
            store.label(args.conversation, args.text)
        elif cmd == 'ack':
            store.acknowledge(args.conversation)
        elif cmd == 'event':
            store.event(read_payload())
        elif cmd == 'hook':
            from .hooks import ingest
            ingest(store, tmux, args.agent, read_payload())
        elif cmd == 'hooks-config':
            from .hooks import configuration
            print(json.dumps(configuration(args.agent), indent=2))
        elif cmd in ('save', 'restore', 'resume', 'pair', 'placeholder', 'run-conversation', 'bootstrap'):
            from . import recovery
            if cmd == 'bootstrap':
                directory = Path(tmux.option('@resurrect-dir'))
                if not (directory / 'last').exists():
                    recovery.save(store, tmux)
            elif cmd == 'save':
                print(recovery.save(store, tmux))
            elif cmd == 'restore':
                recovery.restore(store, tmux)
            elif cmd == 'resume':
                print(recovery.resume(store, tmux, args.conversation))
            elif cmd == 'run-conversation':
                recovery.run_conversation(store, tmux, args.conversation)
            elif cmd == 'pair':
                recovery.pair(store, tmux, args.snapshot)
            else:
                recovery.placeholder(store, tmux, args.token)
        elif cmd in ('status', 'list'):
            from .ui import status_line
            try:
                panes = observe(store, tmux) if cmd == 'list' else tmux.panes()
            except (OSError, RuntimeError):
                panes = []
            if cmd == 'status':
                print(status_line(store, panes))
            else:
                from .tmux import display_status
                cs = store.rows('SELECT * FROM conversations')
                for c in cs:
                    c['display_status'] = display_status(c, panes)
                print(json.dumps({'projects': store.rows('SELECT * FROM projects'), 'conversations': cs, 'panes': panes}, indent=2))
        elif cmd == 'doctor':
            print(json.dumps(doctor(store, tmux), indent=2))
        elif cmd == 'configure-status':
            from .install import configure_status
            configure_status(tmux)
        elif cmd == 'install':
            root = Path(__file__).resolve().parents[2]
            raise SystemExit(subprocess.call([sys.executable, str(root / 'install.py'), *(['--home', str(args.home)] if args.home else [])]))
        elif cmd == 'uninstall':
            from . import install
            print(getattr(install, cmd)(store, tmux, args.home))
    except (OSError, ValueError, RuntimeError, sqlite3.Error, subprocess.TimeoutExpired) as e:
        if args.command in ('save', 'restore', 'pair', 'bootstrap'):
            try:
                import time
                store.meta('last-error', {'command': args.command, 'message': str(e), 'at': time.time()})
            except (UnboundLocalError, sqlite3.Error, OSError):
                pass
        if args.command == 'hook':
            # Exit zero, no stdout: an observational write must never block an agent.
            print('overview hook: ' + str(e), file=sys.stderr)
            return
        print('overview: ' + str(e), file=sys.stderr)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
