# Runbooks

Four jobs you will need to do more than once. Each one is a list of numbered
steps. Run the commands in the Terminal app, one block at a time. Each step
says what you should see and what to do if you do not.

1. [Start and stop the app](#1-start-and-stop-the-app)
2. [Refresh the schedules](#2-refresh-the-schedules)
3. [Check the live-data recorder](#3-check-the-live-data-recorder)
4. [Hosting (not live yet)](#4-hosting-not-live-yet)

Every command assumes your Terminal is inside the `gta-router` folder, the
one that holds `run.sh`. If you opened a new Terminal window, go there first:

```bash
cd ~/Downloads/gta-router
```

(If you keep the folder somewhere else, use that folder instead.)

---

## 1. Start and stop the app

**When to do this:** whenever you want to use the app on your computer, and
before and after any rebuild.

**How long it takes:** 30 to 60 seconds to start. Stopping takes a few seconds.

### Start it

1. Start everything.

   ```bash
   bash run.sh
   ```

   You should see lines about loading the transit network, then:
   `READY - opening http://localhost:8081 (bookmark it!)`. Your browser opens
   the app by itself.

   Leave this Terminal window open. The app runs inside it. The engine's
   messages scroll past in this window, so it is the first place to look when
   something is wrong.

2. If you do not see READY after two minutes, scroll up in the window and look
   for the first line that says an error. Then go to "If the engine fails to
   start" below.

3. The app's address is `http://localhost:8081`. Bookmark it. It works on this
   computer only.

### What "already running" means

If you see `GTA Router is already running (something is using port ...)`,
a copy is already going. Do not start another. Open `http://localhost:8081`
in your browser, or stop the first copy (next section) and start again.

Never run two copies. Each routing engine uses about 6 GB of memory. A second
copy used up the memory once and made every search time out.

### Stop it

1. Press Ctrl+C in the window where `run.sh` is running. That stops
   everything.

2. If you cannot find that window, open any Terminal window and run:

   ```bash
   bash stop.sh
   ```

   You should see `GTA Router is stopped.` If you see
   `Something else is still using port(s) ...`, the thing holding the port may
   not be GTA Router. See "A port is in use" below.

### The three ports

| Port | What it is |
|------|------------|
| 8081 | The app page. This is the address you use. |
| 8080 | The routing engine (OpenTripPlanner 2.9). The app talks to it behind the scenes. You never need to open it. |
| 8090 | The Reach map engine (OpenTripPlanner 2.5). It only draws the Reach map. |

All three answer this computer only.

### The Reach map engine starts by itself

You do not start the Reach engine. It starts the first time you use the Reach
map (about 10 seconds, and the page waits and retries). It uses about 3.3 GB.
It stops by itself after 15 quiet minutes. The page server prints a line in the
`run.sh` window when it starts or stops it.

### Where the logs are

| Log | What is in it |
|-----|---------------|
| The `run.sh` Terminal window | The main engine's messages and the page server's messages. |
| `engine/reach-engine/reach.log` | The Reach engine's messages. |
| `engine/go-alerts.log` | One line a minute from the GO alerts cleaner. |
| `engine/drt-rt.log` | One line a minute from the Durham live-delay cleaner. |

To read the end of a log:

```bash
tail -n 30 engine/reach-engine/reach.log
```

### If the engine fails to start

You will see `Engine failed to start - see errors above.` Check these, in this
order.

1. **Missing key file.** The first thing `run.sh` prints is
   `Missing metrolinx.env. Copy metrolinx.env.example to metrolinx.env ...`.
   Make the file, then open it and put your free Metrolinx Open Data key after
   `METROLINX_KEY=`. Never share this file. It is kept out of GitHub on purpose.

   ```bash
   cp metrolinx.env.example metrolinx.env
   ```

2. **Missing graph.** The graph is the built transit network, the file
   `engine/graph.obj`. If it is gone, the engine cannot load. Build it again
   with the refresh runbook below (it builds both graphs and needs about
   8 GB of free memory). A full `bash setup.sh` also builds it.

3. **A port is in use.** Something else holds 8080, 8081 or 8090. See what it
   is (change the number to the port that `run.sh` named):

   ```bash
   lsof -nP -iTCP:8080 -sTCP:LISTEN
   ```

   If it is an old copy of the app, `bash stop.sh` clears it. If it is some
   other program, close that program.

### If searches time out

"This is taking too long" or searches that never finish usually mean the
computer is out of memory. Close other apps, especially browsers with many
tabs. Check that you are not running two copies (see above). If it is still
slow, restart the computer, then run `bash run.sh` first, before opening
other apps.

---

## 2. Refresh the schedules

**When to do this:** when `python3 scripts/check-feeds.py` says any feed is
EXPIRED, NOT STARTED YET or MISSING, or about every month (TTC changes its
schedule about every 6 weeks). Also when the app shows its red "schedule data
runs out" warning.

**How long it takes:** 15 to 35 minutes of waiting, mostly the two graph
builds. It took 35 minutes on 2026-11-16 on a 16 GB laptop with other apps
open; the "~4 min" the script prints for each build is the best case. You need about 8 GB of free memory, so close other apps first.

Why it matters: when an agency's schedule runs out, the app quietly finds no
trips for that agency. Nothing tells you.

### Steps

1. See what has run out. This only reads files, so it is safe any time.

   ```bash
   python3 scripts/check-feeds.py
   ```

   You get one line per feed with its first day, last day, days left and a
   verdict:

   - `ok`: fine.
   - `EXPIRES SOON`: 14 days or fewer left. Plan a refresh.
   - `EXPIRED`: the schedule has run out. Trips for that agency are missing now.
   - `NOT STARTED YET`: its first day is still in the future. See step 6.
   - `MISSING`: the file is not there, or it cannot be read.

   The last line says in words what to do. If everything says `ok`, stop here.

2. Stop the app and close other apps. `refresh.sh` refuses to run while the
   app is running.

   ```bash
   bash stop.sh
   ```

   You should see `GTA Router is stopped.` If `refresh.sh` later says
   `The app is still running`, run this again.

3. Run the refresh. It does not need `sudo` or a password.

   ```bash
   bash refresh.sh
   ```

   It prints four stages:

   - `=== 1/4 Downloading fresh schedules ===` downloads the ten schedule
     zips. Each feed prints `OK: <file>` or a `WARNING` (see step 4).
   - `=== 2/4 Re-applying the TTC transfer patch + GO fare table ===` patches
     the TTC feed and rebuilds the GO fare table and the map lines. Then it
     runs the schedule check again and prints the same table as step 1. If
     all is well it goes straight on. If not, see step 6.
   - `=== 3/4 Rebuilding the reach-map graph (2.5 engine, ~4 min) ===` builds
     the Reach map's graph. Lots of text scrolls past. This is normal.
   - `=== 4/4 Rebuilding the main graph (2.9 engine, ~4 min) ===` builds the
     main graph.

   It ends with `DONE. Now:`. If instead you see `SOMETHING FAILED`, your
   previous graphs are safe. Read the error just above it, then see "Roll
   back" below.

4. If a download fails. You will see `WARNING: <file> download failed or
   looked broken - KEEPING the old copy.` The old copy is still in place, so
   nothing is lost. The usual cause is that the agency moved the link. Each
   feed in `scripts/feeds.sh` has a comment above it that says where to look
   up the new link. Open the file, replace that feed's link, save, and run
   `bash refresh.sh` again:

   ```bash
   open -e scripts/feeds.sh
   ```

   You can also download the zip by hand in your browser and save it as
   `engine/<name>-gtfs.zip` (for example `engine/yrt-gtfs.zip`). If the
   automatic download then fails, the refresh keeps your copy.

   If you see `PROBLEM: <file> download failed ... and there is no older
   copy`, that agency has no schedule at all and the build will fail until you
   fix the link or save a copy by hand.

5. Wait for `DONE`. Do not close the window or let the computer sleep. If the
   computer sleeps, the build stops.

6. The warning "the schedules above are not all usable today". If any feed is
   EXPIRED, NOT STARTED YET or MISSING after the downloads, `refresh.sh`
   prints a warning and asks:

   `Build anyway? (y/N)`

   Press Enter, or type `n`, to stop. This is almost always the right answer.
   Nothing is built and your current graphs stay as they are.

   Why: an agency sometimes publishes only its next schedule. If you build
   with it, that agency has no trips today. In July 2026 this made the TTC
   disappear for a week. Your old graph is better until the new schedule
   starts. Type `y` only when you accept that the agencies listed will have
   missing trips.

   Note that the downloads in stage 1 have already replaced the zip files in
   `engine/`. The old graph is unchanged. Try the refresh again on or after
   the first day shown in the table.

7. Start the app again.

   ```bash
   bash run.sh
   ```

   Wait for `READY`. This also restarts the GO alerts cleaner and the Durham
   live-delay cleaner, so you do not need to do anything extra for them.

8. Test it. Open a second Terminal window, go to the `gta-router` folder, and
   run the benchmark. It needs the app running.

   ```bash
   python3 tests/benchmark.py
   ```

   Every graded trip should say `PASS`. The last lines give the totals. A trip
   marked `MISS` means the new data may need a fix. Try one of your own trips
   in the app too. If it looks wrong, roll back.

### Roll back to the previous graphs

Do this if the benchmark fails or trips look wrong. `refresh.sh` kept the
graphs from before the refresh as `graph.obj.prev` and `graph.obj.otp25.prev`.

1. Stop the app.

   ```bash
   bash stop.sh
   ```

2. Put the old graphs back. This is the exact command `refresh.sh` prints.

   ```bash
   cd engine && mv graph.obj.prev graph.obj && mv graph.obj.otp25.prev graph.obj.otp25
   ```

   If it says a file does not exist, the refresh never got that far, and there
   is nothing to roll back.

3. Go back up a folder and start the app.

   ```bash
   cd ..
   ```

   ```bash
   bash run.sh
   ```

Careful: running `refresh.sh` again overwrites the `.prev` files with whatever
graphs you have at that moment. Decide about rolling back before you refresh a
second time. A rollback does not bring back the old schedule zips. It only
brings back the old graphs. The old schedules may also be expired by now, so
check with `scripts/check-feeds.py` again.

### When you need `bash setup.sh` instead

`refresh.sh` only updates schedules. It does not download new map data (roads
change slowly). Use `bash setup.sh` instead when you want fresh map data, or
when you are setting up from nothing. It takes longer: about 1.5 GB of
download plus the build.

- `setup.sh` skips the download if `engine/ontario-latest.osm.pbf` already
  exists. To get fresh map data, move the old file aside first (not verified
  end to end):

  ```bash
  mv engine/ontario-latest.osm.pbf engine/ontario-latest.osm.pbf.old
  ```

- It crops the map to the GTA, then re-applies `data/parking-patch.osc`. That
  patch marks about 28 real commuter lots as park-and-ride, which OpenStreetMap
  is missing. Never skip it. Without it, the "drive to the station" trips
  stop parking at those lots. `setup.sh` does it in the right order, so use it
  and do not rebuild the map by hand.

- `setup.sh` builds only the main graph. To rebuild the Reach map graph from
  the new map too, run `bash refresh.sh` afterwards (not verified end to end).

```bash
bash setup.sh
```

It asks for your computer password once (to link Java). Type it yourself.

### Known oddities

- **The TTC link sometimes serves an empty file.** The City of Toronto link
  for the TTC schedule has served a 22-byte empty zip. The refresh sees that
  it has no `stops.txt` and keeps the old copy, so you will see a `WARNING`
  and the TTC stays expired. Try again later. In the meantime, the recorder
  (runbook 3, if it is running) keeps dated copies of the schedules in
  `recordings/schedules/<agency>/`. Copy the newest TTC one over the
  expired one:

  ```bash
  cp "$(ls recordings/schedules/ttc/*.zip | tail -1)" engine/ttc-gtfs.zip
  ```

  Then run `python3 scripts/check-feeds.py` to see if that copy is good, and
  run `bash refresh.sh`. `refresh.sh` re-applies the transfer patch. If the
  link is still empty it keeps your copy.

- **"Invalid CEN header" in a build.** Java rejected one zip. Unzip it and zip
  it again (not verified). This example is for a feed called `miway`. Change
  the name for the feed the error mentioned.

  ```bash
  cd engine && mkdir fix-tmp && cd fix-tmp && unzip -q ../miway-gtfs.zip && zip -q ../miway-gtfs.zip.new *.txt && cd .. && mv miway-gtfs.zip.new miway-gtfs.zip && rm -r fix-tmp && cd ..
  ```

  Running `refresh.sh` again would download the broken zip again. If the
  download works, that is fine and this step may no longer be needed. If it
  is still broken, the build commands in `refresh.sh` (stages 3 and 4) can be
  run by hand from inside `engine/` after `. ../scripts/engine-env.sh`
  (not verified).

- **Never touch `engine/research-buffer/`.** It is a separate graph for a
  research study that is pinned to September 2026 schedules. The zips for
  barrie, grt, guelph and hsr in `engine/` belong to it too. They are not in
  the app's feed list, and `check-feeds.py` does not list them.

### Yearly chores

- **Fares.** Fares change in January or February (MiWay, Brampton) and in
  July (YRT). Look up the new price on each agency's own page. Edit the
  `LOCAL_FARES` table in `web/core.js`. Then check that nothing is out of
  step, and reload the app in your browser.

  ```bash
  python3 tests/fare-sync.py
  ```

- **407 toll rates.** They change every January 1. The script
  `scripts/make_toll_rates.py` needs the new rate chart saved as `rates.json`.
  The chart is drawn by JavaScript, so the steps to copy it out of the 407
  website are in the comment at the top of that script. Read that first. Its
  final command has this shape:

  ```bash
  python3 scripts/make_toll_rates.py rates.json toll.geojson web/toll-rates.json
  ```

  `toll.geojson` is made from the map data; `setup.sh` makes it as a
  temporary file, so see the same comment (not verified).

---

## 3. Check the live-data recorder

**When to do this:** every few days while you are collecting data, and any time
you have not looked for a while.

**How long it takes:** 1 minute to check. Starting it takes a few seconds.

What it is for: the live vehicle and delay feeds only show the present. The
recorder saves them as they arrive so that on-time performance can be worked
out later. Anything it does not save is gone for good. It runs on its own,
separate from the app, so it keeps going while the app is stopped or
rebuilding.

### Steps

1. Look at its status.

   ```bash
   bash scripts/record.sh status
   ```

   The first line says `Recorder: running` or `Recorder: NOT RUNNING`, how
   many seconds ago it last reported, and when it started. It reports every
   minute, so a number above about 180 seconds means it is not running.

   Below that is one line per feed. Read the columns like this:

   | Column | Meaning |
   |--------|---------|
   | feed name | For example `ttc-vehicles` or `go-trips`. Lines starting with `schedule-` are the daily schedule copies. |
   | verdict | `ok`: the last fetch worked. `starting`: no fetch yet. `PROBLEM`: three failures in a row, or no good fetch for 10 minutes or more. `STALE`: the fetches succeed, but a vehicles or trips feed has sent nothing new for 8 hours, so it is stuck on the agency's side. |
   | saved | Snapshots written to disk. |
   | same | Fetches thrown away because nothing had changed. |
   | failed | Fetches that failed. A few are normal. |
   | MB | Disk space used by that feed in this run. |
   | the text at the end | The last error, if there was one. |

   The last line gives the size so far, a daily estimate (about 0.3 GB a day)
   and how much disk space is free.

2. If it says `NOT RUNNING`, or you see `Nothing recorded yet.`, start it.

   ```bash
   bash scripts/record.sh start
   ```

   You should see `The recorder started.` If you see `The recorder is already
   running.`, it is. Check the status again after a minute.

3. To stop it on purpose:

   ```bash
   bash scripts/record.sh stop
   ```

### Where the data goes

Everything goes into the `recordings/` folder, which is not uploaded to
GitHub. Live feeds go in `recordings/feeds/<feed>/<date>/`. Schedule copies
go in `recordings/schedules/<agency>/`. The one health file is
`recordings/status.json`, and the recorder's own messages are in
`recordings/recorder.log`.

It writes about 0.3 GB a day. It stops saving, without stopping itself, when
the disk has less than 20 GB free. Free some space and it carries on by
itself. A failed feed shows the reason at the end of its status line.

### What to do if it stopped

1. Run the status command. If it says `NOT RUNNING`, run
   `bash scripts/record.sh start`.
2. If it starts and stops again, read the end of the log:

   ```bash
   tail -n 30 recordings/recorder.log
   ```

3. If a feed says `PROBLEM`, read its error at the end of the line. A feed
   that fails backs off and retries by itself, up to every 5 minutes. Nothing
   to do unless it lasts more than a day.
4. If the line for the Metrolinx feeds is missing, the log says
   `Skipping <feed>: no Metrolinx key in metrolinx.env`. Fix the key file.

### Known weaknesses

These were measured on 2026-11-16. They matter before you trust the data.

1. **It does not restart after the computer restarts.** After any restart you
   must run `bash scripts/record.sh start` yourself. Anything between the
   restart and that moment is lost.
2. **A laptop with the lid closed goes to sleep and records nothing.** The
   status still says "running" when you open the lid. Between November 3 and
   November 14 about 63% of the hours were missed this way. The recorder uses
   `caffeinate` to stop idle sleep, but a closed lid can still stop it.
3. **A feed can be frozen at the source and still say "ok".** From
   November 14 at 01:33, Metrolinx's GO vehicle and trip feeds returned the
   same 37 vehicles for at least two days, and the UP Express feeds were
   empty. The fetches worked, so it used to read as "ok". The status now marks
   this `STALE` and prints the time of the last new data. There is nothing
   to fix on your side: wait for the agency.
4. **Durham's feed sometimes answers 502 for a day.** The status shows
   `failed` rising and a PROBLEM verdict. This is Durham's server. Nothing to
   fix on your side.

The fix for the first two is to move the recorder to an always-on computer.
Until then, keep the laptop plugged in with the lid open whenever recording
matters, and check the status when you come back.

---

## 4. Hosting (not live yet)

**When to do this:** when you want a link anyone can open any time, with your
computer switched off. Nothing is deployed yet. This runbook is the plan and
the steps to finish it.

**How long it takes:** the first upload is about 1.2 GB, so plan an hour once
a computer exists. Getting the computer can take days (see "Where it is
stuck").

The scripts for this are in the `deploy/` folder.

### The design

- The **page** (the `web/` folder) lives on Vercel, free.
- **Both routing engines** (the main one and the Reach one) live on one free
  Oracle Cloud computer (an Ampere A1 virtual machine, 4 CPUs and 24 GB of
  memory, in the Toronto region). A program called Caddy sits in front of them
  and handles HTTPS.
- Vercel forwards every `/otp/...` request to that computer, so the page never
  needs to know its address.
- Only two addresses are open to the internet: `/otp/gtfs/*` (trip planning)
  and `/otp/traveltime/*` (the Reach map). The engines' own debug pages are
  closed.
- Your Metrolinx key goes only to the Oracle computer. It never goes to Vercel
  or GitHub.

### What exists today

- An Oracle Cloud account in the Toronto region, and a Vercel account.
- The command-line tool `oci` is installed and signed in on your computer.
- These scripts:

  | File | What it does |
  |------|--------------|
  | `deploy/oracle-grab.sh` | Keeps asking Oracle for the free computer until it gets one. It also makes the network (ports 22, 80 and 443 open), a public address and an SSH key at `~/.ssh/oracle-gta`. When it succeeds it saves the address in `deploy/oracle-ip.txt` and speaks and shows a notification. |
  | `deploy/push-engine.sh` | Uploads the engines, graphs and settings (about 1.2 GB the first time, only changes after that) and runs `server-setup.sh` on the computer. |
  | `deploy/server-setup.sh` | Runs on the Oracle computer. Installs Java and Caddy, opens its firewall, and starts both engines as services that come back after a crash or reboot. |
  | `deploy/deploy-web.sh` | Puts `web/` on Vercel with the forwarding rule, and prints the link. |
  | `deploy/Caddyfile`, `deploy/gta-otp.service`, `deploy/gta-reach.service` | The settings those scripts install on the computer. |

- Nothing has been deployed.

### Where it is stuck

Oracle keeps answering "Out of capacity" for the free computer. That is common
on the free tier. `deploy/oracle-grab.sh` tries every 3 minutes (first at
4 CPUs and 24 GB, then at 2 CPUs and 12 GB), but only while your Mac is awake.
To run it with the Mac kept awake:

```bash
caffeinate -i bash deploy/oracle-grab.sh
```

You should see `Network and image ready. Asking Oracle every 3 minutes.` and
then lines like `Round 4: no room for 4 OCPU / 24 GB`. When it works it prints
`GOT ONE` and then `READY. Public IP: ...`. Stop it with Ctrl+C. It is safe to
run again. If it says `STOPPED: ...`, read the reason (a missing or rejected
`~/.oci/config` is the usual one).

Early morning tends to be better for capacity.

You must do the account sign-ups, card details and passwords yourself. Nobody
else can do those for you.

### Steps once a computer exists

1. Read the address that `oracle-grab.sh` saved.

   ```bash
   cat deploy/oracle-ip.txt
   ```

   You should see one address, four numbers separated by dots. If the file is missing, the
   script never finished. Find the address in the Oracle console instead
   (Compute, Instances, your instance).

2. Make sure `metrolinx.env` exists, and that the app's graphs are built and
   current (`python3 scripts/check-feeds.py`, then runbook 2 if needed).

3. Upload and start the engines. Replace `IP` with the address from step 1.

   ```bash
   bash deploy/push-engine.sh IP ~/.ssh/oracle-gta
   ```

   It ends with `READY: https://<address-with-dashes>.sslip.io`. If it says
   `Engine didn't answer after 3 minutes`, log in and look at the engine's log
   (the command is printed):
   `sudo journalctl -u gta-otp -n 50`.

4. Put the page on Vercel. If Vercel's login has expired, first run
   `npx vercel login` and follow the browser window.

   ```bash
   bash deploy/deploy-web.sh IP
   ```

   It prints your link when it finishes.

5. Test one trip in the new link, for example Mount Joy GO to King and Bay.
   You should get a trip in a few seconds. If you get an error, check that the
   Oracle security rule allows ports 80 and 443 and that `server-setup.sh`
   finished.

### Console landmines

These tripped up the Oracle web form. The script `oracle-grab.sh` avoids most
of them.

- Pick the Ubuntu **26.04** image, not the one called "Minimal". Minimal is
  missing tools the setup needs.
- On a new account the "Automatically assign public IPv4 address" switch can be
  greyed out. Skip it and add an ephemeral public address after the computer
  exists (instance page, Networking, the VNIC, IPv4 addresses, Edit).
- The SSH key section sits at the bottom of the Networking step, and the
  private key can only be downloaded at that moment, not later.
- Use "Save as stack" on the Review step so that a retry after "Out of
  capacity" is a couple of clicks.
- Open ports 80 and 443 in the subnet's Default Security List (source
  `0.0.0.0/0`, TCP). `oracle-grab.sh` does this for you.
- If 4 CPUs and 24 GB are not available, 2 CPUs and 12 GB is tight and the
  Reach map may have to go.
- Oracle can reclaim free computers that look idle. The engines keep about
  9 GB of memory busy, which should count as in use. If the link stops finding
  trips, first check that the instance still exists.

### Updating after a refresh

The online copy never updates itself.

1. Do runbook 2 on your computer first. Check the benchmark passes.
2. Upload the new graphs:

   ```bash
   bash deploy/push-engine.sh IP ~/.ssh/oracle-gta
   ```

3. If you changed anything in `web/`, publish the page again:

   ```bash
   bash deploy/deploy-web.sh IP
   ```

Schedules expire online exactly as they do on your computer. Check
`scripts/check-feeds.py` on your computer and refresh in time.

### Known gaps to close before sharing the link widely

- **GO alerts and Durham delays in the cloud are written but untested.** On
  your computer, `run.sh` starts two small cleaner scripts
  (`scripts/go-alerts-filter.py` and `scripts/drt-rt-filter.py`) and the engine
  reads the files they write. For the cloud computer, `deploy/push-engine.sh`
  now uploads them and `deploy/server-setup.sh` installs them as two services
  (`gta-go-alerts` and `gta-drt-rt`). None of this has run on a real server.
  After the first deploy, check both with
  `sudo systemctl status gta-go-alerts gta-drt-rt` on the server.
- **No rate limit in front of the engine.** Each search makes about 21 engine
  queries. A few people clicking quickly can slow it for everyone, and anyone
  who finds the address can send as many as they like.
