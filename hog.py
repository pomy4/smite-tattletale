import curses
import curses.ascii
from typing import *
import time


class PlayerInfo(TypedDict):
    mmr: str
    hours: str
    created: str
    status: str
    gods: List["GodInfo"]
    matches: List["MatchInfo"]


class GodInfo(TypedDict):
    name: str
    matches: str
    wr: str
    last: str


class MatchInfo(TypedDict):
    outcome: str
    length: str
    role: str
    god: str
    kda: str


def call_hirez_api(name: str) -> PlayerInfo:
    # time.sleep(1)
    return {
        "mmr": "1500",
        "hours": "30",
        "created": "yesterday",
        "status": "",
        "gods": [
            {
                "name": "He Bo",
                "matches": "10",
                "wr": "60%",
                "last": "today",
            },
        ],
        "matches": [
            {
                "outcome": "win",
                "length": "30m",
                "role": "mid",
                "god": "He Bo",
                "kda": "3/1/3",
            },
        ],
    }


def redraw_panel(spaces: int, name: str, player: PlayerInfo, panel=curses.initscr()):
    panel.clear()
    panel.addstr(name)
    row = 1
    panel.addstr(row, spaces, "MMR: " + player['mmr'])
    row += 1
    panel.addstr(row, spaces, "Hours played: " + player["hours"])
    row += 1
    panel.addstr(row, spaces, "Account creation date: " + player["created"])
    row += 1
    panel.addstr(row, spaces, "Status message: " + player["status"])
    row += 1
    panel.addstr(row, spaces, "Most played gods (in ranked conquest)")
    row += 1
    for god in player['gods']:
        panel.addstr(row, 2 * spaces, god['name'])
        row += 1
        panel.addstr(row, 3 * spaces, "Matches played: " + god['matches'])
        row += 1
        panel.addstr(row, 3 * spaces, "WR: " + god['wr'])
        row += 1
        panel.addstr(row, 3 * spaces, "Last played date: " + god['last'])
        row += 1
    panel.addstr(row, spaces, "Recent matches (in ranked conquest)")
    row += 1
    for i, match in enumerate(player['matches'], 1):
        panel.addstr(row, 2 * spaces, "Match #1")
        row += 1
        panel.addstr(row, 3 * spaces, "Outcome: " + match['outcome'])
        row += 1
        panel.addstr(row, 3 * spaces, "Length: " + match['length'])
        row += 1
        panel.addstr(row, 3 * spaces, "Role: " + match['role'])
        row += 1
        panel.addstr(row, 3 * spaces, "God: " + match['god'])
        row += 1
        panel.addstr(row, 3 * spaces, "KDA: " + match['kda'])
        row += 1


