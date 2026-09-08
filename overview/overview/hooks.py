"""Strict observational adapters. Successful hooks produce no agent-facing output."""
import os
from pathlib import Path
import time
from .tmux import process_identity

EVENTS = {'SessionStart': 'start', 'UserPromptSubmit': 'prompt', 'PreToolUse': 'tool', 'PostToolUse': 'tool', 'PostToolUseFailure': 'tool', 'PermissionRequest': 'waiting', 'Stop': 'response', 'Interrupt': 'interrupt', 'SessionEnd': 'end', 'Elicitation': 'waiting', 'ElicitationResult': 'tool'}


def ancestor_identity(agent):
    pid = os.getppid()
    for _ in range(20):
        try:
            raw = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
            executable = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')[:2]
            if any(agent in os.path.basename(x.decode(errors='replace')) for x in executable):
                return process_identity(pid)
            pid = int(raw[1])
            if pid <= 1:
                break
        except (OSError, ValueError):
            break
    return ''


def ingest(store, tmux, agent, payload):
    name = payload.get('hook_event_name')
    if name not in EVENTS or payload.get('agent_id') or payload.get('parent_session_id'):
        return False
    # No fallback from legacy notify: its child provenance is insufficient.
    event = dict(agent=agent, session_id=payload.get('session_id'), kind=EVENTS[name],
                 cwd=payload.get('cwd') or os.getcwd(), observed_at=time.time(),
                 prompt=payload.get('prompt'), response=payload.get('last_assistant_message'),
                 turn_id=payload.get('turn_id'), instance_pid=ancestor_identity(agent))
    if name == 'PreToolUse' and payload.get('tool_name') in ('AskUserQuestion', 'request_user_input'):
        event['kind'] = 'waiting'
    if payload.get('event_id'):
        event['event_id'] = agent + ':' + str(payload['event_id'])
    # Hooks may run outside tmux: retain conversation but report no pane association.
    try:
        pane_id = os.environ.get('TMUX_PANE', '')
        pane = next((p for p in tmux.panes() if p['pane_id'] == pane_id), None)
        if pane:
            event.update(runtime=pane['runtime'], pane=pane_id)
    except (RuntimeError, OSError):
        pass
    return store.event(event)


def configuration(agent):
    from .tmux import command
    events = ['SessionStart', 'UserPromptSubmit', 'PreToolUse', 'PostToolUse', 'PermissionRequest', 'Stop']
    events += ['Interrupt'] if agent == 'codex' else ['PostToolUseFailure', 'SessionEnd', 'Elicitation', 'ElicitationResult']
    return {'hooks': {event: [{'hooks': [{'type': 'command', 'command': command('hook', agent), 'timeout': 3}]}] for event in events}}
