"""Compact curses view; rows are equally usable at 65 columns and wide widths."""
import curses
import time
from .state import excerpt
from .tmux import display_status, observe


def age(stamp, now=None):
    if not stamp:
        return 'never'
    seconds = max(0, int((now or time.time()) - stamp))
    if seconds < 60:
        return f'{seconds}s'
    if seconds < 3600:
        return f'{seconds // 60}m'
    if seconds < 86400:
        return f'{seconds // 3600}h'
    return f'{seconds // 86400}d'


def model(store, panes, expanded, query=''):
    result = []
    conversations = store.rows('SELECT * FROM conversations ORDER BY observed_at DESC')
    now = time.time()
    for p in store.rows('SELECT * FROM projects WHERE ignored=0 ORDER BY registered DESC,name COLLATE NOCASE'):
        cs = [c for c in conversations if c['root'] == p['root']]
        ps = [pane for pane in panes if pane.get('root') == p['root']]
        if not p['registered'] and not ps and not cs:
            continue
        if query and query.lower() not in ' '.join([p['name'], p['note'], p['root']] + [c['label'] + ' ' + c['response'] for c in cs]).lower():
            continue
        statuses = {c['id']: display_status(c, panes, now) for c in cs}
        attention = sum(statuses[c['id']] == 'Waiting' or c['ready_at'] > c['ack_at'] for c in cs)
        live = sum(statuses[c['id']] != 'Interrupted/disconnected' for c in cs)
        due = now - p['reviewed_at'] >= 3 * 86400
        p.update(_attention=attention, _live=live, _due=due)
        marker = '-' if p['root'] in expanded else '+'
        tag = ('!' if due else ' ') if p['registered'] else '?'
        text = f"{marker}{tag} {p['name']}  A:{attention} L:{live} reviewed:{age(p['reviewed_at'], now)}"
        result.append(('project', p, text, p['note'] or p['root']))
        if p['root'] in expanded:
            used = set()
            for c in cs:
                used.add((c['runtime'], c['pane']))
                status = statuses[c['id']]
                c['_status'] = status
                ready = ' +response' if c['ready_at'] > c['ack_at'] and status != 'Response ready' else ''
                text = f"  {c['agent']} {c['label'] or c['session_id']}"
                detail = f"{status}{ready} | observed {age(c['observed_at'], now)} ago | {c['response'] or 'No response excerpt observed'}"
                result.append(('conversation', c, text, detail))
            for pane in ps:
                if (pane['runtime'], pane['pane_id']) not in used:
                    result.append(('pane', pane, f"  pane {pane['pane_current_command']}  {':'.join(pane['location'])}", pane['pane_current_path']))
    return result


def status_line(store, panes):
    cs = store.rows('SELECT * FROM conversations WHERE root IN (SELECT root FROM projects WHERE ignored=0)')
    waiting = sum(display_status(c, panes) == 'Waiting' for c in cs)
    ready = sum(c['ready_at'] > c['ack_at'] for c in cs)
    due = store.db.execute('SELECT count(*) FROM projects WHERE registered=1 AND ignored=0 AND reviewed_at<?', (time.time() - 3 * 86400,)).fetchone()[0]
    save = store.meta('last-save')
    stamp = age(save['at']) if save else 'never'
    overdue = not save or time.time() - save['at'] > 10 * 60
    return f'W:{waiting} R:{ready} D:{due} save:{stamp}' + ('!' if overdue else '')


def draw_line(screen, y, value, attr=0):
    h, w = screen.getmaxyx()
    if 0 <= y < h:
        try:
            screen.addnstr(y, 0, excerpt(value, 3000), max(0, w - 1), attr)
        except curses.error:
            pass


def prompt(screen, label, initial=''):
    value = initial
    curses.curs_set(1)
    screen.timeout(-1)
    try:
        while True:
            h, _ = screen.getmaxyx()
            screen.move(h - 1, 0)
            screen.clrtoeol()
            draw_line(screen, h - 1, label + value)
            screen.refresh()
            key = screen.get_wch()
            if key in ('\n', '\r'):
                return value
            if key == '\x1b':
                return None
            if key in ('\b', '\x7f', curses.KEY_BACKSPACE):
                value = value[:-1]
            elif isinstance(key, str) and key.isprintable() and len(value) < 1000:
                value += key
    finally:
        screen.timeout(2000)
        curses.curs_set(0)


