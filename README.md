# tmux config

Personal tmux setup for **Konsole → SSH → tmux**, with **Storm** as the default theme and **Forest** saved as a favorite alternative.

## Themes

| Name | Look |
| --- | --- |
| `storm` | Blue-grey panels, silver text, soft cyan (default) |
| `forest` | Deep evergreen, sage highlights, copper accents |
| `aurora` | Smoky aubergine, soft mint, lavender |
| `glacier` | Light icy panels, navy text, teal accents |
| `deep-sea` | Dark petrol, mint highlights, soft coral |
| `moonlight` | Muted indigo, icy blue, pale lavender |
| `cosmic-pastel` | Plum, lavender session badge, peach active tabs |
| `neon-grid` | Original near-black futuristic theme, cyan and violet |
| `warm-espresso` | Neon Grid layout with warm brown panels |

All themes except Cosmic Pastel include pane labels with the current command and directory. Cosmic Pastel restores the original pane borders and backgrounds. No special icon font is required. Layouts adapt to narrow and wide terminals; the extra clock/date appears on wide clients.

## Install

Requires tmux 3.5a (the tested version), Python 3, and a terminal with true-color support. `tmux-overview`, if used, additionally requires its own Python 3.13 installation and setup.

```sh
git clone https://github.com/AhmadKasem/tmux-config.git
cd tmux-config
python3 install.py
tmux source-file ~/.tmux.conf
```

The installer backs up existing destination files under `~/.local/state/tmux-config/backups/` before replacing them. It installs copies, so subsequent repository edits require running the installer again. Installation defaults to Storm; use `--theme forest` to select another initial theme. Ensure `~/.local/bin` is on PATH.

Switch palettes live:

```sh
tmux-theme storm
tmux-theme forest
tmux-theme aurora
tmux-theme glacier
tmux-theme deep-sea
tmux-theme moonlight
tmux-theme cosmic-pastel
tmux-theme neon-grid
tmux-theme warm-espresso
```

The original black Neon Grid and the later espresso experiment have separate names here. In the original live setup, the espresso experiment occupied the `neon-grid` filename.

## True color over SSH

The config explicitly enables RGB for `xterm-256color`, as used by Konsole over SSH. This matters: reducing subtle dark RGB shades to 256 colors can make them look grey. After enabling this setting, detach and reattach existing tmux clients. Only retain this override when the actual terminal supports true color.

## Input and navigation

- Mouse and focus support.
- Vi copy mode; `y` or Enter copies using OSC 52.
- Mouse selection does not automatically leave copy mode.
- Existing tmux window numbering and navigation conventions are retained.

## Optional overview and restart recovery

`overview.conf` loads only when `~/projects/tmux-overview/bin/overview` exists. That is a separate project; this repository does not install it, its agent hooks, or its vendor plugins. Install it using its own documented setup first. If your checkout or state directory differs, adjust `overview.conf`.

With that dependency installed, prefix → G opens the project overview, the status bar shows attention/review/save cues, and tmux-resurrect plus tmux-continuum provide five-minute layout saves and automatic fresh-server restoration. Previous programs are not automatically replayed. Continuum must remain after the theme and overview status configuration so its status integration is retained.

Private conversation state, database files, tmux snapshots, agent settings, credentials, and experimental backup files are not included.

## Validation

The configuration is checked on a disposable tmux server, including loading each theme and switching back to Cosmic Pastel. Installer backup and repeat-install behavior are checked with a temporary home directory. The real running server is not restarted.
