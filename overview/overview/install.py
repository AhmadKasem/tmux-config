"""Repeatable, owned configuration blocks; user settings and data survive removal."""
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import time
from .hooks import configuration
from .recovery import VENDOR, atomic_json
from .tmux import command, launcher

BEGIN = '# BEGIN tmux-overview (managed)'
END = '# END tmux-overview (managed)'


def same_handler(left, right):
    if not isinstance(left, dict) or not isinstance(right, dict):
        return False
    a, b = dict(left), dict(right)
    try:
        ca, cb = shlex.split(a.pop('command')), shlex.split(b.pop('command'))
        return (a == b and ca[1:] == cb[1:] and bool(ca) and bool(cb)
                and Path(ca[0]).is_absolute() and Path(ca[0]).resolve() == Path(cb[0]).resolve())
    except (KeyError, ValueError, IndexError, TypeError):
        return False


def owned_binding(binding):
    # tmux list-keys quotes the shell command as its final argument.
    try:
        parts = shlex.split(binding)
        cmd = shlex.split(parts[-1])
        return len(cmd) >= 2 and cmd[1] == 'open' and Path(cmd[0]).resolve() == Path(launcher()).resolve()
    except (ValueError, IndexError):
        return False


def validate_hooks(data, path):
    if not isinstance(data, dict) or not isinstance(data.get('hooks', {}), dict):
        raise ValueError('Invalid hook object: ' + str(path))
    for entries in data.get('hooks', {}).values():
        if not isinstance(entries, list):
            raise ValueError('Invalid hook event: ' + str(path))
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get('hooks'), list):
                raise ValueError('Invalid hook group: ' + str(path))
            if any(not isinstance(h, dict) for h in entry['hooks']):
                raise ValueError('Invalid hook handler: ' + str(path))


def without_block(text):
    return re.sub(r'(?m)^' + re.escape(BEGIN) + r'\n.*?^' + re.escape(END) + r'\n?', '', text, flags=re.S)


