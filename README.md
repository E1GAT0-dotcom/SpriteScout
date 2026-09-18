<img src="icon.png" alt="SpriteScout" width="180">

# SpriteScout

[![Build](https://github.com/E1GAT0-dotcom/SpriteScout/actions/workflows/build.yml/badge.svg)](https://github.com/E1GAT0-dotcom/SpriteScout/actions/workflows/build.yml)

I kept sharing games that nobody could find, so I made this to see whether my
Scratch projects and studios actually show up in Scratch search, and what it
would take to rank higher.

It only reads public data through Scratch's API. It never logs in, never posts,
and never changes anything on Scratch.

Not affiliated with Scratch, the Scratch Foundation or MIT.

## Download

The [releases page](https://github.com/E1GAT0-dotcom/SpriteScout/releases) has a
download for each system:

- Windows: `SpriteScout-windows.exe`, double-click it
- Mac (Apple Silicon): `SpriteScout-mac`, right-click it the first time and
  choose Open, since it isn't signed
- Linux: `SpriteScout-linux`, `chmod +x` it and run it from a terminal

On Windows the file isn't signed either, so some PCs block it or warn about it.
If that happens, download the source and double-click `SpriteScout.bat`, which
runs the same tool with Python. Any system with Python 3.8 or newer can skip
the download entirely:

```
python spritescout.py
```

Type `help` in the window to see every command and flag.

Once a day it asks GitHub whether a newer version is out, and says so if there
is one. `--no-update-check` turns that off.

### The window version

There's also a version with a window, which opens a page in your browser
instead of a text prompt. It's early: it checks a username, a project or a
studio and shows the results as a colour-coded list. The rest of the features
are still console-only. Run it from the source with:

```
python spritescout_gui.py
```

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
| `--titles "A" "B"` | Compares titles you're thinking about before you rename |
| `--find-words` | Lists searches your project already comes up for |
| `--contents` | Checks every project in a studio |
| `--history` | A page with charts of your ranks over time |
| `--scan` | Keeps looking past where a check normally stops (press q to stop) |

Results go in the `output` folder: `search_log.csv` keeps every check, so later
checks tell you what moved, and `search_history.html` is the chart page.

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
- Search stops at 10,000 results. Past that, nobody can reach you by scrolling.

## Tests

```
python tests/run_tests.py            offline checks, then every command against Scratch
python tests/run_tests.py --offline  only the checks that don't need the internet
python tests/run_tests.py --exe      also try the main commands with SpriteScout.exe
```

Everything the tests make lands in `output/test-run`, and `report.txt` there has
every command with its full output.

## Building the .exe

```
pip install pyinstaller
pyinstaller --onefile --console --name SpriteScout spritescout.py
```

It's one file, `spritescout.py`, with nothing to install.
