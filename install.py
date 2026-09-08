#!/usr/bin/env python3
"""Install tmux-workspace. Full installation is the default; reload explicitly."""
import argparse
import os
from pathlib import Path
import re
import shutil
import shlex
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
BEGIN = '# BEGIN tmux-workspace (managed)'
END = '# END tmux-workspace (managed)'
THEMES = sorted(p.stem for p in (ROOT / 'config/themes').glob('*.conf'))


def quote(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('$', '\\$') + '"'


def blockless(text, begin=BEGIN, end=END):
    if text.count(begin) != text.count(end) or text.count(begin) > 1:
        raise ValueError('Malformed managed configuration block')
    return re.sub(r'(?ms)^' + re.escape(begin) + r'\n.*?^' + re.escape(end) + r'\n?', '', text)


def existing_configuration(home, full):
    path = home / '.tmux.conf'
    old = path.read_text() if path.exists() else ''
    # Keep recovery separate so config-only also preserves an installed overview.
    ob, oe = '# BEGIN tmux-overview (managed)', '# END tmux-overview (managed)'
    blockless(old, ob, oe)
    match = re.search(r'(?ms)^' + re.escape(ob) + r'\n.*?^' + re.escape(oe) + r'\n?', old)
    recovery = match[0] if match else ''
    text = blockless(blockless(old, ob, oe))
    base = (ROOT / 'config/tmux.conf').read_text()
    owned_lines = set(base.splitlines())
    rest = []
    for line in text.splitlines():
        expanded = line.replace('$HOME', str(home)).replace('${HOME}', str(home))
        # Only remove the known theme/mobile source statements, not arbitrary sources.
        if any(expanded.strip() in ('source-file ' + quote(home / suffix), 'source-file ' + str(home / suffix)) for suffix in ('.config/tmux/themes/current.conf', '.config/tmux/mobile.conf')):
            continue
        if 'source-file' in line and '.config/tmux/overview.conf' in line:
            legacy = home / '.config/tmux/overview.conf'
            if not legacy.exists() or not legacy.read_text().startswith(ob + '\n'):
                raise ValueError('Unverified legacy overview.conf; review it before installation')
            if not recovery:
                recovery = legacy.read_text()
            continue
        if line in owned_lines or line.startswith('# Saved themes:') or line.startswith('# Apply responsive status'):
            continue
        rest.append(line)
    # Existing explicit key bindings that disagree with the config must be reviewed.
    import shlex
    def binding(line):
        try:
            parts = shlex.split(line)
        except ValueError:
            return None
        if not parts or parts[0] not in ('bind', 'bind-key'):
            return None
        table, i = 'prefix', 1
        if len(parts) > 2 and parts[1] == '-T':
            table, i = parts[2], 3
        return (table, parts[i]) if len(parts) > i else None
    keys = {binding(line) for line in base.splitlines()} - {None}
    for line in rest:
        if binding(line) in keys:
            raise ValueError('Shortcut conflicts with workspace configuration: ' + line)
    return '\n'.join(rest).strip() + '\n', recovery


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config-only', action='store_true')
    parser.add_argument('--home', type=Path, default=Path.home())
    parser.add_argument('--theme', choices=THEMES)
    args = parser.parse_args()
    home = args.home.expanduser().resolve()
    if not shutil.which('tmux'):
        parser.error('tmux is required')
    if not args.config_only and sys.version_info < (3, 13):
        parser.error('Full installation requires Python 3.13+; use python3.13 install.py or --config-only')
    if not args.config_only:
        if not shutil.which('python3.13'):
            parser.error('python3.13 must be on PATH for the overview launchers')
        import curses
        import sqlite3
    config = home / '.config/tmux'
    current = config / 'themes/current.conf'
    if current.is_symlink():
        selected = current.resolve().stem
        if selected not in THEMES:
            raise ValueError('Existing selected theme is unknown; preserve/review it before installation')
    elif current.exists():
        raise ValueError('current.conf is not a theme symlink; review before installation')
    else:
        selected = 'storm'
    selected = args.theme or selected
    rest, recovery = existing_configuration(home, not args.config_only)
    # Validate installed launchers before overwriting. Config launchers are copies.
    for name in ('tmux-theme', 'tmux-mobile-status'):
        target = home / '.local/bin' / name
        if target.exists() or target.is_symlink():
            text = target.read_text()
            signature = ('Switch the saved tmux theme' if name == 'tmux-theme' else "Compact attention cues without removing continuum")
            if signature not in text:
                raise ValueError('Unrecognized existing launcher: ' + str(target))
    prepared = None
    if not args.config_only:
        sys.path.insert(0, str(ROOT / 'overview'))
        from overview import install as integration
        from overview.tmux import Tmux
        tmux = Tmux() if home == Path.home().resolve() else Tmux(str(home / '.tmux-workspace-offline.sock'))
        prepared = integration.prepare(tmux, home, rest)
        from overview.state import Store, state_dir
        directory = state_dir() if home == Path.home().resolve() else home / '.local/state/tmux-overview'
        # Store is opened only after every configuration target is validated.
    files = [(ROOT / 'config/bin' / n, home / '.local/bin' / n) for n in ('tmux-theme', 'tmux-mobile-status')]
    files += [(ROOT / 'config/mobile.conf', config / 'mobile.conf')]
    # Installed palettes are user-owned; fill missing themes, never replace edits.
    files += [(p, config / 'themes' / p.name) for p in (ROOT / 'config/themes').glob('*.conf') if not (config / 'themes' / p.name).exists()]
    backup = home / '.local/state/tmux-workspace/backups' / str(time.time_ns())
    targets = [dest for _, dest in files] + [current, home / '.tmux.conf']
    if prepared:
        targets += [path for path, _ in prepared[1]] + [home / '.local/bin/overview']
    for dest in targets:
        if dest.is_dir():
            raise ValueError('Installation target is a directory: ' + str(dest))
    for dest in targets:
        if dest.exists() or dest.is_symlink():
            saved = backup / dest.relative_to(home)
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dest, saved, follow_symlinks=False)
    for src, dest in files:
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + '.workspace-tmp')
        shutil.copy2(src, tmp)
        if src.name == 'mobile.conf':
            tmp.write_text('run-shell ' + quote(shlex.join([str(home / '.local/bin/tmux-mobile-status'), 'configure'])) + '\n')
        os.replace(tmp, dest)
    current.parent.mkdir(parents=True, exist_ok=True)
    tmp = current.with_name('.current-' + str(time.time_ns()))
    tmp.symlink_to(selected + '.conf')
    os.replace(tmp, current)
    if prepared:
        store = Store(directory)
        try:
            # Apply hooks and launcher through the single overview implementation.
            integration.install(store, tmux, home, prepared=prepared, reload=False)
            recovery = integration.configuration_text(store)
        finally:
            store.db.close()
    base = (ROOT / 'config/tmux.conf').read_text().replace('"$HOME/.config/tmux/themes/current.conf"', quote(current))
    text = rest.rstrip() + '\n' + BEGIN + '\n' + base.rstrip() + '\nset -g @tmux-workspace-mobile-script ' + quote(home / '.local/bin/tmux-mobile-status') + '\n' + recovery
    text += 'source-file ' + quote(config / 'mobile.conf') + '\n' + END + '\n'
    conf = home / '.tmux.conf'
    tmp = conf.with_name('.tmux.conf.workspace-tmp')
    tmp.write_text(text)
    os.replace(tmp, conf)
    print('Installed ' + ('config only' if args.config_only else 'full workspace') + '; theme: ' + selected)
    print('Backups: ' + str(backup))
    print('Reload with: tmux source-file ' + str(conf))
    if prepared:
        print('Review new/changed agent hook definitions in /hooks; preserved legacy definitions retain their command paths.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError) as error:
        raise SystemExit('install: ' + str(error))
