import asyncio
import curses
import curses.ascii
import datetime
import json
import subprocess
import sys
import typing
from pathlib import Path

import PIL.Image
import PIL.ImageOps
import pytesseract
from charybdis.aapi import Api

skipped_names = []  # ["Siemka4", "Kapitán"]
history_folder = Path("node_modules")
debug_folder = Path("debug")
assert history_folder.is_dir() and debug_folder.is_dir()
api: Api | None = None


class GodInfo(typing.TypedDict):
    name: str
    matches: str  # noqa
    wins: str
    last: str


class MatchInfo(typing.TypedDict):
    outcome: str
    length: str
    role: str
    god: str
    kda: str


class PlayerInfo(typing.TypedDict):
    level: str
    hours: str
    created: str
    status: str
    alt_name: str
    mmr: str
    matches: str  # noqa
    last: str
    gods: list[GodInfo]
    recent_matches: list[MatchInfo]


class Player(typing.TypedDict, total=False):
    name: str
    info: typing.Optional[PlayerInfo]


def make_date_sensible(date: str) -> str:
    x = date.split("/")
    return f"{x[1]}/{x[0]}/{x[2]}" if len(x) == 3 else date


async def call_hirez_api(player: str) -> PlayerInfo | None:
    getplayer_task = asyncio.create_task(api.call_method("getplayer", player))
    getqueuestats_task = asyncio.create_task(
        api.call_method("getqueuestats", player, "451")
    )
    getmatchhistory_task = asyncio.create_task(
        api.call_method("getmatchhistory", player)
    )

    try:
        getplayer_json = await getplayer_task
    except:
        getqueuestats_task.cancel()
        getmatchhistory_task.cancel()
        raise

    # If player is not found, empty list is returned.
    if not getplayer_json:
        getqueuestats_task.cancel()
        getmatchhistory_task.cancel()
        return None

    x = getplayer_json[0]

    # For private players, integer values return zero and string values null.
    res: PlayerInfo = {
        "level": str(x["Level"]),
        "hours": str(x["HoursPlayed"]),
        "created": make_date_sensible(str(x["Created_Datetime"])),
        "status": str(x["Personal_Status_Message"]),
        "alt_name": str(x["Name"]),
        "mmr": f"{x['Rank_Stat_Conquest']:.0f}",
    }

    try:
        getqueuestats_json = await getqueuestats_task
    except:
        getmatchhistory_task.cancel()
        raise

    matches = sum(x["Matches"] for x in getqueuestats_json)
    res["matches"] = str(matches)
    res["gods"] = [
        {
            "name": x["God"],
            "matches": f"{x['Matches']} ({x['Matches'] / matches:.0%})",
            "wins": f"{x['Wins']} ({x['Wins'] / x['Matches']:.0%})",
            "last": make_date_sensible(x["LastPlayed"]),
        }
        for x in getqueuestats_json[:3]
    ]

    getmatchhistory_json = await getmatchhistory_task
    xx = [x for x in getmatchhistory_json if x["Match_Queue_Id"] == 451]
    res["recent_matches"] = [
        {
            "outcome": x["Win_Status"],
            "length": f"{x['Minutes']}m",
            "role": x["Role"],
            "god": x["God"],
            "kda": f"{x['Kills']}/{x['Deaths']}/{x['Assists']}",
        }
        for x in xx[:3]
    ]
    res["last"] = make_date_sensible(xx[0]["Match_Time"]) if xx else "None"

    return res


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


async def redraw_panel(spaces: int, player: Player, panel=curses.initscr()):
    await _redraw_panel(spaces, player, panel)
    panel.refresh()


async def _redraw_panel(spaces: int, player: Player, panel=curses.initscr()):
    panel.clear()
    panel.box("|", "-")
    panel.addstr(player["name"])

    if not player["name"]:
        return panel.addstr(1, spaces, "empty name")

    if player["name"] in skipped_names:
        return panel.addstr(1, spaces, "skipped")

    if "info" not in player:
        panel.addstr(1, spaces, "loading...")
        panel.refresh()
        try:
            player["info"] = await call_hirez_api(player["name"])
        except Exception as e:
            return wrap_str(1, spaces, f"{e.__class__.__name__}: {e}", spaces, panel)

    if player["info"] is None:
        return panel.addstr(1, spaces, "not found")

    row = 1
    indent = 1
    panel.addstr(row, indent * spaces, "Level: " + player["info"]["level"])
    row += 1
    panel.addstr(row, indent * spaces, "Hours: " + player["info"]["hours"])
    row += 1
    panel.addstr(row, indent * spaces, "Created: " + player["info"]["created"])
    row += 1
    row += wrap_str(
        row, indent * spaces, "Status: " + player["info"]["status"], spaces, panel
    )
    panel.addstr(row, indent * spaces, "Alt name: " + player["info"]["alt_name"])
    row += 1
    panel.addstr(row, indent * spaces, "Ranked conquest")
    row += 1
    indent += 1
    panel.addstr(row, indent * spaces, "MMR: " + player["info"]["mmr"])
    row += 1
    panel.addstr(row, indent * spaces, "Matches: " + player["info"]["matches"])
    row += 1
    panel.addstr(row, indent * spaces, "Last: " + player["info"]["last"])
    row += 1
    panel.addstr(row, indent * spaces, "Most played gods")
    row += 1
    indent += 1
    for god in player["info"]["gods"]:
        panel.addstr(row, indent * spaces, god["name"])
        row += 1
        indent += 1
        panel.addstr(row, indent * spaces, "Matches: " + god["matches"])
        row += 1
        panel.addstr(row, indent * spaces, "Wins: " + god["wins"])
        row += 1
        panel.addstr(row, indent * spaces, "Last: " + god["last"])
        row += 1
        indent -= 1
    indent -= 1
    panel.addstr(row, indent * spaces, "Recent matches")
    row += 1
    indent += 1
    for i, match in enumerate(player["info"]["recent_matches"], 1):
        panel.addstr(row, indent * spaces, f"Match #{i}")
        row += 1
        indent += 1
        panel.addstr(row, indent * spaces, "Outcome: " + match["outcome"])
        row += 1
        panel.addstr(row, indent * spaces, "Length: " + match["length"])
        row += 1
        panel.addstr(row, indent * spaces, "Role: " + match["role"])
        row += 1
        panel.addstr(row, indent * spaces, "God: " + match["god"])
        row += 1
        panel.addstr(row, indent * spaces, "KDA: " + match["kda"])
        row += 1
        indent -= 1
    indent -= 1


