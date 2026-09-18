# Helping out

You don't need to be a programmer to help. Telling me what SpriteScout got
wrong about your own projects is the most useful thing there is, because every
tip it gives comes from measuring real search results.

## Something looks wrong

Open an issue and say which version you're on, which download you used, and
what you gave it. If a file whose name starts with `error-` appeared in the
`output` folder, paste it in — it has the details.

## An idea

Open an issue for that too. The question I ask about every idea is: does it
help someone find projects that search is hiding?

## Changing the code

There's nothing to install. Python 3.8 or newer runs it:

```
python spritescout.py        the text version
python spritescout_gui.py    the GUI version
```

Everything lives in `spritescout.py`, apart from the page the GUI version
serves, which is `gui.html` plus `spritescout_gui.py` on top.

Run the tests before you send anything:

```
python tests/run_tests.py --offline     quick, no internet needed
python tests/run_tests.py               also runs every command against Scratch
```

Both have to pass, and new behaviour needs a test. Add yours next to the ones
it belongs with in `tests/run_tests.py`; each is one `check("what it should do",
it_does_that)` line.

A few habits the rest of the code keeps to:

- The standard library only, so a download stays one file with nothing to install
- Nothing that writes to Scratch: it reads public data and never logs in
- Messages say what to do about the problem, in words a Scratcher would use
- Anything new goes in both versions, or it doesn't go in
