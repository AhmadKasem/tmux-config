# tmux-overview

A project-first tmux overview with persistent agent attention and explicit conversation recovery. Linux, Python 3.13+, tmux, standard-library curses and SQLite. No Python dependencies, web server, model calls or background service.

## Install

From the workspace root run:

```sh
python3 install.py
tmux source-file ~/.tmux.conf
overview project register /path/to/project --note 'Next action, or path to existing notes'
overview open
```

`~/.local/bin` must be on PATH. Installation creates a launcher symlink, a marked block in `~/.tmux.conf`, and observational hook handlers in `~/.codex/hooks.json` and `~/.claude/settings.json`. Existing files get timestamped backups; existing unrelated settings and hook handlers remain. Reinstallation is supported. Reload the configuration explicitly after installation; use `overview save` for an immediate paired snapshot. Otherwise the first server startup takes an initial snapshot after a short startup delay if no saved layout exists.

The installer refuses conflicting prefix-G bindings, existing recovery-plugin configuration, conflicting launchers, malformed JSON and Codex inline hook configuration. Resolve those concrete conflicts before retrying. For an existing plugin setup, use `overview hooks-config codex` / `claude` to obtain the exact hook handlers, and integrate the options in `overview/install.py` manually. The root installer handles workspace installation; the component module remains the integration implementation. Keep resurrect before continuum; point its save/restore script options to this checkout's wrappers. Do not configure a second saver against the same snapshot directory.

The bundled plugins are pinned in [VENDOR.json](VENDOR.json), including their upstream licenses. They are used directly; TPM is not required. The source checkout and bundled scripts must remain installed together. A pip-only wheel is not the supported distribution.

### Activate agent hooks

In Codex, open `/hooks`, inspect the overview commands, and trust them. Trust is tied to the hook definition, so changing the installed command requires review again. Do not bypass hook trust. Restart existing Claude Code sessions to load the merged user settings; inspect `/hooks` and follow any trust prompts. Managed policies may disable hooks. Existing conversations cannot be identified retroactively without supported events: send a normal user prompt or explicitly resume the conversation to produce observations.

The adapters target the current documented Codex and Claude Code command-hook payloads. Check `overview doctor` and your agents' hook UI after upgrades. They never authorize tools, answer questions, add instructions or read `transcript_path`. They produce no stdout and exit zero on observation errors. Hook stderr reports a bounded failure message. A hook configuration present on disk does not establish that the agent has activated it.

