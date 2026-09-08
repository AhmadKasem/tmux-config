"""Presentation helpers for the project overview."""
import curses
import textwrap
import unicodedata
from pathlib import Path


def cells(text):
    return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in ('W', 'F') else 1 for c in text)


def fit(text, width):
    text = ''.join(c if c.isprintable() else ' ' for c in str(text))
    if cells(text) <= width:
        return text
    result = ''
    for c in text:
        if cells(result + c) > max(0, width - 1):
            break
        result += c
    return result + ('…' if width > 0 else '')


def palette():
    colors = {name: 0 for name in ('text', 'muted', 'accent', 'waiting', 'ready', 'border', 'selected', 'selected_muted')}
    if not curses.has_colors():
        colors.update(accent=curses.A_BOLD, selected=curses.A_REVERSE, muted=curses.A_DIM)
        return colors
    curses.start_color()
    curses.use_default_colors()
    rich = curses.COLORS >= 256
    values = [(252, 234), (245, 234), (80, 234), (222, 234), (114, 234), (239, 234), (231, 24), (153, 24)] if rich else [(7, -1), (7, -1), (6, -1), (3, -1), (2, -1), (4, -1), (7, 4), (6, 4)]
    for i, (name, (fg, bg)) in enumerate(zip(colors, values), 1):
        curses.init_pair(i, fg, bg)
        colors[name] = curses.color_pair(i)
    return colors


def put(screen, y, x, text, width, attr=0, fill=False):
    h, w = screen.getmaxyx()
    width = max(0, min(width, w - x - 1))
    if not 0 <= y < h or x < 0 or not width:
        return
    value = fit(text, width)
    if fill:
        value += ' ' * max(0, width - cells(value))
    try:
        screen.addstr(y, x, value, attr)
    except curses.error:
        pass


def short_path(value):
    home = str(Path.home())
    return '~' + value[len(home):] if value == home or value.startswith(home + '/') else value


