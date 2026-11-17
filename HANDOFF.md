# GTA Router: start here

This is the single starting point for anyone picking the project up cold: a
person, or an AI model. Read this page fully before changing anything. It
tells you what the app is, how to run and test it, where everything lives,
what is broken right now, and what to do next.

Last updated: 2026-11-16. If you change the state of the project, update
"State right now" and "What to do next" below in the same change.

---

## 1. What the app is

A trip planner for the Greater Toronto Area that does two things the big map
apps do badly:

1. It suggests trips that mix a short drive or bike ride with transit (park
   at a GO station, bike to a station, Bike Share at the far end), compared
   side by side with transit alone.
2. It shows what each option really costs: fares with transfer discounts,
   gas, and Highway 407 tolls.

How it is built, in one paragraph: the routing is done by
[OpenTripPlanner](https://www.opentripplanner.org/) (OTP), a Java program,
loaded with ten agencies' schedule files (GTFS) and a street map of the
region (OpenStreetMap, plus a small patch of missing park-and-ride lots).
The page in `web/` asks OTP about 21 questions per search (one per "mode
mix", such as "drive to a station" or "Bike Share at the end"), pools the
answers, prices them, and ranks them. OTP knows nothing about fares or
tolls, so the page works those out itself. A second, older copy of OTP runs
only for the "Reach map" (shade everywhere reachable in a given time).

There is no build step, no framework and no installed packages. Python
scripts use the standard library only. Keep it that way.

Words used throughout:

| Word | Meaning |
|---|---|
| OTP | OpenTripPlanner, the routing engine |
| GTFS, "feed", "schedule" | The timetable file each transit agency publishes. Each has a first and a last day of service |
| Graph | The file OTP builds from the map and the schedules (`engine/graph.obj`). Rebuilt whenever either changes |
| Mode mix | One way of combining travel: "transit only", "drive to a station", "Bike Share at the end". Each is one question to the engine |
| Reluctance | A number telling the engine how much to dislike driving. The app asks at several values because each returns a different station |
| Park-and-ride tag | The `park_ride=yes` label in OpenStreetMap. The engine only parks at lots that carry it |
| PRESTO, One Fare | The region's fare card, and the program that makes a second agency's ride free after the first |
| Live feed | An agency's real-time data: vehicle positions, delays, alerts |

---

## 2. Rules before you touch anything

- **The owner is not a programmer.** Explain in plain language. Give direct
  answers first. Say when you are unsure instead of guessing.
- **Ask the owner before anything destructive or slow:** deleting data,
  rebuilding the graph, re-downloading the map, stopping or starting the app
  when they may be using it, pushing to GitHub, merging.
- **The owner's reports of "this route looks wrong" have always been real
  bugs.** Reproduce the exact trip and dig to the cause. Do not explain a
  report away.
- **Do not reopen settled decisions.** `docs/routing-notes.md` and
  `docs/design-rules.md` record what was tried, measured and rejected. If you
  think one is wrong, show new evidence to the owner first.
- **No em dashes in anything a user reads.** Use a colon, a comma or a full
  stop. `bash check-em-dashes.sh` and GitHub check the page source for this.
- **The repository is public.** No names, personal trips, keys or account
  details in code, comments, docs, tests or commit messages.
- **Run the tests before every commit** (section 4). After any change that
  could affect routing, also run the benchmark with the app running.
- **Small verified steps.** One change, test it, look at it in the browser if
  it is visible, commit. Do not stack unverified changes.

How changes go in: make a branch, commit, push, open a pull request, wait for
the GitHub checks to pass, and ask the owner before merging. Commit messages
are a short plain sentence ("Fix the fare on airport trips").

---

## 3. How to run it

First time on a new Mac (installs Java and tools, downloads about 2 GB,
builds the routing graph, 20 to 40 minutes):

```bash
cp metrolinx.env.example metrolinx.env
```

Put a free Metrolinx Open Data key in that file, then:

```bash
bash setup.sh
```

Every day:

```bash
bash run.sh
```

It says READY and opens http://localhost:8081. Stop it with Ctrl+C in that
window, or from any window with:

```bash
bash stop.sh
```

Never run two copies. Each loads a 6 GB engine, and the second makes every
search time out. `run.sh` refuses to start if one is already running.

| Port | What it is |
|------|------------|
| 8081 | The app page (`scripts/web-server.py` serving `web/`) |
| 8080 | The trip engine (OTP 2.9). The app talks to it; you never open it |
| 8090 | The Reach map engine (OTP 2.5). Starts by itself on first use, stops after 15 quiet minutes |

What takes effect when:

| You changed | What is needed |
|---|---|
| Anything in `web/` | Reload the browser page |
| `engine/router-config.json` or `engine/otp-config.json` | Stop and start the app |
| `engine/build-config.json`, the map, or the schedules | Rebuild the graph (`bash refresh.sh`, about 30 minutes) |

Step-by-step versions of every chore are in `docs/runbooks.md`.

---

## 4. How to test it

These need nothing running and take a few seconds. GitHub runs the same ones
on every push.

```bash
node --test tests/core.test.mjs tests/routing.test.mjs
```

```bash
python3 tests/config-guard.py
```

```bash
python3 tests/fare-sync.py
```

```bash
python3 tests/check-feeds.py
```

```bash
python3 tests/record-feeds.py
```

```bash
bash check-em-dashes.sh
```

What each one protects:

| Test | What breaks if it fails |
|---|---|
| `tests/core.test.mjs` | Fares, tolls, ranking, merging of duplicate trips, Toronto time |
| `tests/routing.test.mjs` | The whole "plan a trip" decision, replayed on saved real engine answers. Catches a change that alters which trips are shown, even if nobody remembers why the code is the way it is |
| `tests/config-guard.py` | Engine settings and the park-and-ride patch that routing silently depends on. Each failure says what breaks and what to restore |
| `tests/fare-sync.py` | Every loaded agency has a fare |
| `tests/check-feeds.py` | Tests OF the schedule expiry checker. The checker you actually run is `scripts/check-feeds.py` |
| `tests/record-feeds.py` | Tests OF the live-data recorder (`scripts/record-feeds.py`) |
| `check-em-dashes.sh` | No em dash in the page's source |

With the app running, the routing benchmark asks the real engine for ten
known trips and grades the answers. Run it after any change to routing, to
engine settings, or after a schedule refresh. Every trip should PASS.

```bash
python3 tests/benchmark.py
```

If `tests/routing.test.mjs` says results changed: read its message. If you
meant to change ranking, fares or filters, regenerate the expected files as
it describes and read the difference before committing. If you did not mean
to, your change broke routing. To regenerate:

```bash
UPDATE_ROUTING_SNAPSHOTS=1 node --test tests/routing.test.mjs
```

That keeps the saved engine answers and only rewrites what the page is
expected to make of them. To save fresh engine answers instead (after a
schedule refresh, say, with the app running), run
`node tests/capture-routing-fixtures.mjs` first.

Traps when testing from an AI coding tool (hidden browser tabs freeze the
map, and more) are in `docs/testing-notes.md`.

---

## 5. Where everything lives

| Path | What it is |
|---|---|
| `web/index.html` | Page layout and CSS |
| `web/app.js` | The page's code: map, search boxes, results list, menus |
| `web/core.js` | The rules, with no page or map in them: fares, tolls, the mode mixes, filtering, ranking, Toronto time. Unit-tested |
| `web/*.json` | Data the page loads: GO fare table, toll grid and rates, transit line shapes, subway boarding positions |
| `engine/*.json` | OTP settings for the trip engine. Read `docs/routing-notes.md` before editing: wrong keys fail silently |
| `engine/reach-engine/*.json` | Settings for the Reach map engine: the same routing settings, with live data switched off on purpose |
| `engine/` (not in git) | Downloaded schedules, the map, the two OTP jars, the built graphs |
| `scripts/feeds.sh` | The one list of schedule download links |
| `scripts/check-feeds.py` | Says which schedules have expired |
| `scripts/make_*.py`, `patch_ttc_transfers.py` | Generate the data files and patch the TTC schedule |
| `scripts/*-filter.py` | Clean two broken live feeds so OTP accepts them |
| `scripts/web-server.py` | Serves the page; starts and stops the Reach engine |
| `scripts/record-feeds.py`, `record.sh` | The live-data recorder |
| `data/parking-patch.osc` | Park-and-ride lots missing from OpenStreetMap. Must be re-applied after any fresh map download (`setup.sh` does it) |
| `tests/` | Everything in section 4, plus slower audit tools described in `docs/routing-notes.md` |
| `deploy/` | Scripts for putting the app online. Never run yet |
| `setup.sh`, `run.sh`, `stop.sh`, `refresh.sh` | Install, start, stop, refresh schedules |

The docs, and when to read each:

| Doc | Read it when |
|---|---|
| `docs/runbooks.md` | You need to do a chore: start or stop, refresh schedules, check the recorder, hosting |
| `docs/routing-notes.md` | Before changing anything about routing, engine settings, fares or the mode mixes |
| `docs/design-rules.md` | Before changing anything a user sees |
| `docs/testing-notes.md` | Before testing the page from an AI coding tool |
| `docs/known-issues.md` | Looking for what to fix. Every open problem, with where it is and how to fix it |
| `docs/plans.md` | The four unfinished threads: goals, decisions, next steps |
| `docs/deploy.md` | The hosting setup in detail |

On the owner's computer only, never in the repository: the Metrolinx key
(`metrolinx.env`), everything downloaded or built in `engine/`, the
recordings (`recordings/`), the research study's data, notes and drafts (its
scripts ARE in the repository, see `research/README.md`), an unused
fare calculator (`scripts/costs.py`), the 2005 guide the subway boarding
data came from (a PDF), a design note for an unbuilt feature
(`HANDOFF-go-union-door.md`), and older working notes
(`HANDOFF-archive-*.md`, `ISSUES.md`). The archives are long
session-by-session history. Everything still true in them has been moved
into the docs above, so you should not need them.

---

## 6. State right now (2026-11-16)

Working:

- The app runs on `main`. Schedules were refreshed and both graphs rebuilt on
  2026-11-16. The benchmark passed 10 of 10 afterwards.
- All offline tests pass.

Needs attention soon:

- **Schedules run out again.** GO's schedule ends 2026-11-27 and Durham's on
  2026-11-29. Refresh again in the last week of November
  (`docs/runbooks.md`, "Refresh the schedules"). After that the next ones end
  around 2026-12-19. Check any time with `python3 scripts/check-feeds.py`.
- **The recorder has big holes.** It runs on a laptop that sleeps with the
  lid closed, so about 63% of the hours from Nov 3 to Nov 14 were not
  recorded. It does not restart after a reboot. See `docs/plans.md`,
  section 1.
- **Metrolinx's live feeds were frozen** from 2026-11-14: the GO feeds
  repeated one snapshot and the UP Express feeds were empty. Durham's live
  feed answered with errors from Nov 15. These are faults at the agencies.
  `bash scripts/record.sh status` shows them as STALE or PROBLEM. While they
  last, the app shows no live GO delays.

Not working, known, not urgent:

- Hosting is not live. The free cloud machine has been unavailable since
  September. See `docs/plans.md`, section 4.
- TTC live delays are not possible with the feed TTC publishes
  (`docs/routing-notes.md`).
- Searches take 5 to 14 seconds, and can time out when the computer is short
  of memory (16 GB is tight). Close other apps. Not a code bug.
- Everything else: `docs/known-issues.md`.

Yearly chores: fares change in January or February and in July, and 407 toll
rates every January 1. See the end of "Refresh the schedules" in
`docs/runbooks.md`.

---

## 7. What to do next

In this order. Each has details in the doc named.

1. **Late November: refresh the schedules** (`docs/runbooks.md`). This
   repeats about once a month for as long as the app is used.
2. **Decide where the recorder runs** and move it (`docs/plans.md`,
   section 1). Every week on the laptop loses most of the data.
3. **Decide on hosting**: keep waiting for the free machine, or pay
   (`docs/plans.md`, section 4). The owner's decision.
4. **The research report** needs three things only the owner can do: back up
   `research/`, ask about the survey data's publication terms, choose the
   title (`docs/plans.md`, section 2).
5. **Small fixes** from `docs/known-issues.md`, smallest first. Good first
   ones: the pause between rapid toggle clicks, the search card overlapping
   the first result, Bike Share dock details on touch screens.
6. **The first reliability table** from the recordings (`docs/plans.md`,
   section 1, step 2).

---

## 8. When something looks broken

| What you see | Check this first |
|---|---|
| No trips, or one agency missing from every trip | `python3 scripts/check-feeds.py`. An expired schedule returns nothing, silently |
| Every search times out | Two copies running (`bash stop.sh`, then `bash run.sh`), or the computer is out of memory |
| "Engine failed to start" | `metrolinx.env` missing, a port in use, or no graph in `engine/` (run `bash refresh.sh`) |
| A setting change did nothing | Search the engine's startup output for "Unexpected config parameter". Wrong key names are ignored without an error |
| A test tool prints nothing where it used to print trips | The date it asks about has no schedule. Check dates before believing it |
| Drive-to-station trips vanished after rebuilding from a fresh map | The park-and-ride patch was not applied (`docs/routing-notes.md`). `python3 tests/config-guard.py` checks the scripts still apply it |
| The Reach map does nothing | Its engine needs `engine/otp25.jar` and `engine/graph.obj.otp25`. Its log is `engine/reach-engine/reach.log` |
| The map is blank in an automated browser | The tab is hidden. See `docs/testing-notes.md` |
| Routes look wrong after a schedule refresh | Roll back to the previous graphs (the exact commands are printed at the end of `refresh.sh` and in `docs/runbooks.md`), then investigate |
