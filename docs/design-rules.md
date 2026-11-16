# Design rules: anything a user sees

These are standing decisions about how the app (and its public pages) look and
read. Most of them were learned the hard way, by building something, showing
it to the owner and being told it looked wrong. Follow them. If you want to
break one, ask the owner first and show a real side-by-side, not a description.

Code note: the page code moved from `web/index.html` into `web/app.js` when the
map library was upgraded to MapLibre GL JS 6 (it is vendored in `web/vendor/`).
`web/index.html` now holds layout and CSS, `web/app.js` the page code, and
`web/core.js` fares, tolls, mode mixes and ranking. Function names below were
checked with grep when this was written. If one is missing, it was probably
renamed: search for the behaviour instead (marked "name may have changed").

## Contents

1. Words: no em dashes, plain language
2. The main aesthetic rule: flat and simple reads premium
3. How to compare against Apple Maps
4. What made the map read as Apple
5. The owner rejects designs that look AI-made
6. Decisions not to re-open
7. MapLibre implementation landmines
8. Other UI behaviours worth knowing

---

## 1. Words: no em dashes, plain language

RULE. No em dashes anywhere a user can read them: buttons, labels,
placeholders, tooltips, error messages, fare notes, map labels, and the public
web pages. This is a standing house style. It applies to new strings you write
too. En dashes are fine and are used on purpose ("Youth 13–19").

Replace an em dash with:
- a colon, for labels and placeholders: "Start: click the map"
- a comma, for list-like lines: "UP Express, youth"
- a full stop and a new sentence, for errors: "That took too long. Try again
  in a moment."

All FOUR spellings must be absent: the character itself (Unicode U+2014), and the HTML entities
`&mdash;`, `&#8212;` and `&#x2014;` (plus the old `&#151;`). A grep for the
character alone misses the entities; seven of them once survived a cleanup
that way. Strings built in JavaScript do not exist in the source as readable
text until a menu opens.

HOW TO CHECK, two layers:
1. Source: `bash check-em-dashes.sh` in the repository root (exit 0 is clean). CI runs the same
   pattern over `web/index.html`, `web/app.js` and `web/core.js` on every push
   (`.github/workflows/tests.yml`, step "No em dashes in the app's text").
2. Runtime: CI cannot see strings assembled in JS. Load the app, open every
   menu (the "..." menu, trip options, the calendar, the time list, a trip's
   detail view), then walk every text node plus every `placeholder`, `title`
   and `aria-label` attribute and search for the character. Do this after any
   copy change. Do not trust "I grepped".

Other copy rules in the same spirit: short sentences, plain words, say what is
uncertain ("fare unverified", "light traffic assumed") instead of presenting a
guess as fact. No jargon in the UI.

---

## 2. The main aesthetic rule: flat and simple reads premium

FLAT AND SIMPLE READS PREMIUM. GLOSS, GRADIENTS AND 3D BUBBLES READ CHEAP.

This is the heart of the owner's repeated complaint that the app "looks like
someone made it overnight". It has been confirmed three separate times:

1. Map pins, version 2, were a glossy red teardrop with a radial gradient and a
   specular highlight. The owner said it STILL looked cheap. He was shown four
   flat candidates and picked the Apple "you are here" halo dot.
2. Three bold panel mockups (a sheet, a colourful one, a glassy one) were
   called "incredibly cheap and even worse".
3. Conservative CSS variants of the panel were "still kinda bad".

The same lesson applies to colour ramps: the Reach map uses viridis (a
designed sequential palette) with Heat and Ocean behind a picker. The first
prototype's rainbow ramp read cheap for the same reason as the glossy pin.

---

## 3. How to compare against Apple Maps

What finally worked, after mockups and theory failed: open the REAL Apple Maps
next to the app, zoomed on the same area (downtown Toronto works well), and
name concrete differences ("roads are 3x too fat", "street names are the wrong
case"). Not mockups, not theory.

- Use the NATIVE Maps app on the Mac, not `maps.apple.com`. The web version
  answers HTTP 429 (rate limited) from a coding tool's browser and paints an
  empty tile grid, with a `glViewport: negative width/height` warning. That
  looks like a page bug but is not. In Maps.app: click the globe button
  top-right, choose Explore (it is usually left on Satellite), make it full
  screen, then zoom into regions to read road widths and label style. Put it
  back to Satellite and windowed afterwards.
- To match a colour, put fixed-position swatch rectangles of candidate hex
  values on top of the real map and look for the one with no visible seam.
  Spotting a seam by eye is far more sensitive than judging a colour alone.
- You cannot read Apple's canvas from script: it is WebGL without
  `preserveDrawingBuffer`, so copying it into a 2D canvas returns pure black.

---

## 4. What made the map read as Apple

Colours were right first, but side by side it still read wrong. Every
remaining tell was SHAPE or LETTERING. All of the following are gated on an
`apple: true` flag in the map look's palette (`LOOKS`, `recolorStyle` in
`web/app.js`), so the other looks (Midnight, Graphite, Daylight, Quiet,
Classic) are untouched.

