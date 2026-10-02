<!--
AGENTS.md — guide for coding agents working on pi-monitor.
Licensed under the MIT License — see LICENSE or https://github.com/jonnyry/pi_monitor
-->

# AGENTS.md — guide for coding agents working on pi-monitor

A single-file Python script (`pi_monitor.py`) that generates a static HTML
health dashboard for a Raspberry Pi. Two modes:

- **One-shot** (`python3 pi_monitor.py`): collect stats, render one self-contained
  HTML file, exit. Intended for cron + any static web server.
- **Serve** (`python3 pi_monitor.py --serve`): hold the rendered page **in memory**,
  serve it with Python's built-in `ThreadingHTTPServer`, and re-render it every
  `--interval` seconds. No disk writes unless `--also-write PATH` is given
  (protects SD cards from wear at short intervals).

## Commands

```bash
make test             # full suite: unit + integration (~15 s)
make test-unit        # unit only (~5 s) — run these while iterating
make test-integration # integration only (~10 s) — real subprocesses, live probes
make serve            # serve the live dashboard at http://localhost:8080
make lint             # ruff check pi_monitor.py tests/ (installed in devcontainer)
make clean            # remove output/ dir
```

Tests need no Pi hardware: the devcontainer provides stub `vcgencmd` and `iw`
binaries; everything else degrades to `N/A` placeholders by design. `pytest` and
`ruff` are preinstalled in the devcontainer but not required by the script itself.

## Documentation — always keep in sync with any change

Every behavior or workflow change must land together with its documentation.
Treat the docs as part of the change, not a follow-up:

- **README.md** — new/changed CLI flags go in the options table with accurate
  defaults; new user-facing behavior gets usage examples or a section update.
- **AGENTS.md** — if a change touches architecture, invariants, or testing
  conventions, update the relevant section (invariants are numbered — keep
  numbering stable and add at the end). Commit formatting follows the
  **Commits** section below; keep the two in sync.
- **`--help` strings** — argparse help must match actual behavior and defaults.
- **Module docstring** (top of `pi_monitor.py`) — keep the mode examples current.
- **Makefile help text** — when a target's behavior changes, its help line
  changes with it.

Before finishing any task, re-read the diff and ask: "does any doc now describe
the old behavior?" If yes, the change is not done.

## License compliance

The project is MIT (see `LICENSE`, © 2026 Jonny Rylands). On every change:

- **New files** carrying copyrightable content get the MIT header (copyright
  line + SPDX/reference to `LICENSE`), matching `pi_monitor.py`'s header.
