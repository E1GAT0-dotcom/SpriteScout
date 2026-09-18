"""SpriteScout: check whether Scratch projects and studios show up in Scratch search, and how to rank higher.

Searches Scratch the same way the Scratch search bar does and reports where
things rank. It only reads public data: it never logs in or posts anything.

Double-click SpriteScout.exe (or run this file with no arguments) to type
commands one after another; type help for the list. Or run one command from a
terminal, like:

    SpriteScout.exe griffpatch --max-projects 10
    python spritescout.py 123456789 pizza tycoon --sort popular

Results, the history page and error reports go in the output folder next to
this program. To rebuild SpriteScout.exe after changing this file (needs
PyInstaller):

    pyinstaller --onefile --console --name SpriteScout spritescout.py

Tests are in tests/run_tests.py.
"""

import argparse
import copy
import csv
import functools
import json
import math
import os
import platform
import re
import shlex
import statistics
import subprocess
import sys
import textwrap
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

try:
    import msvcrt  # Windows console keys, so a scan can stop when q is pressed
except ImportError:
    msvcrt = None

VERSION = "2.0"
RELEASES = "https://github.com/E1GAT0-dotcom/SpriteScout/releases"
LATEST_RELEASE = "https://api.github.com/repos/E1GAT0-dotcom/SpriteScout/releases/latest"
FROZEN = getattr(sys, "frozen", False)  # running as SpriteScout.exe
HERE = Path(sys.executable if FROZEN else __file__).resolve().parent
OUTPUT = HERE / "output"  # where results, the history page and error reports go
PROGRAM = "SpriteScout.exe" if FROZEN else "python spritescout.py"

API = "https://api.scratch.mit.edu"
USER_AGENT = f"SpriteScout/{VERSION} (read-only)"
PAGE_SIZE = 40        # most results the API returns per request
USER_DEPTH = 200      # search results to look through per item when checking several
SINGLE_DEPTH = 1000   # search results to look through when checking one item
WORDS_DEPTH = 200     # search results to look through per search for --find-words
MAX_DEPTH = 10000     # search returns nothing past this many results
CROWDED = 2000        # searches matching more than this many are hard to stand out in
REQUEST_DELAY = 0.3   # seconds between requests, to go easy on Scratch
SORTS = {"popular": "Popular", "trending": "Trending"}  # API name -> name on the search page
NOUNS = {"projects": "project", "studios": "studio"}     # API name -> singular
STOP_HINT = "Press q to stop." if msvcrt else "Press Ctrl+C to stop."
STOP_WORDS = {"a", "an", "and", "at", "by", "for", "in", "is", "it", "my", "of", "on", "or", "the", "to", "with"}
LOG_FIELDS = ["checked_at", "type", "id", "title", "search", "sort", "result", "rank",
              "loves", "favorites", "views", "followers", "matches"]

LABELS = {
    "easy": "Easy to find",
    "buried": "Buried",
    "new": "Not in search yet",
    "missing": "Missing from search",
    "unknown": "Not in top {checked:,}",
    "capped": "Past result 10,000",
    "unsearchable": "Can't check",
}

ADVICE = {
    "easy": "Comes up in the first {first} results when someone searches its title.",
    "buried": (
        "In search, but below the first {first} results, where most people won't "
        "scroll. A shorter, more distinctive title helps."
    ),
    "new": (
        "Not in search, but {made} in the last {recent} days. New {nouns} can take "
        "a while to show up, so check again in a few days."
    ),
    "missing": (
        "Scratch listed every {noun} matching its title, and it wasn't among them, "
        "so nobody can find it by searching. Public data doesn't say why."
    ),
    "unknown": (
        "So many {nouns} match its title that the check stopped after {checked:,} "
        "results. It's either buried deeper than anyone scrolls or missing from search."
    ),
    "capped": (
        "Scratch search stops showing results after 10,000, and it isn't in them, so "
        "nobody can scroll to it. A shorter, more distinctive title helps."
    ),
    "unsearchable": "The title has no letters or numbers, so nobody can search for it.",
}
NOT_FOR_EVERYONE = (
    " For projects, a common reason is being marked \"Not for Everyone\", which hides "
    "a project from search and Explore without telling the creator."
)
CONTACT = " The Scratch Team can tell you: https://scratch.mit.edu/contact-us"

def whole_number(low, high=None):
    """An argparse type for whole numbers in a range, with a plain-language error."""
    def parse(text):
        try:
            value = int(text)
        except ValueError:
            value = None
        if value is None or value < low or (high is not None and value > high):
            limit = f"from {low:,} to {high:,}" if high is not None else f"of {low} or more"
            raise argparse.ArgumentTypeError(f"needs a whole number {limit}, but got \"{text}\"")
        return value
    return parse


def seconds(text):
    """An argparse type for a delay in seconds."""
    try:
        value = float(text)
    except ValueError:
        value = None
    if value is None or not 0 <= value <= 60:
        raise argparse.ArgumentTypeError(f"needs a number of seconds from 0 to 60, like 0.5, but got \"{text}\"")
    return value


COMMANDS = [
    ("USERNAME", "Check someone's projects and the studios they host"),
    ("PROJECT", "Check a project by its title (its link or ID)"),
    ("studio ID", "Check a studio by its title (or paste its link)"),
    ("PROJECT WORDS", "Where a project ranks for WORDS, with tips"),
    ("studio ID WORDS", "Where a studio ranks for WORDS, with tips"),
]
WINDOW_COMMANDS = [
    ("scan", "Keep looking for what the last check didn't find"),
    ("help", "Show this list"),
    ("q", "Quit (or type quit or exit)"),
]

# Flags as (section, names, argparse settings, help). The parser and the help
# list are both built from this, so they always match.
OPTIONS = [
    ("Extra features", ["--find-studios"], {"nargs": "+", "metavar": "WORDS"},
     "Active studios about WORDS that anyone can add to"),
    ("Extra features", ["--titles"], {"nargs": "+", "metavar": '"TITLE"'},
     "After a project or studio: compare new titles"),
    ("Extra features", ["--find-words"], {"action": "store_true"},
     "After a project or studio: searches it ranks for"),
    ("Extra features", ["--contents"], {"action": "store_true"},
     "After a studio: check every project in it"),
    ("Extra features", ["--history"], {"action": "store_true"},
     "Open a page charting saved results over time"),
    ("Extra features", ["--scan"], {"action": "store_true"},
     "Keep looking right away for anything not found"),
    ("Settings", ["--sort"], {"choices": ["popular", "trending", "both"], "default": "both", "metavar": "SORT"},
     "popular, trending or both (default both)"),
    ("Settings", ["--depth"], {"type": whole_number(1, MAX_DEPTH), "metavar": "N"},
     f"Results to look through ({SINGLE_DEPTH:,} for one, {USER_DEPTH} for many)"),
    ("Settings", ["--trending-depth"], {"type": whole_number(1, MAX_DEPTH), "default": 200, "metavar": "N"},
     "Results to look through in Trending (default 200)"),
    ("Settings", ["--first-screen"], {"type": whole_number(1, PAGE_SIZE), "default": 16, "metavar": "N"},
     "Results counted as the first screen (default 16)"),
    ("Settings", ["--recent-days"], {"type": whole_number(0), "default": 14, "metavar": "N"},
     "Days a new share counts as too new (default 14)"),
    ("Settings", ["--max-projects"], {"type": whole_number(1), "metavar": "N"},
     "Only check the N newest projects"),
    ("Settings", ["--no-studios"], {"action": "store_true"},
     "Skip hosted studios when checking a user"),
    ("Settings", ["--no-tips"], {"action": "store_true"},
     "Leave out the tips"),
    ("Settings", ["--top"], {"type": whole_number(1), "default": 10, "metavar": "N"},
     "How many results the finders list (default 10)"),
    ("Settings", ["--active-days"], {"type": whole_number(1), "default": 30, "metavar": "N"},
     "For --find-studios: active in N days (default 30)"),
    ("Settings", ["--delay"], {"type": seconds, "metavar": "SECONDS"},
     f"Wait between requests (default {REQUEST_DELAY})"),
    ("Settings", ["--output"], {"type": Path, "metavar": "FOLDER"},
     "Save results in FOLDER (default: the output folder)"),
    ("Settings", ["--no-log"], {"action": "store_true"},
     "Don't save results"),
    ("Settings", ["--no-update-check"], {"action": "store_true"},
     "Don't look for a newer version"),
    ("Settings", ["--version"], {"action": "store_true"},
     "Show the version number"),
    ("Settings", ["-h", "--help"], {"action": "store_true"},
     "Show this list"),
]

# Examples for error messages when a flag is missing what goes after it.
FLAG_EXAMPLES = {
    "--find-studios": "--find-studios platformer games",
    "--titles": '123456789 --titles "New Title" "Another Title"',
    "--sort": "--sort popular",
    "--depth": "--depth 500",
    "--trending-depth": "--trending-depth 400",
    "--first-screen": "--first-screen 16",
    "--recent-days": "--recent-days 14",
    "--max-projects": "--max-projects 10",
    "--top": "--top 5",
    "--active-days": "--active-days 60",
    "--delay": "--delay 1",
    "--output": "--output my_results",
}

EXAMPLES = [
    "griffpatch --no-studios --max-projects 10",
    "123456789 pizza tycoon --sort popular",
    '123456789 --titles "Pizza Tycoon" "Pizza Shop Tycoon"',
    "123456789 --find-words",
    "studio 12345 --contents",
    "--find-studios platformer games",
    "--history",
]


class CheckError(Exception):
    """A problem to show the person running the check, rather than a traceback."""


