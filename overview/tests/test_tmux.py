"""Real tmux integration using disposable sockets and state. No live user server."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch
from overview.state import Store
from overview.tmux import Tmux, command, observe, open_window
from overview.install import install, uninstall
from overview.recovery import save, restore, resume, load_manifest


@unittest.skipUnless(os.environ.get('OVERVIEW_TEST_TMUX') == '1', 'Set OVERVIEW_TEST_TMUX=1 for isolated tmux tests')
class TmuxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='overview-test-')
        self.root = Path(self.tmp.name)
        self.home = self.root / 'home'
        self.home.mkdir()
        self.socket = str(self.root / 'tmux.sock')
        self.env = patch.dict(os.environ, OVERVIEW_STATE_DIR=str(self.root / 'state'), OVERVIEW_SOCKET=self.socket, TMUX='', TMUX_PANE='')
        self.env.start()
        self.store = Store()
        self.tmux = Tmux(self.socket)
        self.start()
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.tmux.run('kill-server', check=False)
        self.store.db.close()
        self.env.stop()
        self.tmp.cleanup()

    def start(self, name='work'):
        result = subprocess.run(['tmux', '-S', self.socket, '-f', '/dev/null', 'new-session', '-d', '-s', name, '-x', '65', '-y', '24', '-c', str(self.home)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.tmux.option('default-shell', '/bin/sh')
        self.tmux.option('status-right', 'original-theme')

    def register(self, pane=None, sid='abc'):
        pane = pane or self.tmux.panes()[0]
        self.store.event(dict(agent='codex', session_id=sid, kind='prompt', cwd=str(self.home), runtime=pane['runtime'], pane=pane['pane_id'], prompt='Exact conversation', observed_at=time.time()))
        return pane

    def setup_install(self):
        (self.home / '.tmux.conf').write_text('set -g status-right "original-theme"\nset -g base-index 1\n')
        install(self.store, self.tmux, self.home)
        # Disable automatic asynchronous restoration during deterministic manual tests.
        self.tmux.option('@continuum-restore', 'off')

    def fake_agent(self):
        bin_dir = self.root / 'bin'
        bin_dir.mkdir()
        binary = bin_dir / 'codex'
        binary.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$OVERVIEW_TEST_ARGS"\nexec sleep 600\n')
        binary.chmod(0o700)
        self.tmux.run('set-environment', '-g', 'PATH', str(bin_dir) + ':' + os.environ['PATH'])
        self.tmux.run('set-environment', '-g', 'OVERVIEW_TEST_ARGS', str(self.root / 'args'))
        return patch.dict(os.environ, PATH=str(bin_dir) + ':' + os.environ['PATH'], OVERVIEW_TEST_ARGS=str(self.root / 'args'))

    def test_link_move_close_and_narrow_wide_ui(self):
        pane = self.tmux.panes()[0]
        self.tmux.run('new-session', '-d', '-s', 'linked')
        self.tmux.run('link-window', '-s', 'work:0', '-t', 'linked:1')
        rows = self.tmux.panes()
        linked = next(r for r in rows if r['pane_id'] == pane['pane_id'])
        self.assertEqual(len(linked['locations']), 2)
        self.tmux.run('move-window', '-s', 'work:0', '-t', 'work:3')
        self.tmux.jump(pane['runtime'], pane['pane_id'])
        self.assertTrue(any(loc[1] == '3' for loc in next(p for p in self.tmux.panes() if p['pane_id'] == pane['pane_id'])['locations']))
        open_window(self.tmux)
        time.sleep(.3)
        windows = self.tmux.run('list-windows', '-F', '#{window_id}').splitlines()
        open_window(self.tmux)
        self.assertEqual(windows, self.tmux.run('list-windows', '-F', '#{window_id}').splitlines())
        active = self.tmux.run('display-message', '-p', '#{pane_id}')
        for width in (65, 160):
            self.tmux.run('resize-window', '-x', str(width), '-y', '24')
            time.sleep(.2)
            output = self.tmux.run('capture-pane', '-p', '-t', active)
            self.assertIn('OVERVIEW', output)
            self.assertNotIn(active, [p['pane_id'] for p in self.tmux.panes()])
        self.tmux.run('kill-pane', '-t', pane['pane_id'])
        with self.assertRaises(RuntimeError):
            self.tmux.jump(pane['runtime'], pane['pane_id'])

    def test_install_repeat_uninstall_preserves_settings(self):
        self.setup_install()
        conf = (self.home / '.tmux.conf').read_text()
        install(self.store, self.tmux, self.home)
        self.assertEqual(conf, (self.home / '.tmux.conf').read_text())
        self.assertEqual(self.tmux.option('status-right').count('overview status'), 1)
        self.assertEqual(self.tmux.option('@continuum-save-interval'), '5')
        settings = self.home / '.claude/settings.json'
        data = json.loads(settings.read_text())
        custom = {'type': 'command', 'command': 'echo mine'}
        data['hooks']['Stop'][0]['hooks'].append(custom)
        settings.write_text(json.dumps(data))
        uninstall(self.store, self.tmux, self.home)
        self.assertEqual((self.home / '.tmux.conf').read_text(), 'set -g status-right "original-theme"\nset -g base-index 1\n')
        self.assertEqual(json.loads(settings.read_text())['hooks']['Stop'][0]['hooks'], [custom])
        self.assertTrue((self.root / 'state/overview.sqlite3').exists())
        self.assertNotIn('overview status', self.tmux.option('status-right'))

    def test_destroy_restore_exact_resume_and_no_duplicates(self):
        original = self.register()
        self.tmux.run('select-pane', '-t', original['pane_id'], '-T', '')
        self.setup_install()
        saved = save(self.store, self.tmux)
        _, manifest = load_manifest(self.tmux)
        self.assertEqual(manifest['entries'][0]['conversation'], 'codex:abc')
        self.assertEqual(manifest['entries'][0]['cwd'], str(self.home))
        self.tmux.run('kill-server')
        time.sleep(.15)
        self.start('bootstrap')
        # Load integration without continuum's asynchronous restore.
        from overview.install import configuration_text
        conf = self.root / 'restore.conf'
        conf.write_text(configuration_text(self.store).replace("set -g @continuum-restore 'on'", "set -g @continuum-restore 'off'"))
        self.tmux.run('source-file', str(conf))
        self.assertNotEqual(original['runtime'], self.tmux.identity())
        restore(self.store, self.tmux)
        time.sleep(.2)
        panes = self.tmux.panes()
        placeholder = next(p for p in panes if p['session_name'] == 'work')
        self.assertTrue(placeholder['@overview_placeholder'])
        restore(self.store, self.tmux)
        self.assertEqual(len(panes), len(self.tmux.panes()))
        with self.fake_agent():
            resumed = resume(self.store, self.tmux, 'codex:abc')
            self.assertEqual(resumed, placeholder['pane_id'])
            time.sleep(.15)
            self.assertEqual((self.root / 'args').read_text().splitlines(), ['resume', 'abc'])
            self.assertEqual(resume(self.store, self.tmux, 'codex:abc'), resumed)
        self.assertEqual(len(panes), len(self.tmux.panes()))

    def test_occupied_pane_protection_and_manifest_tampering(self):
        self.register()
        self.setup_install()
        path, manifest = load_manifest(self.tmux)
        with path.open('a') as f:
            f.write('# changed\n')
        with self.assertRaises(RuntimeError):
            restore(self.store, self.tmux)
        save(self.store, self.tmux)
        self.tmux.run('kill-server')
        time.sleep(.15)
        self.start('bootstrap')
        from overview.install import configuration_text
        conf = self.root / 'restore.conf'
        conf.write_text(configuration_text(self.store).replace("set -g @continuum-restore 'on'", "set -g @continuum-restore 'off'"))
        self.tmux.run('source-file', str(conf))
        restore(self.store, self.tmux)
        time.sleep(.2)
        recovered = next(p for p in self.tmux.panes() if p['session_name'] == 'work')
        self.tmux.run('send-keys', '-t', recovered['pane_id'], 'Enter')
        time.sleep(.15)
        self.tmux.run('send-keys', '-t', recovered['pane_id'], 'sleep 600', 'Enter')
        time.sleep(.15)
        count = len(self.tmux.panes())
        with self.fake_agent():
            resumed = resume(self.store, self.tmux, 'codex:abc')
        self.assertNotEqual(resumed, recovered['pane_id'])
        self.assertEqual(len(self.tmux.panes()), count + 1)
        self.assertEqual(next(p for p in self.tmux.panes() if p['pane_id'] == recovered['pane_id'])['pane_current_command'], 'sleep')

    def test_automatic_continuum_restore_and_initial_save(self):
        self.register()
        self.setup_install()
        self.tmux.run('kill-server')
        time.sleep(.15)
        # Simulate a single-server process listing without interfering with the
        # actual user's server. All other ps invocations pass through unchanged.
        bindir = self.root / 'single-server-bin'
        bindir.mkdir()
        ps = bindir / 'ps'
        ps.write_text('#!/bin/sh\nif [ "$1" = "-u" ]; then exit 0; fi\nexec /usr/bin/ps "$@"\n')
        ps.chmod(0o700)
        from overview.install import configuration_text
        config = self.root / 'auto.conf'
        config.write_text(configuration_text(self.store))
        env = dict(os.environ, PATH=str(bindir) + ':' + os.environ['PATH'])
        subprocess.run(['tmux', '-S', self.socket, '-f', str(config), 'new-session', '-d', '-s', 'bootstrap', '-c', str(self.home)], env=env, check=True, capture_output=True)
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline and not self.store.meta('last-restore'):
            time.sleep(.1)
        self.assertIsNotNone(self.store.meta('last-restore'), repr(self.store.meta('last-error')))
        self.assertIn('continuum_save.sh', self.tmux.option('status-right'))
        self.assertEqual(self.tmux.option('@resurrect-processes'), 'false')
        self.assertTrue(any(p['@overview_placeholder'] for p in self.tmux.panes()))
        # Exercise the actual continuum five-minute save gate without a five-minute wait.
        previous = self.store.meta('last-save')['at']
        self.tmux.option('@continuum-save-last-timestamp', '1')
        from overview.recovery import VENDOR
        subprocess.run([str(VENDOR / 'tmux-continuum/scripts/continuum_save.sh')], env=self.tmux.environment(), check=True, capture_output=True)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and self.store.meta('last-save')['at'] <= previous:
            time.sleep(.1)
        self.assertGreater(self.store.meta('last-save')['at'], previous)
        _, manifest = load_manifest(self.tmux)
        self.assertTrue(any(e['conversation'] == 'codex:abc' for e in manifest['entries']))

    def test_missing_directory_does_not_create_pane(self):
        self.register()
        with self.store.transaction():
            self.store.db.execute("UPDATE conversations SET cwd=?,runtime='gone'", (str(self.root / 'missing'),))
        count = len(self.tmux.panes())
        with self.assertRaisesRegex(RuntimeError, 'Missing directory'):
            resume(self.store, self.tmux, 'codex:abc')
        self.assertEqual(len(self.tmux.panes()), count)


if __name__ == '__main__':
    unittest.main()
