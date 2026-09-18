"""SpriteScout with buttons: the same checks, shown as a page in your browser.

Double-click the GUI build (or run this file) and it opens a page where you
can check a username, project or studio, and see where something ranks for
words people search. It uses the same checking code as spritescout.py, and
saves results to the same place.

    python spritescout_gui.py
"""

import http.server
import json
import os
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.parse
import webbrowser
from datetime import datetime
from pathlib import Path

import spritescout as scout

# When built into one file, the page and icon are unpacked beside the program.
BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
PAGE, ICON = BASE / "gui.html", BASE / "icon.png"

job = {"state": "idle", "kind": "", "heading": "", "checked": 0, "total": 0,
       "items": [], "detail": None, "error": "", "stopped": False}
job_lock = threading.Lock()
unfinished = {}  # row number -> (kind, item, lookup) for results a scan could look deeper for
stopping = threading.Event()
page_served = threading.Event()  # the window got as far as showing something
alive = {"beat": 0.0, "seen": False}  # when the page last said it was still there
showing = {"in_window": False}  # whether it got a window of its own, or a browser tab

SETTING_FLAGS = {"sort": "--sort", "depth": "--depth", "trending_depth": "--trending-depth",
                 "first_screen": "--first-screen", "top": "--top", "max_projects": "--max-projects",
                 "recent_days": "--recent-days", "active_days": "--active-days", "delay": "--delay"}
SETTING_SWITCHES = {"no_update_check": "--no-update-check",  # settings that are on or off
                    "no_studios": "--no-studios", "no_tips": "--no-tips", "no_log": "--no-log"}


# Remembering the person using it

