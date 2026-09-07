# The web interface

`alfenctl ui` serves a small dashboard on this machine. This page is
what it shows and why it is shaped the way it is; see the
[README](../README.md) for the rest of the tool.

```console
$ alfenctl ui --station garage
alfenctl ui is serving on http://127.0.0.1:8088/
  press Ctrl+C to stop
```

A browser opens on a dashboard of the station: each socket it really has,
with its own state and its own maximum current, the live meter with what it
is drawing now and the half hour of it this page has watched, the
temperature against the alarm band it has to stay inside beside the
display's brightness and the on-screen price it shows a session costing,
load balancing with the mode and the two currents that decide it, the
station's identity with its clock and drift, and the doctor's one-pass
health check. Each card is edited as a whole and written when you press
**Apply**, so a half-dragged limit never reaches a charger that is
mid-session. Where a setting will not
have the effect it looks like it has -- a socket above the station maximum,
sockets that add up past it, a limit too low to charge anything -- the card
says so in a few words, with the whole explanation one click (or one hover)
away.

Eight more tabs mirror the CLI. **Charging** holds the full load-balancing
and solar editor, the OCPP charging profiles with the direct-start
override, and Smart Charging Network membership. **Sessions** holds the
charging sessions from the charger's own transaction database, totalled by
month, by socket or by tag. **Logs** holds the event log, following it live
or paged back as far as the charger's buffer goes. **Access** holds the
authorization settings, the RFID whitelist, the master tag, and the
passwords and the Eve Connect PIN. **Network** holds the interface
addresses, the Wi-Fi scan and join, the smart-meter wiring test, and the
custom Modbus register map. **Backoffice** holds the OCPP connection and
the write-only secrets, and says which of the two ways to point a station
at a CSMS is which -- the URLs here by hand, or an operator's preset from
the Properties tab. **Properties** holds the property browser and
editor, backup and restore with a diff preview, and the presets Alfen
publishes. **Actions** holds the restart, clock sync, logo upload and
firmware upgrade, tilt calibration, the console, and erase.

Which tab you are on is in the address bar, so a reload comes back where
you were and a link to `#logs` on this charger is a link somebody can send.
A tab you have opened stays built: switching away and back does not read
the charger again, and does not lose the value you had half-typed into it.


"Each socket it really has" is not the same as each socket it answers for. A
single-socket NG910 builds the whole object dictionary its firmware knows --
its own boot log says `Added object 0x3129`, socket 2's maximum current --
and returns a perfectly good 16 A for a socket that is not on the wall.
Taking the reply at face value put a phantom socket on the dashboard and
raised "the sockets add up past the station maximum" against a station with
one socket at half its limit, so `sysNrOfSockets` decides instead, in the CLI
as well as the browser.

### One column of tiles

Each socket is a tile: its state at the top, the pilot, relay and LED
positions under it as badges, and its own maximum current at the bottom.
Those three were a line of prose -- "relay main off, bypass off" -- which
reads as a sentence about the socket rather than as the switch positions it
is; a badge each, coloured from the charger's own words (error is wrong,
charging or switched on is live, available is well), says which words are
the state.

The station is a tile of the same shape, with its badge, its read-only
installation and safe currents where a socket keeps its state, and the same
limit row at the bottom. It was a row under the tiles until it was noticed
that its slider started and stopped half a tile's padding away from
theirs -- two controls of the same kind out of line, which is what an
unfinished page looks like. In one column of tiles every track shares one
pair of edges, and the numbers under them line up too.

### Currents that only go where a current can go

Currents are sliders, dragged rather than typed, with the sizes an
installation actually uses (6, 10, 16, 25, 32 A ...) marked on the track, and
the reading beside one turns amber while it differs from what the charger
holds. What the slider will *not* offer is as much of the point as what it
will:

* **Not below 6 A.** Mode 3 offers the car a current as a duty cycle on the
  pilot wire, and IEC 61851 defines nothing under 6 A -- a vehicle that sees
  less must not draw at all. The charger agrees: one of its own states is
  "charging power off low maxcurrent". A slider that ran down to 1 A was
  offering four settings that do not charge and look like they should.
* **Not above the limit over it.** The installation maximum caps the
  station's, and the station's caps each socket's -- against the number on
  the slider you are dragging, not the one the charger last reported, so
  pulling the station down takes its sockets with it while you watch. What
  moved is written with everything else on **Apply**; the ends of each track
  are printed under it, so they can be seen to move.

