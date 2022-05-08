import curses
import curses.ascii
from typing import *

from api import Api

skipped_names = ["Siemka4", "kapitán"]
api = Api()


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


class PlayerInfo(TypedDict):
    mmr: str
    hours: str
    created: str
    status: str
    gods: List[GodInfo]
    matches: List[MatchInfo]


class Player(TypedDict):
    name: str
    info: Optional[PlayerInfo]


def call_hirez_api(player: str) -> PlayerInfo | None:
    getplayer_resp = api.call_method("getplayer", player)
    getplayer_resp.raise_for_status()

    getplayer_json = getplayer_resp.json()
    if not getplayer_json:
        return None
    x = getplayer_json[0]

    res = {}
    res["name"] = player
    res["mmr"] = f"{x['Rank_Stat_Conquest']:.0f}"
    res["hours"] = str(x["HoursPlayed"])
    res["created"] = str(x["Created_Datetime"])
    res["status"] = str(x["Personal_Status_Message"])

    getqueuestats_resp = api.call_method("getqueuestats", player, "451")
    getqueuestats_resp.raise_for_status()

    getqueuestats_json = getqueuestats_resp.json()
    res["gods"] = [
        {
            "name": x["God"],
            "matches": str(x["Matches"]),
            "wr": f"{x['Wins'] / x['Matches']:.0%}",
            "last": x["LastPlayed"],
        }
        for x in getqueuestats_json[:3]
    ]

    getmatchhistory_resp = api.call_method("getmatchhistory", player)
    getmatchhistory_resp.raise_for_status()

    xx = getmatchhistory_resp.json()
    xx = [x for x in xx if x["Match_Queue_Id"] == 451]
    res["matches"] = [
        {
            "outcome": x["Win_Status"],
            "length": f"{x['Minutes']}m",
            "role": x["Role"],
            "god": x["God"],
            "kda": f"{x['Kills']}/{x['Deaths']}/{x['Assists']}",
        }
        for x in xx[:3]
    ]

    return res
    # return {
    #     "mmr": "1500",
    #     "hours": "30",
    #     "created": "yesterday",
    #     "status": "x" * 120,
    #     "gods": [
    #         {
    #             "name": "He Bo",
    #             "matches": "10",
    #             "wr": "60%",
    #             "last": "today",
    #         },
    #     ],
    #     "matches": [
    #         {
    #             "outcome": "win",
    #             "length": "30m",
    #             "role": "mid",
    #             "god": "He Bo",
    #             "kda": "3/1/3",
    #         },
    #     ],
    # }


def wrap_str(y: int, x: int, s: str, spaces: int, panel=curses.initscr()):
    _, max_x = panel.getmaxyx()
    curr_s = s
    y_inc = 0
    while True:
        if x + len(curr_s) < max_x:
            panel.addstr(y + y_inc, x, curr_s)
            return y_inc + 1
        # -1 because counting from zero, -1 because hyphen, -1 because border
        offset = max_x - x - 1 - 1 - 1
        panel.addstr(y + y_inc, x, curr_s[:offset] + "-")
        curr_s = curr_s[offset:]
        if y_inc == 0:
            x += spaces
        y_inc += 1


def redraw_panel(spaces: int, player: Player, panel=curses.initscr()):
    panel.clear()
    panel.box("|", "-")
    panel.addstr(player["name"])
    if player["info"] is None:
        panel.addstr(1, spaces, "not found")
        panel.refresh()
        return
    row = 1
    panel.addstr(row, spaces, "MMR: " + player["info"]["mmr"])
    row += 1
    panel.addstr(row, spaces, "Hours played: " + player["info"]["hours"])
    row += 1
    panel.addstr(row, spaces, "Created: " + player["info"]["created"])
    row += 1
    row += wrap_str(row, spaces, "Status: " + player["info"]["status"], spaces, panel)
    panel.addstr(row, spaces, "Most played gods (in ranked conquest)")
    row += 1
    for god in player["info"]["gods"]:
        panel.addstr(row, 2 * spaces, god["name"])
        row += 1
        panel.addstr(row, 3 * spaces, "Matches played: " + god["matches"])
        row += 1
        panel.addstr(row, 3 * spaces, "WR: " + god["wr"])
        row += 1
        panel.addstr(row, 3 * spaces, "Last: " + god["last"])
        row += 1
    panel.addstr(row, spaces, "Recent matches (in ranked conquest)")
    row += 1
    for i, match in enumerate(player["info"]["matches"], 1):
        panel.addstr(row, 2 * spaces, "Match #1")
        row += 1
        panel.addstr(row, 3 * spaces, "Outcome: " + match["outcome"])
        row += 1
        panel.addstr(row, 3 * spaces, "Length: " + match["length"])
        row += 1
        panel.addstr(row, 3 * spaces, "Role: " + match["role"])
        row += 1
        panel.addstr(row, 3 * spaces, "God: " + match["god"])
        row += 1
        panel.addstr(row, 3 * spaces, "KDA: " + match["kda"])
        row += 1
    panel.refresh()


