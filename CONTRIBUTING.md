# Contributing

Bug reports and patches are welcome. If you have a charger the project has
not seen -- an AHP, a Twin, an old pre-5.0 NG9xx -- then the output of
`alfenctl info` and `alfenctl props --json` is itself useful: most of what
this tool knows was learned from one NG910 and a decompiled installer.

## Getting set up

The project uses [uv](https://docs.astral.sh/uv/) for environment and package
management, [pytest](https://docs.pytest.org/) for tests,
[Ruff](https://docs.astral.sh/ruff/) for linting and formatting, and
[ty](https://docs.astral.sh/ty/) for type checking.

```console
$ uv sync                      # create the venv and install everything
$ uv run pytest                # run the test suite (no charger needed)
$ uv run ruff check .          # lint the Python
$ uv run ruff format --check . # formatting
$ uv run ty check              # type-check the package
$ biome ci                     # lint the browser half
$ uv run python tools/frontlint.py  # ... and what Biome cannot see
$ uv run python tools/htmcheck.py   # ... and what only a render would
$ uv build                     # build the sdist and wheel
```

The README's screenshot is generated, not taken by hand: `tools/screenshot.py`
runs the real web server against `tests/webfake.py` -- the same fake charger
the web tests use -- and photographs the dashboard, so no real station's
object ID, position or licence key ends up in a picture. Regenerate it when
the dashboard changes:

```console
$ uv run --with playwright playwright install chromium   # once
$ uv run --with playwright python tools/screenshot.py
```

Playwright is not a project dependency (it brings its own browser, and the
picture is wanted about once a release). The run takes about twenty
seconds: rather than sit in front of the browser for the three minutes the
power chart's narrowest window needs, the script writes a plausible session
straight into the sessionStorage the chart keeps its samples in, so the
trace in the README is a scripted demonstration rather than a recording.
`--help` lists the knobs -- `--history 0` records live instead, and there
are `--theme light`, `--tab` and `--full` for the whole page.

The tests exercise the client against `httpx.MockTransport`, the firmware
parsing/compatibility logic against synthetic container images, the logo
containers byte-for-byte (header CRCs, AES round-trip, embedded vendor
blobs vs. the decompiled sources), the firmware server against an in-memory
FTP stand-in (listing, filtering, download, bundle unpacking), and the
upgrade sequence against a fake charger — no hardware and no network are
required to develop. The web UI is covered too: the event bus, the station
worker's link states and job progress, the API handlers, and the server
itself over a real socket (its guards, its SSE framing).
The browser half lives in `src/alfenctl/web/static/` and is plain ES
modules -- edit and reload, there is nothing to build. Three things check
it. [Biome] parses and lints it (`biome.json`); it is a single native
binary, so it needs no Node (`pacman -S biome`, a [release binary][biome-releases],
or `npx @biomejs/biome`). It is not a project dependency, and the `pytest`
case that runs it skips when it is absent. `tools/frontlint.py` checks what
Biome cannot see -- the wiring between the modules, which has no build step
to catch it, and the wiring between the modules and the stylesheet, in both
directions: a rule nothing wears is dead weight (`C002`), and an element
wearing a class no stylesheet defines is an invisible bug (`C003`), since
the browser applies nothing and reports nothing and the element simply
renders as a plain block. `tools/htmcheck.py` renders every template through the

vendored parser itself, in an embedded V8 (``mini-racer`, a dev
dependency -- one wheel, nothing to compile, and the check skips when it
is absent), because some template mistakes only a render reveals: an
attribute that lost its `$`, or a `/* ... */` written inside the markup,
which is not a comment there and reaches the page as text. Both tools'
docstrings say what and why.


[Biome]: https://biomejs.dev/
[biome-releases]: https://github.com/biomejs/biome/releases


## How the code is laid out

`src/alfenctl/` is one module per subject, and none of them prints:

* `charger.py` -- the HTTP client and the session; every request goes
  through it.
* `eds.py`, `values.py`, `properties.py` -- the property catalog, one
  property's value, and finding properties by name or pattern.
* `upgrade.py`, `firmware.py`, `repo.py`, `logo.py` -- firmware images,
  where to get them, and the containers a charger accepts.
* `status.py`, `logs.py`, `clock.py`, `controls.py`, ... -- one subject
  each, each used by both front ends.
* `report.py` -- how a slow operation says what it is doing, so that
  `upgrade.py` can be driven from a terminal or from a browser.
* `errors.py` -- `AlfenError`, which every expected failure derives from.
  A command reports one; anything else is a bug and gets a traceback.

The two front ends are `cli/` and `web/`, and they are the only places that
print, prompt, or return an exit code.

## The two files we did not write

`src/alfenctl/EDS.xml` (the property catalog) and
`src/alfenctl/logo_blobs.bin` (the display assets every `.fwu` package must
carry) come out of Alfen's own installer and cannot be regenerated from
anything in this repository. `tools/extract_assets.py` is the record of how
they got here: its docstring says where to obtain the inputs, it rebuilds
both files, and `--check` compares them against what we ship without
writing anything -- which is what to run against a new release of the app.

```console
$ tools/extract_assets.py --check --app-dir /path/to/app --objects /path/to/ICUObjects.cs
```

`logo_blobs.bin` has no framing: it is seven byte arrays concatenated, and
`alfenctl.logo.FWU_FIXED_OBJECTS` is the single table that says which,
in what order, and how long each one is. `tests/test_logo.py` rebuilds the
file through the tool and compares, whenever the decompiled sources happen
to be next to the checkout; it skips when they are not.

The vendored Preact/htm bundle (`web/static/vendor/preact-htm.module.js`)
is third-party MIT code; its license notice is embedded as a comment at
the top of the file and must travel with it. The project's own EUPL-1.2
license does not extend into that file.

## Adding a command

Write the handler in the right module of `src/alfenctl/cli/commands/`,
describe it in that module's `add_parsers`, and name it in that module's
`COMMANDS`. Nothing outside that file changes.

## Before you send it

`uv run pytest`, `uv run ruff format .`, `uv run ruff check .` and
`uv run ty check` all have to pass; CI runs exactly those, on Python 3.10,
3.12 and 3.14. New behaviour wants a test -- the suite needs no hardware
and no network, so there is no excuse not to have one.
