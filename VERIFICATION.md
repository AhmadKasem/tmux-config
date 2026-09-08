# Workspace verification

Inspected September 8, 2026, based on tmux-config revision `53b778e` plus its pending mobile changes and the uncommitted overview source. Existing public history and author metadata are retained.

## Automated checks

`make test`: 28 tests (3 config/mobile, 17 overview, 8 whole-workspace integration). Suites run separately through the root Makefile. Disposable servers and temporary homes cover 65/160-column clients, narrow pane labels, all themes, desktop clocks, malformed hook structures, conflicting bindings, Codex trust metadata preservation, full/config-only repeat installation, both legacy installation styles, renamed/spaced checkouts, cue/save command counts across theme changes, verified old hook/placeholder paths, server recreation, paired manifests, exact fake-agent resume, occupied-pane protection and repeat restore/uninstall. `make check` compiles first-party Python. `git diff --check` checks whitespace.

Tests use fake agents. Live hook trust and retained conversation-history availability are not established by automated recovery tests. No physical reboot or survival of processes across reboot is claimed. Continuum startup tests simulate its single-server process listing on disposable sockets only.

## Documentation

The retained `docs/technical-reference.json` generates a standalone HTML reference with inline SVG diagrams. Shared `render.py` and `check_html.py` pass. Isolated headless Chromium with JavaScript disabled checked 320, 390, 768 and 1440-pixel widths: no page overflow, no broken anchors, and both 184-pixel diagrams fit their containers. Both diagrams were visually inspected at 320 pixels. CSS 200% zoom/reflow had no page overflow and print PDF generation succeeded. Native browser zoom, physical touch interaction and a complete keyboard/copy-fidelity review were not performed. The shared browser profile was busy; an independent temporary browser was used.

## Public-content audit

Imported first-party source, tests and portable documentation, plus pinned vendor source/licenses and version records. Overview had no commit history or remote to merge. Excluded private trial feedback, databases, snapshots/manifests, agent settings, caches, backups and nested Git metadata. Machine-specific first-party documentation paths were replaced with portable examples. Ignored legacy vendor test-harness symlinks are excluded; missing submodule test helpers are not used by the workspace suites. The local resurrect patch is retained in `overview/patches/resurrect-space-paths.patch` and declared in VENDOR.json. A staged audit inspected 124 files before migration with no private-state or credential-pattern findings; nested vendor metadata was excluded. Upstream whitespace and patch context are retained with scoped Git attributes.

## Local rollout

Local migration completed with the same tmux server identity and pane processes. Storm selection and every pre-existing palette were preserved byte-for-byte; the missing Warm Espresso palette was added. Hook definitions and Codex trust metadata were unchanged. Both former component paths resolve through compatibility symlinks. Diagnostics reported SQLite integrity ok and a newly paired snapshot; live status contained exactly one overview cue and one continuum save command, and G/g were configured. Backups, the consistent SQLite copy, snapshots and archived original directories remain outside Git. The initial palette-set assertion was too strict about the added missing theme; a follow-up verified all original palette contents against backups.

Final tests were rerun from the relocated checkout: all 28 passed, along with compilation and HTML validation. Live repeat installation/reload and another paired save also passed. All pre-migration project/conversation identities, notes, labels, acknowledgments and review metadata were compared against the consistent backup and retained; schema remains version 1. Lowercase-g ownership requires a verified executable, preserving unrelated commands even if their text mentions overview.
