"""SpriteScout with a window: the same checks, shown as a page in your browser.

Double-click SpriteScout-GUI (or run this file) and it opens a page where you
can type a username, project or studio and see the results as a list. It uses
the same checking code as spritescout.py, and saves results to the same place.

    python spritescout_gui.py
"""

import http.server
import json
import socketserver
import sys
import threading
import traceback
import urllib.parse
import webbrowser
from pathlib import Path

import spritescout as scout

PAGE = (Path(__file__).resolve().parent / "gui.html")
ICON = (Path(__file__).resolve().parent / "icon.png")
job = {"state": "idle", "heading": "", "checked": 0, "total": 0, "items": [], "error": ""}
job_lock = threading.Lock()


def start_check(text):
    """Run a check in the background, filling in `job` as results arrive."""
    with job_lock:
        if job["state"] == "running":
            return
        job.update(state="running", heading="", checked=0, total=0, items=[], error="")
    threading.Thread(target=check, args=(text,), daemon=True).start()


def check(text):
    session = scout.Session(interactive=False)
    try:
        session.use(scout.make_parser().parse_args([]))
        parsed = scout.parse_command(scout.split_command(text))
        if not parsed:
            raise scout.CheckError(f"I can't tell what \"{text}\" is. Type a username, or paste a project "
                                   "or studio link.")
        kind, value, words = parsed
        items, heading = collect(kind, value)
        with job_lock:
            job.update(total=len(items), heading=heading)
        for item_kind, item in items:
            lookup = scout.Lookup(item_kind, item, scout.tidy(item["title"]), title_check=True)
            if not scout.re.search(r"\w", item["title"]):
                lookup.unsearchable = lookup.ended = True
            else:
                scout.keep_looking(lookup, scout.USER_DEPTH)
            status, change = scout.record_title(session, lookup)
            with job_lock:
                job["checked"] += 1
                job["items"].append(describe(item_kind, item, lookup, status, change))
        session.log.save()
    except scout.CheckError as error:
        with job_lock:
            job["error"] = str(error)
    except Exception as error:  # a bug: say so, and save the details like the console version does
        with job_lock:
            job["error"] = scout.bug_message(error, f"window: {text}")
        traceback.print_exc()
    finally:
        with job_lock:
            job["state"] = "done"


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


def describe(kind, item, lookup, status, change):
    """One row for the page."""
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
        if path == "/":
            page = PAGE.read_text(encoding="utf-8").replace("__VERSION__", scout.VERSION)
            self.send_file(page.encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/icon.png" and ICON.exists():
            self.send_file(ICON.read_bytes(), "image/png")
        elif path == "/check":
            start_check(urllib.parse.parse_qs(query).get("what", [""])[0].strip())
            self.send_json({"started": True})
        elif path == "/progress":
            with job_lock:
                self.send_json(dict(job))
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
        pass  # the console stays quiet; the page is the interface


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler) as server:
        address = f"http://127.0.0.1:{server.server_address[1]}/"
        print(f"SpriteScout {scout.VERSION} is open at {address}")
        print("Leave this window open while you use it. Close it to quit.")
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
