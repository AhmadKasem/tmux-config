# tmux-workspace

One checkout for responsive tmux themes, a project dashboard, observational agent hooks, and explicit conversation recovery.

## Install

Linux and tmux are required (tested with tmux 3.5a). Full installation uses Python 3.13+, curses and SQLite from the standard library, and the bundled recovery plugins. Put `~/.local/bin` on PATH.

```sh
git clone https://github.com/AhmadKasem/tmux-workspace.git
cd tmux-workspace
python3 install.py
tmux source-file ~/.tmux.conf
```

Use `python3.13 install.py` if your default Python is older. `python3 install.py --config-only` installs themes, copy keys and mobile status without importing overview, requiring Python 3.13, or adding agent hooks/plugins. It preserves an existing overview installation. `--home /path/to/home` supports a separate destination; `--theme forest` selects a palette. Fresh installs default to Storm; repeat installation retains the selected palette and all installed palette files, including local edits. Remove a specific installed palette file if you intentionally want its repository version restored by the next install.

Installation validates configuration, hooks, launchers and conflicting shortcuts before writes. Changed files have timestamped backups under `~/.local/state/tmux-workspace/backups/`; overview also retains adjacent backups. File replacements are atomic individually; the complete installation is not a filesystem transaction. On I/O failure, keep the reported backups and rerun or restore them. Installation does not reload the running server: use the command above after reviewing the result.

The root installer owns the order: theme/copy keys, overview/recovery, then responsive mobile status. Recovery startup finishes asynchronously after a target pane exists and reapplies the mobile wrapper. `overview install` delegates to this same installer; `config/install.py` delegates with `--config-only`. Source and vendor paths come from the checkout, including differently named paths with spaces. Keep the checkout installed.

## Use

- `tmux-theme storm` switches themes and reloads the configuration.
- Prefix → G opens overview; prefix → g is added only when unused or already owned.
- `overview doctor` checks SQLite, plugin paths, runtime and snapshot pairing.
- `overview save` saves a layout and matching manifest.
- `overview restore` restores layouts into protected recovery placeholders.
- Choose a conversation and press `r` to explicitly resume its exact ID.

At fewer than 80 columns the status uses compact attention counts, short labels and an overdue-save warning. Wide clients retain their theme and clock. Two clients can display different status layouts simultaneously. Pane labels use shared pane geometry.

Agent hooks only observe events. Review new or changed definitions through the agent's `/hooks` UI. Existing verified compatibility-path definitions are preserved; trust activation and retained agent history remain user checks. No model calls, transcript scraping, automatic agent restart or new task-tracking system is introduced.

## Components and state

| Component | Responsibility |
| --- | --- |
| [config](config/README.md) | Nine themes, copy keys, theme command and mobile status |
| [overview](overview/README.md) | Dashboard, event observations, private state and recovery |
| [Technical reference](docs/technical-reference.html) | Architecture, ownership, data and migration; [authoring JSON](docs/technical-reference.json) |
| [Verification](VERIFICATION.md) | Executed checks, public audit and limitations |

State stays in `$XDG_STATE_HOME/tmux-overview` (default `~/.local/state/tmux-overview`), or `OVERVIEW_STATE_DIR` when explicitly set. Schema version 1, conversation IDs, notes, acknowledgments and snapshot/manifest pairs are preserved. Never commit the state directory, agent settings or local trial feedback. Vendor versions, licenses and the recorded path-quoting patch are retained in `overview/VENDOR.json` and `overview/patches/`.

## Migration and rollback

1. Assemble and test the combined checkout while the original directories remain usable.
2. Run `overview save` and confirm `overview doctor` reports a paired snapshot. Back up configuration and hook files, copy the snapshots with their adjacent manifests, and use SQLite's backup API for a consistent database copy outside Git.
3. Archive each original directory outside the checkout. Create compatibility symlinks from the original component paths to `tmux-workspace/config` and `tmux-workspace/overview`. Keep these links while agents cache old hooks or recovery commands reference them.
4. Run the root installer and reload `~/.tmux.conf`. Do not restart tmux or running agents as part of migration. Existing hook command definitions are recognized by their complete handler contract and resolved executable; unrelated commands are preserved.
5. Check theme selection, G/g bindings, one overview cue and one continuum save interpolation. Run a new save and diagnostics. Preserve rollback backups and compatibility paths.

To roll back, restore the archived directories at their former paths and restore backed-up configuration/hooks/launchers, then source the restored tmux configuration. Retain the current private database; do not overwrite newer observations with a stale database backup. The consistent database backup is a last-resort recovery artifact.

`overview uninstall` removes owned overview configuration, verified old/new hook handlers, the launcher and live G/g/status integration. Private data, snapshots, backups and unrelated settings remain. Config/mobile themes remain installed. Keep compatibility paths until cached handlers have been unloaded; do not remove paths while agents still use them.

## Verify

```sh
make test-config       # responsive tmux tests
make test-overview     # state + real disposable-server recovery tests
make test-integration  # whole-workspace installation/migration tests
make test
make check
```

Tests use temporary homes, sockets, state and fake agents. They do not establish live hook trust, retained conversation histories, process survival across reboot or physical reboot behavior.
