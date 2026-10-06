# Building the standalone desktop app

This produces a folder with `MatchdayDB` (or `MatchdayDB.exe` on Windows) at
the top level and a `_internal/` folder beside it holding everything it
needs. Zip that folder and hand it out — no Python, no terminal, no `pip
install` for whoever receives it. They unzip it, double-click the one file
at the top, their browser opens to the dashboard, and the first thing they
see is the existing "connect your API key" screen.

PyInstaller does **not** cross-compile: a Windows build has to run on
Windows, and a macOS build has to run on macOS. There's no way to produce
either from Linux (this was built and proven end-to-end on Linux as a
proof of concept, but that output only runs on Linux — see "Linux" below).

## One-time setup (on the machine you're building on)

```
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS / Linux
pip install -r requirements-dev.txt
```

## Build

From the repo root, with that venv active:

```
pyinstaller packaging/matchdaydb.spec --distpath dist --workpath build --noconfirm
```

Output: `dist/MatchdayDB/` containing:
- **Windows:** `MatchdayDB.exe` + `_internal/`
- **macOS:** `MatchdayDB` + `_internal/` (an unsigned Unix binary — see the
  Gatekeeper note below)
- **Linux:** `MatchdayDB` + `_internal/`

Zip the whole `dist/MatchdayDB` folder (not its contents only — keep the
folder itself) and that's the download.

## What to expect at runtime

- First launch creates a per-user data folder outside the app bundle, so
  reinstalling or moving the app folder never wipes anyone's database or
  remembered API key:
  - Windows: `%APPDATA%\MatchdayDB`
  - macOS: `~/Library/Application Support/MatchdayDB`
  - Linux: `~/.local/share/MatchdayDB`
- A console/terminal window stays open while it runs — that's intentional,
  it's the "stop" button (closing it stops the server) and where a startup
  error would show up, since there's no other UI for that yet. See "Going
  further" below if a fully window-free build matters more than that.
- The dashboard needs one internet connection the very first time it runs,
  to download the ~90MB similarity-search model (it's cached in the data
  folder afterward and works offline from then on, aside from live
  football-data.org syncing which always needs a connection).
- It defaults to `http://127.0.0.1:8000` and falls back to a random free
  port automatically if 8000 is already taken on that machine.

## macOS Gatekeeper

An unsigned app downloaded from the internet gets blocked by Gatekeeper on
first launch ("MatchdayDB can't be opened because it is from an
unidentified developer"). Without an Apple Developer account ($99/yr) to
sign and notarize the build, the workaround for whoever receives it is:
right-click (or Control-click) the file → **Open** → **Open** again in the
dialog that follows. That's a one-time step per machine. This is the same
experience nearly every small, free, unsigned Mac app has — it's not
something this build is doing wrong.

## Windows SmartScreen

Similarly, an unsigned `.exe` from the internet may show "Windows
protected your PC" the first time. The receiving user clicks **More
info** → **Run anyway**. A code-signing certificate removes this but
costs money and isn't necessary to get the app working.

## Antivirus false positives

PyInstaller-built executables are flagged by some antivirus engines more
often than ordinary installers, purely because the bundling technique
looks similar to how malware packs itself (nothing to do with what's
actually inside). If this bites, the fix is either code-signing the
build or submitting it to the antivirus vendor as a false positive — not
a MatchdayDB code problem.

## Going further (not done yet, optional)

- **Icon:** `matchdaydb.spec`'s `icon=None` can point at a `.ico`
  (Windows) / `.icns` (macOS) file once one exists.
- **No console window:** replacing the visible console with a system-tray
  icon (e.g. via `pystray`) for "open" / "quit" would let `console=False`
  be set in the spec, at the cost of a bit more code and one more
  dependency. Worth doing if the console window turns out to bother
  people; skipped for now to keep the first version simple.
- **Bundling the search model:** right now it downloads once on first run.
  It could instead be pre-downloaded during the build and bundled in, so
  even the first launch needs no internet — bigger download up front,
  smaller build effort saved later. Only worth it if "needs internet once"
  turns out to be a real problem for people using this.
