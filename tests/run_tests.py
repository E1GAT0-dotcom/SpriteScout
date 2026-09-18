"""Tests for spritescout.py.

Run from the scratchbot folder:

    python tests/run_tests.py                    offline checks, then every command against Scratch
    python tests/run_tests.py --offline          only the checks that don't need the internet
    python tests/run_tests.py --exe              also try the main commands with SpriteScout.exe
    python tests/run_tests.py --only "--titles"  only the real commands whose test names contain that

Everything the tests make goes in output/test-run, which is emptied first.
report.txt there has every command the tests ran, with its full output.
"""

import argparse
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import time
import urllib.error
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUN = ROOT / "output" / "test-run"
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
import spritescout as scout  # noqa: E402

results = []  # (name, passed, details)
report = []   # lines for report.txt


def check(name, passed, details=""):
    results.append((name, bool(passed), details))
    line = f"  {'PASS' if passed else 'FAIL'}  {name}"
    if details and not passed:
        line += f"\n        {str(details).strip()[:500]}"
    print(line, flush=True)
    report.append(line)


class Patch:
    """Swap attributes for the length of a with block, like a tiny unittest.mock.patch."""

    def __init__(self, target, **values):
        self.target, self.values, self.saved = target, values, {}

    def __enter__(self):
        for name, value in self.values.items():
            self.saved[name] = getattr(self.target, name)
            setattr(self.target, name, value)

    def __exit__(self, *exc):
        for name, value in self.saved.items():
            setattr(self.target, name, value)


def settings(*flags):
    """A session using these flags, with results in output/test-run/offline unless told otherwise."""
    flags = list(flags)
    if "--output" not in flags:
        flags += ["--output", str(RUN / "offline")]
    session = scout.Session(interactive=True)
    session.use(scout.make_parser().parse_args(flags))
    return session


def printed(function, *args):
    """Run a function and return what it printed."""
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        function(*args)
    return buffer.getvalue()


def raises(function, *args):
    """Run a function and return the message of the CheckError it raised, or "" if none."""
    try:
        with redirect_stdout(io.StringIO()):
            function(*args)
    except scout.CheckError as error:
        return str(error)
    return ""