def main(
    players: List[Player],
    screen=curses.initscr(),
):
    assert players
    spaces = 2
    screen.clear()

    # new window -> draw names
    screen.addstr("Players:")
    for i, player in enumerate(players, 1):
        screen.addstr(i, spaces, player["name"])
    screen.noutrefresh()
    offset = 1 + len(players)

    # new windows -> draw info boxes - only name and loading or skipped
    total_width = curses.COLS
    total_height = curses.LINES

    panel_width = int(total_width / len(players))
    panels = [
        curses.newwin(
            total_height - offset,  # nlines
            panel_width,  # ncols
            offset,  # begin_y
            i * panel_width,  # begin_x
        )
        for i in range(len(players))
    ]
    for panel, player in zip(panels, players):
        panel.box("|", "-")
        panel.addstr(player["name"])
        if player["name"] in skipped_names:
            panel.addstr(1, spaces, "skipped")
        else:
            panel.addstr(1, spaces, "loading...")
        panel.noutrefresh()

    screen.move(1, spaces)
    curses.doupdate()

    # go through names and call hirez api, update panel
    for panel, player in zip(panels, players):
        if player["name"] in skipped_names:
            continue
        if player["info"] is None:
            player["info"] = call_hirez_api(player["name"])
        redraw_panel(spaces, player, panel)

    # while true:
    names_buffer = [player["name"] for player in players]
    screen.nodelay(False)
    curses.flushinp()

    def get_yx():
        y_, x_ = curses.getsyx()
        return y_ - 1, x_ - spaces

    def set_yx(y_, x_):
        screen.move(y_ + 1, x_ + spaces)

    def update_name(y_):
        screen.move(y_ + 1, 0)  # So that clrtoeol is called on the correct line.
        screen.clrtoeol()
        if players[y_]["name"] == names_buffer[y_]:
            screen.addstr(y_ + 1, spaces, names_buffer[y_])
        else:
            screen.addstr(y_ + 1, spaces, names_buffer[y_] + " (*)")

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
            names_buffer[y] = names_buffer[y][:x] + names_buffer[y][x + 1 :]
            update_name(y)
            set_yx(y, x)
        elif c == curses.KEY_DC:
            y, x = get_yx()
            if x == len(names_buffer[y]):
                continue
            names_buffer[y] = names_buffer[y][:x] + names_buffer[y][x + 1 :]
            update_name(y)
            set_yx(y, x)
        elif c == "\n":
            y, _ = get_yx()
            players[y]["name"] = names_buffer[y]
            update_name(y)
            panels[y].clear()
            panels[y].addstr(players[y]["name"])
            panels[y].addstr(1, spaces, "loading...")
            panels[y].refresh()
            players[y]["info"] = call_hirez_api(players[y]["name"])
            redraw_panel(spaces, players[y], panels[y])
        elif c == "\x1B":
            return
        elif isinstance(c, str):
            y, x = get_yx()
            if len(names_buffer[y]) >= 32:
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

if __name__ == "__main__":
    names_from_input = [
        {
            "name": "Siemka4",
            "info": None,
        },
        {
            "name": "Jangaru",
            "info": None,
        },
        {
            "name": "sfdgsfdghsf",
            "info": None,
        },
        {
            "name": "sfdgsfdghsf",
            "info": None,
        },
        {
            "name": "sfdgsfdghsf",
            "info": None,
        },
    ]

    curses.wrapper(lambda x: main(names_from_input, x))
