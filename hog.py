import asyncio
import curses
import curses.ascii
import datetime
import json
import subprocess
import sys
import typing
from pathlib import Path

import charybdis
import PIL.Image
import PIL.ImageOps
import pytesseract

skipped_names = []  # ["Siemka4", "Kapitán"]
history_folder = Path("node_modules")
debug_folder = Path("debug")
assert history_folder.is_dir() and debug_folder.is_dir()
api: charybdis.Api | None = None


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
    error: typing.Optional[str]


class UserExit(Exception):
    pass


def make_date_sensible(date: str) -> str:
    x = date.split("/")
    return f"{x[1]}/{x[0]}/{x[2]}" if len(x) == 3 else date


async def call_hirez_api(player: str) -> PlayerInfo | None:
    getplayer_task = asyncio.create_task(api.acall_method("getplayer", player))
    getqueuestats_task = asyncio.create_task(
        api.acall_method("getqueuestats", player, "451")
    )
    getmatchhistory_task = asyncio.create_task(
        api.acall_method("getmatchhistory", player)
    )

    try:
        getplayer_json = await getplayer_task
    except:  # noqa
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
    except:  # noqa
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


def trunc_str(max_x: int, x: int, s: str) -> str:
    s = f"{' ' * x}{s}"
    if len(s) > max_x:
        s = f"{s[:max_x - 3]}..."
    return s


def wrap_str(max_x: int, spaces: int, x: int, s: str):
    curr_s = s
    lines = []
    while True:
        if x + len(curr_s) <= max_x:
            lines.append(f"{' ' * x}{curr_s}")
            return lines
        # -1 for hyphen.
        wrap = max_x - x - 1
        if wrap < 1:
            lines.append(trunc_str(max_x, x, curr_s))
            return lines
        lines.append(f"{' ' * x}{curr_s[:wrap]}-")
        curr_s = curr_s[wrap:]
        if len(lines) == 1:
            x += spaces


async def redraw_panel(retry: bool, player: Player, panel=curses.initscr()):
    spaces = 2
    max_y, max_x = panel.getmaxyx()
    panel.box("|", "-")
    panel.addstr(0, 0, trunc_str(max_x, 0, player["name"]))

    if player["name"] == "":
        lines = ["empty name"]
    elif player["name"] in skipped_names:
        lines = ["skipped"]
    elif not retry and "error" in player:
        lines = wrap_str(max_x - 4, spaces, 0, player["error"])
    elif "info" not in player:
        panel.addstr(1, 2, "loading...")
        panel.refresh()
        try:
            player["info"] = await call_hirez_api(player["name"])
        except Exception as e:
            player["error"] = f"{e.__class__.__name__}: {e}"
            lines = wrap_str(max_x - 4, spaces, 0, player["error"])
        else:
            if "error" in player:
                del player["error"]
            lines = _redraw_panel(max_x - 4, spaces, player["info"])
        panel.addstr(1, 2, " " * len("loading..."))
    else:
        lines = _redraw_panel(max_x - 4, spaces, player["info"])

    if len(lines) > max_y - 2:
        lines = lines[: max_y - 3]
        lines.append("...")
    for y, line in enumerate(lines, 1):
        panel.addstr(y, 2, line)
    panel.refresh()


def _redraw_panel(max_x: int, spaces: int, info: PlayerInfo | None) -> list[str]:
    if info is None:
        return ["not found"]

    lines = []
    x = 0
    lines.append(trunc_str(max_x, x, f"Level: {info['level']}"))
    lines.append(trunc_str(max_x, x, f"Hours: {info['hours']}"))
    lines.append(trunc_str(max_x, x, f"Created: {info['created']}"))
    lines.extend(wrap_str(max_x, spaces, x, f"Status: {info['status']}"))
    lines.append(trunc_str(max_x, x, f"Alt name: {info['alt_name']}"))
    lines.append(trunc_str(max_x, x, f"Ranked conquest"))
    x += spaces
    lines.append(trunc_str(max_x, x, f"MMR: {info['mmr']}"))
    lines.append(trunc_str(max_x, x, f"Matches: {info['matches']}"))
    lines.append(trunc_str(max_x, x, f"Last: {info['last']}"))
    lines.append(trunc_str(max_x, x, f"Most played gods"))
    x += spaces
    for god in info["gods"]:
        lines.append(trunc_str(max_x, x, god["name"]))
        x += spaces
        lines.append(trunc_str(max_x, x, f"Matches: {god['matches']}"))
        lines.append(trunc_str(max_x, x, f"Wins: {god['wins']}"))
        lines.append(trunc_str(max_x, x, f"Last: {god['last']}"))
        x -= spaces
    x -= spaces
    lines.append(trunc_str(max_x, x, f"Recent matches"))
    x += spaces
    for i, match in enumerate(info["recent_matches"], 1):
        lines.append(trunc_str(max_x, x, f"Match #{i}"))
        x += spaces
        lines.append(trunc_str(max_x, x, f"Outcome: {match['outcome']}"))
        lines.append(trunc_str(max_x, x, f"Length: {match['length']}"))
        lines.append(trunc_str(max_x, x, f"Role: {match['role']}"))
        lines.append(trunc_str(max_x, x, f"God: {match['god']}"))
        lines.append(trunc_str(max_x, x, f"KDA: {match['kda']}"))
        x -= spaces
    x -= spaces
    return lines


