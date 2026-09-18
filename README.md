<img src="icon.png" alt="SpriteScout" width="180">

# SpriteScout

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