def run(store, tmux, client=None):
    import os
    pane = os.environ.get('TMUX_PANE')
    if pane:
        tmux.run('set-option', '-p', '-t', pane, '@overview', '1')
    def loop(screen):
        curses.curs_set(0)
        screen.timeout(2000)
        expanded, query, selected, offset = set(), '', 0, 0
        from .presentation import palette, render
        colors = palette()
        message, help_open = '', False
        while True:
            active_client = tmux.run('show-options', '-wqv', '-t', pane, '@overview_client') if pane else client
            try:
                panes = observe(store, tmux)
                rows = model(store, panes, expanded, query)
                status = status_line(store, panes)
            except (RuntimeError, OSError) as e:
                panes, rows, status = [], [], str(e)
            selected = min(selected, max(0, len(rows) - 1))
            conversations = store.rows('SELECT * FROM conversations WHERE root IN (SELECT root FROM projects WHERE ignored=0)')
            saved = store.meta('last-save')
            summary = {'waiting': sum(display_status(c, panes) == 'Waiting' for c in conversations),
                       'ready': sum(c['ready_at'] > c['ack_at'] for c in conversations),
                       'due': store.db.execute('SELECT count(*) FROM projects WHERE registered=1 AND ignored=0 AND reviewed_at<?', (time.time() - 3 * 86400,)).fetchone()[0],
                       'saved': age(saved['at']) + ' ago' if saved else 'never — press s'}
            offset = render(screen, rows, selected, offset, expanded, query, message, summary, colors, help_open)
            screen.refresh()
            try:
                key = screen.get_wch()
            except curses.error:
                continue
            if help_open:
                if key in ('?', '\x1b', 'q'):
                    help_open = False
                continue
            message = ''
            if key == 'q':
                break
            if key in ('j', curses.KEY_DOWN):
                selected += 1
                continue
            if key in ('k', curses.KEY_UP):
                selected = max(0, selected - 1)
                continue
            if key == '/':
                query = prompt(screen, 'Search: ', query) or ''
                continue
            if key == '?':
                help_open = True
                continue
            try:
                if key == 's':
                    from .recovery import save
                    save(store, tmux)
                    message = 'Snapshot and manifest saved'
                    continue
                if not rows:
                    continue
                kind, row, _, detail = rows[selected]
                if key == ' ' and kind == 'project':
                    if row['root'] in expanded:
                        expanded.remove(row['root'])
                    else:
                        expanded.add(row['root'])
                elif key in ('\n', '\r', curses.KEY_ENTER):
                    if kind == 'project':
                        expanded.add(row['root'])
                    else:
                        tmux.jump(row['runtime'], row['pane'] if kind == 'conversation' else row['pane_id'], active_client)
                elif key == 'a' and kind == 'conversation':
                    store.acknowledge(row['id'])
                    message = 'Completed response acknowledged; approval waits remain'
                elif key == 'r' and kind == 'conversation':
                    from .recovery import resume
                    pane_id = resume(store, tmux, row['id'])
                    tmux.jump(tmux.identity(), pane_id, active_client)
                    message = 'Exact conversation requested; agent will report missing history'
                elif key == 'e':
                    if kind == 'project':
                        name = prompt(screen, 'Project name: ', row['name'])
                        if name is not None:
                            note = prompt(screen, 'Next action / notes reference: ', row['note'])
                            store.project(row['root'], name=name, note=note)
                    elif kind == 'conversation':
                        label = prompt(screen, 'Session label: ', row['label'])
                        if label is not None:
                            store.label(row['id'], label)
                elif kind == 'project':
                    if key == 'g':
                        store.project(row['root'], registered=True)
                    elif key == 'i':
                        store.project(row['root'], ignored=True)
                    elif key == 'v':
                        store.reviewed(row['root'])
            except (RuntimeError, ValueError, OSError) as e:
                message = str(e)
    try:
        curses.wrapper(loop)
    finally:
        if pane:
            tmux.run('set-option', '-p', '-t', pane, '-u', '@overview', check=False)
