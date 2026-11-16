# Plans for the unfinished work

Four threads were open when this was written (2026-11-16). For each: the
goal, what is already decided (do not reopen it without the owner), what is
still open, and the next three concrete steps.

If you finish a step, edit this file: move it to "Decided / done" and write
the next one. A plan that is not kept current is worse than none.

Contents:

1. Reliability engine
2. Research report (GTA transit access)
3. The look of the app
4. Hosting

---

## 1. Reliability engine

**Goal.** Tell a rider the odds that a planned trip arrives on time, and from
that, when to leave. Possibly delivered through a calendar ("leave by 7:42 to
make your 9:00 with 9 in 10 odds"). The planner answers "what is the fastest
trip on paper". This answers "how often does that trip actually work".

**Decided / done.**

- Record first. The live feeds only show the present, so nothing can be
  learned about lateness without a history. `scripts/record-feeds.py` has
  recorded TTC, GO, UP Express, YRT, MiWay and Durham since 2026-11-03: raw
  bytes of vehicle positions, trip updates and alerts, plus a dated copy of
  each schedule whenever it changes (live data can only be matched to the
  schedule that was in force that day).
- Raw bytes are kept on purpose, so the method for working out lateness can
  change later and old recordings can be re-read.
- The recorder is separate from the app. It keeps going while the app is
  stopped or rebuilding.

**What the first two weeks showed.**

- The recording has large holes. About 63% of the hours between Nov 3 and
  Nov 14 are missing, because it runs on a laptop that sleeps when the lid is
  closed. It also does not restart after a reboot.
- A feed can be broken at the source. Metrolinx served the identical GO
  snapshot from Nov 14 for days, and empty UP Express feeds. The status now
  shows these as STALE.
- TTC's trip updates cannot be matched to the schedule by trip id (see
  `docs/routing-notes.md`). TTC lateness will have to come from vehicle
  positions, or from the predictions feed matched by route and stop. Nobody
  has checked yet which fields the recorded TTC feeds carry.

**Still open.**

- Where the recorder lives. It needs a computer that is always on.
- The method. Two candidates: (a) compare each recorded prediction with the
  schedule, per route, stop and hour of day; (b) work out actual arrival
  times from vehicle positions. (a) is far simpler and should come first.
- What to show the rider, and where. Needs the owner.
- How much history is enough. A guess: four weeks per schedule period before
  any number is shown to a user.

**Next three steps.**

1. Move the recorder to an always-on machine. The hosting server (section 4)
   is the natural place. It needs Python 3 only, about 0.3 GB of disk a day,
   and the Metrolinx key. Copy `scripts/record-feeds.py`, `scripts/pbwire.py`,
   `scripts/feeds.sh`, `scripts/record.sh` and `metrolinx.env`, keep the same
   folder layout, and run it as a service that restarts by itself. Until
   then: laptop plugged in, lid open, and check
   `bash scripts/record.sh status` daily.
2. Write `scripts/recordings-summary.py`. Part one: coverage, meaning hours
   actually recorded per feed per day, so holes are visible. Use
   `read_records()` from the recorder. Part two: for ONE agency whose live
   trip ids match its schedule (start with YRT or MiWay, then GO), print a
   table of lateness in minutes by route and hour of day. Test it the way
   `tests/record-feeds.py` tests the recorder: tiny made-up feeds, no network.
3. Take that table to the owner and decide the first thing a rider sees. The
   suggestion: for one planned trip, the chance each transfer is made,
   starting with GO train to TTC subway at Union, because a missed transfer
   is what makes a trip late.

---

## 2. Research report (GTA transit access)

**Goal.** A public report on where transit in the Greater Toronto Area serves
people worst, using this project's routing engine: a journal-style paper
(PDF) and a companion web page with maps.

