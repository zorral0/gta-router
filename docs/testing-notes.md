# Testing notes: traps when testing this app from an AI coding tool on a Mac

Testing the app from a coding tool's built-in browser has several traps. Each
one has caused a long hunt for a bug that was not there. Read this before
concluding that something you changed is broken. Most of these are test
harness artifacts, not app bugs.

## Contents

1. Who runs the app (ask first)
2. Starting it without opening a browser
3. The app must be served over http
4. The preview sandbox cannot read ~/Downloads
5. Hidden tabs freeze the map
6. The file:// tab that steals focus
7. Wrong canvas size, and forcing a render
8. The OS theme toggle does not fire matchMedia
9. The benign startup console error
10. Memory: close heavy apps before timing anything

---

## 1. Who runs the app (ask first)

The owner starts and stops the app himself, with `bash run.sh` in his own
Terminal window. It runs three things: the page server (port 8081,
`scripts/web-server.py`), the routing engine (8080, about 6 GB of memory) and,
only on demand, the Reach map engine (8090, about 3.3 GB).

- ASK before starting, stopping or restarting it. Do not kill his process.
- A restart is needed after any change to `engine/router-config.json` or
  `engine/otp-config.json`. Ask him; then `bash stop.sh` and he runs
  `bash run.sh` again. Page-only changes (`web/*`) need only a browser reload.
- `run.sh` refuses to start if port 8080, 8081 or 8090 is already in use. A
  port clash means a copy is already running. Never start a second copy: it
  would load a second 6 GB engine and make every search time out.
- A graph rebuild (`refresh.sh`, `setup.sh`) must run with the app stopped.

## 2. Starting it without opening a browser

`run.sh` ends by calling `open "http://localhost:8081"`, which pops a browser
window on the owner's screen. To test without that, put a do-nothing `open`
first on the PATH for that one command. For example, from the repository root:

```
d=$(mktemp -d) && printf '#!/bin/sh\nexit 0\n' > "$d/open" && chmod +x "$d/open"
PATH="$d:$PATH" bash run.sh
```

(Only do this if the owner has agreed that you start it. See section 1.) The
engine takes about 30 to 60 seconds to load; `run.sh` prints "READY" when it
answers. Stop it with Ctrl+C in that window or `bash stop.sh`.

## 3. The app must be served over http

Open the app at `http://localhost:8081`, never by double-clicking
`web/index.html` (a `file://` address). The page fetches its data files
(`transit-lines.json`, `go-fares.json`, `toll-roads.json`, `toll-rates.json`,
`subway-boarding.json`) with `fetch`, and sends trip searches to `/otp/...` on
its own address, which `scripts/web-server.py` passes on to the engine.
A plain static file server shows the map but cannot plan trips unless something
forwards `/otp/` to port 8080. Serving from the owner's own server at
`http://localhost:8081` worked fine in testing.

## 4. The preview sandbox cannot read ~/Downloads

macOS privacy protection (TCC) blocks the coding tool's preview server from
reading the Downloads folder, so a server started inside the repository shows
nothing or errors. Workaround: serve a COPY of `web/` from the session's
scratchpad folder (for example `scratchpad/webroot/`), using a
`.claude/launch.json` entry that points there (that is a local settings file
of the Claude Code tool, not part of this repository; other tools have their
own way to start a preview server). Then:

- Copy again (`cp -R web/. <webroot>/`) after EVERY edit, or you will test old
  code.
- The scratchpad path is different for every session, so update
  `.claude/launch.json` when a new session starts. That file therefore always
  shows as modified in git. It is not real work; do not commit it.
- Use `"autoPort": true` and read the `PORT` environment variable. A dead
  server from another session once held port 8000.

If the owner's real server is running, using `http://localhost:8081` avoids all
of this.

## 5. Hidden tabs freeze the map

A browser tab that is not visible (a background tab, or one behind another)
stops `requestAnimationFrame`, and MapLibre stalls style and tile loading. A
screenshot wakes the tab. NEVER trust "it didn't load" or "it didn't render"
until you know the tab was visible. Check `document.visibilityState` first.