Neither is a refusal. A charger already set outside those bounds is shown
exactly where it is -- a slider that could not reach its own reading would be
lying about it -- and the caveats under the card are what say so. `alfenctl
current set` still writes anything the charger will take, down to the 1 A
floor the vendor's own dialog allows, because commissioning is not charging.

It is the same code underneath as the CLI: the server calls the same
modules, so a value read in the browser is the value `alfenctl get` prints.

### What the meter has done, not only what it is doing

The live meter leads with kW, because that is what changes while you watch,
and carries the meter's own lifetime total under the phases -- `2221_22`,
`EnergyRealDeliveredSum`. It is not in any property category (a 7.4.5 NG910
answers for `2221_3` through `2221_20` in `meter1` and stops), so it is
asked for by id alongside the walk, in `status.collect`, which both front
ends now read through. A charger that does not answer for it gets no row
rather than a row of nothing.

The register counts watt-hours, though the EDS calls it kWh -- a real
station reads a thousand times the total its own transaction log stops at,
which is the same unit Alfen's Modbus map uses for that measurand. The row
shows kWh. Its companion `2221_26` counts energy going the other way, out
of the car and back to the grid, so on a station that cannot do that it is
zero for its whole life; that row appears only once there is something in
it.

That register was worth the trip for a second reason. The kW figure came
from `2221_11` because the bundled `EDS.xml` labels it "ActivePower"; the
vendor app's own monitoring panel reads Active Power Total from sub 22
(`2221_16`) and the frequency from sub 18, and a live NG910 has 50.11 at
`2221_12` -- a mains frequency at the app's index and not at the catalog's.
The EDS is wrong at exactly those two entries, `2221_11` is Cos φ Total, and
the dashboard was showing a power factor as kilowatts.

### The temperature, and the band it has to stay in

42 °C is fine under a 60 °C alarm and a fault under a 40 °C one, so the
reading and its two limits are together rather than a row in the meter and
two properties nobody can find. The reading is the card's headline, the band
is drawn under it with a mark where the charger currently sits, and the two
ends are sliders: `sensTemperatureAlarmLow` and `sensTemperatureAlarmHigh`
(`2202_0`/`2203_0`) are `rw`, and the app sets them in its *Alerts* panel.
They are written with **Apply** like every other card, and dragging one end
into the other pushes it along rather than crossing it -- so a limit nobody
touched can still be part of the write, exactly as a socket the station
limit pushed down is.

They share a card with the display, and did not always: a reading and two
sliders is a card and a half of content, and in a grid where every card is
as tall as the tallest in its row that is a card mostly made of air. The
two belong together anyway -- both are the station itself rather than what
it is charging, and both are settings somebody comes back to, the band
with the seasons and the brightness the first evening it is too bright.

### A station with no display

Not every Alfen has a screen, and one that has none accepts a logo upload
and shows it nowhere. The dashboard says which it is: the *Temperature,
display and LEDs* card is marked **no display** and says the brightness
reaches the LEDs (that setting is `sysIntensity`, which drives both), and
the Actions tab's logo control is disabled with the reason in its note.
The test is the vendor app's `ICULanDevice.HasDisplay` -- the display
descriptor `12896_1` with a logo box at `12896_3`/`12896_4` above zero, or
one of the models that has a fixed screen without describing one -- and the
app's own dialog greys the same button out.

The server refuses the upload too, rather than trusting the page to have
hidden the button, and `alfenctl logo --force` is the deliberate way past
it: what a charger really does with a package it has nowhere to show is the
charger's to say, and the terminal is where you go to find out.

### What a licence does not include

The licence block lists every feature the model can have, with the ones this
station holds in the primary colour and the rest dashed, under a line that
counts them ("5 of 11 unlocked"). It listed only the installed ones, which
answers "what does this station do" and not "what is left of its licence" --
which is most of why anyone opens it. `alfenctl license show` prints the
same two lists.

The device-unique id is only shown when the charger reports one worth
showing: it is what a vendor derives a key from, and a real NG910 answers
with zeros, which is a row that says nothing. It is still in the property
browser at `21A0_0` either way.

### Knowing when the charger is busy

The charger binds its session to the TCP connection and serves **one
connection at a time**. The server therefore keeps a single connection and
runs every request through one worker, so the page can say exactly what
that connection is doing -- and it does, in a pill in the header that every
open browser sees at the same moment:

| | |
| --- | --- |
| **released** | no connection held; the charger is free for `alfenctl` or its own web page |
| **connecting** | opening the socket and logging in |
| **connected, idle** | session held, nothing in flight, counting down to release |
| **busy** | with the operation named, and a percentage for uploads |
| **error** | with the failure, and a button to try again |