class Parser(argparse.ArgumentParser):
    """Reports mistakes in a command in plain language instead of closing the program."""

    def error(self, message):
        raise CheckError(friendly_parse_error(message))


def friendly_parse_error(message):
    """Reword argparse's error messages so they say what to do."""
    match = re.match(r"argument ([^:]+): (.*)", message)
    if match:
        flag, problem = match.group(1).split("/")[-1], match.group(2)
        choice = re.match(r"invalid choice: '?(.*?)'? \(choose from (.*)\)", problem)
        if choice:
            return f"{flag} can't be \"{choice.group(1)}\". Use one of these: {choice.group(2).replace(chr(39), '')}."
        if problem.startswith("expected"):
            return f"{flag} needs something after it, like: {FLAG_EXAMPLES.get(flag, flag)}"
        return f"{flag} {problem}."
    match = re.match(r"unrecognized arguments: (.*)", message)
    if match:
        return f"There's no flag called {match.group(1)}. Type help to see the flags you can use."
    return f"{message[:1].upper()}{message[1:]}. Type help to see the commands and flags."


def make_parser():
    parser = Parser(prog=PROGRAM, add_help=False, allow_abbrev=False)
    parser.add_argument("what", nargs="*")
    for _, names, options, _ in OPTIONS:
        parser.add_argument(*names, **options)
    return parser


settings = make_parser().parse_args([])  # the current command's settings, see Session.use


def help_text():
    def row(name, text):
        return textwrap.fill(text, width=79, initial_indent=f"  {name:<22}  ", subsequent_indent=" " * 26)

    lines = [
        f"SpriteScout {VERSION}",
        "Finds out whether Scratch projects and studios show up in search, and how to",
        "rank higher. Only reads public data: it never logs in or posts anything.",
        "",
        "Commands",
        *(row(name, text) for name, text in COMMANDS),
        "",
        "In this window",
        *(row(name, text) for name, text in WINDOW_COMMANDS),
    ]
    for section in ("Extra features", "Settings"):
        lines += ["", f"{section} (add after a command)"]
        for option_section, names, options, text in OPTIONS:
            if option_section == section:
                lines.append(row(f"{', '.join(names)} {options.get('metavar', '')}".strip(), text))
    lines += ["", f"Examples (in a terminal, put {PROGRAM} first)", *(f"  {example}" for example in EXAMPLES)]
    return "\n".join(lines)


# Scratch API

request_delay = REQUEST_DELAY


def get_json(path, params=None):
    """GET a Scratch API path. Returns None for 404 and retries when Scratch is busy."""
    global request_delay
    url = API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(1, 7):
        attempts = 3  # tries before giving up; waiting out "too many requests" gets more
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = json.load(response)
            time.sleep(request_delay)
            return data
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            if error.code == 429:
                # Too many requests: wait, then keep a slower pace for the rest of the run.
                request_delay = min(request_delay * 2, 3)
                retry_after = error.headers.get("Retry-After", "")
                wait, attempts = (int(retry_after) if retry_after.isdigit() else 10 * attempt), 6
                note = "Scratch asked for fewer requests"
                problem = ("Scratch has had too many requests from this computer. Wait a few minutes, then "
                           "try again. Adding --delay 1 makes checks slower but gentler.")
            elif error.code >= 500:
                wait, note = 2 ** attempt, f"Scratch's servers had a problem (error {error.code})"
                problem = f"Scratch's servers are having trouble right now (error {error.code}). Try again in a few minutes."
            elif error.code == 400:
                raise CheckError("Scratch couldn't handle that request (error 400). Try different or shorter words.")
            else:
                raise CheckError(f"Scratch refused the request (error {error.code}). If this keeps happening, "
                                 "your network may be blocking Scratch.")
        except (TimeoutError, urllib.error.URLError) as error:
            timed_out = isinstance(error, TimeoutError) or isinstance(getattr(error, "reason", None), TimeoutError)
            wait, note = 2 ** attempt, "Couldn't reach Scratch"
            problem = ("Scratch is taking too long to answer. Try again in a minute." if timed_out else
                       "Can't reach Scratch. Check your internet connection, then try again.")
        except (OSError, ValueError):  # the connection dropped, or the answer wasn't readable data
            wait, note = 2 ** attempt, "Scratch's answer got cut off"
            problem = "Scratch sent back something unexpected. Try again in a minute."
        if attempt >= attempts:
            raise CheckError(problem)
        print(f"\r  {note}, so trying again in {wait} seconds...", flush=True)
        time.sleep(wait)


@functools.lru_cache(maxsize=512)
def search_page(kind, query, sort, offset, limit):
    """One page of search results. Cached, because checks revisit pages."""
    return tuple(get_json(f"/search/{kind}", {
        "q": query,
        "mode": sort,
        "language": "en",
        "limit": limit,
        "offset": offset,
    }) or [])


def count_matches(kind, query):
    """Count the items matching a search by binary searching for the last page."""
    last_page = MAX_DEPTH // PAGE_SIZE - 1
    if search_page(kind, query, "popular", last_page * PAGE_SIZE, PAGE_SIZE):
        return MAX_DEPTH
    if not search_page(kind, query, "popular", 0, PAGE_SIZE):
        return 0
    low, high = 0, last_page  # page `low` has results and page `high` doesn't
    while high - low > 1:
        middle = (low + high) // 2
        if search_page(kind, query, "popular", middle * PAGE_SIZE, PAGE_SIZE):
            low = middle
        else:
            high = middle
    return low * PAGE_SIZE + len(search_page(kind, query, "popular", low * PAGE_SIZE, PAGE_SIZE))


@functools.lru_cache(maxsize=None)
def get_studio(studio_id):
    """A studio with its stats, which studio search results leave out."""
    return get_json(f"/studios/{studio_id}")


@functools.lru_cache(maxsize=None)
def days_since_activity(studio_id):
    """Days since anything happened in a studio, like a project being added.

    None means no recent activity: the activity feed only goes back so far.
    """
    activity = get_json(f"/studios/{studio_id}/activity", {"limit": 1}) or []
    created = activity[0].get("datetime_created") if activity else None
    return days_ago(created) if created else None


def get_shared_projects(username):
    projects = []
    offset = 0
    while True:
        page = get_json(f"/users/{username}/projects", {"limit": PAGE_SIZE, "offset": offset}) or []
        for project in page:
            # A user's project list leaves out the author's username.
            project.setdefault("author", {})["username"] = username
        projects.extend(page)
        if len(page) < PAGE_SIZE:
            return projects
        offset += PAGE_SIZE


def get_hosted_studios(user):
    studios = []
    offset = 0
    while True:
        page = get_json(f"/users/{user['username']}/studios/curate",
                        {"limit": PAGE_SIZE, "offset": offset}) or []
        studios += [get_studio(s["id"]) or s for s in page if s.get("host") == user["id"]]
        if len(page) < PAGE_SIZE:
            return studios
        offset += PAGE_SIZE


def get_studio_projects(studio_id):
    """A studio's projects, most recently added first, without their stats or dates."""
    projects = []
    offset = 0
    while True:
        page = get_json(f"/studios/{studio_id}/projects", {"limit": PAGE_SIZE, "offset": offset}) or []
        projects += [{"id": p["id"], "title": p["title"], "author": {"username": p.get("username", "")}}
                     for p in page]
        if len(page) < PAGE_SIZE:
            return projects
        offset += PAGE_SIZE


def fill_details(kind, item):
    """Fetch a project's dates and stats if it came from a list that leaves them out."""
    if kind == "projects" and "history" not in item:
        details = get_json(f"/projects/{item['id']}") or {}
        item["history"] = details.get("history") or {}
        item["stats"] = details.get("stats") or {}


def update_note():
    """A line about a newer version being out, or "" when there isn't one.

    Looks at the releases page at most once a day, and stays quiet about any
    problem: being unable to check is never worth interrupting someone over.
    """
    if settings.no_update_check:
        return ""
    try:
        folder = output_folder(settings)
    except CheckError:
        folder = OUTPUT
    record, saved = folder / "update-check.json", {}
    try:
        saved = json.loads(record.read_text(encoding="utf-8"))
        if time.time() - saved["checked_at"] < 24 * 60 * 60:
            return newer_version_line(saved.get("version"))
    except (OSError, ValueError, KeyError):
        pass
    version = saved.get("version")
    try:
        request = urllib.request.Request(LATEST_RELEASE, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=5) as response:
            version = json.load(response).get("tag_name", "").lstrip("vV") or version
    except Exception:  # an update check is never worth an error message
        pass
    try:
        folder.mkdir(parents=True, exist_ok=True)
        record.write_text(json.dumps({"checked_at": time.time(), "version": version}), encoding="utf-8")
    except OSError:
        pass
    return newer_version_line(version)


def newer_version_line(version):
    def numbers(text):
        return [int(part) for part in re.findall(r"\d+", text or "")]

    if numbers(version) > numbers(VERSION):
        return f"SpriteScout {version} is out, and this is {VERSION}. Get it from {RELEASES}"
    return ""


def words_with_no_results(kind, text):
    """Words that find nothing when searched on their own, like "horror"."""
    words = list(dict.fromkeys(words_in(text)))[:10]
    return [word for word in words if not search_page(kind, word, "popular", 0, PAGE_SIZE)]


# Looking through search results