- **Runtime dependencies stay stdlib-only** (invariant #1). If one is ever
  truly required, its license must be MIT-compatible (MIT / BSD / Apache-2.0 /
  ISC — not GPL-family for linked code), and it must be documented in
  README.md's Requirements section.
- **Copied/adapted snippets** from third parties: verify the source license is
  MIT-compatible, keep attribution, and note it in a comment.
- Never strip or alter copyright/license headers, and never relicense
  third-party content.
- The Google Fonts stylesheet is a runtime external reference (not bundled), so
  it carries no distribution obligation — keep it that way rather than vendoring
  font files.

## Commits

Every commit message follows the **Conventional Commits** format
(<https://www.conventionalcommits.org>): a mandatory `type`, an optional
scope, and an optional `!` for breaking changes, then the summary line
followed by a blank line and the body:

```
feat(serve): add in-memory live dashboard

- hold the rendered page in a PageStore and serve it from memory (no disk writes)
- regenerate the page on --interval, paced cycle-start to cycle-start
- provide conditional GET (ETag/304) handling; unknown paths 404
- add option flags --serve, --interval, --port, --bind, --also-write to the CLI
- add unit and integration tests for the server and refresh loop
```

Scope (optional, lowercase): the area touched — `serve`, `dash`,
`tests`, `docs`, `ci`, `build`, etc. Scope aliases are acceptable where
the name alone may be ambiguous (`dash` for the dashboard page).
Omit it when a change spans several unrelated areas.

Commit **types** and when to use them:

- **`feat`** — new features: new flags, panels, endpoints, opt-in behavior.
- **`fix`** — bug fixes affecting users.
- **`docs`** — documentation-only changes (README, AGENTS.md, comments).
- **`test`** — test-only additions or corrections.
- **`refactor`** — code restructures with no behavior change.
- **`build`** / **`ci`** — build system, packaging, or CI configuration.
- **`chore`** — maintenance that fits no other type.

Type vs. SemVer: `feat` = MINOR, `fix` = PATCH, anything else = PATCH;
**breaking changes bump MAJOR** regardless of type. Mark them with `!`
after the type/scope plus a `Breaking-Change: reason` trailer, e.g.
`feat(cli)!` or `refactor(page)!`. (The `!` above is a shorthand for
the full form.)

Rules obeyed by every commit: summary line is imperative, lowercase
after the colon, ≤ ~72 chars; bullets are one change each; never bundle
unrelated changes into one commit — split it. For merge commits,
`merge:` may be used for the subject line (Conventional Commits
explicitly permits this).

When in doubt, a `feat` with `Breaking-Change` trailer is the most
explicit, safest encoding of a significant change.

## Architecture (all in pi_monitor.py, ~1500 lines)

Data flow: `make_cards()` builds card objects → cards `.collect()` (parallel,
ThreadPoolExecutor) → `build_html()` renders → output goes to disk (one-shot)
or a `PageStore` (serve).

- **Card classes** (`CpuCard`, `TemperatureCard`, `MemoryCard`, `ConnectivityCard`,
  `WifiCard`, `EthernetCard`, `TailscaleCard`, `DockerCard`, `DiskCard`,
  `PortsCard`, `ProcessesCard`): each has `collect()` (gathers data, defensive —
  never raises on missing probes) and `render()` (returns an HTML fragment).
  Fresh card objects are built every generation cycle; cards write only their
  own attributes.
- **Probing helpers**: `run()` (shell, adds sbin dirs to PATH) and `run_cmd()`
  (argv list) return the `fallback` string on any failure. `read()` reads files
  with fallback. `_safe_iface()` validates interface names against shell injection.
- **`build_html()`**: full page template. Dynamic content lives inside
  `<div id="live">`; header (hostname/uptime/clock) is outside it.
- **`_css()` / `_js()`**: page CSS and JS. `_js()` is a plain string with a
  `__REFRESH_SECS__` placeholder (NOT an f-string — avoids brace escaping);
  `_js(refresh_secs)` substitutes it.
- **Live-update design**: the page JS polls its own URL every cycle, parses with
  `DOMParser`, and swaps `#live` innerHTML only when content differs. Header
  clock/date/`#sysline` (uptime) tick via cheap text updates outside `#live`.
  `<meta http-equiv="refresh">` sits inside `<noscript>` as the no-JS fallback.
- **Serve mode**: `PageStore` holds the current page + weak ETag behind a lock.
  `_make_handler_class(store, filename)` serves from memory (200 / ETag-304 /
  404 for unknown paths; no filesystem access). `_refresh_loop()` paces cycles
  **start-to-start** (`_next_wake()`), prints a one-time note when collection
  is slower than the interval, and keeps serving through per-cycle failures.
- **`_collect_and_render()`** is the shared cycle; `_collect_and_write()` is the
  one-shot wrapper (renders + `_atomic_write()` = tmp file + `os.replace`).

## Invariants — do not break these

1. **Standard library only, Python 3.7+**. No pip dependencies in the script.
2. **Single-file philosophy**: everything lives in `pi_monitor.py`.
3. **Serve mode writes nothing to disk** unless `--also-write` is passed.
   The one-shot mode writes atomically (tmp + `os.replace`) — never plain
   `write_text` directly to the target when browsers/fileservers may read it.
4. **Nothing that changes every cycle may live inside `<div id="live">`**
   (e.g. no per-cycle timestamps in the footer): it would force a full dashboard
   DOM rebuild every cycle and reintroduce scrollbar/layout churn. Header clock
   and `#sysline` are the sanctioned per-cycle text updates.
5. **Exactly one `<header>` in `build_html()` output**, closed before
   `<div id="live">`. `test_build_html_structure_is_well_formed` parses the
   emitted page and enforces balanced tags — if it fails, fix the template,
   don't weaken the test.
6. **`--interval` semantics**: measured cycle-start to cycle-start (not
   sleep-after-work); CLI floor is 1 second; a collection cycle slower than the
   interval means back-to-back refreshes with a printed note. The page's
   `<meta http-equiv=refresh>` (noscript) and JS poll interval must match it.
7. **HTML-escape every dynamic value** in templates (`h = html.escape`) —
   hostnames, interface names, etc. are untrusted.
8. **Pings use `-i 0.2` with fallback** to the plain form (some ping variants
   reject fractional intervals — never let the fallback silently disappear).
9. Card `collect()` methods must stay defensive: missing tools/files degrade to
   `N/A` or hidden cards, never crash the page.

## Testing notes

- `tests/test_unit.py`: fast, all I/O mocked (`unittest.mock.patch` of
  `pi_monitor.read` / `pi_monitor.run` / card methods). HTTP handler tests run an
  in-process `ThreadingHTTPServer` on an ephemeral port (port 0) — no fixture
  port conflicts.
- `tests/test_integration.py`: runs `pi_monitor.py` as a real subprocess. Serve
  tests pick a free port via `_free_port()` and wait with generous deadlines;
  they assert serve mode writes **no** file (unless `--also-write`). One-shot
  tests assert stdout contains `[pi_monitor] Written to`.
- Timing-based loop tests use sub-second intervals (0.05s) and generous
  assertions (≥ 2 calls) — don't make them tighter; flaky CI isn't worth it.
- The subprocess in integration tests is launched with `python3 -u` so stdout
  assertions aren't lost to block buffering.
- Run `make test-unit` while iterating; run the full `make test` before done.

## Style

- Section headers use the `# ── Section ──...` box-drawing comment style.
- f-strings everywhere; keep the aligned-assignment style used in config/main.
- MIT license header — new files should reference it if they carry the same
  copyright line (see License compliance).

Doc sync, license checks, and commit formatting are covered by their own
sections above — they apply to every change, not just style-sensitive ones.