def remembered():
    try:
        return json.loads((settings_file()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def saved_flags(saved=None):
    """The remembered settings, as the flags the console version takes."""
    saved = remembered() if saved is None else saved
    flags = []
    for name, flag in SETTING_FLAGS.items():
        if saved.get(name):
            flags += [flag, str(saved[name])]
    for name, flag in SETTING_SWITCHES.items():
        if saved.get(name):
            flags.append(flag)
    return flags


def save_settings(values):
    """Remember new settings, once they make sense."""
    scout.make_parser().parse_args(saved_flags(values))  # complains about an unusable value
    remember(values)
    return remembered()


def remember(values):
    try:
        path = settings_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({**remembered(), **values}), encoding="utf-8")
    except OSError:
        pass  # not being able to remember isn't worth interrupting anyone


def settings_file():
    """Where the settings live, brought over from the name an older version used."""
    folder = scout.output_folder(scout.make_parser().parse_args([]))
    path, older = folder / "gui-settings.json", folder / "window-settings.json"
    if older.exists() and not path.exists():
        try:
            older.replace(path)
        except OSError:
            return older  # keep using the old one rather than forget everything
    return path


# Running checks in the background, so the page can show them as they arrive

def start(kind, work, *arguments, keep=False):
    """Start a check in the background, unless one is already going.

    `keep` leaves the results already on screen alone. Returns whether it started.
    """
    with job_lock:
        if job["state"] == "running":
            return False
        job.update(state="running", error="", stopped=False)
        if not keep:
            job.update(kind=kind, heading="", checked=0, total=0, items=[], detail=None)
            unfinished.clear()
    stopping.clear()
    threading.Thread(target=guard, args=(work, arguments), daemon=True).start()
    return True


def guard(work, arguments):
    """Run a check, turning problems into something the page can show."""
    session = scout.Session(interactive=False)
    try:
        session.use(scout.make_parser().parse_args(saved_flags()))
        work(session, *arguments)
    except scout.CheckError as error:
        with job_lock:
            job["error"] = str(error)
    except Exception as error:  # a bug: say so, and save the details like the console version does
        with job_lock:
            job["error"] = scout.bug_message(error, f"gui: {arguments}")
        traceback.print_exc()
    finally:
        # Keep whatever did finish, even when the rest went wrong.
        trouble = session.log.save() if session.log else ""
        with job_lock:
            job["error"] = job["error"] or trouble
            job["state"] = "done"


def depth_for(usual):
    """How far to look through search: what the settings ask for, or the usual amount."""
    return scout.clamp_depth(scout.settings.depth or usual)


def check_titles(session, text, contents=False):
    """Check a username, project or studio by title, adding rows as they finish."""
    parsed = scout.parse_command(scout.split_command(text))
    if not parsed:
        raise scout.CheckError(f"I can't tell what \"{text}\" is. Type a username, or paste a project "
                               "or studio link.")
    kind, value, _ = parsed
    items, heading = collect(kind, value, contents=contents)
    if kind == "user":
        remember({"username": value})
    with job_lock:
        job.update(total=len(items), heading=heading)
    depth = depth_for(scout.SINGLE_DEPTH if len(items) == 1 else scout.USER_DEPTH)
    for item_kind, item in items:
        if stopping.is_set():
            with job_lock:
                job["stopped"] = True  # the bar keeps showing how far it got
            return
        lookup = scout.Lookup(item_kind, item, scout.tidy(item["title"]), scout.title_sort(),
                              title_check=True)
        status, change = scout.search_title(session, lookup, depth)
        with job_lock:
            place = len(job["items"])
            if lookup.unfinished:
                unfinished[place] = (item_kind, item, lookup)
            job["checked"] += 1
            job["items"].append(row(item_kind, item, lookup, status, change, place))


def scan_deeper(session, place):
    """Keep looking for one result that stopped early, until it's found or Stop is pressed."""
    found = unfinished.get(int(place)) if str(place).isdigit() else None
    if not found:
        raise scout.CheckError("That result isn't on screen any more. Check it again first.")
    kind, item, lookup = found
    with job_lock:
        job.update(heading=f"deeper into \"{scout.short_title(item['title'], 40)}\"",
                   checked=lookup.checked, total=scout.MAX_DEPTH)
    scout.keep_looking(lookup, scout.MAX_DEPTH, should_stop=stopping.is_set,
                       progress=lambda current: job.update(checked=current.checked))
    status, change = scout.record_title(session, lookup)
    with job_lock:
        job["stopped"] = lookup.unfinished
        job["items"][int(place)] = row(kind, item, lookup, status, change, int(place))
        if not lookup.unfinished:
            unfinished.pop(int(place), None)


def check_words(session, text, words):
    """See where one project or studio ranks for some search words."""
    query = " ".join(words.split())
    if not query or not scout.re.search(r"\w", query):
        raise scout.CheckError("Type the words someone would search for, like \"pizza tycoon\".")
    parsed = scout.parse_command(scout.split_command(text))
    if not parsed or parsed[0] == "user":
        raise scout.CheckError("Search words work with one project or studio. Paste its link above.")
    items, heading = collect(parsed[0], parsed[1])
    kind, item = items[0]
    wanted = list(scout.SORTS) if scout.settings.sort == "both" else [scout.settings.sort]
    with job_lock:
        job.update(total=len(wanted), heading=f"{heading} for \"{query}\"")

    matches = scout.count_matches(kind, query)
    depth = depth_for(scout.SINGLE_DEPTH)
    depths = {"popular": depth, "trending": min(depth, scout.settings.trending_depth)}
    lookups, sorts = {}, []
    for sort in wanted:
        lookup = scout.Lookup(kind, item, query, sort)
        lookup.matches = scout.format_count(matches).replace(",", "")
        if scout.keep_looking(lookup, depths[sort], should_stop=stopping.is_set):
            with job_lock:
                job["stopped"] = True
            return
        lookups[sort] = lookup
        change = session.log.add(kind, item, query, sort, scout.result_text(lookup), lookup.rank, lookup.matches)
        sorts.append({
            "sort": scout.SORTS[sort],
            "result": scout.result_text(lookup),
            "rank": lookup.rank,
            "first": scout.on_first(lookup),
            "screen": scout.describe_first_screen(kind, query, sort),
            "change": "" if change.startswith("no change") else change,
        })
        with job_lock:
            job["checked"] += 1
            job["detail"] = {"title": scout.tidy(item["title"]), "url": scout.item_url(kind, item),
                             "kind": scout.NOUNS[kind], "query": query,
                             "matches": scout.format_count(matches), "sorts": list(sorts),
                             "about": scout.describe_item(kind, item), "tips": []}
    tips = [tip for tip, _ in scout.rank_tips(session, kind, item, query, lookups, matches)]
    with job_lock:
        job["detail"]["tips"] = tips


def try_titles(session, text, titles):
    """Compare titles someone is thinking about for one project or studio."""
    wanted = [line.strip() for line in titles.splitlines() if line.strip()]
    if not wanted:
        raise scout.CheckError("Type the titles you're thinking about, one per line.")
    kind, item = one_item(text, "Testing titles works with one project or studio. Paste its link above.")
    options = scout.possible_titles(item, wanted)
    with job_lock:
        job.update(total=len(options), heading=f"titles for \"{scout.tidy(item['title'])}\"",
                   detail={"title": scout.tidy(item["title"]), "url": scout.item_url(kind, item),
                           "kind": scout.NOUNS[kind], "about": scout.describe_item(kind, item), "titles": []})
    for title in options:
        if stopping.is_set():
            with job_lock:
                job["stopped"] = True
            return
        verdict = scout.title_verdict(kind, item, title)
        with job_lock:
            job["checked"] += 1
            job["detail"]["titles"].append({"title": title, "current": title == scout.tidy(item["title"]),
                                            "verdict": verdict})


def suggest_titles(session, text, words):
    """Titles one project or studio could reach the first screen with."""
    kind, item = one_item(text, "Suggesting titles works with one project or studio. Paste its link above.")
    hints = words.split()
    with job_lock:
        job.update(total=scout.MOST_IDEAS,
                   heading=f"titles for \"{scout.short_title(item['title'], 40)}\"")

    def step(done, total):
        job.update(checked=done, total=total)

    winners, empty, now = scout.better_titles(kind, item, hints, should_stop=stopping.is_set,
                                              progress=step)
    with job_lock:
        job["stopped"] = stopping.is_set()
        job["detail"] = {
            "title": scout.tidy(item["title"]), "url": scout.item_url(kind, item),
            "kind": scout.NOUNS[kind], "about": scout.describe_item(kind, item),
            "now": {"title": now["title"], "line": scout.idea_line(kind, item, now), "wins": now["wins"]},
            "winners": [{"title": idea["title"], "line": scout.idea_line(kind, item, idea)}
                        for idea in winners],
            "empty": empty[:5],
            "beaten": now["beaten"],
        }


def find_studios(session, words):
    """Studios about some words that anyone can add projects to."""
    query = " ".join(words.split())
    if not query:
        raise scout.CheckError("Type what the studios should be about, like \"platformer games\".")
    with job_lock:
        job.update(total=1, heading=f"studios about \"{query}\"")

    def step(done, total):  # checking how active each studio is takes a moment each
        job.update(checked=done, total=total)

    studios, note = scout.open_studios(query.split(), progress=step, should_stop=stopping.is_set)
    with job_lock:
        job["stopped"] = stopping.is_set()
        if job["stopped"]:
            note = ""  # "none found" would be wrong when it was called off early
        else:
            job["checked"] = job["total"]
        job["detail"] = {"query": query, "note": note, "studios": [
            {"title": scout.tidy(studio["title"]), "url": scout.item_url("studios", studio),
             "followers": scout.plural(scout.followers_of(studio), "follower"),
             "active": scout.ago(scout.days_since_activity(studio["id"]))}
            for studio in studios]}


def find_searches(session, text):
    """Which searches a project or studio already comes up for."""
    kind, item = one_item(text, "This works with one project or studio. Paste its link above.")
    sort, depth = scout.title_sort(), depth_for(scout.WORDS_DEPTH)
    with job_lock:
        job.update(total=1, heading=f"searches for \"{scout.tidy(item['title'])}\"")
    ranked, unranked = scout.word_rankings(session, kind, item, (), depth, sort,
                                           should_stop=stopping.is_set)
    with job_lock:
        job["stopped"] = stopping.is_set()
        job["checked"] = 1
        job["detail"] = {
            "title": scout.tidy(item["title"]), "url": scout.item_url(kind, item),
            "kind": scout.NOUNS[kind], "sort": scout.SORTS[sort], "depth": f"{depth:,}",
            "ranked": [{"query": lookup.query, "rank": lookup.rank, "first": scout.on_first(lookup)}
                       for lookup in ranked[: max(scout.settings.top, 1)]],
            "unranked": [lookup.query for lookup in unranked],
        }


def one_item(text, complaint):
    """The single project or studio a box refers to."""
    parsed = scout.parse_command(scout.split_command(text)) if text else None
    if not parsed or parsed[0] == "user":
        raise scout.CheckError(complaint)
    items, _ = collect(parsed[0], parsed[1])
    return items[0]


def update_notice():
    """What to put at the top of the page when a newer version is out.

    The GUI build has no console, so the notice the text version prints
    has to appear on the page instead.
    """
    if remembered().get("no_update_check"):
        return {}
    note = scout.update_note()
    if not note:
        return {}
    return {"note": note.replace(f" Get it from {scout.RELEASES}", "").strip(), "url": scout.RELEASES}


def history_page():
    """The saved results as a page of charts, or None when nothing has been saved yet."""
    log = scout.output_folder(scout.make_parser().parse_args([])) / "search_log.csv"
    rows = [row for row in scout.read_log(log)[0] if row["id"].isdigit()]
    if not rows:
        return None
    return scout.HISTORY_PAGE.replace("__DATA__", scout.history_json(rows, log.name))


def collect(kind, value, contents=False):
    """The projects and studios a command asks about, and a heading for them.

    `contents` asks for the projects inside a studio instead of the studio itself.
    """
    if kind == "studio":
        studio = scout.get_studio(int(value))
        if not studio:
            raise scout.CheckError(f"There's no studio with ID {value}.")
        name = f"the studio \"{scout.tidy(studio['title'])}\""
        if not contents:
            return [("studios", studio)], name
        projects = scout.get_studio_projects(studio["id"])[: scout.settings.max_projects or None]
        if not projects:
            raise scout.CheckError(f"There are no projects in {name}.")
        return ([("projects", project) for project in projects],
                f"{scout.plural(len(projects), 'project')} in {name}")
    project = scout.get_json(f"/projects/{value}") if kind != "user" else None
    if project:
        return [("projects", project)], scout.describe("projects", project)
    if kind == "project":
        raise scout.CheckError(f"There's no shared project with ID {value}. Unshared projects can't show up "
                               "in search.")
    user = scout.get_json(f"/users/{value}")
    if not user:
        raise scout.CheckError(f"There's no Scratch user named \"{value}\"." if kind == "user" else
                               f"There's no shared project or user called {value}.")
    projects = sorted(scout.get_shared_projects(user["username"]), key=scout.shared_date, reverse=True)
    projects = projects[: scout.settings.max_projects or None]
    studios = [] if scout.settings.no_studios else scout.get_hosted_studios(user)
    items = [("projects", project) for project in projects] + [("studios", studio) for studio in studios]
    if not items:
        raise scout.CheckError(f"{user['username']} has no shared projects or hosted studios, so "
                               "there's nothing to find in search.")
    heading = scout.plural(len(projects), "shared project")
    if not scout.settings.no_studios:
        heading += f" and {scout.plural(len(studios), 'hosted studio')}"
    return items, f"{heading} by {user['username']}"


def row(kind, item, lookup, status, change, place=None):
    """One line of results for the page."""
    return {
        "place": place,
        "scannable": bool(lookup.unfinished),
        "kind": scout.NOUNS[kind],
        "title": scout.tidy(item["title"]),
        "url": scout.item_url(kind, item),
        "status": status,
        "label": scout.label(status, lookup),
        "rank": lookup.rank,
        "change": "" if change.startswith("no change") else change,
        "advice": scout.title_advice(status, {kind}, lookup.checked),
        "count": (scout.plural(scout.loves_of(item), "love") if kind == "projects"
                  else scout.plural(scout.followers_of(item), "follower")),
    }


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        path, _, query = self.path.partition("?")
        asked = urllib.parse.parse_qs(query, keep_blank_values=True)  # an emptied box means "clear it"
        if path == "/":
            page = PAGE.read_text(encoding="utf-8").replace("__VERSION__", scout.VERSION)
            self.send_file(page.encode("utf-8"), "text/html; charset=utf-8")
            page_served.set()
            alive.update(seen=True, beat=time.monotonic())
        elif path == "/alive":
            alive.update(seen=True, beat=time.monotonic())
            self.send_json({})
        elif path == "/bye":
            # The page is going. Wait a moment in case another one is still open.
            alive["beat"] = time.monotonic() - GONE_AFTER + 2
            self.send_json({})
        elif path == "/where":
            self.send_json({"folder": str(results_folder())})
        elif path == "/open-folder":
            try:
                open_folder(results_folder())
                self.send_json({"opened": True})
            except (OSError, scout.CheckError) as error:
                self.send_json({"error": f"Couldn't open the folder ({error})."})
        elif path == "/window":
            self.send_json({"windowed": showing["in_window"], "browsers": BROWSER_NAMES})
        elif path == "/icon.png" and ICON.exists():
            self.send_file(ICON.read_bytes(), "image/png")
        elif path == "/check":
            self.send_started(start("titles", check_titles, asked.get("what", [""])[0].strip(),
                                    bool(asked.get("contents", [""])[0])))
        elif path == "/words":
            self.send_started(start("words", check_words, asked.get("what", [""])[0].strip(),
                                    asked.get("words", [""])[0]))
        elif path == "/suggest":
            self.send_started(start("suggest", suggest_titles, asked.get("what", [""])[0].strip(),
                                    asked.get("words", [""])[0]))
        elif path == "/titles":
            self.send_started(start("titles-test", try_titles, asked.get("what", [""])[0].strip(),
                                    asked.get("titles", [""])[0]))
        elif path == "/studios":
            self.send_started(start("studios", find_studios, asked.get("words", [""])[0]))
        elif path == "/searches":
            self.send_started(start("searches", find_searches, asked.get("what", [""])[0].strip()))
        elif path == "/history":
            page = history_page()
            if page:
                self.send_file(page.encode("utf-8"), "text/html; charset=utf-8")
            else:
                self.send_file(b"<p style='font:16px system-ui;padding:24px'>No saved results yet. "
                               b"Check something first.</p>", "text/html; charset=utf-8")
        elif path == "/progress":
            with job_lock:
                self.send_json(dict(job))
        elif path == "/scan":
            self.send_started(start("titles", scan_deeper, asked.get("place", [""])[0], keep=True))
        elif path == "/stop":
            stopping.set()
            self.send_json({"stopping": True})
        elif path == "/update":
            self.send_json(update_notice())
        elif path == "/settings":
            self.send_json(remembered())
        elif path == "/save":
            wanted = {name: asked[name][0].strip()
                      for name in (*SETTING_FLAGS, *SETTING_SWITCHES) if name in asked}
            try:
                self.send_json(save_settings({**remembered(), **wanted}))
            except scout.CheckError as error:
                self.send_json({"error": str(error)})
        else:
            self.send_error(404)

    def send_file(self, body, kind):
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self.do_GET()  # the page says goodbye with a beacon, which is a POST

    def send_started(self, started):
        self.send_json({"started": started})

    def send_json(self, data):
        self.send_file(json.dumps(data).encode("utf-8"), "application/json")

    def log_message(self, *args):
        pass  # the page is the interface; the console stays quiet


# Showing it as a window of its own

# Edge, Chrome and their relatives can show a page as a plain window: no address
# bar, no tabs, its own button on the taskbar. It uses the browser already set
# up on the computer, so nothing asks to be signed into or set as the default.
WINDOW_SIZE = "1120,860"
GONE_AFTER = 15  # seconds of silence from the page before it counts as closed
WINDOWS_BROWSERS = {  # what to look up in the registry, and what to call it
    "msedge.exe": "Edge", "chrome.exe": "Chrome", "brave.exe": "Brave",
    "vivaldi.exe": "Vivaldi", "opera.exe": "Opera", "chromium.exe": "Chromium",
}
MAC_BROWSERS = {
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome": "Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge": "Edge",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser": "Brave",
    "/Applications/Vivaldi.app/Contents/MacOS/Vivaldi": "Vivaldi",
    "/Applications/Opera.app/Contents/MacOS/Opera": "Opera",
    "/Applications/Chromium.app/Contents/MacOS/Chromium": "Chromium",
}
LINUX_BROWSERS = {
    "/usr/bin/google-chrome": "Chrome", "/usr/bin/google-chrome-stable": "Chrome",
    "/usr/bin/microsoft-edge": "Edge", "/usr/bin/microsoft-edge-stable": "Edge",
    "/usr/bin/brave-browser": "Brave", "/usr/bin/vivaldi": "Vivaldi", "/usr/bin/opera": "Opera",
    "/usr/bin/chromium": "Chromium", "/usr/bin/chromium-browser": "Chromium",
    "/snap/bin/chromium": "Chromium",
}
BROWSER_NAMES = ["Edge", "Chrome", "Brave", "Vivaldi", "Opera", "Chromium"]


def registry_path(name):
    """Where Windows says a program lives, or None."""
    import winreg
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(
                    root, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{name}") as key:
                found = winreg.QueryValue(key, None)
        except OSError:
            continue
        if found and Path(found).exists():
            return found
    return None


def usual_browser():
    """Where the browser Windows opens links with lives, when it can do windows.

    Windows records the choice in one of two places depending on how it was made,
    so this tries both before giving up.
    """
    import winreg
    for scheme in ("https", "http"):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                rf"SOFTWARE\Microsoft\Windows\CurrentVersion\Shell\Associations"
                                rf"\UrlAssociations\{scheme}\UserChoice") as key:
                chosen = winreg.QueryValueEx(key, "ProgId")[0].lower()
        except OSError:
            continue
        for name, label in WINDOWS_BROWSERS.items():
            if label.lower() in chosen or name.split(".")[0] in chosen:
                found = registry_path(name)
                if found:
                    return found
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"https\shell\open\command") as key:
            command = winreg.QueryValue(key, None)
    except OSError:
        return None
    opener = (command.split('"')[1] if command.startswith('"') else command.split()[0]) if command else ""
    if opener and Path(opener).name.lower() in WINDOWS_BROWSERS and Path(opener).exists():
        return opener
    return None