- Roads were too fat. The size gap between a laneway and an arterial was about
  3x; Apple runs nearer 1.5x. That compression is why Apple's downtown stays
  legible where ours matted into one grey slab.
- Road casings (the outline stroke) were drawn everywhere. Apple's night map
  has essentially none and its day map a hairline.
- Street labels were mixed case at 13 px. Apple sets them ALL CAPS, letter
  spaced, about 10 px. This was the loudest single tell and the cheapest to
  fix (the code uses `text-transform: uppercase` and `text-letter-spacing`).
- Point-of-interest labels were italic (the base style ships them that way).
  Apple's are upright.
- Minor roads and footpaths appeared several zoom levels too early
  (`APPLE_MINZOOM`).
- Buildings were extruded even when the map was flat. Apple draws footprints
  looking straight down and goes 3D only when you tilt.
- Point-of-interest pins: circles, not rounded squares; glyphs as solid filled
  silhouettes, not 2.4 px strokes (wiry at 20 px); and the LABEL tinted to the
  category colour. A white ring around each disc is load-bearing: without it
  the slate and purple badges vanish into the dark map.

Not fixable: Apple abbreviates street names ("RICHMOND ST W"). The vector
tiles carry only the full name and MapLibre expressions have no string
replace.

Buildings, why they were "a grey lump" (measured on the live layer):
1. The base style set `fill-extrusion-opacity` to 0.8. With about 1945
   buildings in view downtown, translucent boxes show through each other and
   smear into one mass. Setting it to 1 was the biggest single win.
2. One flat colour for every building, so a 125 m tower looked like a 3 m shed.
3. The style ships no light, so the default near-overhead sun gives every wall
   the same tone.

Fix (see `buildingPaint`, `shadeHex`, `applyBuildingLight` in `web/app.js`):
opacity 1, `fill-extrusion-vertical-gradient`, colour graded by the tiles' own
`render_height` (toward white on dark maps, toward black on light ones, so
"taller" always means more contrast), and a directional light.
`setLight({ anchor: "viewport", ... })` is deliberately viewport-anchored: a
map-anchored light swings the sun around the city when you spin the compass.
The height grading was later softened (0.10/0.22 down to 0.05/0.13) because it
had been tuned while tilted and was too heavy from above. Check any building
change in BOTH light and dark themes and both flat and tilted.

---

## 5. The owner rejects designs that look AI-made

This applies to every public page, not just the app. The owner rejects work
that looks templated, including tasteful minimal work. Restrained, generic
"good taste" reads as AI to him just as much as the card template does. What
was missing each time was an identity specific to the subject.

The tells he rejected (the first research-report page, October 2026):
- rounded cards everywhere
- a row of four big-number stat tiles
- a periwinkle (blue-violet) accent
- pill-shaped buttons
- an uppercase "eyebrow" label above a heading, plus a pill badge
- soft drop shadows
- colon headlines ("Topic: what we found")
- bullet lists that start with a bold lead-in phrase
- three identical story blocks in a row

The "fix" that was also rejected: system serif type, one column, hairline rules,
muted blue links, plain bar charts, blue map shading, and an opening line that
starts with a statistic. Small polish (focus rings, removing a stat strip) did
not change his mind. A third attempt (a transit-timetable theme with yellow,
condensed sign lettering and a route line) "looks better" but he disliked the
theme.

WHAT TO DO INSTEAD.
- Do not invent a theme. For the research report he said he does not know what
  a good research paper looks like, then picked a standard journal-article
  format over a policy report or a news feature. The result is a plain
  two-column preprint: abstract, numbered figures with lettered panels,
  numbered references, a "Preprint, not peer reviewed" line, and no journal
  branding. The web page is a plain companion in the same typefaces
  (Source Serif 4 and Source Sans 3) and blue palettes. (The report files live
  outside this repository.) His reaction to the finished paper was not known
  when this was written.
- Where a theme IS wanted, take the visual world from the subject and commit to
  it, with graphics drawn from the real data. Charts should differ from each
  other (a dot unit chart, a strip plot of every neighbourhood, lines with
  stops, 100 squares) rather than five copies of one bar chart.
- A headline should state a finding. An opening should start with a place, not
  a number. No colon headlines. No em dashes.
- Ask the owner for his own words (stories, a "why I did this" note). No
  styling replaces that.
- One accent colour at most. Real charts, plain copy.

---

## 6. Decisions not to re-open

