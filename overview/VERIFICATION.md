# Release 0.1.0 verification

Verified on Linux with Python 3.13 and tmux 3.5a, September 7, 2026.

Command: `OVERVIEW_TEST_TMUX=1 python3.13 -m unittest discover -s tests -v`

17 tests pass. Integration servers use temporary sockets and private temporary state. The actual user server is not destroyed or restarted.

Coverage includes concurrent SQLite initialization/writes; duplicate, older and stale-turn events; subagent isolation; editable labels including explicit blank labels; acknowledgment and new activity; worktree grouping; persistent empty projects and review indicators; linked/moved/closed panes; reusable curses windows at 65 and 160 columns; snapshot/manifest hashes; same-second saves; empty-title snapshot field repair; manual and automatic startup restore; continuum's periodic save gate; exact conversation resume arguments; placeholder reuse and occupied-pane protection; missing directories; and repeatable configuration installation/removal.

Automatic startup tests substitute a single-server process listing for continuum's multiple-server safeguard. Fake agent executables verify resume arguments without model calls or access to real histories. Live agent hook trust, approval/question visibility, and retained-history recovery remain trial checks, kept outside the public repository. Running process survival and a physical reboot are not claimed.

Workspace migration verification is recorded in the root `VERIFICATION.md`.