Everything for it lives in `research/`, which is deliberately NOT in this
repository (it stays on the owner's computer). `research/PLAN.md` is the full
record of every decision and number, and `research/` has no backup yet.

**Decided / done.**

- The analysis is finished and checked (steps 1 to 4 in `research/PLAN.md`):
  13,460 starting points, travel-time maps for a weekday morning, scores for
  jobs, grocery stores, emergency departments and people reached, compared
  with driving, and cross-checked against Statistics Canada's own access
  measures and the Transportation Tomorrow Survey.
- The study is pinned to the schedules of the week of 2026-09-22. Its own
  graph is in `engine/research-buffer/`. Never refresh or rebuild that
  folder; refreshing the app's schedules does not touch it.
- Three neighbourhood stories, chosen by the owner after hand checks: South
  Oshawa (jobs), Brampton (emergency rooms), Kerr Village in Oakville.
- Headline number: people in low-income areas with poor transit reach, in
  the version that stays stable across the sensitivity tests.
- Format: a standard journal-article layout (`research/phase5/report/paper.html`),
  chosen by the owner over an invented visual theme. The web page is a plain
  companion in the same typefaces. See `docs/design-rules.md` for why.

**Still open.**

- The title. The working title was written by the developer and has not been
  approved by the owner.
- The owner has not yet said what they think of the paper format.
- The methods page contains a disclosure of how AI was used. The owner has to
  read it and correct it in their own words.
- Publication terms for the Transportation Tomorrow Survey numbers. The owner
  has to ask the Data Management Group at the University of Toronto. This
  blocks publishing.
- Where the report is hosted.

**Next three steps.**

1. Back up `research/` (about 6 GB) to an external drive or private cloud
   folder. Only the owner can do this. Nothing else protects two months of
   work.
2. The owner: email the Data Management Group about publishing and citing
   the survey numbers, read the AI-use disclosure, pick the title.
3. After ANY change to text or figures, rebuild both outputs and look at
   every page: `python3 research/phase5/build_standalone.py`, then
   `node research/phase5/make_pdf.mjs` (the report must be served over http
   first; the commands are at the end of `research/PLAN.md`). The paper's
   page breaks are tuned by hand, so a small edit can open a blank gap.
   Then publish, with the owner's OK, since it goes out under their name.

---

## 3. The look of the app

**Goal.** An app that reads as carefully made. The owner's reference is Apple
Maps. This has been the longest-running complaint.

**Decided / done.** All of `docs/design-rules.md`. The short version: flat and
simple reads as premium; gloss, gradients and 3D bubbles read as cheap;
compare against the real Apple Maps side by side and name concrete
differences instead of making mockups; anything that looks like a generic
AI-made page is rejected; no em dashes in anything a user reads. The map
style, pins, result cards, menus and motion have all been through this.

**Still open.**

- The search card stays pinned and floats over the first result as you
  scroll.
- A trip with many legs shows a long chain of badges.
- There is no real phone layout. The page works at phone width but was not
  designed for it.
- In 3D downtown, towers hide the route line. That is the owner's own earlier
  request working as asked, so it is their call.

**Next three steps.**

1. Fix the two small ones: the search card overlap and the badge chain (cap
   the middle legs on lower-ranked cards). Details are in
   `docs/known-issues.md`. Take a screenshot before and after, in light and
   dark.
2. Before designing a phone layout, ask the owner questions with real
   examples: open Apple Maps on a phone next to the app and ask which
   behaviours they want (a sheet that slides up from the bottom, how much of
   the map stays visible, where the search boxes go). Do not build from a
   guess.
3. Remove the unused CSS only after a search proves each class is unused.

---

## 4. Hosting

**Goal.** A link that works at any time with the owner's computer off, for a
small number of visitors.

**Decided / done.**

- The page goes on Vercel (free). The two engines go on an Oracle Cloud
  "Always Free" Ampere machine in Toronto (4 cores, 24 GB), behind Caddy,
  which provides https. Vercel forwards `/otp/*` to the engine, so the page
  never needs the engine's address. Vercel cannot run the engines itself:
  they need about 9 GB of memory.
- Every script is written: `deploy/` and `docs/deploy.md`. Both accounts
  exist. Nothing has ever been deployed.
- Deploy from the owner's computer, not from GitHub, because the engine needs
  the private Metrolinx key.

**Where it is stuck.** Oracle has answered "Out of capacity" for the free
machine every time since 2026-09-12. `deploy/oracle-grab.sh` retries, but
only while the owner's computer is awake. The owner chose to keep retrying
over paying.

**Still open.**

- Whether to keep waiting. The alternatives, all needing the owner's
  decision and their card: switch the Oracle account to pay-as-you-go (widely
  reported to get free-tier machines much sooner while still costing nothing
  inside the free limits; not verified here), or rent a small server
  elsewhere (roughly 10 to 15 dollars a month for 16 GB).
- Three gaps to close before the link is shared widely: no rate limit in
  front of the engine, no pause between rapid toggle clicks, and the live
  feed filters on the server are written but untested. See
  `docs/known-issues.md`.

**Next three steps.**

1. The owner decides between waiting, pay-as-you-go, or a paid server. After
   two months of "Out of capacity", waiting alone is unlikely to work.
2. Once a machine exists, follow "Hosting" in `docs/runbooks.md`: push the
   engine, deploy the page, plan one trip from a phone on mobile data.
3. Close the three gaps, then put the recorder on the same machine
   (section 1) and add the hosting steps to the schedule-refresh routine, so
   the online copy does not go stale when schedules expire.