class Lookup:
    """Where one project or studio ranks in one search, and how far the search has got."""

    def __init__(self, kind, item, query, sort="popular", title_check=False):
        self.kind = kind                # "projects" or "studios"
        self.item = item
        self.query = query
        self.sort = sort                # "popular" or "trending"
        self.title_check = title_check  # searching the item's own title
        self.rank = None
        self.checked = 0                # results looked through
        self.ended = False              # Scratch ran out of results without it
        self.unsearchable = False
        self.silent_words = []          # title words that find nothing on their own
        self.matches = ""               # how many items match, for word checks
        self.offset = 0                 # where the current pass carries on from
        self.second_pass = False
        self.last_page_full = True

    @property
    def unfinished(self):
        """Not found, but there are more results a scan could look through."""
        return self.rank is None and not self.ended and self.checked < MAX_DEPTH


def keep_looking(lookup, depth, should_stop=None, progress=None):
    """Page through results from where the lookup left off.

    Stops once the item is found, Scratch runs out of results, `depth` results
    have been looked through, or should_stop() returns True. Returns True only
    when should_stop() stopped it.
    """
    while lookup.rank is None and not lookup.ended:
        if not lookup.second_pass:
            if lookup.offset >= MAX_DEPTH:
                return False
            # A short page is usually the last one, so after `depth` results
            # look one page further if the last page was short.
            if lookup.offset >= depth and lookup.last_page_full:
                return False
        if should_stop and should_stop():
            return True
        limit = PAGE_SIZE // 2 if lookup.second_pass and lookup.offset == 0 else PAGE_SIZE
        results = search_page(lookup.kind, lookup.query, lookup.sort, lookup.offset, limit)
        for index, result in enumerate(results):
            if result["id"] == lookup.item["id"]:
                lookup.rank = lookup.offset + index + 1
                return False
        if not results:
            if lookup.second_pass:
                lookup.ended = True
            else:
                # Items that tie in the ranking can appear on two pages while
                # others get skipped, so look again with the page breaks moved
                # before deciding it doesn't come up.
                lookup.second_pass, lookup.offset = True, 0
            continue
        if not lookup.second_pass:
            lookup.checked = lookup.offset + len(results)
        lookup.offset += limit
        lookup.last_page_full = len(results) == limit
        if progress:
            progress(lookup)
    return False


def title_status(lookup):
    """How a search for an item's own title went, like "easy" or "missing"."""
    if lookup.unsearchable:
        return "unsearchable"
    if lookup.rank:
        return "easy" if on_first(lookup) else "buried"
    if lookup.ended:
        made = item_date(lookup.kind, lookup.item)
        return "new" if made and days_ago(made) < settings.recent_days else "missing"
    return "capped" if lookup.checked >= MAX_DEPTH else "unknown"


def result_text(lookup):
    """A word search's result, like "#12" or "not in top 1,000"."""
    if lookup.rank:
        return f"#{lookup.rank:,}"
    if lookup.ended:
        return "doesn't come up"
    if lookup.checked >= MAX_DEPTH:
        return "past result 10,000"
    return f"not in top {lookup.checked:,}"


# Results log

