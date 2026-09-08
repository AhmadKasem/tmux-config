"""Whole-checkout installation and compatibility contract, using disposable homes."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'overview'))
from overview.hooks import configuration
from overview.install import same_handler, uninstall
from overview.state import Store
from overview.tmux import Tmux


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='workspace-test-')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.home = self.base / 'home with spaces'
        self.home.mkdir()
        self.socket = str(self.base / 'socket')
        self.env = dict(os.environ, HOME=str(self.home), TMUX='', OVERVIEW_SOCKET=self.socket,
                        OVERVIEW_STATE_DIR=str(self.home / '.local/state/tmux-overview'))
        self.env['PATH'] = str(self.home / '.local/bin') + ':' + os.environ['PATH']

    def install(self, *args, root=ROOT, success=True):
        result = subprocess.run([sys.executable, str(root / 'install.py'), '--home', str(self.home), *args], env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        return result

    def contents(self):
        return {str(p.relative_to(self.home)): (os.readlink(p) if p.is_symlink() else p.read_bytes()) for p in self.home.rglob('*') if p.is_file() or p.is_symlink()}

    def test_full_repeat_config_only_preserves_theme_palette_hooks_and_data(self):
        self.install('--theme', 'forest')
        theme = self.home / '.config/tmux/themes/forest.conf'
        theme.write_text(theme.read_text() + '\n# local palette\n')
        hooks = (self.home / '.codex/hooks.json').read_bytes()
        conf = (self.home / '.tmux.conf').read_text()
        self.install()
        self.assertEqual(conf, (self.home / '.tmux.conf').read_text())
        self.install('--config-only')
        self.assertEqual(hooks, (self.home / '.codex/hooks.json').read_bytes())
        self.assertTrue(theme.read_text().endswith('# local palette\n'))
        self.assertEqual(os.readlink(theme.parent / 'current.conf'), 'forest.conf')
        self.assertEqual((self.home / '.tmux.conf').read_text().count('# BEGIN tmux-overview'), 1)

    def test_config_only_has_no_overview_side_effects(self):
        self.install('--config-only')
        self.assertFalse((self.home / '.codex').exists())
        self.assertFalse((self.home / '.local/state/tmux-overview').exists())
        self.assertFalse((self.home / '.local/bin/overview').exists())

    def test_invalid_targets_and_shortcut_conflicts_are_atomic(self):
        for text in ('{broken', '[]', '{"hooks":{"Stop":{}}}', '{"hooks":{"Stop":[{"hooks":"bad"}]}}'):
            path = self.home / '.claude/settings.json'
            path.parent.mkdir(exist_ok=True)
            path.write_text(text)
            before = self.contents()
            self.install(success=False)
            self.assertEqual(before, self.contents())
        path.unlink()
        for line in ('bind G display-message mine\n', 'bind -T copy-mode-vi y send-keys mine\n'):
            (self.home / '.tmux.conf').write_text(line)
            before = self.contents()
            self.install(success=False)
            self.assertEqual(before, self.contents())

    def test_codex_trust_metadata_preserved_inline_definitions_rejected(self):
        path = self.home / '.codex/config.toml'
        path.parent.mkdir()
        trusted = '[hooks.state."example:stop:0:0"]\ntrusted_hash = "sha256:example"\n'
        path.write_text(trusted)
        self.install()
        self.assertEqual(path.read_text(), trusted)
        path.write_text('[hooks.Stop]\ncommand = "echo mine"\n')
        before = self.contents()
        self.install(success=False)
        self.assertEqual(before, self.contents())

    def test_migration_from_inline_and_sourced_styles(self):
        for sourced in (False, True):
            self.install()
            conf = self.home / '.tmux.conf'
            text = conf.read_text()
            start, end = text.index('# BEGIN tmux-overview'), text.index('# END tmux-overview') + len('# END tmux-overview (managed)\n')
            recovery = text[start:end]
            config = self.home / '.config/tmux'
            (config / 'overview.conf').write_text(recovery)
            integration = ('if-shell \'test -x "$HOME/projects/tmux-overview/bin/overview"\' \'source-file "$HOME/.config/tmux/overview.conf"\'\n' if sourced else recovery)
            conf.write_text('set -g history-limit 23456\nsource-file "$HOME/.config/tmux/themes/current.conf"\n' + integration + 'source-file "$HOME/.config/tmux/mobile.conf"\n')
            self.install()
            text = conf.read_text()
            self.assertEqual(text.count('# BEGIN tmux-overview'), 1)
            self.assertIn('history-limit 23456', text)
            self.assertLess(text.index('current.conf'), text.index('# BEGIN tmux-overview'))
            self.assertLess(text.index('# END tmux-overview'), text.index('mobile.conf'))

    def test_verified_legacy_hooks_survive_relocation_and_uninstall(self):
        legacy = self.base / 'former overview'
        legacy.symlink_to(ROOT / 'overview', target_is_directory=True)
        self.install()
        path = self.home / '.codex/hooks.json'
        data = json.loads(path.read_text())
        import shlex
        for entries in data['hooks'].values():
            for e in entries:
                for h in e['hooks']:
                    h['command'] = shlex.join([str(legacy / 'bin/overview'), 'hook', 'codex'])
        custom = {'type': 'command', 'command': 'echo untouched'}
        data['hooks']['Stop'][0]['hooks'].append(custom)
        path.write_text(json.dumps(data))
        before = path.read_bytes()
        self.install()
        self.assertEqual(json.loads(before), json.loads(path.read_text()))
        result = subprocess.run([str(legacy / 'bin/overview'), 'status'], env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run([str(ROOT / 'overview/bin/overview'), 'uninstall', '--home', str(self.home)], env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(path.read_text())['hooks']['Stop'][0]['hooks'], [custom])
        self.assertTrue((self.home / '.local/state/tmux-overview/overview.sqlite3').exists())

    def test_legacy_placeholder_ownership_requires_resolved_executable(self):
        import shlex
        from overview.recovery import started_as
        from overview.tmux import command
        legacy = self.base / 'legacy'
        legacy.symlink_to(ROOT / 'overview', target_is_directory=True)
        old = shlex.join([str(legacy / 'bin/overview'), 'placeholder', 'token'])
        self.assertTrue(started_as({'pane_start_command': old}, command('placeholder', 'token')))
        self.assertTrue(started_as({'pane_start_command': shlex.quote(old)}, command('placeholder', 'token')))
        self.assertFalse(started_as({'pane_start_command': old}, command('placeholder', 'other-token')))
        impostor = shlex.join([str(self.base / 'unrelated/overview'), 'placeholder', 'token'])
        self.assertFalse(started_as({'pane_start_command': impostor}, command('placeholder', 'token')))

    def test_renamed_checkout_spaces_reload_and_theme_switch(self):
        root = self.base / 'different checkout name'
        shutil.copytree(ROOT, root, symlinks=True, ignore=shutil.ignore_patterns('.git', '__pycache__'))
        self.install(root=root)
        # Simulate a single server only inside this test, as the recovery suite does.
        bindir = self.base / 'bin'
        bindir.mkdir()
        ps = bindir / 'ps'
        ps.write_text('#!/bin/sh\nif [ "$1" = "-u" ]; then exit 0; fi\nexec /usr/bin/ps "$@"\n')
        ps.chmod(0o755)
        self.env['PATH'] = str(bindir) + ':' + self.env['PATH']
        def tmux(*args):
            r = subprocess.run(['tmux', '-S', self.socket, *args], env=self.env, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            return r.stdout.strip()
        self.addCleanup(lambda: subprocess.run(['tmux', '-S', self.socket, 'kill-server'], capture_output=True))
        tmux('-f', str(self.home / '.tmux.conf'), 'new-session', '-d', '-s', 'test')
        self.env['TMUX'] = tmux('display-message', '-p', '#{socket_path},#{pid},0')
        for theme in ('storm', 'forest', 'storm'):
            result = subprocess.run([str(self.home / '.local/bin/tmux-theme'), theme], env=self.env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                right = tmux('show-options', '-gqv', 'status-right')
                wide = tmux('show-options', '-gqv', '@tmux-mobile-wide-status')
                if right.count('continuum_save.sh') == 1 and wide.count('overview\' status') == 1 and "continuum_save.sh')" in right:
                    break
                time.sleep(.1)
            self.assertEqual(right.count('continuum_save.sh'), 1, right)
            self.assertEqual(wide.count('overview\' status'), 1, wide)
            self.assertIn("continuum_save.sh')", right)
        result = subprocess.run([str(root / 'overview/bin/overview'), 'save'], env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
