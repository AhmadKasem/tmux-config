# tmux config

Personal tmux setup for **Konsole or Blink on iPhone → SSH → tmux**, with **Storm** as the default theme and **Forest** saved as a favorite alternative.

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

From the workspace root, run `python3 install.py` for the full setup or
`python3 install.py --config-only` for configuration alone. The compatibility
`config/install.py` entry point selects config-only. Then run
`tmux source-file ~/.tmux.conf`.

Fresh installs select Storm. Reinstallation preserves the current theme and
installed palette edits; `--theme` explicitly changes the selection. Backups
live under `~/.local/state/tmux-workspace/backups/`. Keep `~/.local/bin` on PATH.
Config-only needs Python 3 and tmux; full installation needs Python 3.13+.

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

Neon Grid and Warm Espresso are separate palettes.

## Phone-friendly layout

Below 80 columns, session labels shorten to six characters and window names to eight. The status bar keeps W/R/D counts, hides the routine save age, and displays `S!` when saving is overdue or no successful save exists. `overview?` means status could not be read. On wider clients the original desktop status returns. The choice uses each client's width, so a phone and desktop can display different status bars simultaneously.

Pane headers shorten commands and omit directories below 80 columns of pane width. This follows the actual shared pane geometry. It does not change tmux's window-sizing policy, rearrange splits, or zoom automatically.

With overview installed, **prefix → g** opens it without Shift; the existing **prefix → G** remains available. An existing unrelated lowercase-g binding is left alone. **Prefix → z** is tmux's existing pane-zoom toggle.

The `tmux-mobile-status` helper wraps the existing status content and retains continuum's save command outside the compact/desktop conditional. Load `mobile.conf` after the theme and overview integration. Theme switching and configuration reloads keep a single status wrapper.

## True color over SSH

The config explicitly enables RGB for `xterm-256color`, as used by Konsole over SSH. This matters: reducing subtle dark RGB shades to 256 colors can make them look grey. After enabling this setting, detach and reattach existing tmux clients. Only retain this override when the actual terminal supports true color.

## Input and navigation

- Mouse and focus support.
- Vi copy mode; `y` or Enter copies using OSC 52.
- Mouse selection does not automatically leave copy mode.
- Existing tmux window numbering and navigation conventions are retained.

## Optional overview and restart recovery

Overview is the sibling component, installed by default through the root installer.
The root managed block loads theme and key settings, overview/recovery, then
mobile status. No old-checkout auto-detection remains. Config-only preserves
already-installed recovery configuration without installing hooks or plugins.

Private conversation state, database files, tmux snapshots, agent settings, credentials, and experimental backup files are not included.

## Validation

The configuration is checked on a disposable tmux server, including loading each theme and switching back to Cosmic Pastel. Installer backup and repeat-install behavior are checked with a temporary home directory. The real running server is not restarted.

Run the mobile integration checks with `make test-config` from the workspace root (or `python3 -m unittest discover -s tests -v` inside `config`. These use temporary homes and disposable tmux servers to check simultaneous 65/160-column clients, 40/65/160-column pane labels, save warnings, shortcut conflicts, and all theme reloads.