class Log:
    """Adds results to a CSV file and remembers the last result for each search."""

    def __init__(self, path):
        self.path = path  # None when results aren't saved
        self.pending = []
        self.latest = {}
        for row in read_log(path)[0] if path else []:
            self.latest[(row["type"], row["id"], row["search"].lower(), row["sort"])] = row

    def add(self, kind, item, search, sort, result, rank, matches=""):
        """Record a result and describe how it changed since the last check."""
        stats = item.get("stats") or {}
        row = {
            "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "type": NOUNS[kind],
            "id": str(item["id"]),
            "title": tidy(item["title"]),
            "search": search,
            "sort": SORTS[sort],
            "result": result,
            "rank": rank or "",
            "loves": stats.get("loves", ""),
            "favorites": stats.get("favorites", ""),
            "views": stats.get("views", ""),
            "followers": stats.get("followers", ""),
            "matches": matches,
        }
        key = (row["type"], row["id"], search.lower(), row["sort"])
        change = describe_change(self.latest.get(key), rank, result)
        self.latest[key] = row
        self.pending.append(row)
        return change

    def save(self):
        """Write the results waiting to be saved. Returns a message when they couldn't be."""
        if not self.path:
            self.pending.clear()
            return ""
        if not self.pending:
            return ""
        temp = self.path.with_name(self.path.name + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            rows, outdated = read_log(self.path)
            if outdated:
                # Logs from older versions have different columns, so rewrite
                # the whole file in the current layout, keeping every row.
                with open(temp, "w", newline="", encoding="utf-8-sig") as file:
                    writer = csv.DictWriter(file, fieldnames=LOG_FIELDS)
                    writer.writeheader()
                    writer.writerows(rows + self.pending)
                os.replace(temp, self.path)
            else:
                is_new = not self.path.exists() or self.path.stat().st_size == 0
                with open(self.path, "a", newline="", encoding="utf-8-sig") as file:
                    writer = csv.DictWriter(file, fieldnames=LOG_FIELDS)
                    if is_new:
                        writer.writeheader()
                    writer.writerows(self.pending)
            self.pending.clear()
        except OSError as error:
            if temp.exists():
                temp.unlink()
            return (f"Couldn't save results to {self.path} ({error.strerror or error}). "
                    "If it's open in Excel, close it and they'll be saved after the next check.")
        return ""


def read_log(path):
    """Return the log's rows in the current layout, and whether the file uses an older one."""
    try:
        with open(path, newline="", encoding="utf-8-sig") as file:
            reader = csv.DictReader(file)
            rows = list(reader)
    except (OSError, csv.Error):
        return [], False
    outdated = bool(reader.fieldnames) and reader.fieldnames != LOG_FIELDS
    upgraded = []
    for row in rows:
        if "project_id" in row:  # logs from before studios could be checked
            row = dict(row, type="project", id=row["project_id"])
        upgraded.append({field: row.get(field) or "" for field in LOG_FIELDS})
    return upgraded, outdated


def describe_change(previous, rank, result):
    """How a result moved since it was last logged, like "up 3 since 2026-09-10"."""
    if not previous:
        return ""
    date = previous["checked_at"][:10]
    old_rank = int(previous["rank"]) if str(previous["rank"]).isdigit() else None
    if rank and old_rank and rank != old_rank:
        direction = "up" if rank < old_rank else "down"
        return f"{direction} {abs(old_rank - rank):,} since {date}"
    if previous["result"] != result:
        return f"was {previous['result']} on {date}"
    return f"no change since {date}"


# Checking items by their own titles

def search_title(session, lookup, depth):
    """Search for an item's own title, log the result, and return (status, change)."""
    if re.search(r"\w", lookup.item["title"]):
        keep_looking(lookup, depth)
    else:
        lookup.unsearchable = lookup.ended = True
    return record_title(session, lookup)


def record_title(session, lookup):
    if lookup.ended:
        fill_details(lookup.kind, lookup.item)  # the share date decides "new" or "missing"
    status = title_status(lookup)
    if status == "missing" and lookup.checked == 0:
        lookup.silent_words = words_with_no_results(lookup.kind, lookup.query)
    change = session.log.add(lookup.kind, lookup.item, lookup.query, lookup.sort,
                             label(status, lookup), lookup.rank)
    return status, change


def title_advice(status, kinds, checked=0):
    """Advice for a title search's status, for items of the given kinds."""
    kinds = sorted(kinds)
    text = ADVICE[status].format(
        first=settings.first_screen,
        recent=settings.recent_days,
        checked=checked,
        noun=" or ".join(NOUNS[kind] for kind in kinds),
        nouns=" and ".join(NOUNS[kind] + "s" for kind in kinds),
        made="shared" if kinds == ["projects"] else "created" if kinds == ["studios"] else "shared or created",
    )
    if status == "missing":
        text += (NOT_FOR_EVERYONE if "projects" in kinds else "") + CONTACT
    return text


def print_title_advice(session, status, lookup, indent="  ", with_advice=True):
    advice = title_advice(status, {lookup.kind}, lookup.checked)
    if lookup.silent_words:
        # A blocked word explains a title that finds nothing better than the
        # usual guesses, so lead with it.
        note = silent_note(lookup.silent_words) + " Then nobody can find this title by searching it."
        others = [word for word in re.findall(r"\w+", lookup.query) if word.lower() not in lookup.silent_words]
        if others:
            note += " To see where it ranks for the rest of its title, check:"
        print_with_command(note, session.item_command(lookup, others) if others else None, indent)
        if not with_advice:
            return
        print()
        advice = "If that's not the reason: " + advice
    print(wrap(advice, indent))


def silent_note(words):
    """Explain words that find nothing when searched on their own.

    Both made-up words and words Scratch blocks from search (like "horror")
    find nothing, and there's no way to tell them apart from outside, so this
    gives the person the rule to tell for themselves.
    """
    one = len(words) == 1
    examples = [word for word in ("horror", "fnaf", "scary") if word not in words][:2]
    return (f"Searching {quoted(words)} on {'its' if one else 'their'} own finds nothing. If "
            f"{'that is a common word' if one else 'those are common words'}, Scratch probably blocks "
            f"{'it' if one else 'them'} from search, like it does {quoted(examples)}.")


def print_with_command(text, command, indent="  "):
    """Print wrapped text, with a follow-up command on its own line so it's easy to copy."""
    print(wrap(text, indent))
    if command:
        print(f"{indent}    {command}")


def check_single(session, kind, item, depth):
    print(f"\nChecking {describe(kind, item)}, looking through up to {depth:,} search results.")
    lookup = Lookup(kind, item, tidy(item["title"]), title_sort(), title_check=True)
    status, change = search_title(session, lookup, depth)
    if lookup.unfinished:
        session.unfinished.append(lookup)
    where = f" at #{lookup.rank:,}" if lookup.rank else ""
    print(f"\n  {label(status, lookup)}{where}" + (f"  ({change})" if change else ""))
    print(f"  {item_url(kind, item)}\n")
    print_title_advice(session, status, lookup)


def check_user(session, user, depth):
    username = user["username"]
    projects = sorted(get_shared_projects(username), key=shared_date, reverse=True)
    projects = projects[: settings.max_projects or None]
    studios = [] if settings.no_studios else get_hosted_studios(user)
    items = [("projects", project) for project in projects] + [("studios", studio) for studio in studios]
    if not items:
        print(f"\n{username} has no shared projects or hosted studios, so there's nothing to find in search.")
        return
    heading = plural(len(projects), "shared project")
    if not settings.no_studios:
        heading += f" and {plural(len(studios), 'hosted studio')}"
    check_many(session, f"{heading} by {username}", username, items, depth)


def check_contents(session, studio, depth):
    name = f"the studio \"{short_title(studio['title'], 60)}\""
    projects = get_studio_projects(studio["id"])[: settings.max_projects or None]
    if not projects:
        print(f"\nThere are no projects in {name}.")
        return
    check_many(session, f"{plural(len(projects), 'project')} in {name}", name,
               [("projects", project) for project in projects], depth)


def check_many(session, heading, owner, items, depth):
    """Check several projects and studios by their titles, then sum up."""
    print(f"\nChecking {heading}, looking through up to {depth:,} search results each.\n")
    checked = []
    for number, (kind, item) in enumerate(items, 1):
        lookup = Lookup(kind, item, tidy(item["title"]), title_sort(), title_check=True)
        status, change = search_title(session, lookup, depth)
        if lookup.unfinished:
            session.unfinished.append(lookup)
        checked.append((lookup, status))
        name = ("Studio: " if kind == "studios" else "") + short_title(item["title"])
        note = f"  ({change})" if change and not change.startswith("no change") else ""
        print(f"  [{number:>{len(str(len(items)))}}/{len(items)}] {label(status, lookup):<20} "
              f"{rank_label(lookup):<7} {name}{note}")

    print(f"\nSummary for {owner}")
    for status in LABELS:
        group = [lookup for lookup, s in checked if s == status]
        if group:
            print(f"  {label(status, group[0]):<20} {len(group)}")

    for status in ("missing", "new", "unknown", "capped", "buried", "unsearchable"):
        group = [lookup for lookup, s in checked if s == status]
        if not group:
            continue
        print(f"\n{label(status, group[0])}")
        print(wrap(title_advice(status, {lookup.kind for lookup in group}, group[0].checked)))
        for lookup in group:
            rank = f"{rank_label(lookup):<7}" if lookup.rank else ""
            print(f"    {rank}{short_title(lookup.item['title'])}  {item_url(lookup.kind, lookup.item)}")
            if lookup.silent_words:
                # The group's advice is printed above, so just explain the blocked word.
                print_title_advice(session, status, lookup, indent="      ", with_advice=False)


# Checking where an item ranks for search words

def check_words(session, kind, item, query, depth):
    noun = NOUNS[kind]
    sorts = list(SORTS) if settings.sort == "both" else [settings.sort]
    depths = {"popular": depth, "trending": min(depth, settings.trending_depth)}
    print(f"\nChecking {describe(kind, item)} when someone searches \"{query}\".")
    print("Looking through up to " + " and ".join(f"{depths[sort]:,} results in {SORTS[sort]}" for sort in sorts)
          + ", so this can take a minute.")

    matches = count_matches(kind, query)
    print(f"\n  {matching(matches, noun)} \"{query}\".")

    lookups = {}
    for sort in sorts:
        lookup = Lookup(kind, item, query, sort)
        lookup.matches = format_count(matches).replace(",", "")
        keep_looking(lookup, depths[sort])
        lookups[sort] = lookup
        if lookup.unfinished:
            session.unfinished.append(lookup)
        change = session.log.add(kind, item, query, sort, result_text(lookup), lookup.rank, lookup.matches)
        heading = "Popular, the default sort" if sort == "popular" else "Trending"
        first = ", on the first screen" if on_first(lookup) else ""
        print(f"\n  {heading}: {result_text(lookup)}{first}" + (f" ({change})" if change else ""))
        print(f"    First screen: {describe_first_screen(kind, query, sort)}")

    print(f"\n  This {noun}: {describe_item(kind, item)}")
    if settings.no_tips:
        return
    tips = rank_tips(session, kind, item, query, lookups, matches)
    if not tips:
        print("\n  It's on the first screen for this search. Nothing to fix.")
        return
    print("\n  Ways to rank higher")
    for tip, command in tips:
        print(textwrap.fill(tip, width=78, initial_indent="  - ", subsequent_indent="    "))
        if command:
            print(f"      {command}")


def rank_tips(session, kind, item, query, lookups, matches):
    """Suggestions for ranking higher in a search, based on what ranks well right now.

    They come from patterns in Scratch's search results: results almost always
    have every search word in their title; in Popular, short titles that match
    often beat items with far more loves or followers; Trending's first screen
    is nearly all recently shared projects, or studios with recent activity;
    and some words, like "horror", find nothing at all. Each tip is
    (text, follow-up command or None).
    """
    if all(on_first(lookup) for lookup in lookups.values()):
        return []
    noun, nouns = NOUNS[kind], NOUNS[kind] + "s"
    title = item["title"]

    if matches == 0:
        silent = words_with_no_results(kind, query)
        if silent:
            made_up = (f"If it's made up instead, no shared {noun} uses it yet." if len(silent) == 1 else
                       f"If they're made up instead, no shared {noun} uses them yet.")
            return [(f"{silent_note(silent)} {made_up} Either way, try other words players might search.", None)]

    tips = []
    missing = [word for word in words_in(query) if not has_word(words_in(title), word)]
    any_lookup = next(iter(lookups.values()))  # every sort has the same matching items
    if missing:
        tips.append(f"Put {quoted(missing)} in the title. {nouns.capitalize()} almost never come up "
                    "for a search unless every word is in their title.")
    elif any_lookup.rank is None and any_lookup.ended:
        # Ranking tips can't help something that isn't in the results at all.
        return [(f"The title has every word, but the {noun} doesn't come up at all, so it may be "
                 "missing from search. To find out, check:", session.item_command(any_lookup))]

    popular = lookups.get("popular")
    first_popular = first_screen(kind, query, "popular") if popular else []
    if first_popular and not on_first(popular):
        typical = round(statistics.median(word_count(other["title"]) for other in first_popular))
        length = word_count(title)
        extras = [part for part in title_extras(title) if not set(words_in(part)) & set(words_in(query))]
        if length > typical and (extras or length - typical >= 2):
            tip = (f"Keep the title short. In Popular, a short title that matches the search often "
                   f"beats {nouns} with far more {'loves' if kind == 'projects' else 'followers'}. "
                   f"This one has {length} words, and titles on the first screen have about {typical}.")
            if extras:
                tip += f" {quoted(extras)} could go in the {'Notes' if kind == 'projects' else 'description'} instead."
            tips.append(tip)
        stat = "loves" if kind == "projects" else "followers"
        least = min(stat_of(kind, other) for other in first_popular)
        if stat_of(kind, item) < least:
            tips.append(f"Get more {stat}. The {noun} with the fewest {stat} on Popular's first screen "
                        f"has {least:,}, and this one has {stat_of(kind, item):,}.")

    trending = lookups.get("trending")
    first_trending = first_screen(kind, query, "trending") if trending else []
    if first_trending and not on_first(trending):
        if kind == "projects":
            oldest = min(shared_date(p) for p in first_trending)
            least = min(loves_of(p) for p in first_trending)
            if shared_date(item) < oldest:
                tips.append(f"Trending's first screen only has projects shared since {oldest}, and this "
                            f"one was shared {shared_date(item)}. A new project, like a sequel, has a much "
                            "better shot there.")
            elif loves_of(item) < least:
                tips.append(f"This project is new enough for Trending's first screen, where the "
                            f"least-loved project has {plural(least, 'love')}. Loves soon after sharing count "
                            "most there, so post it in the Show and Tell forum and add it to game studios.")
        else:
            recent = [days_since_activity(s["id"]) for s in first_trending]
            mine = days_since_activity(item["id"])
            if None not in recent and (mine is None or mine > max(recent)):
                latest = "this one hasn't had any recently" if mine is None else f"this one's latest was {ago(mine)}"
                tips.append(f"Every studio on Trending's first screen had activity, like a project being "
                            f"added, in the last {within_days(max(recent))}, and {latest}. Adding "
                            "projects often keeps a studio active.")

    if matches > CROWDED and not any(on_first(lookup) for lookup in lookups.values()):
        tips.append(f"{format_count(matches)} {nouns} match \"{query}\". A more specific search that "
                    "still fits, like one with an extra word from the title, has less competition.")
    return [tip if isinstance(tip, tuple) else (tip, None) for tip in tips]


def first_screen(kind, query, sort):
    return search_page(kind, query, sort, 0, PAGE_SIZE)[: settings.first_screen]


def describe_first_screen(kind, query, sort):
    items = first_screen(kind, query, sort)
    if not items:
        return f"no {NOUNS[kind]}s"
    words = span([word_count(i["title"]) for i in items])
    if kind == "projects":
        return (f"{units([loves_of(p) for p in items], 'love')}, {words} word titles, "
                f"shared since {min(shared_date(p) for p in items)}")
    if sort == "popular":
        return f"{units([followers_of(s) for s in items], 'follower')}, {words} word titles"
    recent = [days_since_activity(s["id"]) for s in items]
    active = "" if None in recent else f", all active in the last {within_days(max(recent))}"
    return f"{words} word titles{active}"


def describe_item(kind, item):
    length = word_count(item["title"])
    if kind == "projects":
        return f"{plural(loves_of(item), 'love')}, {length}-word title, shared {shared_date(item)}"
    days = days_since_activity(item["id"])
    activity = "no recent activity" if days is None else f"last activity {ago(days)}"
    return f"{plural(followers_of(item), 'follower')}, {length}-word title, {activity}"


def title_extras(title):
    """Hashtags, version numbers and bracketed notes: parts of a title that could go elsewhere."""
    patterns = (r"#\w+", r"\bv\d+(?:\.\d+)*\b", r"\[[^\]]*\]", r"\([^)]*\)")
    found = [match for pattern in patterns for match in re.findall(pattern, title, re.IGNORECASE)]
    return list(dict.fromkeys(found))


def has_word(words, word):
    """True if the word, or its singular or plural, is in the list."""
    return word in words or word + "s" in words or (word.endswith("s") and word[:-1] in words)


# Extra features, each turned on with its own flag

def open_studios(words, progress=None, should_stop=None):
    """Active studios about some words that anyone can add projects to, most followed first.

    Checking how active each one is takes a request each, so `progress` is called
    with (done, total) along the way, and should_stop() can call it off. Returns
    (studios, note), where the note explains an empty list.
    """
    query = " ".join(words)
    topic = [word for word in words_in(query) if word not in STOP_WORDS]
    candidates = {}
    for sort in ("trending", "popular"):
        for offset in (0, PAGE_SIZE):
            for studio in search_page("studios", query, sort, offset, PAGE_SIZE):
                # Studios can match on their description alone, so also want a search word in the title.
                about = not topic or any(has_word(words_in(studio["title"]), word) for word in topic)
                if studio.get("open_to_all") and about:
                    candidates.setdefault(studio["id"], studio)
    if not candidates and not search_page("studios", query, "popular", 0, PAGE_SIZE):
        silent = words_with_no_results("studios", query)
        return [], (f"No studios come up for \"{query}\" at all. "
                    + (silent_note(silent) + " " if silent else "") + "Try other words.")
    wanted = list(candidates.values())[: max(settings.top, 1) * 3]
    active = []
    for done, studio in enumerate(wanted, 1):
        if should_stop and should_stop():
            break
        if progress:
            progress(done, len(wanted))
        if (days_since_activity(studio["id"]) or float("inf")) <= settings.active_days:
            active.append(studio)
    if not active:
        return [], "None found. Try other words, or allow older activity with --active-days."
    active.sort(key=followers_of, reverse=True)
    return active[: max(settings.top, 1)], ""


def find_studios(words):
    """--find-studios: active studios about some words that anyone can add projects to."""
    query = " ".join(words)
    print(f"\nLooking for active studios about \"{query}\" that anyone can add projects to.")
    studios, note = open_studios(words, progress=show_studio_progress)
    end_progress()
    if note:
        print()
        print(wrap(note))
        return
    print("\n  Most followed first:\n")
    for number, studio in enumerate(studios, 1):
        print(f"  {number:>2}. {short_title(studio['title'], 50)}  "
              f"({plural(followers_of(studio), 'follower')}, active {ago(days_since_activity(studio['id']))})")
        print(f"      {item_url('studios', studio)}")
    print("\n  Only add projects that fit a studio's topic.")


def title_verdict(kind, item, title):
    """What a possible title would be up against in search."""
    noun, stat = NOUNS[kind], "loves" if kind == "projects" else "followers"
    current = tidy(item["title"])
    if not re.search(r"\w", title):
        return "Has no letters or numbers, so nobody could find it by searching."
    matches = count_matches(kind, title)
    if matches == 0:
        silent = words_with_no_results(kind, title)
        if silent and title == current:
            return (f"Finds nothing, not even this {noun}. " + silent_note(silent)
                    + f" If not, this {noun} isn't in search right now.")
        if silent:
            return (f"No {noun}s match yet, so it would be the only result, unless Scratch blocks one of "
                    "its words. " + silent_note(silent))
        if title == current:
            return f"Finds nothing, not even this {noun}, so it isn't in search right now."
        return f"No {noun}s match yet, so it would be the only result."
    first = first_screen(kind, title, title_sort())
    stats = [stat_of(kind, other) for other in first]
    typical = round(statistics.median(word_count(other["title"]) for other in first))
    text = (f"{matching(matches, noun)}. First screen: {units(stats, stat[:-1])}, "
            f"titles of about {typical} words.")
    if matches <= settings.first_screen or stat_of(kind, item) >= min(stats):
        text += " Likely on the first screen."
    else:
        text += f" Unlikely on the first screen, where the lowest has {plural(min(stats), stat[:-1])}."
    if word_count(title) > typical + 1:
        text += " Shorter titles tend to rank higher."
    return text


def possible_titles(item, titles):
    """The current title first, then the ones being tried, without repeats or blanks."""
    return list(dict.fromkeys([tidy(item["title"])] + [tidy(title) for title in titles if tidy(title)]))


def test_titles(kind, item, titles):
    """--titles: how crowded each possible title is, and whether the item could make the first screen."""
    stat = "loves" if kind == "projects" else "followers"
    current = tidy(item["title"])
    print(f"\nTesting titles for {describe(kind, item)}, which has {plural(stat_of(kind, item), stat[:-1])}.")
    for title in possible_titles(item, titles):
        print(f"\n  \"{title}\"" + ("  (current title)" if title == current else ""))
        print(wrap(title_verdict(kind, item, title), "    "))
    print("\n  After renaming, check again in a few days. Search can take a while to catch up.")


def search_ideas(kind, item, extra_words):
    """Searches worth trying for an item, or an explanation when there are none."""
    ideas = search_word_ideas(item["title"], extra_words)
    if not ideas:
        raise CheckError(f"The title of {describe(kind, item)} has no words to search for. "
                         "Add some words after it to try those instead.")
    return ideas


def word_rankings(session, kind, item, extra_words, depth, sort, should_stop=None):
    """Try a title's words as searches; returns (the ones it comes up for, the ones it doesn't).

    A search that should_stop() cut short is left out of both lists, because
    nobody knows yet whether it comes up.
    """
    ideas = search_ideas(kind, item, extra_words)
    ranked, unranked = [], []
    for query in ideas:
        lookup = Lookup(kind, item, query, sort)
        if keep_looking(lookup, depth, should_stop=should_stop):
            break
        session.log.add(kind, item, query, sort, result_text(lookup), lookup.rank)
        (ranked if lookup.rank else unranked).append(lookup)
    return sorted(ranked, key=lambda lookup: lookup.rank), unranked


def find_words(session, kind, item, extra_words, depth):
    """--find-words: try the words in a title and list the searches the item comes up for."""
    sort = title_sort()
    ideas = search_ideas(kind, item, extra_words)
    print(f"\nTrying {plural(len(ideas), 'search', 'searches')} for {describe(kind, item)} in "
          f"{SORTS[sort]}, looking through up to {depth:,} results each.")
    ranked, unranked = word_rankings(session, kind, item, extra_words, depth, sort)
    if not ranked:
        print(f"\n  It isn't in the top {depth:,} for any of them.")
        return
    print("\n  Searches it comes up for, best first:")
    for lookup in sorted(ranked, key=lambda lookup: lookup.rank)[: max(settings.top, 1)]:
        screen = "  (first screen)" if on_first(lookup) else ""
        print(f"    {rank_label(lookup):<8}{lookup.query}{screen}")
    if unranked:
        print()
        print(wrap(f"Not in the top {depth:,}: " + ", ".join(f"\"{lookup.query}\"" for lookup in unranked)))


def search_word_ideas(title, extra_words=()):
    """Searches worth trying: the whole title, its words, and pairs of neighbouring words."""
    words = [word for word in re.findall(r"[^\W_]+", title.lower())
             if len(word) > 1 and not word.isdigit() and not re.fullmatch(r"v\d+", word)
             and word not in STOP_WORDS]
    ideas = [tidy(title).lower(), *words, *(f"{a} {b}" for a, b in zip(words, words[1:]))]
    if extra_words:
        ideas.insert(1, " ".join(extra_words).lower())
    return list(dict.fromkeys(idea for idea in ideas if re.search(r"\w", idea)))[:15]


def make_history():
    """--history: turn the log into a page of rank-over-time charts, and open it."""
    folder = output_folder(settings)
    log_path = folder / "search_log.csv"
    rows = [row for row in read_log(log_path)[0] if row["id"].isdigit()]
    if not rows:
        raise CheckError(f"There are no saved results in {log_path} yet, so there's no history to show. "
                         "Check something first (without --no-log).")
    page = folder / "search_history.html"
    try:
        page.write_text(HISTORY_PAGE.replace("__DATA__", history_json(rows, log_path.name)), encoding="utf-8")
    except OSError as error:
        raise CheckError(f"Couldn't save {page} ({error.strerror or error}). "
                         "If it's open somewhere, close it and try again.") from None
    opened = webbrowser.open(page.resolve().as_uri())
    print(f"\nMade a history page from {plural(len(rows), 'saved result')}"
          f"{' and opened it' if opened else ''}:\n  {page}")


def output_folder(args):
    """The folder for results: --output, or the output folder next to this program."""
    if args.output:
        if args.output.exists() and not args.output.is_dir():
            raise CheckError(f"--output needs a folder, but {args.output} is a file.")
        return args.output
    # Older versions saved results next to the program, so move them in.
    for name in ("search_log.csv", "search_history.html"):
        old, new = HERE / name, OUTPUT / name
        if old.exists() and not new.exists():
            try:
                OUTPUT.mkdir(exist_ok=True)
                old.replace(new)
            except OSError:
                if name == "search_log.csv":
                    return HERE  # couldn't move it (open in Excel?), so keep using it where it is
    return OUTPUT


def history_json(rows, source):
    """The log grouped by project or studio, then by search, for the history page."""
    items = {}
    for row in rows:
        item = items.setdefault((row["type"], row["id"]), {"type": row["type"], "id": row["id"], "searches": {}})
        item["title"], item["last"] = row["title"], row["checked_at"]
        search = item["searches"].setdefault(row["search"].lower(), {"search": row["search"], "points": []})
        search["points"].append({
            "time": row["checked_at"],
            "sort": row["sort"],
            "rank": int(row["rank"]) if row["rank"].isdigit() else None,
            "result": row["result"],
        })
    ordered = sorted(items.values(), key=lambda item: item["last"], reverse=True)
    for item in ordered:
        item["searches"] = list(item["searches"].values())
    # Escape "</" so a title can't end the page's <script> block early.
    return json.dumps({"source": source, "items": ordered}).replace("</", "<\\/")


HISTORY_PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Search History</title>
<style>
  :root {
    color-scheme: light;
    --page: #f9f9f7; --surface: #fcfcfb; --ink: #0b0b0b; --ink-2: #52514e; --muted: #898781;
    --grid: #e1e0d9; --axis: #c3c2b7; --border: rgba(11, 11, 11, 0.10);
    --popular: #2a78d6; --trending: #eb6834;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      color-scheme: dark;
      --page: #0d0d0d; --surface: #1a1a19; --ink: #ffffff; --ink-2: #c3c2b7; --muted: #898781;
      --grid: #2c2c2a; --axis: #383835; --border: rgba(255, 255, 255, 0.10);
      --popular: #3987e5; --trending: #d95926;
    }
  }
  body { margin: 0; background: var(--page); color: var(--ink);
         font: 15px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
  main { max-width: 760px; margin: 0 auto; padding: 24px 16px 48px; }
  h1 { font-size: 24px; margin: 0 0 4px; }
  .note { color: var(--ink-2); margin: 0; }
  .item { background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
          padding: 16px; margin-top: 16px; }
  .item > header { display: flex; gap: 12px; align-items: center; }
  .item img { width: 80px; height: 60px; object-fit: cover; border-radius: 6px; background: var(--grid); flex: none; }
  .item a { color: var(--ink); font-weight: 600; overflow-wrap: anywhere; }
  .kind { color: var(--muted); font-size: 13px; }
  .search { border-top: 1px solid var(--grid); margin-top: 14px; padding-top: 12px; }
  .search h2 { font-size: 15px; margin: 0; overflow-wrap: anywhere; }
  .latest { color: var(--ink-2); margin: 2px 0 8px; }
  .legend { display: flex; gap: 16px; color: var(--ink-2); font-size: 13px; }
  .key { display: inline-block; width: 14px; height: 2px; border-radius: 1px; vertical-align: middle; margin-right: 6px; }
  .chart { position: relative; }
  .chart svg { display: block; width: 100%; height: auto; overflow: visible; }
  .chart svg:focus-visible { outline: 2px solid var(--popular); outline-offset: 2px; border-radius: 4px; }
  .tick { fill: var(--muted); font-size: 11px; font-variant-numeric: tabular-nums; }
  .end { fill: var(--ink-2); font-size: 12px; }
  .tip { position: absolute; top: 0; pointer-events: none; background: var(--surface); color: var(--ink);
         border: 1px solid var(--border); border-radius: 8px; padding: 6px 10px; font-size: 13px;
         box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12); white-space: nowrap; }
  .tip b { font-weight: 600; margin-right: 6px; }
  .tip .when { color: var(--muted); font-size: 12px; }
  details { margin-top: 6px; color: var(--ink-2); font-size: 13px; }
  table { border-collapse: collapse; margin-top: 6px; }
  td, th { text-align: left; padding: 2px 16px 2px 0; font-variant-numeric: tabular-nums; }
  th { color: var(--muted); font-weight: 500; }