async def main(
    players: list[Player],
    screen=curses.initscr(),
):
    assert players
    spaces = 2
    screen.clear()

    # new window -> draw names
    screen.addstr("Players:")
    for i, player in enumerate(players, 1):
        screen.addstr(i, spaces, player["name"])
    screen.refresh()
    offset = 1 + len(players) + 1  # +1 for header and +1 for an empty line.

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
    tasks = [
        redraw_panel(spaces, player, panel) for player, panel in zip(players, panels)
    ]
    await asyncio.gather(*tasks)

    screen.move(1, spaces)
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
            y, x = get_yx()
            players[y]["name"] = names_buffer[y]
            update_name(y)
            await redraw_panel(spaces, players[y], panels[y])
            set_yx(y, x)
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


def take_screenshot() -> PIL.Image.Image:
    path = "tmp.png"
    subprocess.run(["./nircmd.exe", "savescreenshot", path], check=True)
    return get_image_from_file(path)


def get_players_from_history(desired_i: int) -> list[Player]:
    history = sorted(history_folder.iterdir(), reverse=True)
    fp = next(x for i, x in enumerate(history, 1) if i == desired_i)
    return get_players_from_file(fp)


def get_image_from_file(fp: str | Path) -> PIL.Image.Image | None:
    try:
        return PIL.Image.open(fp)
    except PIL.UnidentifiedImageError:
        return None


def get_players_from_file(fp: str | Path) -> list[Player]:
    with open(fp, encoding="utf8") as f:
        return json.load(f)


def b(top, height, left, width):
    right = 1920 - left - width
    bottom = 1080 - top - height
    return left, top, right, bottom


def cleanup(name: str) -> str:
    name = [part for part in name.split() if len(part) > 2]
    name = " ".join(name)
    name = name.strip(" \n|")
    if name == "Kapitan":
        name = "Kapitán"
    return name


def get_names_from_screenshot(img_screen: PIL.Image.Image) -> list[str]:
    height = 33
    left = 95
    width = 320

    inc = 140
    first_top = 182
    second_top = first_top + inc
    third_top = second_top + inc
    fourth_top = third_top + inc
    fifth_top = fourth_top + inc
    tops = [first_top, second_top, third_top, fourth_top, fifth_top]

    names = []
    for i, top in enumerate(tops, 1):
        border = b(top, height, left, width)
        img_name = PIL.ImageOps.crop(img_screen, typing.cast(int, border))
        img_name.save(debug_folder / f"name{i}.png")
        name = pytesseract.image_to_string(img_name)
        names.append(name)
    with open(debug_folder / "names.json", "w", encoding="utf8") as f:
        json.dump(names, f)
    names = [cleanup(name) for name in names]
    return names


def main_outer(screen=curses.initscr()):
    asyncio.run(amain_outer(screen))


async def amain_outer(screen=curses.initscr()):
    img = names = players = None
    save_to_history = False
    if len(sys.argv) == 1:
        img = take_screenshot()
        save_to_history = True
    elif len(sys.argv) == 2:
        arg = sys.argv[1]
        if arg.isdigit():
            players = get_players_from_history(int(arg))
        elif img := get_image_from_file(arg):
            pass
        elif players := get_players_from_file(arg):
            pass
        else:
            names = [arg]
    else:
        names = sys.argv[1:]

    if players is None:
        if names is None:
            if img is None:
                assert False
            names = get_names_from_screenshot(img)
        players = [{"name": name} for name in names]

    now = datetime.datetime.now().isoformat()
    now = now.replace(":", "꞉")  # https://stackoverflow.com/a/25477235
    try:
        async with Api() as _api:
            global api
            api = _api
            await main(players, screen)
    except KeyboardInterrupt:
        pass
    if save_to_history:
        with open(f"node_modules/{now}.json", "w") as f:
            json.dump(players, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    curses.wrapper(main_outer)
