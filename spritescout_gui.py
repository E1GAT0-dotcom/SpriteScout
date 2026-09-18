"""SpriteScout with a window: the same checks, shown as a page in your browser.

Double-click the window build (or run this file) and it opens a page where you
can check a username, project or studio, and see where something ranks for
words people search. It uses the same checking code as spritescout.py, and
saves results to the same place.

    python spritescout_gui.py
"""

import http.server
import json
import os
import socketserver
import sys
import threading
import traceback
import urllib.parse
import webbrowser
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

SETTING_FLAGS = {"sort": "--sort", "depth": "--depth", "first_screen": "--first-screen", "top": "--top"}
SETTING_SWITCHES = {"no_update_check": "--no-update-check"}  # settings that are on or off


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
    return scout.output_folder(scout.make_parser().parse_args([])) / "window-settings.json"


# Running checks in the background, so the page can show them as they arrive

def start(kind, work, *arguments, keep=False):
    """Run a check in the background. `keep` leaves the results already on screen alone."""
    with job_lock:
        if job["state"] == "running":
            return
        job.update(state="running", error="", stopped=False)
        if not keep:
            job.update(kind=kind, heading="", checked=0, total=0, items=[], detail=None)
            unfinished.clear()
    stopping.clear()
    threading.Thread(target=guard, args=(work, arguments), daemon=True).start()


def guard(work, arguments):
    """Run a check, turning problems into something the page can show."""
    session = scout.Session(interactive=False)
    try:
        session.use(scout.make_parser().parse_args(saved_flags()))
        work(session, *arguments)
        session.log.save()
    except scout.CheckError as error:
        with job_lock:
            job["error"] = str(error)
    except Exception as error:  # a bug: say so, and save the details like the console version does
        with job_lock:
            job["error"] = scout.bug_message(error, f"window: {arguments}")
        traceback.print_exc()
    finally:
        with job_lock:
            job["state"] = "done"


def depth_for(usual):
    """How far to look through search: what the settings ask for, or the usual amount."""
    return scout.clamp_depth(scout.settings.depth or usual)


def check_titles(session, text):
    """Check a username, project or studio by title, adding rows as they finish."""
    parsed = scout.parse_command(scout.split_command(text))
    if not parsed:
        raise scout.CheckError(f"I can't tell what \"{text}\" is. Type a username, or paste a project "
                               "or studio link.")
    kind, value, _ = parsed
    items, heading = collect(kind, value)
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
    found = unfinished.get(int(place))
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
        scout.keep_looking(lookup, depths[sort])
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
        verdict = scout.title_verdict(kind, item, title)
        with job_lock:
            job["checked"] += 1
            job["detail"]["titles"].append({"title": title, "current": title == scout.tidy(item["title"]),
                                            "verdict": verdict})


def find_studios(session, words):
    """Studios about some words that anyone can add projects to."""
    query = " ".join(words.split())
    if not query:
        raise scout.CheckError("Type what the studios should be about, like \"platformer games\".")
    with job_lock:
        job.update(total=1, heading=f"studios about \"{query}\"")

    def step(done, total):  # checking how active each studio is takes a moment each
        job.update(checked=done, total=total)

    studios, note = scout.open_studios(query.split(), progress=step)
    with job_lock:
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
    ranked, unranked = scout.word_rankings(session, kind, item, (), depth, sort)
    with job_lock:
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

    The window build has no console, so the notice the console version prints
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


def collect(kind, value):
    """The projects and studios a command asks about, and a heading for them."""
    if kind == "studio":
        studio = scout.get_studio(int(value))
        if not studio:
            raise scout.CheckError(f"There's no studio with ID {value}.")
        return [("studios", studio)], f"the studio \"{scout.tidy(studio['title'])}\""
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
    studios = scout.get_hosted_studios(user)
    items = [("projects", project) for project in projects] + [("studios", studio) for studio in studios]
    return items, (f"{scout.plural(len(projects), 'shared project')} and "
                   f"{scout.plural(len(studios), 'hosted studio')} by {user['username']}")


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
        elif path == "/icon.png" and ICON.exists():
            self.send_file(ICON.read_bytes(), "image/png")
        elif path == "/check":
            start("titles", check_titles, asked.get("what", [""])[0].strip())
            self.send_json({"started": True})
        elif path == "/words":
            start("words", check_words, asked.get("what", [""])[0].strip(), asked.get("words", [""])[0])
            self.send_json({"started": True})
        elif path == "/titles":
            start("titles-test", try_titles, asked.get("what", [""])[0].strip(), asked.get("titles", [""])[0])
            self.send_json({"started": True})
        elif path == "/studios":
            start("studios", find_studios, asked.get("words", [""])[0])
            self.send_json({"started": True})
        elif path == "/searches":
            start("searches", find_searches, asked.get("what", [""])[0].strip())
            self.send_json({"started": True})
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
            start("titles", scan_deeper, asked.get("place", ["0"])[0], keep=True)
            self.send_json({"started": True})
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

    def send_json(self, data):
        self.send_file(json.dumps(data).encode("utf-8"), "application/json")

    def log_message(self, *args):
        pass  # the page is the interface; the console stays quiet


def main():
    # A windowless build has nowhere to print, so give printing somewhere to go.
    if sys.stdout is None or sys.stderr is None:
        sys.stdout = sys.stderr = open(os.devnull, "w")
    else:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler) as server:
        address = f"http://127.0.0.1:{server.server_address[1]}/"
        print(f"SpriteScout {scout.VERSION} is open at {address}")
        print("Leave this running while you use it. Close it to quit.")
        update = scout.update_note()
        if update:
            print(f"\n{update}")
        webbrowser.open(address)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nClosed.")


if __name__ == "__main__":
    main()