If your action is waiting behind someone else's firmware upload, the pill
says so. And a read that pages the charger -- the transaction database, the
log walked back a week, every property for a backup -- reports how far it
has got, both on the pill and as a bar in the panel that asked for it: a
percentage where there is an honest denominator (a backup knows how many
categories it has to walk before it starts) and a count where there is not
(nothing knows how many pages of log a charger has kept). Without that,
eight seconds of paging and a hang look identical.

The pill is also the control. Clicking it opens everything there is to say
or do about the connection: the live-updates switch and its interval,
**Release** and **Connect**, who else is watching, and the history of what
the link has done -- every operation the page has been told about, newest
first, with how long ago each ran, which is a longer history than the
server keeps, since the page remembers what the link event has carried
past it. That used to be a bar under the tabs holding four controls nobody
touches twice an hour, sitting between the tabs and the content they were
there to look at; the pill was already the one place that says what the
connection is doing, so it is where the rest belongs, and the page got the
row back. The watcher list names who is actually connected -- address,
browser and how long each has been there, with this browser marked --
because "someone is holding the station" is more useful with a face on it.


The pill is the only thing on the page that moves for a live refresh, and
even it stays in the colours of a connection at rest while one runs. The
refresh takes the connection every few seconds; a page that treated that as
work greyed out every button on it and brought them back on the beat, which
reads as a fault rather than as a refresh. So the worker marks the work
nobody asked for as quiet, the controls ignore it -- a click during a refresh
is queued behind it and runs perfectly well -- and what is left has to last
0.4 s before anything is disabled for it, so a write that lands quickly goes
past without the page flinching.

An unused connection is handed back by itself after 45 seconds
(`--idle-timeout S`), and **Release** in the pill's menu does it at once --
so leaving the page open does not keep a terminal locked out. Live updates
are off until you turn them on, and are shared rather than per-browser:
there is one connection, so there is one answer to "is it being polled".

### When the server itself has gone

The pill says what the *charger* connection is doing, which is a different
question from whether the program drawing the page is still running. Stop
`alfenctl ui` with the tab open and every control on it is suddenly a
description of a world that ended: the readings are the last ones that
arrived, and a click does nothing anybody can see.

So the page watches for that too. The event stream dropping, or any request
failing to reach the server at all, starts a countdown; the stream
reconnects on its own within a few seconds, so a server that is merely
being restarted comes back without the page saying anything. Longer than
that and a banner appears under the header -- *the alfenctl server is not
answering* -- the pill is struck through, the connection controls are
disabled, and there is a button to try now. When the stream does come back,
the page re-reads the whole state rather than carrying on with what it
held, because a restarted server has forgotten the station, the link and
every job the page was told about.


Ctrl+C returns the prompt in about a fifth of a second, whatever the worker
is in the middle of. It used to wait for the refresh in flight and then for
a logout on top of it -- several seconds against a charger on a slow link.
Closing a socket under a thread parked in `recv` does not wake it, so the
worker is asked to stop, given a moment to notice, and then left to the
interpreter: it is a daemon thread with nothing to write down, and the
charger binds its session to the TCP connection, so the process exiting
frees the station exactly as a logout would. A second Ctrl+C leaves at once.

### One tab, not a new one each time

Starting `alfenctl ui` again should not leave a trail of tabs behind. It
does not: before opening anything, the server waits a moment to see whether
a tab is already watching its event stream, and if one is, it asks that tab
to come forward instead of opening another. A tab whose server was
restarted finds its way back on its own -- the stream tells the browser to
reconnect after a second, so the old tab is watching again before the new
server decides what to do.

If the port is already taken because an `alfenctl ui` is *still* running
there, the second one asks the first to raise its tab and exits quietly,
rather than reporting a port clash you did not need to hear about.

No browser can be told from outside to switch to a tab, so the page raises
itself: it calls `window.focus()`, and where the browser ignores that (most
do, unless the tab is already frontmost) it flashes its own title, which is
what makes the right tab findable in a crowded strip.

In Firefox neither of those shows: content script may not raise a window
outside a user gesture, and a tab whose title changed is not highlighted or
animated by anything, so in a full tab strip nothing visibly happens at
all. The bell in the header is the answer, if you ask for it. Press it
once, let the browser's prompt through, and a second `alfenctl ui` puts a
note on the desktop naming the tab it meant; clicking that note *is* a user
gesture, so it is allowed to do the raising the page itself may not.

