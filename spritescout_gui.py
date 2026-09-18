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
       "items": [], "detail": None, "error": ""}
job_lock = threading.Lock()


# Remembering the person using it

def remembered():
    try:
        return json.loads((settings_file()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


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

def start(kind, work, *arguments):
    with job_lock:
        if job["state"] == "running":
            return
        job.update(state="running", kind=kind, heading="", checked=0, total=0,
                   items=[], detail=None, error="")
    threading.Thread(target=guard, args=(work, arguments), daemon=True).start()


def guard(work, arguments):
    """Run a check, turning problems into something the page can show."""
    session = scout.Session(interactive=False)
    try:
        session.use(scout.make_parser().parse_args([]))
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
    for item_kind, item in items:
        lookup = scout.Lookup(item_kind, item, scout.tidy(item["title"]), title_check=True)
        if scout.re.search(r"\w", item["title"]):
            scout.keep_looking(lookup, scout.USER_DEPTH)
        else:
            lookup.unsearchable = lookup.ended = True
        status, change = scout.record_title(session, lookup)
        with job_lock:
            job["checked"] += 1
            job["items"].append(row(item_kind, item, lookup, status, change))


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
    with job_lock:
        job.update(total=len(scout.SORTS), heading=f"{heading} for \"{query}\"")

    matches = scout.count_matches(kind, query)
    depths = {"popular": scout.SINGLE_DEPTH, "trending": scout.settings.trending_depth}
    lookups, sorts = {}, []
    for sort in scout.SORTS:
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


def row(kind, item, lookup, status, change):
    """One line of results for the page."""
    return {
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
        asked = urllib.parse.parse_qs(query)
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
        elif path == "/progress":
            with job_lock:
                self.send_json(dict(job))
        elif path == "/settings":
            self.send_json(remembered())
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