Sources: [Codex hook reference](https://learn.chatgpt.com/docs/hooks), [Claude Code hook reference](https://code.claude.com/docs/en/hooks), [tmux-resurrect](https://github.com/tmux-plugins/tmux-resurrect), [tmux-continuum](https://github.com/tmux-plugins/tmux-continuum). No legacy Codex `notify` fallback is used because its child provenance is insufficient for this purpose.

## Daily use

Open the reusable window with **prefix → G** or `overview open`. Window names, numbering, base index, theme and shared-session navigation settings remain yours. The overview adds its own window and a compact status-right cue; it does not renumber existing windows. Opening or jumping to a pane does **not** acknowledge a response.

| Key | Action |
| --- | --- |
| j/k or arrows | Select a row |
| Space | Expand/collapse project |
| Enter | Expand project or jump to live pane |
| / | Search projects, notes, labels and response excerpts |
| g / i | Register / ignore selected project |
| e | Edit project name and note, or conversation label |
| v | Mark project explicitly reviewed |
| a | Acknowledge completed response only |
| r | Resume exact conversation, with no new prompt |
| s | Save layout and paired manifest |
| ? / q | Key reminder / close overview |

An empty project row persists once registered. Candidate projects have `?`; tracked projects due for review have `!`. Worktrees group by Git's common repository, while conversation and pane directories remain distinct. Non-Git candidates use the pane directory. Review becomes due after three days, including a newly registered project never reviewed. The note is a next action or a reference to your existing system, not a new task tracker.

`W:2 R:1 D:3 save:4m` means two observed waits, one unacknowledged completed response, three projects due for review, and a successful save four minutes ago. `save:never!` or an age over ten minutes with `!` warns that saves are overdue while monitoring. These cues are local; no external notifications are sent.

Every session has an editable label initially taken from its first observed prompt, a status, an observation age and a bounded response excerpt. The terminal view uses a dark teal palette, full-row selection, and aligned status labels. Narrow terminals show a compact list with selected-row details below; at 110 columns and wider, a side panel shows project notes, response excerpts, and directories. Press `?` for the keyboard help overlay. Full values and recovery directories are available through `overview list`.

| Status | Evidence |
| --- | --- |
| Working | Recent prompt/tool event from a live observed instance |
| Waiting | Permission or supported interactive-question event, unresolved by subsequent activity |
| Response ready | Completed response newer than acknowledgment |
| Unknown | Insufficient observations, acknowledged response, or active observation older than two minutes |
| Interrupted/disconnected | Explicit interruption/end, vanished process/pane, or different server generation |

Silence does not establish failure. Waiting indicators persist until observed activity resolves them. A new user prompt clears the preceding response indicator. Completed responses remain available after disconnection; acknowledgment clears their attention indicator without changing the interruption state. Ignored projects are excluded from attention counts. Hooks received outside tmux remain visible with unknown pane association.

## Recovery

`overview save` is the planned-shutdown command. Continuum invokes the same wrapper at five-minute intervals while a tmux client renders its status bar. Save health is based on successful snapshot/manifest completion, not continuum's attempted-save timestamp. No client, a disabled status bar, or continuum's multiple-server safeguard can stop automatic saving; `overview doctor` reports the integration and save age. With multiple servers, keep separate `OVERVIEW_STATE_DIR` values and check each server's diagnostics.

On a fresh tmux server, continuum invokes overview's restore wrapper. Resurrect restores sessions, windows, layouts and working directories. Program replay and pane-content capture are disabled. Newly restored panes run a small recovery placeholder, not the previous program. Existing panes are preserved using resurrect's never-overwrite option. The short-lived startup helper is not a daemon.

1. Reconnect and start tmux. The saved layout returns.
2. Open overview. Projects, notes, acknowledgments and response cues remain.
3. Prior runtime identities appear interrupted.
4. Select a conversation and press `r` to request `codex resume ID` or `claude --resume ID` in its recorded directory.

Recovery reuses an untouched, verified placeholder. Pressing Enter in a placeholder relinquishes it permanently to a shell. If the placeholder has been used, moved ambiguously, closed, or cannot be verified, overview creates a new window/pane. It never sends a command into an existing shell. The placeholder and resumer coordinate with a lock so entering a shell cannot race a replacement. Repeated resume requests jump to the existing instance; repeated layout restores preserve existing panes.

The save wrapper repairs upstream empty-title field shifts using a pane verified at the same location before and after the snapshot. It leaves user pane titles unchanged.

A manifest records saved locations and persistent conversation IDs, and is bound to the SHA-256 of its specific snapshot. Pane IDs from the previous server are never used to find restored conversations. Directory alone is never used as conversation identity. A missing/tampered manifest stops restoration before any layout change. Ambiguous mappings appear in `overview doctor`; individual conversations can still be resumed in a new pane. Missing directories stop resume visibly. Agents validate their own retained histories; a missing-history/error exit remains visible in its pane and the conversation stays registered.

Snapshots and adjacent `.overview.json` manifests live under the private state directory's `snapshots/`. `last` selects the active snapshot. Resurrect retains snapshot history (normally thirty days, at least five snapshots); orphan manifests may remain and are harmless. To select an older snapshot, point `last` at that snapshot only when its adjacent manifest is present, then run `overview restore`. Snapshot files can contain directory names, pane titles and process command lines: treat the entire state directory as private.

Processes do not survive reboot. Snapshots can lag; unsaved application state may be lost. Recovery depends on agent history retained by Codex/Claude. Check interrupted operations before continuing. There is no automatic replay of prompts or side effects.

## Commands and state

```sh
overview project list
overview project register ~/projects/example --name Example --note 'Review draft'
overview project edit ~/projects/example --note '~/notes/example.md'
overview project review ~/projects/example
overview project ignore ~/projects/example
overview label codex:CONVERSATION_ID 'Review migration'
overview ack codex:CONVERSATION_ID
overview resume claude:CONVERSATION_ID
overview status
overview list
overview save
overview restore
overview doctor
overview --socket /path/to/tmux.sock open
overview uninstall
```

State defaults to `$XDG_STATE_HOME/tmux-overview`, or `~/.local/state/tmux-overview`. `OVERVIEW_STATE_DIR` overrides it. `OVERVIEW_SOCKET` overrides tmux server selection, otherwise the current `TMUX` socket is used. Set these consistently before starting tmux and agents. Private directories use 0700 and the database/files use 0600. SQLite uses versioned migrations, foreign keys, transactional writes and a two-second busy timeout. Recovery operations use a bounded process lock. The application never reads private transcript formats or scrapes pane scrollback; integration tests capture their own test UI only.

Normalized integrations can send one JSON object on stdin to `overview event`:

```json
{"agent":"codex","session_id":"abc","kind":"response","event_id":"producer-unique-event-id","observed_at":1788750000.0,"cwd":"/home/me/project","turn_id":"turn-1","response":"Finished the migration"}
```

Kinds: `start`, `prompt`, `tool`, `waiting`, `response`, `interrupt`, `end`. Optional `runtime`, `pane` and `instance_pid` must come from a real current pane/process; omit them if unavailable. `runtime` is the identity returned by diagnostics, not a saved pre-restart ID. Events with `child:true` are ignored. Event IDs must be globally unique. Duplicate IDs, older timestamps, and stale turn completions are rejected transactionally. Source hooks lacking unique IDs/timestamps are ordered by receipt; arbitrary replay of such source payloads cannot be distinguished from genuine repeated input. Use normalized IDs/timestamps for replayable integrations. SubagentStop and explicitly identified child events never complete the parent. Unsupported event names are ignored. Excerpts are capped at 400 printable characters; labels at 120 and project notes at 1000. Explicit label edits survive new prompts.

Uninstall removes the owned config block, exact owned hook handlers and owned launcher symlink. User data, snapshot history and configuration backups are retained. It removes owned live status/binding settings without restarting or killing the server. Restart agents to unload their cached handlers. Manual edits to owned entries are preserved when ownership is no longer an exact match.

## Verify and trial

```sh
python3.13 -m unittest discover -s tests -v
OVERVIEW_TEST_TMUX=1 python3.13 -m unittest discover -s tests -v
```

The integration suite creates disposable sockets and temporary state. It covers linked/moved/closed panes, 65/160-column curses rendering, server destruction/recreation, exact resume arguments, occupied-pane protection, repeated restore/resume, manifest integrity, installation/removal, and continuum startup/save execution. The automatic-start test simulates a single-server process listing locally because the real user server must remain untouched. Agent launches use a fake executable; live interactive agent trust/history must still be checked during the trial. No reboot or model call is required for the suite.

Use this release for one week before adding scope. Keep personal evaluation notes outside the public checkout. Assess missed waiting agents, forgotten tracked projects, context reconstruction when returning, and maintenance effort. Task lifecycles, priorities, commitments, snoozes, focus limits, guided reviews and exports are intentionally deferred.