Symptoms you will see, each of which has cost time:

- `map.easeTo(...)` seems to record the call but never animates, so a
  tap-to-north compass looks like a no-op. `setBearing` is immediate and works
  regardless.
- Map canvas screenshots come back blank, or show stale frames for a whole
  session and refuse to repaint a theme change even after a hard reload.
  Verify theme changes by reading the live style values (for example
  `map.getStyle()` paint properties), not by looking at pixels.
- MapLibre's own scroll-zoom easing runs on `requestAnimationFrame`, so a
  scripted scroll-zoom that "does nothing" is usually this throttle, not a
  regression. Confirm with a real scroll through the `computer` tool.
- CSS entrance animations freeze at their first frame (often opacity 0), so
  elements look missing. Before a proof screenshot, inject
  `* { animation: none !important }`.
- Synthetic clicks may never reach MapLibre's handlers. Drive the app by
  calling its own functions instead (for example `setPoint(...)` and `plan()`
  in `web/app.js`).

The app guards its own animations with `document.hidden` for exactly this
reason. Keep that pattern.

## 6. The file:// tab that steals focus

The editor's post-edit hook can open a second browser tab on
`file:///.../web/index.html` and bring it to the front. The `localhost` tab you
are testing then goes hidden (`document.visibilityState === "hidden"`), and
MapLibre never finishes loading the style: `map.getStyle()` returns
`undefined`, `isStyleLoaded()` stays false forever, and nothing paints. It
looks exactly like a bug you just wrote.

Before any visual check: close the `file://` tab, select the `localhost` tab,
and check `document.visibilityState` is "visible".

## 7. Wrong canvas size, and forcing a render

In a hidden tab the map canvas can also start at the wrong size (for example
400 by 300 instead of the real window). To get a correct screenshot:

1. Make the tab visible (sections 5 and 6).
2. Call `map.resize()`.
3. Force a repaint with `map.triggerRepaint()`. Call it again a few times as
   tiles arrive; `map.areTilesLoaded()` tells you when they are in.

Older notes used `map._render(0)` for step 3. The page now uses MapLibre 6
(vendored in `web/vendor/`), and `map._render` no longer exists there (from
older notes, not re-verified). Use `triggerRepaint()`. Then wait for the
`idle` event before screenshotting.

## 8. The OS theme toggle does not fire matchMedia

Switching the operating system between light and dark does not fire the
`matchMedia("(prefers-color-scheme: dark)")` `change` event inside the preview
browser. The map therefore keeps its old style until `applyLook()` is called by
hand. On a real Mac the listener (`darkMql` in `web/app.js`) swaps it
automatically. This is a harness quirk, not an app bug. To test the dark map,
call `applyLook()` after changing the theme.

## 9. The benign startup console error

Every page load logs one pair of console errors that read like
`[object Object]` and `Error`. They have been there for a long time and are
unrelated to recent changes. Do not chase them unless a NEW error appears
beside them. Compare the console against a fresh load of the unchanged code
before blaming your edit.

## 10. Memory: close heavy apps before timing anything

The owner's Mac has 16 GB of memory and is usually short of it. The main
engine alone wants about 6 GB; macOS had been compressing most of it, and a
whole search then ran many times slower, and once timed out. With only the
main engine running there was about 70 MB free.

Before you time a search, benchmark or build:
- Ask the owner to quit heavy apps (browsers with many tabs, chat apps, virtual
  machines). Do not quit them yourself.
- Check for a second copy of the engine (`pgrep -f "otp.jar --load"`).
- Look at `top -stats pid,mem,cmprs`. A large "compressed" figure for the
  engine means it is being starved. `ps` RSS is misleading (it shows tiny
  numbers).
- Expect the FIRST search after idle to be the slowest. Time warm searches.
- Do not conclude a code change made things slower or faster from one run on
  a swapping machine; repeat it.

Engine checks in the same spirit: after any config change, search the engine's
startup output for `Unexpected config parameter` (there must be none), and
re-run `python3 tests/benchmark.py` after any routing change
(see `docs/routing-notes.md`).
