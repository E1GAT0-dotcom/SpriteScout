<img src="icon.png" alt="SpriteScout" width="180">

# SpriteScout

[![Build](https://github.com/E1GAT0-dotcom/SpriteScout/actions/workflows/build.yml/badge.svg)](https://github.com/E1GAT0-dotcom/SpriteScout/actions/workflows/build.yml)
[![Latest release](https://img.shields.io/github/v/release/E1GAT0-dotcom/SpriteScout?label=download)](https://github.com/E1GAT0-dotcom/SpriteScout/releases/latest)

I kept sharing games that nobody could find, so I made this to see whether my
Scratch projects and studios actually show up in Scratch search, and what it
would take to rank higher.

It only reads public data through Scratch's API. It never logs in, never posts,
and never changes anything on Scratch.

Not affiliated with Scratch, the Scratch Foundation or MIT.

## Download

There are two versions on the
[releases page](https://github.com/E1GAT0-dotcom/SpriteScout/releases), and they
do the same checks. Pick one:

| System | GUI version | Text version |
|---|---|---|
| Windows | `SpriteScout-gui-windows.exe` | `SpriteScout-windows.exe` |
| Mac (Apple Silicon) | `SpriteScout-gui-mac.dmg` | `SpriteScout-mac.zip` |
| Mac (Intel) | `SpriteScout-gui-mac-intel.dmg` | `SpriteScout-mac-intel.zip` |
| Linux | `SpriteScout-gui-linux.zip` | `SpriteScout-linux.zip` |

Not sure which Mac you have?  → About This Mac. "Apple M1" and up means Apple
Silicon; "Intel" means the Intel downloads.

> [!TIP]
> **Early testing:** for the fewest bugs, use the Windows text version,
> `SpriteScout-windows.exe` — it's the most tested. The GUI version and the Mac
> and Linux downloads work too, but they're newer, so they're more likely to
> have bugs. If you try them, bug reports are really appreciated:
> [tell me what went wrong](https://github.com/E1GAT0-dotcom/SpriteScout/issues/new/choose).

The **GUI version** opens in a window of its own, with tabs and buttons and no
typing of commands. Close the window and it quits. Nothing is uploaded: the page
inside the window comes from the program running on your own computer, and
closing it stops there.

The **text version** runs in a terminal and takes typed commands. It's smaller,
it's what the tests drive, and it's handy if you like the keyboard.

> [!NOTE]
> **If a virus scanner complains:** one or two of the seventy-odd scanners on
> VirusTotal flag the Windows downloads. SpriteScout is Python packed into a
> single file, so that there's nothing to install, and a few scanners guess from
> that shape alone — every program built this way looks the same to them. None of
> them name anything they found inside it, and the rest, Microsoft Defender
> included, come back clean. Every release lists each download with a link to its
> own report, so you can see exactly who said what, and
> [Check it yourself](#check-it-yourself) shows how to scan it or check the
> fingerprint yourself.

### Opening it the first time

- **Mac, GUI version:** open the `.dmg` and drag SpriteScout onto the
  Applications folder beside it. It has to go there: macOS runs an app you
  downloaded from a hidden read-only copy of itself until you move it.
- **Mac, text version:** unzip it and keep it wherever you like — Downloads is
  fine, it doesn't need Applications. You get a file called `SpriteScout` that
  opens in Terminal when you double-click it.
- **Getting past "Apple could not verify SpriteScout":** that appears the first
  time, because the app isn't signed yet. Click **Done**, then open **System
  Settings → Privacy & Security**, scroll to the bottom, and click **Open
  Anyway** next to SpriteScout. Confirm once and it opens normally from then on.
  (On macOS 14 and older you can instead right-click it and choose **Open**.)
- **Windows:** if SmartScreen says it protected your PC, click **More info**, then
  **Run anyway**. If Windows blocks it outright, download the source and
  double-click `SpriteScout.bat`, which runs the same tool with Python.
- **Linux:** unzip it and run `./SpriteScout`. Nothing blocks it.

The Mac and Linux downloads come as a disk image or a zip on purpose.
Downloading a program strips its permission to run, so a bare file opens as a
page of gibberish instead; opening the disk image or unzipping gives it back.

### Running it

Any system with Python 3.8 or newer can skip the downloads:

```
python spritescout_gui.py    the GUI version
python spritescout.py        the text version
```

The window is drawn by a browser you already have — Edge, Chrome, Brave,
Vivaldi, Opera or Chromium — with none of the browser around it, so there's
nothing to install. On a computer with none of those it opens in a tab instead,
and says so at the top of the page.

If anything stops it starting, it says what, in a message box rather than a
console nobody can see: a damaged download, a folder it can't save in, a
firewall blocking its own server, or no browser it could open.

Type `help` in the text version to see every command and flag.

Once a day it asks GitHub whether a newer version is out: the text version says
so when it starts, and the GUI version puts a bar at the top of the page.
`--no-update-check` turns that off, as does the tickbox in Settings.

### What the GUI version has

Each tab is one of the checks, and results appear as they arrive:

- **Check** — a username, project or studio, colour-coded by how findable it
  is, or every project inside a studio
- **Search words** — where something ranks for words people type, and what
  would move it up
- **Try titles** — suggests titles it could reach the first screen with, or
  says how crowded the ones you're considering already are
- **Find studios** — studios about a topic that anyone can add projects to
- **Where it ranks** — the searches something already comes up for
- **History** — the chart page of every check you've run
- **Settings** — every setting the text version takes: the sort, how deep to
  look (and how deep in Trending), what counts as the first screen, how many
  projects to check, how many results the finders list, what counts as new and
  as active, the wait between requests, whether to include studios, whether to
  show tips, whether to save results, and whether to mention new versions

**Keep looking** appears on anything the check stopped short of, and carries on
to the end of search. **Stop** ends a long check without losing the rows that
are already there.

## What it looks like

Checking my own account:

```
Checking 6 shared projects by E1GAT0_, looking through up to 200 search results each.

  [1/6] Not in search yet    -       The Boring Legal Machine V2
  [2/6] Easy to find         #1      E1GAT0_'s suggestion box
  [3/6] Not in search yet    -       Fish Clicker V1
  [4/6] Easy to find         #1      Ice Drifter v4 FASTER AND COMPRESSED
  [5/6] Easy to find         #3      Once upon a time there was a lovely princess. But…
  [6/6] Easy to find         #1      Fishtale - Chapter One

Summary for E1GAT0_
  Easy to find         4
  Not in search yet    2

Not in search yet
  Not in search, but shared in the last 14 days. New projects can take a while
  to show up, so check again in a few days.
    The Boring Legal Machine V2  https://scratch.mit.edu/projects/1256400969/
    Fish Clicker V1  https://scratch.mit.edu/projects/1380420363/
```

`--suggest` looks for a title it could actually be found by. This project was
past result 200 for its own name:

```
  Now: "Clock"
    Not on the first screen. 40+ projects match, and the first screen starts
    at 350 loves. This one has 2 loves.

  Titles it could be on the first screen for, busiest search first:

  1. "Clock Simulator"
     40+ projects match, and the first screen starts at 2 loves. This one has
     2 loves.
```

Adding words checks a search people would actually type, and says what would
help:

```
  Popular, the default sort: #46
    First screen: 9,994-142,712 loves, 1-4 word titles, shared since 2016-03-26

  Ways to rank higher
  - Keep the title short. In Popular, a short title that matches the search
    often beats projects with far more loves. This one has 6 words, and titles
    on the first screen have about 2.
```

## Using it

What follows is the text version, where you type things. The GUI version has all
of it as tabs and buttons instead.

Give it a username, a project or a studio:

```
griffpatch                    every shared project, plus the studios they host
scratch.mit.edu/projects/123456789/   one project, searched by its title
studio 12345                  one studio, searched by its title
123456789 pizza tycoon        where a project ranks when people search that
```

Every project or studio comes back as one of these:

| Result | What it means |
|---|---|
| Easy to find | In the first 16 results, which is all most people look at |
| Buried | In search, but further down |
| Not in search yet | Shared in the last 14 days, so search hasn't caught up |
| Missing from search | Search listed every match for the title and it wasn't there |
| Not in top N | So many things match the title that the check stopped |

There's more, but only if you ask for it:

| Flag | What it does |
|---|---|
| `--find-studios WORDS` | Active studios about WORDS that anyone can add projects to |
| `--suggest` | Titles it could reach the first screen with, busiest search first |
| `--titles "A" "B"` | Compares titles you're thinking about before you rename |
| `--find-words` | Lists searches your project already comes up for |
| `--contents` | Checks every project in a studio (a tickbox in the GUI version) |
| `--history` | A page with charts of your ranks over time |
| `--scan` | Keeps looking past where a check normally stops (press q to stop) |
| `--uninstall` | Moves SpriteScout and everything it saved to the Trash |

Results go in the `output` folder next to the program: `search_log.csv` keeps
every check, so later checks tell you what moved, and `search_history.html` is
the chart page.

The Mac app keeps them in `~/Library/Application Support/SpriteScout` instead,
because an app is never allowed to write inside itself. The same folder (or
`%LOCALAPPDATA%\SpriteScout` on Windows) is where results go whenever the folder
next to the program can't be written to. The GUI version's Settings tab says
where they are and has a button to open the folder.

## Removing it

There's no installer, so there's nothing to uninstall in the usual sense — but
the Mac GUI version has to live in the Applications folder, and both versions
keep results in a folder of their own, so SpriteScout can round it all up for
you:

- **GUI version:** Settings → **Remove it**. It lists the app and everything it
  saved, with sizes, and moves the lot when you say so.
- **Text version:** type `uninstall`, or run it with `--uninstall`.

Nothing is erased. Everything goes to the Trash (the Recycle Bin on Windows), so
you can put it back if you change your mind. On Windows the program is in use
while it's running, so it clears out the saved results and leaves you to delete
the `.exe` once you've closed it.

## What I found out about Scratch search

The tips it gives come from measuring real search results, not guessing:

- Every word someone types has to be in the title. Words in the instructions
  almost never match, and usernames never do.
- Popular, the default sort, isn't only about loves. A short title that matches
  the search often beats a project with twice the loves: when that happened, the
  winner had the shorter title 87-95% of the time. Studios work the same way
  with followers, where shorter titles won 96% of those pairs.
- Trending is mostly about being new. Its first screen was nearly all projects
  shared in the last few weeks, some with only a handful of loves. For studios
  it's recent activity, like projects being added.
- Some words find nothing at all. "horror", "scary" and "fnaf" return zero
  results, for projects and studios.
- Search pages aren't reliable. When results tie, some show up twice and others
  get skipped, so SpriteScout looks again with the page breaks moved before it
  says anything is missing.
- No single common word is within reach. Every one-word search I measured —
  game, simulator, clicker, tycoon, obby, idle and thirty more — has a first
  screen held by projects with hundreds or thousands of loves. The cheapest,
  "idle", still needs 128. Pairing a word of your own with one people search is
  what gets you on the first screen, which is what `--suggest` looks for.
- Search stops at 10,000 results. Past that, nobody can reach you by scrolling.

## Check it yourself

Don't take my word that a download is safe — look for yourself. None of this
needs an account.

**Scan it.** Drag the file onto
[VirusTotal](https://www.virustotal.com/gui/home/upload) and about seventy virus
scanners read it in under a minute, free. If someone has scanned that exact file
already, pasting its fingerprint into the search box there brings up the report
without uploading anything.

A few scanners flag any program packed into a single file, whoever wrote it, with
a name like "Wacatac" or "MalwareX-gen" — those are guesses from the shape of the
file, not something found inside it. The ones that do it are listed on each
build's summary in the [Actions
tab](https://github.com/E1GAT0-dotcom/SpriteScout/actions), along with everything
that came back clean.

**Check it's the real file.** Every release carries a `SHA256SUMS.txt` listing
the fingerprint of each download. This prints the fingerprint of your copy:

```
certutil -hashfile SpriteScout-windows.exe SHA256    on Windows
shasum -a 256 SpriteScout-mac.zip                    on a Mac or Linux
```

If it matches, nothing changed on the way to you.

**Read it.** Nothing here is a mystery: the downloads are built by GitHub from
the code in this repository, on GitHub's own computers, and the log of every
build is public on the
[Actions tab](https://github.com/E1GAT0-dotcom/SpriteScout/actions).

## Privacy

SpriteScout has no account to sign into and collects nothing about you. It only
ever talks to two places over the internet:

- **Scratch** (`api.scratch.mit.edu`): the usernames, projects, studios and search
  words you ask it to check, so it can look them up in Scratch's public data. It
  doesn't sign in, so it never sees anything that isn't already public. The
  History page also shows project pictures, which your browser fetches from
  Scratch's own image server (`uploads.scratch.mit.edu`).
- **GitHub** (`api.github.com`), at most once a day: a request for the latest
  version number, so it can tell you when there's an update. Nothing about you
  goes with it. Turn it off with `--no-update-check`, or untick "Tell me about
  new versions" in the GUI version's Settings.

Your results stay on your computer, in the folder described under
[Using it](#using-it).

## Code signing policy

- Every download is built by GitHub Actions from the source code in this
  repository, never on anyone's own computer, and the log of each build is
  public on the [Actions tab](https://github.com/E1GAT0-dotcom/SpriteScout/actions).
- **Team:** [E1GAT0-dotcom](https://github.com/E1GAT0-dotcom) is the author, the
  reviewer and the approver. Changes from anyone else arrive as pull requests,
  and are reviewed before they're merged.
- The Windows programs aren't signed yet. Once they are, every signing request
  will be approved by hand before anything is signed.

## Helping out

Telling me what it got wrong about your own projects is the most useful thing
there is. [CONTRIBUTING.md](CONTRIBUTING.md) says what to include, and how to
run the tests if you want to change the code.

## Tests

```
python tests/run_tests.py            offline checks, then every command against Scratch
python tests/run_tests.py --offline  only the checks that don't need the internet
python tests/run_tests.py --exe      also try the main commands with SpriteScout.exe
```

Everything the tests make lands in `output/test-run`, and `report.txt` there has
every command with its full output.

## Building it yourself

```
pip install pyinstaller
pyinstaller --onefile --console --name SpriteScout spritescout.py
pyinstaller --onefile --windowed --name SpriteScout --add-data "gui.html;." --add-data "icon.png;." spritescout_gui.py
```

On Mac and Linux the `--add-data` separator is `:` instead of `;`. GitHub builds
all six downloads on every release; see
[.github/workflows/build.yml](.github/workflows/build.yml). For the Windows
builds it first runs `tools/windows_version.py`, which gives each program the
name and version Windows shows in its Properties.

Nothing to install: `spritescout.py` is the whole tool, and
`spritescout_gui.py` serves `gui.html` on top of it. Standard library only.