</style>
</head>
<body>
<main>
  <h1>Search history</h1>
  <p class="note" id="summary"></p>
</main>
<script id="data" type="application/json">__DATA__</script>
<script>
const data = JSON.parse(document.getElementById("data").textContent);
const main = document.querySelector("main");
const SVG = "http://www.w3.org/2000/svg";

function el(tag, attributes, text) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attributes || {})) node.setAttribute(name, value);
  if (text !== undefined) node.textContent = text;
  return node;
}
function shape(tag, attributes) {
  const node = document.createElementNS(SVG, tag);
  for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
  return node;
}
const when = text => new Date(text.replace(" ", "T")).getTime();
const color = sort => `var(--${sort.toLowerCase()})`;
const shown = point => point.rank && !point.result.startsWith("#")
  ? `#${point.rank.toLocaleString()} (${point.result})` : point.result;

document.getElementById("summary").textContent =
  `Every saved result from ${data.source}, most recently checked first. Higher on a chart means a better rank.`;

const charts = [];
for (const item of data.items) {
  const folder = item.type === "studio" ? "studios" : "projects";
  const thumbnail = item.type === "studio"
    ? `https://uploads.scratch.mit.edu/get_image/gallery/${item.id}_170x100.png`
    : `https://uploads.scratch.mit.edu/get_image/project/${item.id}_100x80.png`;
  const card = el("section", {class: "item"});
  const header = el("header");
  const name = el("div");
  name.append(el("a", {href: `https://scratch.mit.edu/${folder}/${item.id}/`}, item.title),
              el("div", {class: "kind"}, item.type === "studio" ? "Studio" : "Project"));
  header.append(el("img", {src: thumbnail, alt: "", loading: "lazy"}), name);
  card.append(header);
  for (const search of item.searches) card.append(searchSection(item, search));
  main.append(card);
}
// Charts are drawn at their real width so the text stays readable, and redrawn when that changes.
const drawCharts = () => charts.forEach(drawChart);
drawCharts();
let resizing;
window.addEventListener("resize", () => {
  clearTimeout(resizing);
  resizing = setTimeout(drawCharts, 150);
});