It stays off until pressed, deliberately: a page that asks for notification
permission unbidden is how a site gets them refused for good. The answer is
remembered per browser, next to the theme, and the bell turns them off
again. Notifications also need a secure context -- this machine, or https
-- so the bell is not there at all on a page shared over plain http to
someone else.

### Sharing it

By default the server listens on `127.0.0.1` and needs no token. To let
someone else watch:

```console
$ alfenctl ui --listen 0.0.0.0 --read-only
alfenctl ui is serving on http://127.0.0.1:8088/?token=Zx8-QpN1yq0hV3mA
  read-only: nothing on the charger can be changed from the browser
  shareable: http://192.168.1.20:8088/?token=Zx8-QpN1yq0hV3mA
  the link includes an access token -- share it deliberately
```

Off loopback an access token is generated and included in the link; the
browser keeps it in a `SameSite=Strict` cookie, so it appears in the address
bar only once (`--token` to pin one, `--no-token` on a trusted LAN).
`--read-only` refuses every write server-side -- not by hiding the buttons --
so a dashboard can be shared without handing over the charger.

Two more guards, both because a local server that reconfigures hardware is a
worthwhile target: the `Host` header must be an IP address or `localhost`
(`--allow-host NAME` if you use a hostname), which is what stops a page
elsewhere from pointing a name it controls at your loopback address; and
every write must carry a header a cross-origin form cannot set.

### What a property is about, not just what it is called

The charger answers `GET /api/prop` with an id, a value and a type code, and
nothing else -- the names live only in the vendor's `EDS.xml`, which ships
with the app and with this package. The property browser leads with what
that catalog says a property *is* ("Plug/Charge Id"), keeps the parameter
name and the protocol id under it for the questions that are id-shaped, and
shows an enumerated value as the word the catalog gives it as well as the
number the charger stores and a write has to send back: `sysLoadBalancingMode`
reads `0`, and `0` is "Static and Active Load Balancing Off".

The catalog is not complete. A 7.4.5 NG910 answers for 311 properties and
the EDS describes 93 of them, so a browser that printed the id where the name
should go -- which is what it did -- said nothing about two rows in three.
Some of the rest are properties *this* program understands, because it reads
them by id in `status.py`, `hardware.py`, `scn.py` and the others, every one
a named constant with the app's own field name beside it;
[`glossary.py`](src/alfenctl/glossary.py) is that knowledge in the shape the
browser wants, and it names hundreds more besides -- the board revisions,
the modem, the socket state blocks, the smart-meter register map. The rest
of the file is filled in from the vendor's own apps, each reverse-engineered
in this repo's ``research/`` directory (guide and findings per source): the
Windows installer's panels and the tooltip catalog it ships
(``research/windows/windows-findings.md``), the My Eve Android app's
embedded id-to-name dictionary
(``research/android/android-findings.md``), and the alfen-wallbox Home
Assistant integration (``research/home-assistant/ha-findings.md``) --
together they name everything a live charger reports except three registers
(`3251_0`, `3253_0`, `3295_0`) that no source has a word for. Nothing in
it is inferred. What no source describes is not left to guesswork: a
guessed name on a register that reconfigures a charger is worse than no
name at all, so the row carries a "purpose unknown" badge in place of a
name, the tooltip says what that means (not in the vendor's catalog, its
apps, or this program), the count above the table says how many rows are
in that state, and the "described only" checkbox hides them when you are
looking for something else. The CLI marks the same rows with a `?` in the
TITLE column, and both JSON shapes carry the same fact as `known: false`.

The reads accumulate. A read of one category used to clear whatever the
last one had brought back, so looking at two categories meant reading each
of them twice; now a read refreshes the rows it covers and leaves the rest
where they were, and the category badge on a row is the category the
charger itself reported for it. The license registers belong to no
category -- they answer only to reads by id -- so they appear in the
"every category" walk and in no single category, rather than trailing
along after whichever one the browser asked for.

The tab is also where it was left. It used to rebuild itself on every visit
-- a fresh read of the category list, a hold of the one connection, and the
rows you had just read gone -- so what survives a tab switch (the
categories, the loaded rows, the category, the filter and the two
checkboxes) lives in the page's own state and is cleared when the station
changes. The category list is read once per charger, and the select is wide
enough for a name before the list arrives, which is what used to move every
control beside it a second after the tab opened. The select also holds
still while the page re-renders around it: the link beat redraws the page
once a second while a station is connected, and each redraw used to touch
every option in the list, which rebuilt the open dropdown under the
pointer and moved the highlight -- the selection "jumped" to a different
option every few seconds. An option list that has not changed now hands
the differ back what it already rendered, so the open dropdown is left
alone.