def app_browser():
    """A browser that can show a page as its own window, or None if there isn't one.

    Their usual browser comes first: it has been through its own setup already,
    so it opens straight onto the page with nothing in the way.
    """
    if sys.platform == "win32":
        theirs = usual_browser()
        if theirs:
            return theirs
        for name in WINDOWS_BROWSERS:
            found = registry_path(name)
            if found:
                return found
        return None
    places = MAC_BROWSERS if sys.platform == "darwin" else LINUX_BROWSERS
    return next((place for place in places if Path(place).exists()), None)


def window_command(browser, address):
    """How to ask a browser for a bare window showing one page."""
    return [browser, f"--app={address}", f"--window-size={WINDOW_SIZE}",
            "--no-first-run", "--no-default-browser-check"]


def open_window(address):
    """Show the page as a window of its own. Returns whether that worked."""
    browser = app_browser()
    if not browser:
        return False
    try:
        subprocess.Popen(window_command(browser, address),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return False
    return True


def still_there():
    """True while a page is open. Closing the window stops the beating."""
    return not alive["seen"] or time.monotonic() - alive["beat"] < GONE_AFTER


def complain(trouble, fatal=True):
    """Say what went wrong. A built copy has no console, so it puts it on the screen."""
    print(trouble)
    try:
        note = scout.output_folder(scout.make_parser().parse_args([])) / "last-problem.txt"
        note.write_text(f"{datetime.now():%Y-%m-%d %H:%M}\n{trouble}\n", encoding="utf-8")
    except Exception:
        pass  # if even that fails, the message on screen is what matters
    if not getattr(sys, "frozen", False):
        return  # run from the source, so the console has it already
    title = "SpriteScout couldn't start" if fatal else "SpriteScout"
    try:
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, trouble, title, 0x10 if fatal else 0x40)
        elif sys.platform == "darwin":
            subprocess.run(["osascript", "-e", f'display dialog {json.dumps(trouble)} '
                                               f'with title {json.dumps(title)} buttons {{"OK"}}'],
                           check=False)
        else:
            for teller in (["zenity", "--error", f"--text={trouble}"],
                           ["kdialog", "--error", trouble],
                           ["xmessage", "-center", trouble]):
                try:
                    subprocess.run(teller, check=False)
                    break
                except OSError:
                    continue
    except Exception:
        pass