def main(
    names: List[str],
    screen=curses.initscr(),
):
    assert names
    spaces = 2
    screen.clear()

    # new window -> draw names
    screen.addstr("Players:")
    for i, name in enumerate(names, 1):
        screen.addstr(i, spaces, name)
    screen.noutrefresh()
    offset = 1 + len(names)

    # new windows -> draw info boxes - only name and loading or skipped
    total_width = curses.COLS
    total_height = curses.LINES

    panel_width = int(total_width / len(names))
    panels = [
        curses.newwin(
            total_height - offset,  # nlines
            panel_width,  # ncols
            offset,  # begin_y
            i * panel_width,  # begin_x
        )
        for i in range(len(names))
    ]
    for panel, name in zip(panels, names):
        panel.addstr(name)
        panel.addstr(1, spaces, "Loading...")
        panel.noutrefresh()

    screen.move(1, spaces)
    curses.doupdate()

    # go through names and call hirez api, update panel
    for panel, name in zip(panels, names):
        info = call_hirez_api(name)
        redraw_panel(spaces, name, info, panel)
        panel.refresh()

    # while true:
    names_buffer = names.copy()
    screen.nodelay(False)
    curses.flushinp()

    def get_yx():
        y_, x_ = curses.getsyx()
        return y_ - 1, x_ - spaces

    def set_yx(y_, x_):
        screen.move(y_ + 1, x_ + spaces)

    def update_name(y_):
        screen.clrtoeol()
        if names[y] == names_buffer[y]:
            screen.addstr(y + 1, spaces, names_buffer[y])
        else:
            screen.addstr(y + 1, spaces, names_buffer[y] + " (*)")

    while True:
        c = screen.get_wch()
        # Moving the cursor, maybe should be a bit more DRY.
        if c == curses.KEY_UP:
            y, x = get_yx()
            if y == 0:
                continue
            y -= 1
            x = min(x, len(names_buffer[y]))
            set_yx(y, x)
        elif c == curses.KEY_DOWN:
            y, x = get_yx()
            if y == len(names_buffer) - 1:
                continue
            y += 1
            x = min(x, len(names_buffer[y]))
            set_yx(y, x)
        elif c == curses.KEY_LEFT:
            y, x = get_yx()
            if x == 0:
                continue
            x -= 1
            set_yx(y, x)
        elif c == curses.KEY_RIGHT:
            y, x = get_yx()
            if x == len(names_buffer[y]):
                continue
            x += 1
            set_yx(y, x)
        elif c == curses.KEY_BACKSPACE:
            y, x = get_yx()
            if x == 0:
                continue
            x -= 1
            names_buffer[y] = names_buffer[y][:x] + names_buffer[y][x + 1:]
            update_name(y)
            set_yx(y, x)
        elif c == curses.KEY_DC:
            y, x = get_yx()
            if x == len(names_buffer[y]):
                continue
            names_buffer[y] = names_buffer[y][:x] + names_buffer[y][x + 1:]
            update_name(y)
            set_yx(y, x)
        elif c == '\n':
            pass
        elif c == '\x1B':
            return
        elif isinstance(c, str):
            y, x = get_yx()
            if len(names_buffer[y]) > total_width - 10:
                continue
            names_buffer[y] = names_buffer[y][:x] + c + names_buffer[y][x:]
            x += len(c)
            update_name(y)
            set_yx(y, x)

        # Maybe need to refresh screen here?

        # if x == "\x1B":
        #     return
        # if x == curses.KEY_BACKSPACE:
        #     screen.addstr("BACK")
        # if x == '\n':
        # screen.addstr(str(x))
        # screen.addstr(x[1])
    # if unicode add at cursor
    # if backspace delete at cursor
    # if arrow key move cursor around
    # if escape quit (return)
    # enter - refresh hirez api based on row

    # panel_cnt = len(names)
    # while True:
    #     panel_width = int(total_width / panel_cnt)
    #     panel_height = int(total_height / panel_cnt)
    #     panels = [
    #         curses.newwin(
    #             panel_height,  # nlines
    #             panel_width,  # ncols
    #             0,  # begin_y
    #             i * panel_width,  # begin_x
    #         )
    #         for i in range(panel_cnt)
    #     ]
    #     for i, panel in enumerate(panels, 1):
    #         panel.addstr(str(i) * 120)
    #         panel.noutrefresh()
    #     curses.doupdate()
    #
    #     got_input = False
    #     while not got_input:
    #         got_input = True
    #         match screen.getch():
    #             case curses.KEY_UP:
    #                 panel_cnt += 1
    #             case curses.KEY_DOWN:
    #                 panel_cnt = max(1, panel_cnt - 1)
    #             case _:
    #                 got_input = False

    # main_window.addstr(0, 0, str())
    # main_window.addstr(1, 0, str(curses.COLS))
    # main_window.addstr(2, 0, "x" * 230 + "y")
    #
    # main_window.refresh()
    # while True:
    #     main_window.getkey()


# if no input, take a screenshot and OCR it
# if input is a single filename, OCR it
# otherwise all inputs are playernames


names_from_input = ["player1", "player2", "player3", "player4", "player5"]

curses.wrapper(lambda x: main(names_from_input, x))