### The dashboard's first two rows

On a laptop the grid is three cards wide, so the first two rows -- six
cards -- carry what anybody opening the page is looking for: the sockets
with their limits, the live meter, the temperature with its alarm band
beside the display's brightness, a load-balancing summary (the answer to
"why is it only drawing 6 A" without leaving the dashboard), the
station's identity with its clock, and the doctor's health check. The
licence -- opened rarely, and never in a hurry -- sits below the fold.

Three cards were folded into others to make that fit. The on-screen
price is a display setting rather than a tariff -- nothing on the charger
bills anybody -- so it lives under what the screen shows. The
temperature joins it, for the reason above. The clock lives in
*Station*: a clock nobody set is part of who the station is, and the
drift badge beside the uptime says so. The temperature and display card
comes third, ahead of load balancing: between the two, it is the one
more likely to be what somebody came to change.

*Health* is the doctor's one-pass check. It is not run on load -- a full
pass reads every panel and takes seconds -- but one click answers "is
this charger okay" with the same findings the terminal prints, each with
the area it came from. It used to be a loose button above the grid, which
made it the one thing on the page that was not a card and looked it.

#### The line under the number

The live meter carries a chart of what the station has been drawing, and
it is the page's own memory rather than anything the charger keeps: the
station's registers say what is happening now and what has happened in
total, and nothing in between. Every reading the live refresh brings is
kept -- about half an hour of them at the default beat -- in the tab, per
station, and thrown away when the station changes.

It exists for one question that a number on its own cannot answer: you
moved a slider, and did anything happen? Which is also why the writes are
on it. The page already remembers every operation the connection has run,
so each write is a dashed tick under the line, and the change and its
effect are next to each other. The full scale is rounded up to a whole
kilowatt so the line's height means the same thing between one look and
the next, instead of rescaling every time the car takes another 40 W.

#### Load balancing, with the mode

The load-balancing card was five read-only rows and a sentence saying the
controls were on another tab, which is an odd thing for a dashboard to say
about the answer to "why is it only drawing 6 A" -- that answer is usually
"because one of these is set to what it is set to". The mode, and the two
currents the station falls back to, are editable here, with the meter
protocol beside them.

The mode is one setting made of two register bits. The charger keeps
static and active in one byte and the vendor's app offers them as two
checkboxes, which is what this card offered too -- with the word those two
add up to printed above them, read-only. So the row that says what the
station is doing was the row that could not be changed, and "stop managing
it" was a puzzle in two parts with its answer written out beside it. Four
combinations, four options; the Charging tab keeps the two switches for
anyone who would rather think in bits.

The phases, the meter's data source and solar stay in the full editor on
the Charging tab: those are configuration, not a decision anybody makes
while looking at a charging car. The card says so in its own folding
line now, rather than as a sentence printed under its last field.

Both write to the same endpoint, and the reply goes into the panel store,
so the full editor already agrees with the dashboard by the time anyone
opens it.


### The panel tabs

The other tabs are named for the job, not the command: someone looking
for "why won't my car charge" checks the dashboard and then Access;
"why is it only drawing 6 A" checks Charging; "is it talking to my
CSMS" checks Backoffice. Where the vendor's own app has a panel with
the same content, the card carries its name -- *Load balancing*,
*Authorization* -- so a user arriving from ACE Service Installer or My
Eve recognises the layout.

The log used to be a radio button inside a *History* tab, which is a poor
place for the one thing that answers "why did it stop charging at three in
the morning": two clicks away, and invisible until you found it. It is a
tab, next to the *Sessions* it explains.

Every panel keeps its own state: read once per station on first visit,
kept across tab switches, cleared when the station changes. That claim
was in this document before it was true -- the tabs swapped components,
so leaving one unmounted it and coming back re-read a charger that had
not changed, and threw away whatever was half-typed into it on the way.
A visited tab now stays built and is hidden, and what each panel read
lives in a store keyed by the endpoint rather than by the component that
asked, so two cards that want the same document (the balancing card and
the solar card are both `/lb`) share one read instead of making two.

Editing follows the dashboard's pattern -- a card's fields edit together,
Apply sends what changed, Discard drops it -- and anything destructive (a
profile clear, a whitelist clear, a rebooting SCN join, an erase) asks
first, with the reason in the dialog.