def write_header_and_get_panel_y_width_height(
    players: list[Player], screen=curses.initscr()
) -> tuple[int, int, int]:
    screen.clear()
    screen.move(0, 0)
    y = 1 + len(players) + 1  # +1 for header and +1 for an empty line
    max_y, max_x = screen.getmaxyx()

    if y + 3 > max_y or max_x < 80:
        screen.addstr(trunc_str(max_x, 0, "Screen too small, please resize."))
        screen.refresh()

        screen.nodelay(False)
        while True:
            c = screen.get_wch()
            if c == "\x1B":
                raise UserExit
            elif c == curses.KEY_RESIZE:
                max_y, max_x = screen.getmaxyx()
                if y + 3 <= max_y and max_x >= 80:
                    screen.clear()
                    screen.move(0, 0)
                    break

    screen.addstr("Players:")
    for i, player in enumerate(players, 1):
        screen.addstr(i, 2, player["name"])
    screen.refresh()

    width = max_x // len(players)
    height = max_y - y
    return y, width, height


async def main(
    players: list[Player],
    screen=curses.initscr(),
):
    if not players:
        raise ValueError("No players selected")

    (
        initial_panel_y,
        initial_panel_width,
        initial_panel_height,
    ) = write_header_and_get_panel_y_width_height(players, screen)
    panels = [
        curses.newwin(
            initial_panel_height,  # nlines
            initial_panel_width,  # ncols
            initial_panel_y,  # begin_y
            i * initial_panel_width,  # begin_x
        )
        for i in range(len(players))
    ]
    tasks = [
        redraw_panel(False, player, panel) for player, panel in zip(players, panels)
    ]
    await asyncio.gather(*tasks)

    names_buffer = [player["name"] for player in players]

    def get_yx():
        y_, x_ = curses.getsyx()
        return y_ - 1, x_ - 2

    def set_yx(y_, x_):
        screen.move(y_ + 1, x_ + 2)

    def update_name(y_):
        screen.move(y_ + 1, 0)  # So that clrtoeol is called on the correct line.
        screen.clrtoeol()
        if players[y_]["name"] == names_buffer[y_]:
            screen.addstr(y_ + 1, 2, names_buffer[y_])
        else:
            screen.addstr(y_ + 1, 2, names_buffer[y_] + " (*)")

    async def resize():
        (
            panel_y,
            panel_width,
            panel_height,
        ) = write_header_and_get_panel_y_width_height(players, screen)
        for i, panel in enumerate(panels):
            panel_x = i * panel_width
            panel.clear()
            panel.resize(1, 1)
            panel.mvwin(panel_y, panel_x)
            panel.resize(panel_height, panel_width)
        for player, panel in zip(players, panels):
            await redraw_panel(False, player, panel)

    screen.nodelay(True)
    while True:
        try:
            c = screen.get_wch()
            if c == "\x1B":
                return
            elif c == curses.KEY_RESIZE:
                await resize()
                break
        except curses.error as e:
            if str(e) == "no input":
                break
            else:
                raise
    screen.move(1, 2)

    screen.nodelay(False)
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
            if players[y]["name"] != names_buffer[y] and "info" in players[y]:
                del players[y]["info"]
            players[y]["name"] = names_buffer[y]
            update_name(y)
            panels[y].clear()
            await redraw_panel(True, players[y], panels[y])
            set_yx(y, x)
        elif c == "\x1B":
            return
        elif c == curses.KEY_RESIZE:
            y, x = get_yx()
            await resize()
            set_yx(y, x)
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
        async with charybdis.Api() as _api:
            global api
            api = _api
            await main(players, screen)
    except (KeyboardInterrupt, UserExit):
        pass
    if save_to_history:
        with open(f"node_modules/{now}.json", "w") as f:
            json.dump(players, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    curses.wrapper(main_outer)