def start_problems():
    """Everything that would stop it working, checked before anything opens."""
    problems = []
    if not PAGE.exists():
        problems.append(f"The page SpriteScout shows is missing ({PAGE}).\n\n"
                        f"The download may be damaged. Get it again from {scout.RELEASES}")
    folder = None
    try:
        folder = scout.output_folder(scout.make_parser().parse_args([]))
        folder.mkdir(parents=True, exist_ok=True)
        pen = folder / "write-test.tmp"
        pen.write_text("ok", encoding="utf-8")
        pen.unlink()
    except scout.CheckError as error:
        problems.append(str(error))
    except OSError as error:
        # output_folder() already fell back to the computer's usual place for program
        # files, so reaching here means even that is refusing.
        problems.append(f"SpriteScout can't save anything in {folder} ({error.strerror or error}).\n\n"
                        "That's the folder this computer keeps program files in, so something unusual "
                        "is stopping it: the disk may be full, or a security program may be blocking "
                        "SpriteScout. Restarting the computer sometimes clears it.")
    return problems


def results_folder():
    return scout.output_folder(scout.make_parser().parse_args(saved_flags()))


def open_folder(folder):
    """Show a folder in the computer's file manager."""
    folder.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(folder)  # noqa: the only Windows way to open a folder without a console
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(folder)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def nothing_opened(address):
    """Wait a while, and say something if no page ever appeared."""
    for _ in range(40):
        time.sleep(0.5)
        if page_served.is_set():
            return
    complain(f"SpriteScout is running, but nothing has opened it after 20 seconds.\n\n"
             f"Type this into a browser and it will be there:\n{address}\n\n"
             "If no browser appeared, this computer may not have one set up to open links. "
             "If one did, something like a security program may be stopping it.", fatal=False)