def offline_tests():
    print("\nOffline checks (no internet needed)")
    report.append("\nOffline checks")
    parser = scout.make_parser()

    commands = {
        "griffpatch": ("user", "griffpatch", []),
        "https://scratch.mit.edu/users/griffpatch/": ("user", "griffpatch", []),
        "74763380": ("either", "74763380", []),
        "74763380 pizza rush": ("either", "74763380", ["pizza", "rush"]),
        "project 74763380": ("project", "74763380", []),
        "https://scratch.mit.edu/projects/74763380/editor/": ("project", "74763380", []),
        "https://turbowarp.org/74763380": ("project", "74763380", []),
        "https://turbowarp.org/#74763380": ("project", "74763380", []),
        "studio 416070 games": ("studio", "416070", ["games"]),
        "https://scratch.mit.edu/studios/416070/projects": ("studio", "416070", []),
        "bad!name": None,
    }
    for text, expected in commands.items():
        got = scout.parse_command(text.split())
        check(f"reads {text!r}", got == expected, f"got {got}")

    words = scout.split_command('1 --titles "Pizza Rush" Griffpatch\'s #games C:\\folder')
    check("keeps quoted titles, apostrophes, hashtags and backslashes",
          words == ["1", "--titles", "Pizza Rush", "Griffpatch's", "#games", "C:\\folder"], words)
    check("explains a missing quote", "closing quote" in raises(scout.split_command, '1 --titles "unclosed'))
    check("ignores invisible characters in pasted text", scout.clean_input("﻿q ​") == "q")
    check("reads usernames that start with -",
          scout.protect_usernames(["-Zinnea-", "--no-log"], parser) == ["https://scratch.mit.edu/users/-Zinnea-/", "--no-log"])

    for argv, phrase in [
        (["1", "--sort", "sideways"], "--sort can't be \"sideways\""),
        (["1", "--depth", "abc"], "--depth needs a whole number"),
        (["1", "--depth", "0"], "--depth needs a whole number"),
        (["1", "--first-screen", "99"], "from 1 to 40"),
        (["1", "--top", "-3"], "--top needs a whole number"),
        (["1", "--delay", "fast"], "--delay needs a number of seconds"),
        (["1", "--titles"], "--titles needs something after it"),
        (["--find-studios"], "--find-studios needs something after it"),
        (["1", "--frobnicate"], "There's no flag called --frobnicate"),
    ]:
        message = raises(parser.parse_intermixed_args, argv)
        check(f"explains the mistake in {' '.join(argv)!r}", phrase in message, message or "no error")

    help_text = scout.help_text()
    check("help lines fit in 79 characters", max(len(line) for line in help_text.splitlines()) <= 79)
    missing = [names[-1] for _, names, _, _ in scout.OPTIONS if names[-1] not in help_text]
    check("help lists every flag", not missing, f"missing {missing}")

    check("counts title words like a person", scout.word_count("Pizza Rush v1.5") == 3)
    check("matches singulars and plurals", scout.has_word(["game"], "games") and scout.has_word(["games"], "game"))
    check("joins lists", scout.quoted(["a", "b", "c"]) == '"a", "b" and "c"')
    check("formats ranges and counts", scout.span([3, 5405]) == "3-5,405" and scout.format_count(10000) == "10,000+")
    check("finds hashtags, versions and brackets in titles",
          scout.title_extras("Game V1.4 [New] (Pen) #games") == ["#games", "V1.4", "[New]", "(Pen)"])
    check("makes search ideas from a title",
          scout.search_word_ideas("The Pizza Rush v1.5")[:4] == ["the pizza rush v1.5", "pizza", "rush", "pizza rush"])
    check("has no search ideas for an emoji-only title", scout.search_word_ideas("\U0001F3AE\U0001F3AE") == [])
    check("describes projects whose list left out the username (the scan KeyError)",
          scout.describe("projects", {"id": 5, "title": "Fish Clicker", "author": {"id": 1}}) == 'the project "Fish Clicker"')

    previous = {"checked_at": "2026-09-01 10:00", "rank": "12", "result": "#12"}
    check("describes rank changes",
          scout.describe_change(previous, 5, "#5") == "up 7 since 2026-09-01"
          and scout.describe_change(previous, 20, "#20") == "down 8 since 2026-09-01"
          and scout.describe_change(previous, None, "not in top 200") == "was #12 on 2026-09-01"
          and scout.describe_change(dict(previous, rank="oops"), 3, "#3") == "was #12 on 2026-09-01")

    settings("--recent-days", "14")
    new = scout.Lookup("projects", {"id": 1, "title": "x", "history": {"shared": datetime.now(timezone.utc).isoformat()}}, "x")
    old = scout.Lookup("projects", {"id": 1, "title": "x", "history": {"shared": "2020-01-01T00:00:00.000Z"}}, "x")
    new.ended = old.ended = True
    check("tells new projects apart from missing ones", scout.title_status(new) == "new" and scout.title_status(old) == "missing")

    # The results log
    folder = RUN / "offline"
    folder.mkdir(parents=True, exist_ok=True)
    old_log = folder / "old_format.csv"
    old_log.write_text("\ufeffchecked_at,project_id,title,search,sort,result,rank,loves,favorites,views,matches\n"
                       '2026-09-01 10:00,111,"Game, with comma","Game, with comma",Popular,Buried,44,3,2,9,\n',
                       encoding="utf-8")
    log = scout.Log(old_log)
    change = log.add("projects", {"id": 111, "title": "Game, with comma", "stats": {"loves": 5}},
                     "Game, with comma", "popular", "Buried", 30)
    log.save()
    rows, outdated = scout.read_log(old_log)
    check("upgrades logs from older versions without losing rows",
          not outdated and len(rows) == 2 and rows[0]["type"] == "project" and rows[0]["title"] == "Game, with comma", rows)
    check("compares with rows from older logs", change == "up 14 since 2026-09-01", change)

    locked = folder / "read_only.csv"
    shutil.copy(old_log, locked)
    os.chmod(locked, stat.S_IREAD)
    log = scout.Log(locked)
    log.add("projects", {"id": 1, "title": "x"}, "x", "popular", "Easy to find", 1)
    trouble = log.save()
    spoken = printed(scout.say_any_problem, trouble)
    os.chmod(locked, stat.S_IREAD | stat.S_IWRITE)
    check("explains a log it can't save, and keeps the results for later",
          "Couldn't save results" in trouble and "Couldn't save results" in spoken
          and len(log.pending) == 1, (trouble, spoken))

    home = folder / "old_home"
    home.mkdir(exist_ok=True)
    (home / "search_log.csv").write_text("checked_at\n", encoding="utf-8")
    (home / "search_history.html").write_text("<html></html>", encoding="utf-8")
    with Patch(scout, HERE=home, OUTPUT=home / "output"):
        moved_to = scout.output_folder(parser.parse_args([]))
    check("moves results from older versions into the output folder",
          moved_to == home / "output" and (home / "output" / "search_log.csv").exists()
          and (home / "output" / "search_history.html").exists() and not (home / "search_log.csv").exists())
    not_a_folder = folder / "not_a_folder.txt"
    not_a_folder.write_text("x", encoding="utf-8")
    check("explains --output pointing at a file",
          "needs a folder" in raises(scout.output_folder, parser.parse_args(["--output", str(not_a_folder)])))

    # The history page
    row = dict.fromkeys(scout.LOG_FIELDS, "")
    row.update(checked_at="2026-09-01 10:00", type="project", id="1", title="</script><b>", search="x",
               sort="Popular", result="#1", rank="1")
    payload = scout.history_json([row, dict(row, checked_at="2026-09-02 10:00", rank="3", result="#3")], "log.csv")
    check("escapes titles so they can't break the history page",
          "</script>" not in payload and json.loads(payload)["items"][0]["title"] == "</script><b>")
    settings()
    with open(folder / "search_log.csv", "w", newline="", encoding="utf-8-sig") as file:
        file.write(",".join(scout.LOG_FIELDS) + "\n" + ",".join(dict(row, title="Test").values()) + "\n")
    opened = []
    with Patch(scout.webbrowser, open=lambda url: opened.append(url) or True):
        message = printed(scout.make_history)
    check("makes and opens the history page",
          (folder / "search_history.html").exists() and opened and "Made a history page" in message, message)

    # Looking through results, with pretend search pages
    everything = [{"id": n} for n in range(1, 101)]
    skipped = [item for item in everything if item["id"] != 50]

    def pages_that_skip_50(kind, query, sort, offset, limit):
        # The normal page breaks skip #50, like Scratch does with tied rankings.
        source = skipped if offset % 40 == 0 and limit == 40 else everything
        return tuple(source[offset:offset + limit])

    def endless_pages(kind, query, sort, offset, limit):
        return tuple({"id": -1} for _ in range(limit)) if offset < scout.MAX_DEPTH else ()

    with Patch(scout, search_page=pages_that_skip_50):
        lookup = scout.Lookup("projects", {"id": 50, "title": "x"}, "x")
        scout.keep_looking(lookup, 1000)
        check("finds results that the first pass skipped", lookup.rank == 50 and lookup.second_pass, vars(lookup))
        lookup = scout.Lookup("projects", {"id": 999, "title": "x"}, "x")
        scout.keep_looking(lookup, 1000)
        check("knows when something doesn't come up at all", lookup.rank is None and lookup.ended)
    session = settings("--no-log")  # before swapping search_page, which a session clears the cache of
    with Patch(scout, search_page=endless_pages):
        lookup = scout.Lookup("projects", {"id": 999, "title": "x"}, "x")
        scout.keep_looking(lookup, 40)
        check("stops at the depth, ready to scan further", lookup.checked == 40 and lookup.unfinished)
        scout.keep_looking(lookup, scout.MAX_DEPTH)
        check("stops at result 10,000, where search stops", lookup.checked == scout.MAX_DEPTH and not lookup.unfinished)

        lookup = scout.Lookup("projects", {"id": 999, "title": "x", "author": {"id": 1}}, "x", title_check=True)
        scout.keep_looking(lookup, 40)
        session.unfinished = [lookup]
        presses = iter([False, False, True])  # q is pressed after one more page
        with Patch(scout, q_pressed=lambda: next(presses, True)):
            message = printed(scout.scan, session)
        check("scan stops when q is pressed, and can pick up again",
              "Stopped after 80 results" in message and lookup in session.unfinished, message)

    # A username check with hosted studios, using a pretend Scratch
    fake_scratch = {
        "/users/demo/projects": [{"id": 1, "title": "Demo Game", "stats": {"loves": 3},
                                  "history": {"shared": "2020-01-01T00:00:00.000Z"}}],
        "/users/demo/studios/curate": [{"id": 7, "title": "Demo Studio", "host": 42},
                                       {"id": 8, "title": "Someone Else's Studio", "host": 99}],
        "/studios/7": {"id": 7, "title": "Demo Studio", "host": 42, "stats": {"followers": 5}},
    }

    def fake_get_json(path, params=None):
        answer = fake_scratch.get(path)
        return [] if isinstance(answer, list) and params and params.get("offset") else answer

    def fake_search(kind, query, sort, offset, limit):
        return ({"id": 1 if kind == "projects" else 7},) if offset == 0 else ()

    with Patch(scout, get_json=fake_get_json):
        session = settings("--no-log")
        with Patch(scout, search_page=fake_search):
            message = printed(scout.check_user, session, {"username": "demo", "id": 42}, 200)
    check("checks the studios a user hosts, and only those",
          "Studio: Demo Studio" in message and "Someone Else" not in message and "1 hosted studio" in message, message)

    # Words that find nothing: made up, or blocked by Scratch
    check("explains one word that finds nothing",
          scout.silent_note(["horror"]) == 'Searching "horror" on its own finds nothing. If that is a common word, '
          'Scratch probably blocks it from search, like it does "fnaf" and "scary".', scout.silent_note(["horror"]))
    check("explains several words that find nothing", "on their own" in scout.silent_note(["a", "b"])
          and "those are common words" in scout.silent_note(["a", "b"]))
    with Patch(scout, count_matches=lambda kind, query: 0, words_with_no_results=lambda kind, text: ["zorblax"]):
        settings("--no-log")
        message = printed(scout.test_titles, "projects", {"id": 1, "title": "Old", "author": {}, "stats": {"loves": 1}},
                          ["Zorblax Quest"])
    check("a title with a made-up word could be the only result",
          "it would be the only result, unless Scratch blocks" in " ".join(message.split()), message)
    check("says 1 love, not 1 loves", "which has 1 love." in message and scout.units([1, 1], "love") == "1 love"
          and scout.units([0, 7], "love") == "0-7 loves" and scout.matching(1, "project") == "1 project matches")

    def closed_studios(kind, query, sort, offset, limit):
        return ({"id": 1, "title": "Platformer Games", "open_to_all": False},) if offset == 0 else ()

    session = settings("--no-log")
    with Patch(scout, search_page=closed_studios):
        message = printed(scout.find_studios, ["platformer"])
    check("says when no studios are open to everyone", "None found" in message, message)

    def open_to_all(kind, query, sort, offset, limit):
        return (({"id": 7, "title": "Platformer Games", "open_to_all": True},
                 {"id": 8, "title": "Platformer Games Too", "open_to_all": True}) if offset == 0 else ())

    looked_at = []
    with Patch(scout, search_page=open_to_all, days_since_activity=looked_at.append):
        stopped_studios = scout.open_studios(["platformer"], should_stop=lambda: True)
    check("stops working out which studios are active when asked to",
          stopped_studios[0] == [] and looked_at == [], (stopped_studios, looked_at))

    tried = []

    def note_search(kind, query, sort, offset, limit):
        tried.append(query)
        return ()

    many_words = {"id": 5, "title": "Pizza Tycoon Deluxe Edition", "stats": {"loves": 1}}
    session = settings("--no-log")
    with Patch(scout, search_page=note_search):
        ideas = len(scout.search_ideas("projects", many_words, ()))
        tried.clear()
        ranked, unranked = scout.word_rankings(session, "projects", many_words, (), 200, "popular",
                                               should_stop=lambda: len(tried) >= 2)
    check("a search stopped partway isn't counted as missing",
          len(ranked) + len(unranked) < ideas and ideas > 2, (ranked, unranked, ideas))

    # The GUI version: it serves its page and shares the text version's engine
    import socketserver
    import threading
    import urllib.request

    import spritescout_gui as gui

    lookup = scout.Lookup("projects", {"id": 5, "title": "Demo", "stats": {"loves": 1}}, "Demo")
    lookup.rank = 3
    row = gui.row("projects", lookup.item, lookup, "easy", "no change since 2026-09-01")
    check("the GUI version describes results the same way the console does",
          row["label"] == "Easy to find" and row["rank"] == 3 and row["count"] == "1 love"
          and row["url"].endswith("/projects/5/") and row["change"] == "", row)

    stopped = scout.Lookup("projects", lookup.item, "Demo")
    stopped.checked = 200
    later = gui.row("projects", stopped.item, stopped, "unknown", "", 2)
    check("the GUI version marks results a scan could look further for",
          later["scannable"] is True and later["place"] == 2 and row["scannable"] is False, later)

    home = RUN / "offline" / "gui"
    with Patch(scout, HERE=home, OUTPUT=home / "output"):
        moved = home / "output" / "window-settings.json"
        moved.parent.mkdir(parents=True, exist_ok=True)
        moved.write_text('{"username": "from-before"}', encoding="utf-8")
        check("the GUI version keeps the settings an older version saved",
              gui.remembered().get("username") == "from-before" and not moved.exists(),
              (gui.remembered(), moved.exists()))

        gui.remember({"username": "demo"})
        check("the GUI version remembers your username", gui.remembered().get("username") == "demo",
              gui.remembered())

        gui.save_settings({"sort": "trending", "depth": "500", "first_screen": "", "top": "3"})
        check("the GUI version passes saved settings to the checks",
              gui.saved_flags() == ["--sort", "trending", "--depth", "500", "--top", "3"],
              gui.saved_flags())
        try:
            gui.save_settings({"depth": "99999"})
            refused = "(allowed it)"
        except scout.CheckError as error:
            refused = str(error)
        check("the GUI version turns down a setting it can't use",
              "10,000" in refused and "depth" in refused, refused)
        check("a setting it turns down doesn't replace the saved one",
              gui.remembered().get("depth") == "500", gui.remembered())

        gui.save_settings({**gui.remembered(), "no_update_check": "1"})
        check("the GUI version can be told to stop checking for new versions",
              "--no-update-check" in gui.saved_flags() and gui.update_notice() == {}, gui.saved_flags())
        gui.save_settings({**gui.remembered(), "no_update_check": ""})

    def gui_error(work, *arguments):
        gui.start("test", work, *arguments)
        for _ in range(50):
            if gui.job["state"] == "done":
                return gui.job["error"]
            time.sleep(0.1)
        return "(never finished)"

    check("the GUI version explains search words without a project",
          "one project or studio" in gui_error(gui.check_words, "griffpatch", "platformer"))
    check("the GUI version explains titles without a project",
          "one project or studio" in gui_error(gui.try_titles, "griffpatch", "A title"))
    check("the GUI version asks for titles to try",
          "one per line" in gui_error(gui.try_titles, "123", ""))
    check("the GUI version asks what the studios should be about",
          "what the studios should be about" in gui_error(gui.find_studios, "").lower())
    check("the GUI version explains searches without a project",
          "one project or studio" in gui_error(gui.find_searches, "griffpatch"))
    check("the GUI version explains a scan for a result that has gone",
          "Check it again first" in gui_error(gui.scan_deeper, "7"))
    check("the GUI version explains a scan for something that isn't a row",
          "Check it again first" in gui_error(gui.scan_deeper, "not-a-row"))

    locked_log = home / "output" / "search_log.csv"
    locked_log.parent.mkdir(parents=True, exist_ok=True)
    # A current-format log, so saving appends to it: a read-only file blocks that
    # on every system, where replacing a whole file only needs a writable folder.
    locked_log.write_text(",".join(scout.LOG_FIELDS) + chr(10), encoding="utf-8-sig")
    os.chmod(locked_log, stat.S_IREAD)
    with Patch(scout, HERE=home, OUTPUT=home / "output"):
        unsaved = gui_error(lambda session: session.log.add(
            "projects", {"id": 1, "title": "x"}, "x", "popular", "Easy to find", 1))
    os.chmod(locked_log, stat.S_IREAD | stat.S_IWRITE)
    check("the GUI version says when results wouldn't save, having no console to say it in",
          "Couldn't save results" in unsaved, unsaved)

    busy = threading.Event()
    first_start = gui.start("test", lambda session: busy.wait(10))
    second_start = gui.start("test", lambda session: None)
    busy.set()
    for _ in range(100):
        if gui.job["state"] == "done":
            break
        time.sleep(0.1)
    check("the GUI version turns down a second check while one is still going",
          first_start is True and second_start is False and gui.job["state"] == "done",
          (first_start, second_start, gui.job["state"]))

    pages = {"asked": 0}

    def busy_search(kind, query, sort, offset, limit):
        pages["asked"] += 1
        if pages["asked"] >= 3:
            gui.stopping.set()  # as if Stop was pressed partway through
        return tuple({"id": 900 + offset + index, "title": "Sand box"} for index in range(limit))

    waiting = scout.Lookup("projects", {"id": 5, "title": "Sand box", "stats": {"loves": 1}}, "Sand box")
    waiting.checked = waiting.offset = 80
    gui.job.update(kind="titles", stopped=False,
                   items=[gui.row("projects", waiting.item, waiting, "unknown", "", 0)])
    gui.unfinished[0] = ("projects", waiting.item, waiting)
    session = settings("--no-log")  # made first: patching search_page hides its cache
    with Patch(scout, search_page=busy_search):
        gui.scan_deeper(session, "0")
    check("the GUI version's scan stops when asked, and can be carried on later",
          gui.job["stopped"] and gui.job["items"][0]["scannable"] is True and 0 in gui.unfinished
          and waiting.checked > 80, (gui.job["items"][0], waiting.checked))
    gui.stopping.clear()
    gui.unfinished.clear()

    # Settings saved through the server go to the test folder, not anyone's real one.
    with Patch(scout, HERE=home, OUTPUT=home / "output"),             socketserver.ThreadingTCPServer(("127.0.0.1", 0), gui.Handler) as server:
        threading.Thread(target=server.serve_forever, daemon=True).start()
        address = f"http://127.0.0.1:{server.server_address[1]}/"
        page = urllib.request.urlopen(address, timeout=10).read().decode("utf-8")
        icon = urllib.request.urlopen(address + "icon.png", timeout=10)
        refused = json.loads(urllib.request.urlopen(address + "save?depth=lots", timeout=10).read())
        cleared = json.loads(urllib.request.urlopen(address + "save?depth=", timeout=10).read())
        stopping = json.loads(urllib.request.urlopen(address + "stop", timeout=10).read())
        server.shutdown()
    gui.stopping.clear()
    check("the GUI version serves its page", f">{scout.VERSION}<" in page and "SpriteScout" in page
          and "__VERSION__" not in page and icon.status == 200, page[:200])
    check("the page says what happened instead of going quiet when the program is closed",
          "isn't running any more" in page and "Still finishing the last check" in page)
    check("the GUI version's page has its stop, scan and settings controls",
          'id="stop"' in page and "Keep looking" in page and 'id="set-depth"' in page
          and "/save?" in page and "/scan?" in page and '"/update"' in page)

    with Patch(scout, update_note=lambda: f"SpriteScout 9.9 is out, and this is {scout.VERSION}. "
                                          f"Get it from {scout.RELEASES}"):
        notice = gui.update_notice()
    with Patch(scout, update_note=lambda: ""):
        quiet = gui.update_notice()
    check("the GUI version shows a new version on the page, having no console to print to",
          notice["note"] == f"SpriteScout 9.9 is out, and this is {scout.VERSION}."
          and notice["url"] == scout.RELEASES and quiet == {}, (notice, quiet))
    check("the GUI version lets you clear a setting by emptying the box",
          not cleared.get("depth"), cleared)
    check("the GUI version says why a setting won't do, instead of breaking",
          "whole number" in refused.get("error", "") and stopping == {"stopping": True},
          (refused, stopping))

    # Telling you when a newer version is out
    major, minor = (int(part) for part in scout.VERSION.split("."))
    later, much_later = f"{major}.{minor + 1}", f"{major}.{minor + 10}"
    check("compares versions",
          scout.newer_version_line(later).startswith(f"SpriteScout {later} is out")
          and scout.newer_version_line(much_later).startswith(f"SpriteScout {much_later} is out")
          and scout.newer_version_line(scout.VERSION) == ""
          and scout.newer_version_line("0.9") == "" and scout.newer_version_line(None) == "")

    class Answer(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.close()

    settings("--output", str(RUN / "offline" / "update"))
    with Patch(scout.urllib.request, urlopen=lambda request, timeout=None: Answer(b'{"tag_name": "v9.9"}')):
        first = scout.update_note()
    def refuse(request, timeout=None):
        raise AssertionError("checked twice in one day")
    with Patch(scout.urllib.request, urlopen=refuse):
        second = scout.update_note()
    check("notices a newer version, and only asks once a day",
          first.startswith("SpriteScout 9.9 is out") and second == first, (first, second))

    with Patch(scout.urllib.request, urlopen=refuse):
        settings("--output", str(RUN / "offline" / "update2"), "--no-update-check")
        check("skips the check when asked", scout.update_note() == "")
        settings("--output", str(RUN / "offline" / "update3"))
        def fail(request, timeout=None):
            raise urllib.error.URLError("no internet")
        with Patch(scout.urllib.request, urlopen=fail):
            quiet = scout.update_note()
            check("stays quiet when it can't check", quiet == "", f"got {quiet!r}")

    # Talking to Scratch when things go wrong, with a pretend internet
    class Answer(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.close()

    def pretend_internet(*answers):
        answers = iter(answers)

        def urlopen(request, timeout=None):
            answer = next(answers)
            if isinstance(answer, BaseException):
                raise answer
            return Answer(answer)
        return urlopen

    def http_error(code):
        return urllib.error.HTTPError("https://api.scratch.mit.edu/x", code, "error", {}, None)

    for name, answers, expected, phrase in [
        ("treats 404 as not found", [http_error(404)], None, None),
        ("waits out too many requests, then carries on", [http_error(429), b'{"ok": 1}'], {"ok": 1}, None),
        ("explains server trouble", [http_error(503)] * 3, None, "servers are having trouble"),
        ("explains having no internet", [urllib.error.URLError("getaddrinfo failed")] * 3, None, "Can't reach Scratch"),
        ("explains timeouts", [TimeoutError()] * 3, None, "taking too long"),
        ("explains answers that aren't data", [b"<html>"] * 3, None, "something unexpected"),
        ("explains requests Scratch can't handle", [http_error(400)], None, "couldn't handle"),
    ]:
        with Patch(scout.time, sleep=lambda seconds: None), Patch(scout.urllib.request, urlopen=pretend_internet(*answers)):
            buffer = io.StringIO()
            try:
                with redirect_stdout(buffer):
                    got = scout.get_json("/x")
                check(name, phrase is None and got == expected, f"got {got}")
            except scout.CheckError as error:
                check(name, phrase is not None and phrase in str(error), str(error))
    scout.request_delay = scout.REQUEST_DELAY

    # Bugs get a plain explanation and a saved report
    settings()
    try:
        raise ValueError("pretend bug")
    except ValueError as error:
        message = scout.bug_message(error, "pretend command")
    errors = folder / "errors.txt"
    saved = errors.read_text(encoding="utf-8") if errors.exists() else ""
    check("explains unexpected errors and saves the details",
          "didn't expect" in message and "pretend bug" in saved and "Traceback" in saved, message)


WINDOW_SCRIPT = """help me
--version
--no-tips
scan
griffpatch platformer
74763380 --titles "Unclosed
bad!name
74763380 pizza rush --sort popular
exit
"""


def live_tests(program, quick, only=None):
    print(f"\nReal commands with {' '.join(Path(part).name for part in program)} (needs the internet)")
    report.append(f"\nReal commands with {' '.join(program)}")
    fake_browser = RUN / "fake_browser.py"
    fake_browser.write_text("import sys, pathlib\n"
                            "with open(pathlib.Path(__file__).with_name('opened.txt'), 'a') as f:\n"
                            "    f.write(sys.argv[1] + '\\n')\n", encoding="utf-8")
    environment = dict(os.environ, PYTHONIOENCODING="utf-8",
                       BROWSER=f"{Path(sys.executable).as_posix()} {fake_browser.as_posix()} %s")

    # (name, arguments, what the output must include ("!" at the start means it mustn't),
    #  exit code, typed input, part of the quick run)
    tests = [
        ("shows help", ["--help"], ["Commands", "--find-studios", "--output FOLDER"], 0, None, True),
        ("shows the version", ["--version"], [scout.VERSION], 0, None, True),
        ("checks a username", ["griffpatch", "--max-projects", "2", "--no-studios"],
         ["Summary for griffpatch", "Easy to find"], 0, None, True),
        ("checks a profile link", ["https://scratch.mit.edu/users/griffpatch/", "--max-projects", "1", "--no-studios"],
         ["Summary for griffpatch"], 0, None, False),
        ("checks a project link", ["https://scratch.mit.edu/projects/74763380/"], ['"Pizza Rush', "Easy to find"], 0, None, True),
        ("checks a project ID", ["74763380"], ["Easy to find"], 0, None, False),
        ("checks project + ID", ["project", "74763380"], ["Easy to find"], 0, None, False),
        ("checks a TurboWarp link", ["https://turbowarp.org/74763380"], ["Pizza Rush"], 0, None, False),
        ("checks a studio link", ["https://scratch.mit.edu/studios/416070/"], ["Griffpatch's Games", "Easy to find"], 0, None, False),
        ("checks studio + ID", ["studio", "416070"], ["Griffpatch's Games"], 0, None, True),
        ("checks search words", ["74763380", "pizza", "rush"], ["Popular, the default sort", "Trending:", "First screen"], 0, None, True),
        ("--sort popular and --no-tips", ["74763380", "pizza", "rush", "--sort", "popular", "--no-tips"],
         ["Popular, the default sort"], 0, None, False),
        ("--sort trending and --trending-depth", ["74763380", "pizza", "rush", "--sort", "trending", "--trending-depth", "40"],
         ["Trending: not in top 40", "--scan"], 0, None, False),
        ("checks a studio's search words", ["studio", "416070", "games"], ["studios match", "followers"], 0, None, False),
        ("explains a blocked search word", ["74763380", "horror"], ["0 projects match", "finds nothing"], 0, None, False),
        ("--titles", ["74763380", "--titles", "Pizza Rush", "Horror Pizza", "!!!"],
         ["(current title)", 'Searching "horror" on its own finds nothing', "no letters or numbers"], 0, None, True),
        ("--titles for a studio", ["studio", "416070", "--titles", "Games"], ["followers"], 0, None, False),
        ("--find-words", ["74763380", "--find-words", "--top", "3"], ["Searches it comes up for"], 0, None, False),
        ("--find-words with extra words", ["74763380", "delivery", "--find-words", "--top", "3"], ["Trying"], 0, None, False),
        ("--find-words for a studio", ["studio", "416070", "--find-words", "--top", "3"], ["Searches it comes up for"], 0, None, False),
        ("--find-studios", ["--find-studios", "platformer", "games", "--top", "3"], ["followers, active"], 0, None, True),
        ("--find-studios with a made-up word", ["--find-studios", "zqxjvwkplm"], ["No studios come up"], 0, None, False),
        ("--find-studios with a blocked word", ["--find-studios", "horror"],
         ['Searching "horror" on its own finds nothing'], 0, None, False),
        ("--contents", ["studio", "416070", "--contents", "--max-projects", "2"], ["Summary for the studio"], 0, None, False),
        ("--scan right after a check", ["74763380", "pizza", "rush", "--sort", "trending", "--scan"],
         ["Scanning for", "Trending: #"], 0, None, False),
        ("--first-screen, --recent-days, --depth and --delay",
         ["74763380", "--first-screen", "1", "--recent-days", "0", "--depth", "40", "--delay", "0.5"],
         ["Easy to find at #1"], 0, None, False),
        ("--no-log", ["74763380", "--no-log"], ["Easy to find"], 0, None, False),
        ("--history", ["--history"], ["Made a history page"], 0, None, True),
        ("unknown username", ["zz_no_such_user_q8x7"], ["no Scratch user named"], 1, None, True),
        ("unknown project", ["project", "1"], ["no shared project with ID 1"], 1, None, False),
        ("unknown studio", ["studio", "999999999999"], ["no studio with ID"], 1, None, False),
        ("input it can't read", ["bad!name"], ["can't tell what"], 1, None, False),
        ("bad --sort", ["74763380", "--sort", "sideways"], ["--sort can't be"], 1, None, True),
        ("bad number", ["74763380", "--depth", "abc"], ["--depth needs a whole number"], 1, None, False),
        ("unknown flag", ["74763380", "--frobnicate"], ["no flag called --frobnicate"], 1, None, False),
        ("--titles with no titles", ["74763380", "--titles"], ["--titles needs something after it"], 1, None, False),
        ("--contents after a project", ["74763380", "--contents"], ["goes after a studio"], 1, None, False),
        ("search words after a username", ["griffpatch", "platformer"], ["looks like a username"], 1, None, False),
        ("--find-words on its own", ["--find-words"], ["go after a project or studio"], 1, None, False),
        ("search words with no letters", ["74763380", "!!!"], ["at least one letter"], 1, None, False),
        ("prompt: quit right away", [], ["Commands", "Results are saved in"], 0, "q\n", True),
        ("prompt: many commands and mistakes", [],
         [f"SpriteScout {scout.VERSION}", "Those settings will be used", "Nothing to scan",
          "looks like a username", "closing quote", "can't tell what", "Popular, the default sort"], 0, WINDOW_SCRIPT, True),
        ("prompt: input ends without quitting", [], ["Commands"], 0, "", False),
        ("prompt: pasted text with an invisible mark", [], ["Commands", "!can't tell what"], 0, "﻿q\n", False),
    ]
    log_file = RUN / "search_log.csv"
    for name, arguments, expected, exit_code, typed, in_quick_run in tests:
        if (quick and not in_quick_run) or (only and only.lower() not in name.lower()):
            continue
        rows_before = len(scout.read_log(log_file)[0])
        (RUN / "opened.txt").unlink(missing_ok=True)
        command = [*program, *arguments, "--output", str(RUN)]
        started = time.time()
        try:
            done = subprocess.run(command, input=typed, capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", env=environment, timeout=900, cwd=ROOT)
            output, code = done.stdout + done.stderr, done.returncode
        except subprocess.TimeoutExpired:
            output, code = "(timed out after 15 minutes)", None
        except OSError as error:  # for example, Windows Smart App Control blocking the .exe
            check(f"{name}  (couldn't start)", False, f"{program[0]} couldn't start: {error}")
            return
        seconds = time.time() - started
        flat = " ".join(output.split())  # long messages wrap across lines
        missing = [phrase for phrase in expected if not phrase.startswith("!") and phrase not in flat]
        unwanted = [phrase[1:] for phrase in expected if phrase.startswith("!") and phrase[1:] in flat]
        crashed = "Traceback" in output or "didn't expect" in output
        problems = []
        if missing:
            problems.append(f"missing {missing}")
        if unwanted:
            problems.append(f"shouldn't say {unwanted}")
        if code != exit_code:
            problems.append(f"exit code {code}, expected {exit_code}")
        if crashed:
            problems.append("crashed")
        if name == "--no-log" and len(scout.read_log(log_file)[0]) != rows_before:
            problems.append("saved results anyway")
        if name == "--history" and not ((RUN / "search_history.html").exists() and (RUN / "opened.txt").exists()):
            problems.append("didn't make or open the page")
        check(f"{name}  ({seconds:.0f}s)", not problems, "; ".join(problems))
        report.append(f"    $ {subprocess.list2cmdline(command)}\n    exit code {code}\n"
                      + "\n".join(f"    | {line}" for line in output.splitlines()) + "\n")


def main():
    options = argparse.ArgumentParser(description="Tests for spritescout.py")
    options.add_argument("--offline", action="store_true", help="only run the checks that don't need the internet")
    options.add_argument("--exe", action="store_true", help="also try the main commands with SpriteScout.exe")
    options.add_argument("--only", metavar="TEXT", help="only run the real commands whose test names contain TEXT")
    args = options.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    shutil.rmtree(RUN, ignore_errors=True)
    RUN.mkdir(parents=True)
    started = time.time()
    offline_tests()
    if not args.offline:
        live_tests([sys.executable, str(ROOT / "spritescout.py")], quick=False, only=args.only)
        if args.exe:
            live_tests([str(ROOT / "SpriteScout.exe")], quick=True, only=args.only)

    failed = [name for name, passed, _ in results if not passed]
    summary = (f"\n{len(results) - len(failed)} passed, {len(failed)} failed "
               f"in {(time.time() - started) / 60:.1f} minutes.")
    print(summary)
    print(f"Every command and its output: {RUN / 'report.txt'}")
    (RUN / "report.txt").write_text("\n".join(report) + summary + "\n", encoding="utf-8")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