### MapKit JS (Apple's own map tiles in a web page)

Researched and rejected. The Transit app gets Apple's actual map because it is a
NATIVE iOS app, and Apple gives MapKit to native apps free. A web page needs
MapKit JS, which requires the paid Apple Developer Program (99 USD a year, no
free tier, no anonymous key). Even paid, it is a different library: route
lines, Reach shading, the toll overlay, dock dots, crown shields, pins and
popups would all be rewritten against Apple's overlay API, Apple's map cannot
be restyled (so the several map looks become impossible), and it could not be
confirmed from Apple's docs whether MapKit JS tilts at all, so 3D and the
compass might be lost. Do not start that migration without answering the tilt
question first.

### Apple's 3D landmark models

Out of reach. Those are bespoke 3D art made by artists, one per landmark. It is
an art-asset problem, not a code problem. Hand-drawn SVG miniatures would look
worse than clean icons. The only standing offer is flat silhouette markers for
a handful of Toronto landmarks, explicitly not Apple-equivalent.

### Trackpad twist to rotate is Safari only

Do not retry. macOS reports a two-finger twist to a web page only through
Safari's non-standard `GestureEvent`. Chrome does not implement it at all
(`typeof GestureEvent` is "undefined" and `'ongesturestart' in window` is
false in Chromium). Trackpads emit no touch or multi-pointer events either, so
there is no second route. The owner uses Chrome.

So the app has a split: the twist in Safari, and Option plus two-finger drag
everywhere. The Option path is not dead weight; it is the only rotate that
exists in Chrome. Why Option and not another key: ctrl+wheel is how browsers
signal a trackpad PINCH (intercepting it breaks pinch to zoom, and it is also
the macOS accessibility zoom); shift+wheel is rewritten by the browser into
horizontal scroll. The handler checks `altKey` only. The listener is
capture-phase on `map.getContainer()`, an ancestor of the canvas container
MapLibre binds to, so it runs first. Fingers up tilts INTO 3D, like Maps on
iPhone. Pitch is clamped to `map.getMaxPitch()` (60), not a number of our
own: a first version clamped to 75 and MapLibre silently clamped to 60 anyway.

### Pure CAR mode held back

A whole-way drive option is the same one-line change as bike or walk, but on
free-flow times (no traffic model) it wins almost every trip. It waits for a
traffic answer. See `docs/routing-notes.md`, section 9.

### Lines in 3D fade instead of re-ordering

There is no good occlusion answer for a street-level line in a tilted city:
over the rooftops it cuts across towers like pen on glass, under them it
vanishes. So transit lines are treated as flat-map furniture. `tiltFade()` in
`web/app.js` gives full strength to pitch 20 and zero by pitch 48, driven off
the `pitch` event (not `pitchend`) so it fades smoothly. Still open and the
owner's call: in 3D at downtown zoom the trip route is hard to see because
towers hide it. That is his own earlier request (the route runs behind the
buildings) working as asked, so it was not changed unilaterally.

---

## 7. MapLibre implementation landmines

### The styledata re-entrancy latch

`map.addImage` and `map.setLayoutProperty` both fire the `styledata` event
SYNCHRONOUSLY. If an installer hooked to `styledata` has no latch, it calls
itself from inside its own first `setLayoutProperty` and dies with "RangeError:
Maximum call stack size exceeded". `shieldBusy` and `badgeBusy` in
`web/app.js` are that latch. They are not decoration.

Do not trust a plain boolean for "the artwork is installed". A from-scratch
style rebuild silently drops the images and the layer overrides,
independently. `shieldsLive()` and `badgesLive()` check `map.hasImage(...)`
AND that a layer still carries our icon size.

Images added with `addImage` SURVIVE `setStyle`'s diff, which is why the old
look's shields stayed painted until idle fired. Install BEFORE `setStyle`, into
the outgoing style, and hook the re-apply to `styledata`, not `idle`.

`applyLook` can run during module start-up, above the shield code, so anything
it touches must be a hoisted function declaration, not a `const` arrow.

### Layer ordering (it took two goes)

- `building-3d` sits near the TOP of the base style (index about 87 of 115),
  not down with the other fills. Anchoring lines to the first symbol layer
  buried them under the extrusions.
- The first symbol layer in that style is `road_one_way_arrow`, a road
  decoration, so it is not the label boundary either.
- The anchor is "the first symbol layer that comes AFTER building-3d" (look
  for the `findIndex` on `building-3d` in `web/app.js`, name may have changed).
- That caused a second problem that only shows on screen: once background lines
  sat in front of the buildings, a full-strength subway line painted over the
  trip's route and the actual trip became the faintest thing on screen.
  `syncTransitEmphasis()` drops the background lines to 0.3 opacity whenever a
  route is shown. Always look at the map in both themes after touching layers.

