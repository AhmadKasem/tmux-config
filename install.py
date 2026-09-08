#!/usr/bin/env python3
"""Install saved configuration with backups. Reload explicitly after review."""
import argparse
from pathlib import Path
import os
import shutil
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--home', type=Path, default=Path.home(), help='Destination home (also useful for testing)')
parser.add_argument('--theme', choices=['deep-sea','moonlight','cosmic-pastel','neon-grid','warm-espresso'], default='deep-sea')
args = parser.parse_args()
source = Path(__file__).resolve().parent
home = args.home.expanduser().resolve()
config = home / '.config/tmux'
backup = home / '.local/state/tmux-config/backups' / str(time.time_ns())
files = [(source / 'tmux.conf', home / '.tmux.conf'), (source / 'overview.conf', config / 'overview.conf'), (source / 'bin/tmux-theme', home / '.local/bin/tmux-theme')]
files += [(p, config / 'themes' / p.name) for p in sorted((source / 'themes').glob('*.conf'))]
current = config / 'themes/current.conf'
for src, dest in files:
    if dest.exists() or dest.is_symlink():
        saved = backup / dest.relative_to(home)
        saved.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(dest, saved, follow_symlinks=False)
    dest.parent.mkdir(parents=True, exist_ok=True)
    temporary = dest.with_name(dest.name + '.install-tmp')
    shutil.copy2(src, temporary)
    os.replace(temporary, dest)
if current.exists() or current.is_symlink():
    saved = backup / current.relative_to(home)
    saved.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(current, saved, follow_symlinks=False)
temporary = current.with_name('.current-' + str(time.time_ns()))
temporary.symlink_to(args.theme + '.conf')
os.replace(temporary, current)
print('Installed theme:', args.theme)
print('Existing files backed up under:', backup)
print('Reload with: tmux source-file ~/.tmux.conf')