def render(screen, rows, selected, offset, expanded, query, message, summary, colors, help_open=False):
    from overview.ui import age
    h, w = screen.getmaxyx()
    screen.bkgd(' ', colors['text'])
    screen.erase()
    if h < 12 or w < 40:
        put(screen, 0, 1, 'OVERVIEW', w - 2, colors['accent'])
        put(screen, 2, 1, 'Enlarge terminal to at least 40 × 12.', w - 2)
        put(screen, 4, 1, 'q  close', w - 2, colors['muted'])
        return offset
    wide = w >= 110
    split = max(62, int(w * .59)) if wide else w
    list_width = split - 4
    top = 6
    bottom = h - (3 if wide else 6)
    page = max(1, (bottom - top) // 3)
    offset = max(0, min(offset, selected))
    if selected >= offset + page:
        offset = selected - page + 1
    put(screen, 1, 2, 'OVERVIEW', 15, colors['accent'] | curses.A_BOLD)
    put(screen, 1, 17, 'Your projects, at a glance', w - 20, colors['muted'])
    metrics = f"{summary['waiting']} waiting   ·   {summary['ready']} response{'s' if summary['ready'] != 1 else ''}   ·   {summary['due']} review due"
    put(screen, 3, 2, metrics, w - 4, colors['waiting'] if summary['waiting'] else colors['text'])
    put(screen, 4, 2, '─' * (w - 4), w - 4, colors['border'])
    put(screen, 5, 2, ('SEARCH  /' + query) if query else 'PROJECTS', list_width, colors['muted'])
    for index, (kind, row, _, detail) in enumerate(rows[offset:offset + page], offset):
        y = top + (index - offset) * 3
        chosen = index == selected
        base = colors['selected'] if chosen else colors['text']
        muted = colors['selected_muted'] if chosen else colors['muted']
        put(screen, y, 1, '', split - 2, base, True)
        put(screen, y + 1, 1, '', split - 2, base, True)
        if kind == 'project':
            marker = '▾' if row['root'] in expanded else '▸'
            title = marker + '  ' + row['name']
            badge = f"{row['_attention']} attention" if row['_attention'] else ('Not tracked' if not row['registered'] else ('Review due' if row['_due'] else 'Reviewed'))
            sub = row['note'] or short_path(row['root'])
            if row['_live']:
                sub = f"{row['_live']} live  ·  " + sub
        elif kind == 'conversation':
            title = '   ' + (row['label'] or row['agent'])
            badge = row['_status'].replace('Interrupted/disconnected', 'Interrupted')
            sub = f"   {row['agent']}  ·  {age(row['observed_at'])} ago"
            if row['ready_at'] > row['ack_at'] and badge != 'Response ready':
                sub += '  ·  Unread response'
        else:
            title = '   ' + row['pane_current_command']
            badge = 'Terminal'
            sub = '   ' + short_path(row['pane_current_path'])
        badge_width = cells(badge)
        title_width = max(8, list_width - badge_width - 3)
        put(screen, y, 2, title, title_width, base | (curses.A_BOLD if kind == 'project' else 0))
        tone = colors['waiting'] if 'attention' in badge or badge in ('Waiting', 'Review due') else colors['ready'] if badge == 'Response ready' else colors['muted']
        put(screen, y, split - badge_width - 3, badge, badge_width, muted if chosen else tone)
        put(screen, y + 1, 2, sub, list_width, muted)
    if not rows:
        put(screen, top + 1, 3, 'No matching projects' if query else 'A little room to focus.', list_width, colors['accent'])
        put(screen, top + 3, 3, 'Clear search with /' if query else 'Open a project in tmux to discover it.', list_width, colors['muted'])
    if wide:
        for y in range(5, h - 3):
            put(screen, y, split, '│', 1, colors['border'])
        x, width, y = split + 3, w - split - 6, 6
    else:
        x, width, y = 2, w - 4, h - 6
        put(screen, y, x, '─' * width, width, colors['border'])
        y += 1
    if rows:
        kind, row, _, detail = rows[selected]
        if wide:
            title = row['name'] if kind == 'project' else row.get('label') or row.get('pane_current_command', '')
            put(screen, y, x, 'SELECTED PROJECT' if kind == 'project' else 'SESSION DETAILS', width, colors['muted'])
            put(screen, y + 2, x, title, width, colors['accent'] | curses.A_BOLD)
            if kind == 'project':
                blocks = [('NEXT ACTION', row['note'] or 'Add a next action or notes reference with e.'), ('LOCATION', short_path(row['root'])), ('LAST REVIEW', age(row['reviewed_at']) + (' ago' if row['reviewed_at'] else ' reviewed'))]
            elif kind == 'conversation':
                blocks = [('STATUS', row['_status'] + ' · observed ' + age(row['observed_at']) + ' ago'), ('LATEST RESPONSE', row['response'] or 'No response observed yet.'), ('DIRECTORY', short_path(row['cwd']))]
            else:
                blocks = [('DIRECTORY', short_path(row['pane_current_path'])), ('TMUX LOCATION', ':'.join(row['location']))]
            y += 5
            for label, value in blocks:
                if y >= h - 5:
                    break
                put(screen, y, x, label, width, colors['muted'])
                for line in textwrap.wrap(value, max(1, width))[:3]:
                    y += 1
                    if y >= h - 4:
                        break
                    put(screen, y, x, line, width, colors['text'])
                y += 3
        else:
            put(screen, y, x, detail, width, colors['muted'])
            action = 'g track  ·  e edit  ·  v reviewed' if kind == 'project' else 'a acknowledge  ·  r resume  ·  e label' if kind == 'conversation' else 'Enter  jump to terminal'
            put(screen, y + 1, x, action, width, colors['accent'])
    put(screen, h - 3, 2, message or f"Saved {summary['saved']}  ·  {selected + 1 if rows else 0}/{len(rows)}", w - 4, colors['waiting'] if message else colors['muted'])
    put(screen, h - 2, 2, '↑↓ move  Space expand  Enter jump  / find  ? help  q quit', w - 4, colors['muted'])
    if help_open:
        help_lines = ['KEYBOARD SHORTCUTS', '', 'j / k or ↑ / ↓   Move selection', 'Space             Expand project', 'Enter             Jump to pane', '/                 Search', 'g / i             Track / ignore project', 'e                 Edit name, note or label', 'v                 Mark project reviewed', 'a                 Acknowledge response', 'r                 Resume conversation', 's                 Save layout', '', '? or Esc          Close help']
        box_width = min(52, w - 4)
        bx, by = (w - box_width) // 2, max(1, (h - len(help_lines) - 2) // 2)
        for dy, line in enumerate([''] + help_lines + ['']):
            put(screen, by + dy, bx, '  ' + line, box_width, colors['selected'], True)
    return offset