def write_preserving(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text() == text:
        return
    if path.exists():
        backup = path.with_name(path.name + '.overview-backup-' + str(time.time_ns()))
        shutil.copy2(path, backup)
    tmp = path.with_name(path.name + '.overview-tmp')
    with tmp.open('w') as f:
        os.chmod(tmp, 0o600)
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def tmux_quote(value):
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('$', '\\$') + '"'


def configuration_text(store):
    root = Path(launcher()).parents[1]
    lines = [BEGIN,
             'set -g @resurrect-dir ' + tmux_quote(str(store.directory / 'snapshots')),
             "set -g @resurrect-processes 'false'", "set -g @resurrect-capture-pane-contents 'off'",
             "set -g @resurrect-never-overwrite 'on'", "set -g @resurrect-save ''", "set -g @resurrect-restore ''",
             "set -g @continuum-save-interval '5'", "set -g @continuum-restore 'on'",
             'set -g @resurrect-hook-post-save-layout ' + tmux_quote(command('pair')),
             'bind-key G run-shell ' + tmux_quote(command('open', '--client', '#{client_name}')),
             'run-shell ' + tmux_quote(command('configure-status')),
             'run-shell ' + tmux_quote(shlex.quote(str(VENDOR / 'tmux-resurrect/resurrect.tmux'))),
             'set -g @resurrect-save-script-path ' + tmux_quote(str(root / 'bin/overview-save')),
             'set -g @resurrect-restore-script-path ' + tmux_quote(str(root / 'bin/overview-restore')),
             'run-shell -b ' + tmux_quote(shlex.quote(str(root / 'bin/overview-integrate'))),
             'run-shell -b ' + tmux_quote(shlex.quote(str(root / 'bin/overview-bootstrap'))), END]
    return '\n'.join(lines) + '\n'


def prepare(tmux, home=None, text=None):
    home = Path(home or Path.home())
    conf = home / '.tmux.conf'
    old = text if text is not None else (conf.read_text() if conf.exists() else '')
    rest = without_block(old)
    if re.search(r'(?m)^\s*bind(?:-key)?\s+(?:-T\s+prefix\s+)?G\b', rest):
        raise RuntimeError('Prefix G is already configured; choose/remove that binding before installation')
    for plugin in ('tmux-resurrect', 'tmux-continuum'):
        if not (VENDOR / plugin / (('resurrect' if plugin.endswith('resurrect') else 'continuum') + '.tmux')).exists():
            raise RuntimeError('Required vendor plugin missing: ' + plugin)
    if re.search(r'(?m)^[^#\n]*(?:tmux-resurrect|tmux-continuum|@resurrect-hook-post-save-layout)', rest):
        raise RuntimeError('Existing recovery plugin configuration needs manual integration; see README')
    running = False
    try:
        tmux.identity()
        running = True
    except (RuntimeError, OSError):
        pass
    if running:
        binding = tmux.run('list-keys', '-T', 'prefix', 'G', check=False)
        if binding and not owned_binding(binding):
            raise RuntimeError('Live prefix G binding conflicts with overview')
    codex_toml = home / '.codex/config.toml'
    if codex_toml.exists():
        import tomllib
        codex_hooks = tomllib.loads(codex_toml.read_text()).get('hooks', {})
        # Trust decisions are metadata, not a second hook definition source.
        if not isinstance(codex_hooks, dict) or set(codex_hooks) - {'state'}:
            raise RuntimeError('Codex inline hooks already exist; merge hooks-config output there instead of adding hooks.json')
    # Validate every target before changing any user file.
    merged = []
    for agent, path in [('codex', home / '.codex/hooks.json'), ('claude', home / '.claude/settings.json')]:
        data = json.loads(path.read_text()) if path.exists() else {}
        validate_hooks(data, path)
        hooks = data.setdefault('hooks', {})
        if not isinstance(hooks, dict):
            raise ValueError('Invalid existing hook configuration: ' + str(path))
        for event, entries in configuration(agent)['hooks'].items():
            existing = hooks.setdefault(event, [])
            for entry in entries:
                missing = [h for h in entry['hooks'] if not any(any(same_handler(h, candidate) for candidate in e.get('hooks', [])) for e in existing)]
                if missing:
                    existing.append({'hooks': missing})
        merged.append((path, json.dumps(data, indent=2) + '\n'))
    target = home / '.local/bin/overview'
    if (target.exists() or target.is_symlink()) and (not target.is_symlink() or target.resolve() != Path(launcher()).resolve()):
        raise RuntimeError('Existing overview executable is not owned by this project')
    return rest, merged, running


def install(store, tmux, home=None, prepared=None, reload=True):
    home = Path(home or Path.home())
    conf = home / '.tmux.conf'
    target = home / '.local/bin/overview'
    rest, merged, running = prepared or prepare(tmux, home)
    (store.directory / 'snapshots').mkdir(mode=0o700, parents=True, exist_ok=True)
    for path, data in merged:
        write_preserving(path, data)
    write_preserving(conf, rest.rstrip('\n') + '\n' + configuration_text(store))
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.is_symlink():
        target.symlink_to(launcher())
    store.meta('installation', {'home': str(home), 'launcher': launcher(), 'at': time.time()})
    if running and reload:
        # Source user's full config: their theme initializes status-right once; continuum
        # then appends its interpolation after overview's cue. Reload is idempotent.
        tmux.run('source-file', str(conf))
        from .recovery import save
        save(store, tmux)
    return 'Installed. Review and trust Codex hooks with /hooks; restart Claude sessions to load hooks.'


def uninstall(store, tmux, home=None):
    home = Path(home or Path.home())
    conf = home / '.tmux.conf'
    if conf.exists():
        write_preserving(conf, without_block(conf.read_text()))
    for agent, path in [('codex', home / '.codex/hooks.json'), ('claude', home / '.claude/settings.json')]:
        if not path.exists():
            continue
        data = json.loads(path.read_text())
        for event, owned in configuration(agent)['hooks'].items():
            entries = data.get('hooks', {}).get(event, [])
            # Remove exact handlers only, retaining unrelated additions to their group.
            kept = []
            commands = [h for e in owned for h in e['hooks']]
            for entry in entries:
                copy = dict(entry)
                copy['hooks'] = [h for h in entry.get('hooks', []) if not any(same_handler(h, owned) for owned in commands)]
                if copy['hooks']:
                    kept.append(copy)
            if event in data.get('hooks', {}):
                data['hooks'][event] = kept
        write_preserving(path, json.dumps(data, indent=2) + '\n')
    target = home / '.local/bin/overview'
    if target.is_symlink() and target.resolve() == Path(launcher()).resolve():
        target.unlink()
    try:
        for key in ('G', 'g'):
            binding = tmux.run('list-keys', '-T', 'prefix', key, check=False)
            if owned_binding(binding):
                tmux.run('unbind-key', key)
        def remove_owned_status(value):
            def keep(match):
                try:
                    parts = shlex.split(match[0][2:-1])
                    if parts and ((len(parts) == 2 and parts[1] == 'status' and Path(parts[0]).resolve() == Path(launcher()).resolve())
                                  or (len(parts) == 1 and Path(parts[0]).resolve() == (VENDOR / 'tmux-continuum/scripts/continuum_save.sh').resolve())):
                        return ''
                except ValueError:
                    pass
                return match[0]
            return re.sub(r'#\([^()\n]*\)', keep, value)
        for key in ('status-right', '@tmux-mobile-wide-status'):
            value = tmux.option(key)
            cleaned = remove_owned_status(value)
            if cleaned != value:
                tmux.option(key, cleaned)
        # Only clear options whose value still matches our installation.
        for line in configuration_text(store).splitlines():
            parts = shlex.split(line)
            if len(parts) == 4 and parts[:2] == ['set', '-g'] and parts[2].startswith('@') and tmux.option(parts[2]) == parts[3]:
                tmux.run('set-option', '-gu', parts[2])
    except (RuntimeError, OSError):
        pass
    return 'Removed owned configuration and launcher. Private state, snapshots and backups retained.'


def configure_status(tmux):
    cue = '#(' + command('status') + ')'
    current = tmux.option('status-right').replace(cue + ' ', '').replace(' ' + cue, '').replace(cue, '')
    tmux.option('status-right', cue + ' ' + current)
