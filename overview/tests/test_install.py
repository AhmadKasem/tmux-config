import json
from pathlib import Path
import tempfile
import unittest
from overview.install import install, uninstall
from overview.state import Store


class OfflineTmux:
    def identity(self):
        raise RuntimeError('offline')
    def run(self, *args, **kwargs):
        raise RuntimeError('offline')


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / 'home'
        self.home.mkdir()
        self.store = Store(Path(self.tmp.name) / 'state')
        self.addCleanup(self.store.db.close)

    def test_conflict_is_rejected_before_mutations(self):
        conf = self.home / '.tmux.conf'
        conf.write_text('bind G display-message existing\n')
        with self.assertRaises(RuntimeError):
            install(self.store, OfflineTmux(), self.home)
        self.assertEqual(conf.read_text(), 'bind G display-message existing\n')
        self.assertFalse((self.home / '.codex').exists())

    def test_invalid_hook_file_is_rejected_before_mutations(self):
        (self.home / '.claude').mkdir()
        (self.home / '.claude/settings.json').write_text('{broken')
        with self.assertRaises(ValueError):
            install(self.store, OfflineTmux(), self.home)
        self.assertFalse((self.home / '.codex').exists())
        self.assertFalse((self.home / '.tmux.conf').exists())

    def test_reinstall_with_custom_handler_keeps_single_owned_handler(self):
        install(self.store, OfflineTmux(), self.home)
        path = self.home / '.claude/settings.json'
        data = json.loads(path.read_text())
        data['hooks']['Stop'][0]['hooks'].append({'type': 'command', 'command': 'echo mine'})
        path.write_text(json.dumps(data))
        install(self.store, OfflineTmux(), self.home)
        self.assertEqual(len(json.loads(path.read_text())['hooks']['Stop']), 1)
        uninstall(self.store, OfflineTmux(), self.home)
        self.assertEqual(json.loads(path.read_text())['hooks']['Stop'][0]['hooks'], [{'type': 'command', 'command': 'echo mine'}])
        self.assertTrue(self.store.directory.exists())


if __name__ == '__main__':
    unittest.main()
