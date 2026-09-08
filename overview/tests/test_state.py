import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch
from overview.state import Store, repository
from overview.hooks import ingest
from overview.tmux import display_status
from overview.ui import model, status_line


class StateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        self.addCleanup(self.store.db.close)
        self.base = time.time() - 100
        self.pane = {'runtime': 'r', 'pane_id': '%1', 'pane_dead': '0', 'root': self.tmp.name}

    def event(self, kind, seq, **extra):
        return self.store.event(dict(agent='codex', session_id='abc', kind=kind, observed_at=self.base + seq, event_id=str(seq), cwd=self.tmp.name, runtime='r', pane='%1', **extra))

    def conversation(self):
        return self.store.rows('SELECT * FROM conversations')[0]

    def test_transitions_ack_does_not_resolve_wait(self):
        self.event('prompt', 1, prompt='First task', turn_id='t1')
        self.event('response', 2, response='Done', turn_id='t1')
        self.assertEqual(display_status(self.conversation(), [self.pane]), 'Response ready')
        self.store.acknowledge('codex:abc')
        self.assertEqual(display_status(self.conversation(), [self.pane]), 'Unknown')
        self.event('prompt', 3, prompt='Next turn', turn_id='t2')
        self.event('waiting', 4, turn_id='t2')
        self.store.acknowledge('codex:abc')
        self.assertEqual(display_status(self.conversation(), [self.pane]), 'Waiting')
        self.event('tool', 5, turn_id='t2')
        self.assertEqual(display_status(self.conversation(), [self.pane]), 'Working')
        self.event('response', 6, response='New answer', turn_id='t2')
        self.assertEqual(display_status(self.conversation(), [self.pane]), 'Response ready')
        self.event('prompt', 7, prompt='Another', turn_id='t3')
        self.assertEqual(self.conversation()['ready_at'], 0)

    def test_duplicate_old_wrong_turn_child_and_label(self):
        self.event('prompt', 1, prompt='Initial', turn_id='t1')
        self.store.label('codex:abc', 'Edited')
        self.event('prompt', 3, prompt='Later', turn_id='t2')
        self.assertFalse(self.event('response', 2, response='Old', turn_id='t1'))
        self.assertFalse(self.event('response', 3, response='Duplicate'))
        self.assertFalse(self.event('response', 4, response='Old turn delayed', turn_id='t1'))
        self.assertFalse(self.event('response', 5, response='Child', child=True))
        self.assertEqual(self.conversation()['label'], 'Edited')
        self.store.label('codex:abc', '')
        self.event('prompt', 6, prompt='Do not overwrite explicit blank label', turn_id='t3')
        self.assertEqual(self.conversation()['label'], '')
        self.assertEqual(self.conversation()['status'], 'Working')
        self.assertEqual(self.conversation()['response'], '')

    def test_restart_stale_and_persistent_response(self):
        self.event('prompt', 1)
        self.assertEqual(display_status(self.conversation(), [self.pane], self.base + 500), 'Unknown')
        self.assertEqual(display_status(self.conversation(), []), 'Interrupted/disconnected')
        self.event('response', 2, response='answer')
        self.assertEqual(display_status(self.conversation(), []), 'Interrupted/disconnected')
        self.assertIn('R:1', status_line(self.store, []))

    def test_registered_project_without_panes_and_due(self):
        root = self.store.project(self.tmp.name, registered=True, note='notes.md')
        self.assertEqual(len(model(self.store, [], set())), 1)
        self.assertIn('D:1', status_line(self.store, []))
        self.store.reviewed(root)
        self.assertIn('D:0', status_line(self.store, []))
        self.store.project(root, ignored=True)
        self.assertEqual(model(self.store, [], set()), [])

    def test_concurrent_updates_and_migration(self):
        def write(n):
            store = Store(self.tmp.name)
            try:
                store.event(dict(agent='claude', session_id='concurrent', kind='response', cwd=self.tmp.name, event_id='thread-' + str(n), observed_at=self.base + n, response=str(n)))
            finally:
                store.db.close()
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            list(pool.map(write, range(1, 40)))
        c = self.store.rows("SELECT * FROM conversations WHERE session_id='concurrent'")[0]
        self.assertEqual(c['response'], '39')
        self.assertEqual(self.store.db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        self.assertEqual((Path(self.tmp.name) / 'overview.sqlite3').stat().st_mode & 0o777, 0o600)

    def test_child_hook_is_ignored_without_tmux_access(self):
        class NoTmux:
            def panes(self):
                raise AssertionError('Must not inspect pane for child')
        self.assertFalse(ingest(self.store, NoTmux(), 'codex', {'hook_event_name': 'SubagentStop', 'session_id': 'abc', 'last_assistant_message': 'child'}))
        self.assertFalse(ingest(self.store, NoTmux(), 'claude', {'hook_event_name': 'Stop', 'session_id': 'abc', 'agent_id': 'child'}))

    def test_excerpt_bounded_and_control_characters_removed(self):
        self.event('response', 1, response='\x1b\n' + 'x' * 10000)
        self.assertEqual(len(self.conversation()['response']), 400)
        self.assertNotIn('\x1b', self.conversation()['response'])

    def test_worktrees_group_by_common_repository(self):
        repo = Path(self.tmp.name) / 'repo'
        wt = Path(self.tmp.name) / 'worktree'
        subprocess.run(['git', 'init', '-q', str(repo)], check=True)
        subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'init', '--allow-empty'], check=True)
        subprocess.run(['git', '-C', str(repo), 'worktree', 'add', '-qb', 'work', str(wt)], check=True)
        self.assertEqual(repository(repo), repository(wt))


if __name__ == '__main__':
    unittest.main()