### Fixed-position popups (menus, address suggestions, skinned selects)

Every menu is `position: fixed` with coordinates set by JavaScript, because
`#panelScroll` has `overflow` set and would clip an absolutely positioned
child. Two landmines:

- Close-on-scroll closed the menu's own list. The scroll listener is on
  `document` with capture, so scrolling the time picker's 96 options closed it.
  It now ignores scroll events whose target is inside the menu (see the
  `document.addEventListener("scroll", ...)` in `skinSelect`). Any new
  fixed-position popup with an internal scrollbox needs the same guard.
- Positioning once, on open, is not enough. The disruptions bar loads a second
  or two in and pushed the anchor button 30 px down, dropping the calendar on
  top of its own button. `place()` (name may have changed) now runs every
  animation frame while a menu is open, and stops on close.

### Skinned selects

A native `<select>`'s option popup is drawn by the operating system and cannot
be themed; the grey system menu was a complaint. `skinSelect(sel, opts)` keeps
the real select in the page (it still owns the options, `.value` and change
events, so `plan()`, the share link and the trip-from-URL code needed no
changes), hides it inside a `.selwrap`, and draws the list in the app's own
material.

- Landmine: assigning `.value` in code fires no event, so the button label
  would drift. `skinSelect` redefines the `value` property on the instance,
  delegating to the prototype, to re-sync. If you swap the element, call
  `skinSelect` again.
- Keyboard: the button's keydown must `stopPropagation` when it opens the menu,
  or the document-level handler sees the same key and skips the first item.

### Hidden tabs

Every animation is guarded with `document.hidden` (there are guards around the
dock refresh, the counting animation and the Reach reveal). Keep that pattern.
See `docs/testing-notes.md` for why.

### A saved look beats a new default

A saved map look wins over the default, so shipping a new default changes
nothing for anyone who has used the app. When the Apple look became the
default, the owner's reaction was "it doesn't seem like you even changed
anything". The fix is a one-time bump keyed by `sawAppleLook` in
`web/app.js`: if the stored look is still one of the OLD defaults (Midnight or
Daylight), it is moved to Apple once. A look picked on purpose (Graphite,
Quiet, Classic) is left alone, and the flag makes it run exactly once.
REMEMBER THIS FOR ANY FUTURE DEFAULT CHANGE: add a migration with its own flag,
or the change will be invisible to everyone who already has a saved value.

### Transit lines on the map: the deliberate exclusions

Built by `scripts/make_transit_lines.py` into `web/transit-lines.json` (rapid
transit routes in their own colours from the schedule data).
- Buses are excluded (the script says 3 = bus is "deliberately absent"). 210
  TTC bus routes is a grey hairball.
- TTC 3xx routes are dropped. They are the overnight Blue Night versions of
  the same streetcars in a different blue, so keeping them paints every line
  twice in the wrong colour.
- One shape per route (the one with most trips, longest wins ties), so branches
  off a trunk are lost. Deliberate: a clean picture over spaghetti.
- Streetcars only from zoom 11; major lines fade in from 7.5.
- A `rgba(0,0,0,0.28)` casing under every line (`casing` in `web/app.js`):
  Line 1's official yellow is nearly invisible on the light map's near-white
  land. This is why you must look at the thing in both themes.
- Landmine: the transit-lines on/off toggle reads `localStorage` directly, not
  through `loadStored()`, because `loadStored()` only returns objects and would
  turn a stored `false` back into the default `true`.

---

## 8. Other UI behaviours worth knowing

- `loadStored()` wraps every `localStorage` read in try/catch. A corrupt value
  once killed the whole script mid-load and gave a dead Plan button. Keep every
  storage access guarded: it can also throw in private windows.
- `plan()` uses an AbortController, a sequence token and a 25 second timeout,
  so overlapping plans cannot paint stale results and a hung engine cannot
  spin forever. `friendlyErr()` turns failures into plain words.
- Colours from schedule data (route colours) are hex-validated by
  `routeColor()` before they reach a style attribute, and `esc()` escapes
  quotes. Keep that for any new place text from outside enters the page.
- `prefers-reduced-motion` calms the animations; keep it working.
- The app opens with empty search boxes on purpose (the owner asked for it).
- Public repository: do not put a personal route, a home area or a named
  personal building in screenshots, example trips, test data or copy. Use
  public stations and generic downtown intersections.
- Known rough edges the owner is aware of: the sticky search card floats over
  the top result as you scroll; busy trips show a long chain of badges; there
  is no real phone layout or bottom sheet (cards work at 375 px, the layout is
  not designed for it); some orphaned CSS classes remain, harmless (from older
  notes, not re-verified).