#### Sessions, added up

The charger's transaction database is paged in whole -- there is no way to
ask it for less -- so one read answers every question the tab can be
asked, and the server totals the rows all three ways on the way past.
Switching between by-month, by-socket and by-tag is then a click rather
than another walk of the charger. It opens on the monthly view, as
`alfenctl transactions --summary` does: "how much was March" is the
question people have, and four hundred rows is not the answer to it. A
month opens in place to the sessions behind it, and every session is still
one click away for anyone who wants to read the lot. The grouping used to
exist only inside the CSV download, which is a strange place to keep it.

Above the table is one bar per period, standing on the axis, and the
period is whichever the table is grouped by. It was always a day, so the
monthly view the tab opens on sat under four hundred daily bars, most of
them the days nobody charged: a floor of nothing with a scatter of
one-pixel spikes over it, which is neither a shape anybody can read nor
what the table underneath was saying. Twelve bars answer what twelve rows
are asking, and each is wide enough to point at. By socket and by tag are
not periods at all, so they keep the daily history: their table is not
about time, and the history is still worth having above it.

Pointing at one lights the bar, and the reading appears above it. There
is no vertical rule on this chart, as there is on the live meter's line:
the line has nothing else to mark the moment with, and a bar chart has
the bar.

#### One shape for a card

Three widths, and no more: one column of the grid, two for a form that
needs them, and the full row for content that genuinely is a row wide -- a
table, the log, a list of firmware releases. Eleven cards used to take the
full row, which is what made a page of them read as a stack of banners.

The width of a field's name is one number for the whole page rather than a
fraction of each card, so the values line up down the page instead of
stepping in and out with whatever the longest label in each card happened
to be. And a card opens with one line about itself, with the paragraph
folded behind it: half of them used to lead with three or four sentences,
which pushes the controls down, wraps to a different number of lines in
every card, and leaves the cards in a row ending at four different heights.


Long operations run as jobs and report on the event stream, exactly as
firmware uploads always have: a backoffice preset clears the old
operator's settings, uploads through the firmware channel, and needs a
reboot, so it answers with a job id and progress rather than holding
the request.

### How it is built

No web framework, on either side. The server is `http.server`'s threading
server with a small router (~300 lines): everything behind it is
synchronous -- one httpx client on one worker thread -- so thread-per-
connection is the shape that fits, and an event stream is just a handler
thread blocking on a queue. Updates reach the browser over one
Server-Sent Events stream, multiplexed by event name.

The page is [Preact] with [htm], vendored as a single 13 KB ES module, so
there is **no build step and no Node toolchain**: the files that ship in the
wheel are the files you edit. Dark on true black, with Alfen's blue for
identity and amber for anything live or in motion. What a build step would
have caught is caught by [Biome] and `tools/frontlint.py` instead (see
[CONTRIBUTING.md](../CONTRIBUTING.md)).

Which theme you get is the system's answer, not ours: the button in the
header cycles **system → light → dark**, and on *system* the page follows
`prefers-color-scheme` and re-follows it when the machine changes its mind
at dusk. Only an explicit choice is remembered, and it is remembered per
browser. The stylesheet declares `color-scheme` with each palette, so the
half of the page the *browser* paints -- a checkbox's tick, a number
input's spinners, a select's arrow and popup, a scrollbar -- follows the
same choice: `<meta name="color-scheme">` cannot, since it names the
schemes a page supports and lets the machine pick between them, which is
how a laptop set to dark used to put black checkboxes on a light page.

The resolution happens in JavaScript rather than in a media query
because the stylesheet is dark on `:root` and light behind
`[data-theme="light"]`, and answering the media query as well would mean
keeping the light palette written twice -- and the page does not run without
JavaScript in any case.

The dark theme keeps the canvas at `#000` -- a station checked at night in a
dark garage should not light up the room -- but the panels on it were only
1.07:1 above that with a 1.3:1 border, which is a card you can find only by
knowing where it is. The edge does the separating now (2.3:1 against the
canvas, and 3:1 for a control's own outline) with the fill still dark, so
nothing glows that is not text. Cards stretch to their row rather than each
keeping its own height, and the row that commits a card's edits sits against
its bottom edge, so a page of them reads as a grid instead of a pile; values
end at the card's right edge rather than starting at the label's, which is
what puts the readings in a column with each other and with the card below.

[Preact]: https://preactjs.com/
[htm]: https://github.com/developit/htm

