"""Disposable tmux clients verify per-client rendering and shared pane labels."""
import fcntl
import os
from pathlib import Path
import pty
import re
import struct
import subprocess
import tempfile
import termios
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MobileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='tmux-mobile-test-')
        self.home = Path(self.temp.name) / 'home'
        self.home.mkdir()
        self.socket = str(Path(self.temp.name) / 'tmux.sock')
        self.clients = []
        self.addCleanup(self.cleanup)
        subprocess.run(['python3', str(ROOT / 'install.py'), '--home', str(self.home)], check=True, capture_output=True)
        self.env = dict(os.environ, HOME=str(self.home), TMUX='', TERM='xterm-256color', PATH=str(self.home / '.local/bin') + ':' + os.environ['PATH'])
        overview = self.home / '.local/bin/overview'
        overview.write_text('#!/usr/bin/env python3\nfrom pathlib import Path\nprint((Path.home()/"status.txt").read_text().strip())\n')
        overview.chmod(0o700)
        (self.home / 'status.txt').write_text('W:2 R:3 D:1 save:2m')
        self.tmux('-f', str(self.home / '.tmux.conf'), 'new-session', '-d', '-s', 'long-session-name', '-n', 'long-window-name-here', '-c', str(self.home))
        self.env['TMUX'] = self.tmux('display-message', '-p', '#{socket_path},#{pid},0')
        self.helper = self.home / '.local/bin/tmux-mobile-status'

    def cleanup(self):
        subprocess.run(['tmux', '-S', self.socket, 'kill-server'], capture_output=True)
        for process, master, _ in self.clients:
            process.wait(timeout=3)
            os.close(master)
        self.temp.cleanup()

    def tmux(self, *args):
        result = subprocess.run(['tmux', '-S', self.socket, *args], env=self.env, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stderr)
        return result.stdout.rstrip('\n')

    def helper_run(self, action):
        return subprocess.run([str(self.helper), action], env=self.env, check=True, capture_output=True, text=True).stdout.strip()

    def attach(self, width):
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 24, width, 0, 0))
        name = os.ttyname(slave)
        process = subprocess.Popen(['tmux', '-S', self.socket, 'attach-session', '-t', 'long-session-name'], env=dict(self.env, TMUX=''), stdin=slave, stdout=slave, stderr=slave)
        self.clients.append((process, master, name))
        os.close(slave)
        deadline = time.monotonic() + 3
        while name not in self.tmux('list-clients', '-F', '#{client_name}'):
            if time.monotonic() > deadline:
                self.fail('Client did not attach')
            time.sleep(.05)
        return name

    def test_phone_and_desktop_render_independently(self):
        phone, desktop = self.attach(65), self.attach(160)
        save = self.home / 'continuum_save.sh'
        save.write_text('#!/bin/sh\nexit 0\n')
        save.chmod(0o700)
        interpolation = '#(' + str(save) + ')'
        self.tmux('set-option', '-g', 'status-right', interpolation + 'DESKTOP %H:%M save:2m')
        self.helper_run('configure')
        first = self.tmux('show-options', '-gqv', 'status-right')
        self.helper_run('configure')
        self.assertEqual(first, self.tmux('show-options', '-gqv', 'status-right'))
        self.assertEqual(first.count('continuum_save.sh'), 1)
        small = self.tmux('display-message', '-p', '-c', phone, '#{E:status-left}')
        large = self.tmux('display-message', '-p', '-c', desktop, '#{E:status-left}')
        self.assertIn('long-s', small)
        self.assertNotIn('long-session', small)
        self.assertIn('long-session', large)
        small_tab = self.tmux('display-message', '-p', '-c', phone, '#{E:window-status-current-format}')
        large_tab = self.tmux('display-message', '-p', '-c', desktop, '#{E:window-status-current-format}')
        self.assertIn('long-win', small_tab)
        self.assertNotIn('long-window-name', small_tab)
        self.assertIn('long-window-name', large_tab)
        wide = self.tmux('display-message', '-p', '-c', desktop, '#{E:status-right}')
        self.assertIn('DESKTOP', wide)
        self.assertNotIn('%H', wide)
        self.assertRegex(wide, r'\d{2}:\d{2}')
        # #() jobs are asynchronous and display-message -p does not wait for
        # them. Inspect the disposable phone client's actual terminal output.
        master = next(master for _, master, name in self.clients if name == phone)
        os.set_blocking(master, False)
        while True:
            try:
                os.read(master, 65536)
            except BlockingIOError:
                break
        self.tmux('refresh-client', '-t', phone)
        raw = b''
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                raw += os.read(master, 65536)
            except BlockingIOError:
                pass
            visible = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', raw.decode(errors='replace'))
            if 'W:2 R:3 D:1' in visible:
                break
            time.sleep(.05)
        self.assertIn('W:2 R:3 D:1', visible, repr(visible[-500:]))
        self.assertNotIn('save:2m', visible)
        self.assertNotIn('DESKTOP', visible)

    def test_compact_save_warning_and_short_pane_labels(self):
        self.assertEqual(self.helper_run('compact'), 'W:2 R:3 D:1')
        (self.home / 'status.txt').write_text('W:2 R:3 D:1 save:11m!')
        self.assertEqual(self.helper_run('compact'), 'W:2 R:3 D:1 S!')
        (self.home / 'status.txt').write_text('W:0 R:0 D:0 save:never!')
        self.assertEqual(self.helper_run('compact'), 'W:0 R:0 D:0 S!')
        for width in (40, 65, 160):
            self.tmux('resize-window', '-x', str(width), '-y', '24')
            label = self.tmux('display-message', '-p', '#{E:pane-border-format}')
            self.assertEqual('//' in label, width >= 80)

    def test_alias_conflict_and_all_theme_reloads(self):
        self.helper_run('configure')
        self.assertIn('overview open', self.tmux('list-keys', '-T', 'prefix', 'g'))
        self.tmux('bind-key', 'g', 'display-message', 'custom binding overview open')
        for theme in (self.home / '.config/tmux/themes').glob('*.conf'):
            if theme.name == 'current.conf':
                continue
            self.tmux('source-file', str(theme))
            self.helper_run('configure')
            self.assertEqual(self.tmux('show-options', '-gqv', 'status-right').count('@tmux-mobile-wide-status'), 1)
        self.assertIn('custom binding overview open', self.tmux('list-keys', '-T', 'prefix', 'g'))


if __name__ == '__main__':
    unittest.main()
