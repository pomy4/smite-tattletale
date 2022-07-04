import asyncio
import curses
import datetime
import json
import os
import subprocess
import sys
import typing
from pathlib import Path

import charybdis
import PIL.Image
import PIL.ImageOps
import pytesseract

skipped_names = []
debug_dir = Path("debug")
history_dir = Path("history")


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


# -------------------------------------
# Obtaining player names
# -------------------------------------


# The default parameter for screen is there only for type hinting.
async def main_outer(screen=curses.initscr()):
    img = names = players = None
    save_to_history = False
    if len(sys.argv) == 1:
        img = take_screenshot()
        save_to_history = True
    elif len(sys.argv) == 2:
        arg = sys.argv[1]
        if is_positive_integer(arg) and history_dir.is_dir():
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
                raise ValueError("No players found")
            names = get_names_from_screenshot(img)
        players = [{"name": name} for name in names]

    now = datetime.datetime.now().isoformat()
    now = now.replace(":", "꞉")  # https://stackoverflow.com/a/25477235
    try:
        async with charybdis.Api() as api:
            await main(api, players, screen)
    except (KeyboardInterrupt, UserExit):
        pass
    if save_to_history and history_dir.is_dir():
        with open(history_dir / f"{now}.json", "w") as f:
            json.dump(players, f, indent=2, ensure_ascii=False)


def take_screenshot() -> PIL.Image.Image:
    img_path = debug_dir / "lobby.png" if debug_dir.is_dir() else Path("tmp.png")
    nircmd = "./nircmd.exe" if Path("nircmd.exe").is_file() else "nircmd.exe"
    subprocess.run([nircmd, "savescreenshot", img_path], check=True)
    try:
        img = get_image_from_file(img_path)
    finally:
        if not debug_dir.is_dir():
            img_path.unlink()
    return img


def get_image_from_file(fp: str | Path) -> PIL.Image.Image | None:
    try:
        return PIL.Image.open(fp)
    except (FileNotFoundError, PIL.UnidentifiedImageError):
        return None


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
        if debug_dir.is_dir():
            img_name.save(debug_dir / f"name{i}.png")
        name = pytesseract.image_to_string(img_name)
        names.append(name)
    clean_names = [cleanup(name) for name in names]
    if debug_dir.is_dir():
        with open(debug_dir / "names.txt", "w", encoding="utf8") as f:
            f.write(f"{names}\n{clean_names}\n")
    return clean_names


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


def is_positive_integer(s: str) -> bool:
    try:
        return int(s) > 0
    except ValueError:
        return False


def get_players_from_history(desired_i: int) -> list[Player]:
    history = sorted(history_dir.iterdir(), reverse=True)
    try:
        fp = next(x for i, x in enumerate(history, 1) if i == desired_i)
    except StopIteration:
        raise ValueError(
            f"Did not find record #{desired_i} in history"
            f" (its current size is {len(history)})"
        )
    return get_players_from_file(fp)


def get_players_from_file(fp: str | Path) -> list[Player] | None:
    try:
        with open(fp, encoding="utf8") as f:
            return json.load(f)  # TODO: validate.
    except FileNotFoundError:
        return None


# -------------------------------------
# Showing player info - curses stuff
# -------------------------------------


async def main(
    api: charybdis.Api,
    players: list[Player],
    screen=curses.initscr(),
):
    if len(players) == 0:
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
        redraw_panel(api, False, player, panel)
        for player, panel in zip(players, panels)
    ]
    await asyncio.gather(*tasks)

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
            await redraw_panel(api, False, player, panel)

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

    def get_yx():
        y_, x_ = curses.getsyx()
        return y_ - 1, x_ - 2

    def set_yx(y_, x_):
        screen.move(y_ + 1, x_ + 2)

    names_buffer = [player["name"] for player in players]

    def update_name(y_):
        screen.move(y_ + 1, 0)  # So that clrtoeol is called on the correct line.
        screen.clrtoeol()
        if players[y_]["name"] == names_buffer[y_]:
            screen.addstr(y_ + 1, 2, names_buffer[y_])
        else:
            screen.addstr(y_ + 1, 2, names_buffer[y_] + " (*)")

    screen.nodelay(False)
    while True:
        c = screen.get_wch()
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
            await redraw_panel(api, True, players[y], panels[y])
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

        # I think screen.get_wch() also refreshes screen,
        # so explicit screen.refresh() is not needed here.


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


async def redraw_panel(
    api: charybdis.Api, retry: bool, player: Player, panel=curses.initscr()
):
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
            player["info"] = await call_hirez_api(api, player["name"])
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


def trunc_str(max_x: int, x: int, s: str) -> str:
    s = f"{' ' * x}{s}"
    if len(s) > max_x:
        s = f"{s[:max_x - 3]}..."
    return s


# -------------------------------------
# Getting player info - hirez stuff
# -------------------------------------


async def call_hirez_api(api: charybdis.Api, player: str) -> PlayerInfo | None:
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
        "created": make_full_date(x["Created_Datetime"])
        if x["Created_Datetime"] is not None
        else "None",
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
            "last": make_ago_date(x["LastPlayed"]),
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
    res["last"] = make_ago_date(xx[0]["Match_Time"]) if xx else "None"

    return res


def make_full_date(date: str) -> str:
    return parse_date(date).astimezone().strftime("%d/%m/%Y %H:%M:%S")


def make_ago_date(date: str) -> str:
    before = parse_date(date)
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    seconds_ago = (now - before).total_seconds()
    if seconds_ago < 60:
        return f"<1 minute ago"
    minutes_ago = seconds_ago / 60
    if minutes_ago < 60:
        return f"{int(minutes_ago)} minutes ago"
    hours_ago = minutes_ago / 60
    if hours_ago < 24:
        msg = f"{int(hours_ago)} hours"
        minutes_ago = int(minutes_ago % 60)
        if minutes_ago > 0:
            msg += f" and {minutes_ago} minutes"
        return f"{msg} ago"
    days_ago = hours_ago / 24
    if days_ago < 30:
        msg = f"{int(days_ago)} days"
        hours_ago = int(hours_ago % 24)
        if hours_ago > 0:
            msg += f" and {hours_ago} hours"
        return f"{msg} ago"
    months_ago = days_ago / 30
    if months_ago < 12:
        msg = f"{int(months_ago)} months"
        days_ago = int(days_ago % 30)
        if days_ago > 0:
            msg += f" and {days_ago} days"
        return f"{msg} ago"
    years_ago = months_ago / 12
    msg = f"{int(years_ago)} years"
    months_ago = int(months_ago % 12)
    if months_ago > 0:
        msg += f" and {months_ago} months"
    return f"{msg} ago"


def parse_date(date: str) -> datetime.datetime:
    date, time, meridiem = date.split(" ")
    month, day, year = date.split("/")
    hour, minute, second = time.split(":")
    year = int(year)
    month = int(month)
    day = int(day)
    hour = int(hour)
    minute = int(minute)
    second = int(second)
    if meridiem == "AM" and hour == 12:
        hour = 0
    if meridiem == "PM" and hour < 12:
        hour += 12
    return datetime.datetime(
        year=year,
        month=month,
        day=day,
        hour=hour,
        minute=minute,
        second=second,
        tzinfo=datetime.timezone.utc,
    )


if __name__ == "__main__":
    skipped_names_str = os.getenv("TT_SKIPPED_NAMES")
    if skipped_names_str is not None:
        skipped_names.extend(skipped_names_str.split(";"))
    curses.wrapper(lambda screen: asyncio.run(main_outer(screen)))