function searchSection(item, search) {
  const box = el("div", {class: "search"});
  const series = ["Popular", "Trending"]
    .map(sort => ({sort, points: search.points.filter(point => point.sort === sort)}))
    .filter(line => line.points.length);
  const what = search.search.toLowerCase() === item.title.toLowerCase() ? "Searching its title" : `Searching "${search.search}"`;
  box.append(el("h2", {}, what + (series.length === 1 ? ` · ${series[0].sort}` : "")));
  const last = search.points[search.points.length - 1];
  const latest = series.map(line => (series.length > 1 ? `${line.sort} ` : "") + shown(line.points[line.points.length - 1]));
  box.append(el("p", {class: "latest"}, `Latest, ${last.time.slice(0, 10)}: ${latest.join(", ")}`));
  const times = [...new Set(search.points.map(point => point.time))].sort();
  if (times.length > 1 && search.points.some(point => point.rank)) {
    if (series.length > 1) {
      const legend = el("div", {class: "legend"});
      for (const line of series) {
        const entry = el("span");
        entry.append(el("span", {class: "key", style: `background: ${color(line.sort)}`}), document.createTextNode(line.sort));
        legend.append(entry);
      }
      box.append(legend);
    }
    const holder = el("div", {class: "chart"});
    charts.push({holder, series, times});
    box.append(holder);
  }
  box.append(table(search.points));
  return box;
}