def main():
    # A windowless build has nowhere to print, so give printing somewhere to go.
    if sys.stdout is None or sys.stderr is None:
        sys.stdout = sys.stderr = open(os.devnull, "w")
    else:
        # Line by line, so a message isn't held back when the output goes to a file.
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

    problems = start_problems()
    if problems:
        complain("\n\n".join(problems))
        return 1

    try:
        server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
    except OSError as error:
        complain("SpriteScout couldn't start the little server it shows its page from "
                 f"({error.strerror or error}).\n\n"
                 "A firewall or security program may be stopping it from talking to itself. "
                 "Allowing SpriteScout through, or restarting the computer, usually fixes it.")
        return 1

    with server:
        port = server.server_address[1]
        address = f"http://127.0.0.1:{port}/"
        print(f"SpriteScout {scout.VERSION} is open at {address}")
        update = scout.update_note()
        if update:
            print(f"\n{update}")
        threading.Thread(target=server.serve_forever, daemon=True).start()

        showing["in_window"] = open_window(address)
        if not showing["in_window"]:
            opened = False
            try:
                opened = webbrowser.open(address)
            except Exception:
                opened = False
            if not opened:
                complain("SpriteScout is running, but it couldn't open a browser to show itself in.\n\n"
                         f"Type this into a browser and it will be there:\n{address}\n\n"
                         "For a window of its own instead of a tab, install any of: "
                         + ", ".join(BROWSER_NAMES) + ".", fatal=False)
        threading.Thread(target=nothing_opened, args=(address,), daemon=True).start()

        print("Close the SpriteScout window to quit."
              if showing["in_window"] else "Close the SpriteScout tab to quit.")
        try:
            while still_there():
                time.sleep(1)
            print("Closed.")
        except KeyboardInterrupt:
            print("\nClosed.")
        finally:
            server.shutdown()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as error:  # nothing gets to die quietly
        try:
            details = scout.bug_message(error, "gui: starting up")
        except Exception:
            details = f"{type(error).__name__}: {error}"
        complain(f"SpriteScout hit a problem it didn't expect.\n\n{details}")
        sys.exit(1)