function drawChart({holder, series, times}) {
  const W = Math.max(260, holder.clientWidth), H = 170, left = 48, right = 56, top = 10, bottom = 26;
  const t0 = when(times[0]), t1 = when(times[times.length - 1]);
  const worst = Math.max(...series.flatMap(line => line.points.map(point => point.rank || 0)));
  const floor = [16, 50, 100, 200, 500, 1000, 2000, 5000, 10000].find(n => n >= worst) || worst;
  const x = time => left + (when(time) - t0) / (t1 - t0) * (W - left - right);
  const y = rank => top + (rank - 1) / (floor - 1) * (H - top - bottom);
  const svg = shape("svg", {viewBox: `0 0 ${W} ${H}`, tabindex: "0", role: "img",
    "aria-label": "Rank over time. Use the left and right arrow keys to read each check."});

  for (const rank of [1, Math.round(floor / 2), floor]) {
    svg.append(shape("line", {x1: left, x2: W - right, y1: y(rank), y2: y(rank), stroke: "var(--grid)", "stroke-width": 1}));
    const tick = shape("text", {x: left - 8, y: y(rank) + 4, "text-anchor": "end", class: "tick"});
    tick.textContent = `#${rank.toLocaleString()}`;
    svg.append(tick);
  }
  const sameDay = times[0].slice(0, 10) === times[times.length - 1].slice(0, 10);
  for (const [time, anchor] of [[times[0], "start"], [times[times.length - 1], "end"]]) {
    const tick = shape("text", {x: x(time), y: H - 6, "text-anchor": anchor, class: "tick"});
    tick.textContent = sameDay ? time.slice(11) : time.slice(0, 10);
    svg.append(tick);
  }

  const ends = [];
  for (const line of series) {
    const dot = point => svg.append(shape("circle", {cx: x(point.time), cy: y(point.rank), r: 4,
      fill: color(line.sort), stroke: "var(--surface)", "stroke-width": 2}));
    let run = [];
    const draw = () => {
      if (run.length > 1) {
        svg.append(shape("polyline", {points: run.map(point => `${x(point.time)},${y(point.rank)}`).join(" "),
          fill: "none", stroke: color(line.sort), "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round"}));
      } else if (run.length === 1) {
        dot(run[0]);
      }
      run = [];
    };
    for (const point of line.points) point.rank ? run.push(point) : draw();
    draw();
    const lastRanked = [...line.points].reverse().find(point => point.rank);
    if (lastRanked) {
      dot(lastRanked);
      ends.push(lastRanked);
    }
  }
  // Label line ends, unless two labels would sit on top of each other.
  if (ends.length < 2 || Math.abs(y(ends[0].rank) - y(ends[1].rank)) >= 14) {
    for (const point of ends) {
      const label = shape("text", {x: x(point.time) + 8, y: y(point.rank) + 4, class: "end"});
      label.textContent = `#${point.rank.toLocaleString()}`;
      svg.append(label);
    }
  }

  const tip = el("div", {class: "tip"});
  tip.hidden = true;
  const cross = shape("line", {y1: top, y2: H - bottom, stroke: "var(--axis)", "stroke-width": 1, visibility: "hidden"});
  svg.append(cross);
  let current = times.length - 1;
  const show = index => {
    const time = times[index];
    cross.setAttribute("x1", x(time));
    cross.setAttribute("x2", x(time));
    cross.setAttribute("visibility", "visible");
    tip.replaceChildren(el("div", {class: "when"}, time));
    for (const line of series) {
      const point = line.points.find(p => p.time === time);
      if (!point) continue;
      const row = el("div");
      row.append(el("span", {class: "key", style: `background: ${color(line.sort)}`}), el("b", {}, shown(point)),
                 document.createTextNode(line.sort));
      tip.append(row);
    }
    tip.hidden = false;
    const box = svg.getBoundingClientRect();
    const px = x(time) / W * box.width;
    tip.style.left = `${Math.max(0, Math.min(px + 12, box.width - tip.offsetWidth))}px`;
  };
  const hide = () => {
    tip.hidden = true;
    cross.setAttribute("visibility", "hidden");
  };
  svg.addEventListener("pointermove", event => {
    const box = svg.getBoundingClientRect();
    const px = (event.clientX - box.left) / box.width * W;
    current = times.reduce((best, time, index) => Math.abs(x(time) - px) < Math.abs(x(times[best]) - px) ? index : best, 0);
    show(current);
  });
  svg.addEventListener("pointerleave", hide);
  svg.addEventListener("focus", () => show(current));
  svg.addEventListener("blur", hide);
  svg.addEventListener("keydown", event => {
    if (event.key === "ArrowLeft") current = Math.max(0, current - 1);
    else if (event.key === "ArrowRight") current = Math.min(times.length - 1, current + 1);
    else return;
    event.preventDefault();
    show(current);
  });
  holder.replaceChildren(svg, tip);
}

function table(points) {
  const details = el("details");
  details.append(el("summary", {}, "Table"));
  const grid = el("table");
  const head = el("tr");
  for (const name of ["Checked", "Sort", "Result"]) head.append(el("th", {}, name));
  grid.append(head);
  for (const point of [...points].reverse()) {
    const row = el("tr");
    for (const value of [point.time, point.sort, shown(point)]) row.append(el("td", {}, value));
    grid.append(row);
  }
  details.append(grid);
  return details;
}
</script>
</body>
</html>
"""


# Scanning for what a check didn't find

class Session:
    """The settings in use, the log, and what the last check didn't find."""

    def __init__(self, interactive):
        self.interactive = interactive
        self.log = None
        self.unfinished = []

    def use(self, args):
        """Switch to a command's settings."""
        global settings, request_delay
        settings = args
        if args.delay is not None:
            request_delay = args.delay
        path = None if args.no_log else output_folder(args) / "search_log.csv"
        if self.log is None or self.log.path != path:
            if self.log:
                say_any_problem(self.log.save())
            self.log = Log(path)
        for cached in (search_page, get_studio, days_since_activity):
            cached.cache_clear()  # rankings may have changed since the last command

    def command(self, *parts):
        """A follow-up command: as typed in the window, or as run in a terminal."""
        if self.interactive:
            return " ".join(parts)
        command = ([sys.argv[0]] if FROZEN else ["python", sys.argv[0]]) + list(parts)
        return subprocess.list2cmdline(command) if os.name == "nt" else shlex.join(command)

    def item_command(self, lookup, words=()):
        prefix = ["studio"] if lookup.kind == "studios" else []
        return self.command(*prefix, str(lookup.item["id"]), *words)


def scan(session):
    """Keep looking for what the last check didn't find, until it's found or q is pressed."""
    if not session.unfinished:
        print("\nNothing to scan. Scan keeps looking for results the last check didn't find.")
        return
    q_pressed()  # ignore keys pressed before the scan started
    try:
        for lookup in list(session.unfinished):
            print(f"\nScanning for {describe_search(lookup)}. {STOP_HINT}")
            try:
                stopped = keep_looking(lookup, MAX_DEPTH, should_stop=q_pressed, progress=show_progress)
            except KeyboardInterrupt:
                stopped = True
            except CheckError as error:
                end_progress()
                resume = " Type scan to try again from where it stopped." if session.interactive else ""
                print(f"  {error}{resume}")
                return
            end_progress()
            if stopped:
                session.log.add(lookup.kind, lookup.item, lookup.query, lookup.sort,
                                label(title_status(lookup), lookup) if lookup.title_check else result_text(lookup),
                                None, lookup.matches)
                resume = " Type scan to pick up from there." if session.interactive else ""
                print(f"  Stopped after {lookup.checked:,} results.{resume}")
                return
            session.unfinished.remove(lookup)
            report_scan(session, lookup)
    finally:
        say_any_problem(session.log.save())


def report_scan(session, lookup):
    if lookup.title_check:
        status, change = record_title(session, lookup)
        where = f" at #{lookup.rank:,}" if lookup.rank else ""
        print(f"  {label(status, lookup)}{where}" + (f" ({change})" if change else ""))
        print_title_advice(session, status, lookup)
        return
    text = result_text(lookup)
    change = session.log.add(lookup.kind, lookup.item, lookup.query, lookup.sort, text, lookup.rank, lookup.matches)
    print(f"  {SORTS[lookup.sort]}: {text}" + (f" ({change})" if change else ""))
    if lookup.rank is None and lookup.checked >= MAX_DEPTH:
        print(wrap("Scratch search stops showing results after 10,000, so nobody can scroll this far."))


def print_scan_hint(session, args):
    count = len(session.unfinished)
    if not count or args.scan:
        return
    found = "it's found" if count == 1 else "they're found"
    if session.interactive:
        print(f"\nType scan to keep looking until {found}. {STOP_HINT}")
    else:
        print(f"\nTo keep looking until {found}, run:\n  {session.command(*sys.argv[1:], '--scan')}")


def describe_search(lookup):
    if lookup.title_check:
        return f"{describe(lookup.kind, lookup.item)} in results for its title"
    return f"{describe(lookup.kind, lookup.item)} in {SORTS[lookup.sort]} results for \"{lookup.query}\""


def q_pressed():
    """True if q was pressed in this console window since the last call (Windows only)."""
    pressed = False
    while msvcrt and msvcrt.kbhit():
        pressed = msvcrt.getwch().lower() == "q" or pressed
    return pressed


def show_progress(lookup):
    if not sys.stdout.isatty():
        return
    if lookup.second_pass:
        text = f"Double-checking: {lookup.offset:,} of {lookup.checked:,} results"
    else:
        text = f"Looked through {lookup.checked:,} results"
    print(f"\r  {text:<60}", end="", flush=True)


def show_studio_progress(done, total):
    if sys.stdout.isatty():
        print(f"\r  Checking how active {done} of {total} studios are", end="", flush=True)


def say_any_problem(message):
    """Print a problem that isn't worth stopping for, like results that wouldn't save."""
    if message:
        print(chr(10) + message)


def end_progress():
    if sys.stdout.isatty():
        print(f"\r{'':<64}\r", end="", flush=True)


# Formatting

def words_in(text):
    """Lowercase words for matching searches, so "#Games v1.5" gives games, v1, 5."""
    return re.findall(r"\w+", text.lower())


def word_count(title):
    """Words as a person would count them, so "Pizza Rush v1.5" has 3."""
    return sum(1 for chunk in title.split() if re.search(r"\w", chunk))


def loves_of(project):
    return (project.get("stats") or {}).get("loves", 0)


def followers_of(studio):
    stats = studio.get("stats") or {}
    if "followers" not in stats:  # studio search results leave stats out
        stats = (get_studio(studio["id"]) or {}).get("stats") or {}
    return stats.get("followers", 0)


def stat_of(kind, item):
    """What Popular ranks by besides the title: loves for projects, followers for studios."""
    return loves_of(item) if kind == "projects" else followers_of(item)


def shared_date(project):
    return ((project.get("history") or {}).get("shared") or "")[:10]


def item_date(kind, item):
    """When a project was shared or a studio was created."""
    return (item.get("history") or {}).get("shared" if kind == "projects" else "created")


def days_ago(timestamp):
    then = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - then).total_seconds() / 86400


def within_days(days):
    count = max(1, math.ceil(days))
    return "day" if count == 1 else f"{count} days"


def ago(days):
    if days < 1:
        return "today"
    return "1 day ago" if days < 2 else f"{int(days)} days ago"


def plural(count, noun, many=None):
    return f"{count:,} {noun if count == 1 else many or noun + 's'}"


def units(values, noun):
    """A range of counts with its unit, like "0-7 loves" or "1 love"."""
    return f"{span(values)} {noun}" + ("" if min(values) == max(values) == 1 else "s")


def matching(count, noun):
    """How many items match a search, like "1 project matches" or "464 projects match"."""
    return f"{format_count(count)} {noun} matches" if count == 1 else f"{format_count(count)} {noun}s match"


def span(values):
    low, high = min(values), max(values)
    return f"{low:,}" if low == high else f"{low:,}-{high:,}"


def format_count(count):
    return f"{count:,}+" if count >= MAX_DEPTH else f"{count:,}"


def quoted(items):
    items = [f'"{item}"' for item in items]
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def label(status, lookup):
    return LABELS[status].format(checked=lookup.checked)


def rank_label(lookup):
    return f"#{lookup.rank:,}" if lookup.rank else "-"


def on_first(lookup):
    return bool(lookup.rank and lookup.rank <= settings.first_screen)


def title_sort():
    return "trending" if settings.sort == "trending" else "popular"


def wrap(text, indent="  "):
    return textwrap.fill(text, width=78, initial_indent=indent, subsequent_indent=indent)


def tidy(title):
    return " ".join(title.split())


def short_title(title, width=50):
    title = tidy(title) or "(untitled)"
    return title if len(title) <= width else title[: width - 1] + "…"


def item_url(kind, item):
    return f"https://scratch.mit.edu/{kind}/{item['id']}/"


def describe(kind, item):
    title = short_title(item["title"], 60)
    if kind == "studios":
        return f"the studio \"{title}\""
    author = (item.get("author") or {}).get("username")
    return f"the project \"{title}\"" + (f" by {author}" if author else "")


# Running commands

def parse_command(tokens):
    """Work out what to check: (kind, value, words).

    kind is "project", "studio", "user", or "either" for a bare number, which
    could be a project ID or a username made of digits.
    """
    first, rest = tokens[0], tokens[1:]
    match = re.search(r"turbowarp\.org/#?(\d+)", first)  # TurboWarp links use Scratch project IDs
    if match:
        return "project", match.group(1), rest
    for kind in ("project", "studio"):
        match = re.search(rf"/{kind}s/(\d+)", first)
        if match:
            return kind, match.group(1), rest
        if first.lower() == kind and rest and re.fullmatch(r"[0-9]+", rest[0]):
            return kind, rest[0], rest[1:]
    match = re.search(r"/users/([^/?#\s]+)", first)
    if not match and re.fullmatch(r"[0-9]+", first):
        return "either", first, rest
    name = match.group(1) if match else first
    if re.fullmatch(r"[A-Za-z0-9_-]+", name):
        return "user", name, rest
    return None


def clean_input(text):
    """Remove invisible characters that sneak into typed or pasted text, like a byte-order mark."""
    return re.sub(r"[﻿​‌‍⁠]", "", text).strip()


def split_command(text):
    """Split a typed command into words, keeping "quoted titles" together."""
    lexer = shlex.shlex(text, posix=True)
    lexer.whitespace_split = True
    lexer.quotes = '"'     # only double quotes, so words like Griffpatch's still work
    lexer.escape = ""      # keep backslashes, for Windows paths
    lexer.commenters = ""  # keep hashtags like #games
    try:
        return list(lexer)
    except ValueError:
        raise CheckError("A quote is missing its closing quote.") from None


def protect_usernames(tokens, parser):
    """Usernames can start with "-", which looks like a flag, so turn them into profile links."""
    flags = parser._option_string_actions
    return [f"https://scratch.mit.edu/users/{token}/"
            if token.startswith("-") and not token.startswith("--") and token not in flags
            and re.fullmatch(r"[A-Za-z0-9_-]+", token) else token
            for token in tokens]


def clamp_depth(depth):
    return max(PAGE_SIZE, min(depth, MAX_DEPTH))


def run(session, args):
    """Do everything a command asks for. Returns False if it only had settings in it."""
    session.use(args)
    if args.history:
        make_history()
    if args.find_studios:
        find_studios(args.find_studios)
    if args.what:
        run_check(session, args)
    elif args.titles or args.find_words or args.contents:
        raise CheckError("--titles, --find-words and --contents go after a project or studio, "
                         "like: 123456789 --find-words")
    return bool(args.what or args.history or args.find_studios)


def run_check(session, args):
    parsed = parse_command(args.what)
    if not parsed:
        raise CheckError(f"I can't tell what \"{args.what[0]}\" is. Type a username, a project link or ID, "
                         "or \"studio\" and a studio ID. Type help for examples.")
    kind, value, words = parsed
    if kind == "user" and (words or args.titles or args.find_words):
        raise CheckError(f"\"{value}\" looks like a username. Search words, --titles and --find-words go "
                         "after a project or studio, like: 123456789 pizza tycoon")
    if args.contents and kind != "studio":
        raise CheckError("--contents goes after a studio, like: studio 12345 --contents")
    if words and not re.search(r"\w", " ".join(words)):
        raise CheckError("Search words need at least one letter or number.")

    session.unfinished = []
    try:
        check_target(session, kind, value, words, args)
    finally:
        say_any_problem(session.log.save())
    print_scan_hint(session, args)
    if args.scan and session.unfinished:
        scan(session)


def check_target(session, kind, value, words, args):
    if kind == "studio":
        item = get_studio(int(value))
        if not item:
            raise CheckError(f"There's no studio with ID {value}. Check the number in the studio's link.")
        item_kind = "studios"
    else:
        item = get_json(f"/projects/{value}") if kind != "user" else None
        item_kind = "projects"
        if not item:
            if kind == "project" or words or args.titles or args.find_words:
                raise CheckError(f"There's no shared project with ID {value}. Check the number in the project's "
                                 "link. Unshared projects can't be checked, because they can't show up in search.")
            user = get_json(f"/users/{value}")
            if not user:
                raise CheckError(f"There's no shared project with ID {value}, and no user named {value}. "
                                 "Check the number or the name." if kind == "either" else
                                 f"There's no Scratch user named \"{value}\". Check the spelling.")
            check_user(session, user, clamp_depth(args.depth or USER_DEPTH))
            return

    if args.contents:
        check_contents(session, item, clamp_depth(args.depth or USER_DEPTH))
    if args.titles:
        test_titles(item_kind, item, args.titles)
    if args.find_words:
        find_words(session, item_kind, item, words, clamp_depth(args.depth or WORDS_DEPTH))
    if not (args.contents or args.titles or args.find_words):
        depth = clamp_depth(args.depth or SINGLE_DEPTH)
        if words:
            check_words(session, item_kind, item, " ".join(words), depth)
        else:
            check_single(session, item_kind, item, depth)


def bug_message(error, command):
    """Save an unexpected error's details, and explain it in plain language."""
    where = save_error_report(error, command)
    saved = f" The details were saved to {where}. Sharing that file makes it easy to fix." if where else ""
    return (f"Something went wrong that SpriteScout didn't expect ({type(error).__name__}: {error}). "
            f"It's a bug in SpriteScout, not something you did.{saved}")


def save_error_report(error, command):
    """Add an unexpected error's full details to errors.txt. Returns the file, or None if that failed."""
    try:
        path = output_folder(settings) / "errors.txt"
    except CheckError:
        path = OUTPUT / "errors.txt"
    details = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as file:
            file.write(f"=== {datetime.now():%Y-%m-%d %H:%M:%S} | SpriteScout {VERSION} | "
                       f"Python {platform.python_version()} | {platform.platform()}\n"
                       f"Command: {command}\n{details}\n")
    except OSError:
        return None
    return path


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = make_parser()
    try:
        defaults = parser.parse_intermixed_args(protect_usernames(sys.argv[1:], parser))
    except CheckError as error:
        sys.exit(str(error))
    if defaults.help or defaults.version:
        print(help_text() if defaults.help else f"SpriteScout {VERSION}")
        return

    if defaults.what or defaults.history or defaults.find_studios or defaults.titles \
            or defaults.find_words or defaults.contents:
        session = Session(interactive=False)
        try:
            run(session, defaults)
        except CheckError as error:
            sys.exit(str(error))
        update = update_note()
        if update:
            print(f"\n{update}")
        return

    # Nothing to do yet (for example, the program was double-clicked): keep
    # asking for commands until the person quits, so the window stays open.
    session = Session(interactive=True)
    try:
        session.use(defaults)
    except CheckError as error:
        sys.exit(str(error))
    print(help_text())
    saving = "Results aren't being saved." if defaults.no_log else f"Results are saved in {session.log.path.parent}"
    print(f"\n{saving}\nType help to see this list again.")
    update = update_note()
    if update:
        print(f"\n{update}")
    while True:
        try:
            text = clean_input(input("\nCommand: "))
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if text.lower() in ("q", "quit", "exit"):
            return
        if not text:
            continue
        first = text.split()[0].lower()
        try:
            if first in ("help", "-h", "--help"):
                print(help_text())
            elif first in ("version", "--version"):
                print(f"SpriteScout {VERSION}")
            elif first == "scan":
                scan(session)
            else:
                tokens = protect_usernames(split_command(text), parser)
                args = parser.parse_intermixed_args(tokens, namespace=copy.copy(defaults))
                if args.help or args.version:
                    print(help_text() if args.help else f"SpriteScout {VERSION}")
                elif not run(session, args):
                    defaults = args
                    print("Those settings will be used for the rest of this session.")
        except CheckError as error:
            print(error)
        except KeyboardInterrupt:
            print("\nStopped.")
        except Exception as error:  # a bug: explain it and keep the window open
            print(bug_message(error, text))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nStopped.")
    except Exception as error:  # a bug outside the command loop
        print(bug_message(error, " ".join(sys.argv[1:]) or "(opened the window)"))
        if len(sys.argv) == 1:  # double-clicked, so keep the window open long enough to read it
            try:
                input("Press Enter to close.")
            except (EOFError, KeyboardInterrupt):
                pass
        sys.exit(1)
