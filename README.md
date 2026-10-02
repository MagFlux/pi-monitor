# pi-monitor

A single-file Python script (`pi_monitor.py`) that generates a static HTML health dashboard for a Raspberry Pi. Run it with `--serve` to host the page **and** regenerate it automatically on a configurable schedule — one command, no cron, no separate web server, and no SD-card writes (the page lives in memory). Or run it on a cron schedule and serve the output with any web server.

## Screenshots

### Light mode:

![](docs/images/pimonitor-light.png)

### Dark mode:

![](docs/images/pimonitor-dark.png)

## Requirements

- Python 3.7+
- Standard library only — no pip dependencies
- Optional: `iw` for Wi-Fi stats, `vcgencmd` for temperature/throttle/voltage (Raspberry Pi firmware tool)

## Usage

All-in-one (recommended) — serve and auto-update in one command, no disk writes:

```bash
# Serve at http://localhost:8080 and regenerate the page every 5 minutes
python3 pi_monitor.py --serve

# Same, but refresh every 60 seconds and listen on port 9000
python3 pi_monitor.py --serve --interval 60 --port 9000

# Only reachable from the Pi itself (not the LAN)
python3 pi_monitor.py --serve --bind 127.0.0.1

# Additionally mirror each update to a file (e.g. for nginx on the same box)
python3 pi_monitor.py --serve --also-write /var/www/html/index.html
```

One-shot (generate once and exit, e.g. from cron):

```bash
# Write to the default location (same directory as the script)
python3 pi_monitor.py

# Write to a different location
python3 /home/pi/pi_monitor.py --output /var/www/html/index.html

# Enable optional status panels
python3 /home/pi/pi_monitor.py --tailscale
python3 pi_monitor.py --docker

# See all options
python3 pi_monitor.py --help
```

### Command-line options

| Option | Default | Description |
|---|---|---|
| `--output`, `-o` | `pi_monitor.html` next to the script | Where to write the HTML file in one-shot mode. With `--serve`, a file is only written when `--also-write` is used |
| `--ping-host` | `8.8.8.8` | Host to ping for the connectivity check |
| `--ping-count` | `4` | Number of ping packets to send |
| `--tailscale` | off | Enable the Tailscale status panel |
| `--tailscale-container` | `tailscale` | Docker container name to query when native `tailscale` is not found |
| `--docker` | off | Enable Docker status panel. The user running the script must be in the `docker` group, see below |
| `--serve` | off | Serve the page with Python's built-in web server and regenerate it every `--interval` seconds. The rendered page is held in memory — no SD-card writes. Blocks until Ctrl+C |
| `--also-write` | off | With `--serve`: also write every update to this file (e.g. to publish it with nginx) |
| `--interval` | `300` | Seconds between regenerations while serving, measured cycle-start to cycle-start. The browser auto-reloads at the same rate. If a collection cycle is slower than the interval, the page refreshes as fast as possible |
| `--port`, `-p` | `8080` | Port for the built-in web server (with `--serve`) |
| `--bind` | `0.0.0.0` | Interface to bind to. `0.0.0.0` serves the LAN, `127.0.0.1` local only (with `--serve`) |

### Run as a service

`--serve` blocks until Ctrl+C, so it also works well under systemd:

```ini
[Unit]
Description=pi-monitor dashboard
After=network-online.target

[Service]
ExecStart=/usr/bin/python3 /home/pi/pi_monitor.py --serve --interval 300
Restart=on-failure
User=pi

[Install]
WantedBy=multi-user.target
```

### Cron setup

Alternative when you already have a web server (e.g. nginx): skip `--serve`, write to the web root from cron, and let the server host the file.

```cron
*/5 * * * * /usr/bin/python3 /home/pi/pi_monitor.py --output /var/www/html/index.html > /dev/null
```

The generated page auto-refreshes every 5 minutes to match. If you use a different cron period, also pass a matching `--interval <seconds>` so the browser reloads in step.

## What it monitors

### Core

- **System info** — hostname, uptime, OS, kernel, architecture
- **CPU** — usage %, load average (1/5/15 min), frequency, core voltage
- **Temperature** — SoC temperature with throttle status and active throttle flags
- **Memory** — used/available RAM and swap
- **Connectivity** — public IP, ping RTT and packet loss to `--ping-host` (default `8.8.8.8`)
- **Ethernet** — state, speed and IP (if your Pi has an Ethernet port)
- **Wi-Fi** — SSID, signal, TX rate and IP
- **Disks** — usage for all non-virtual mounts
- **Listening ports** — TCP/UDP ports read from `/proc/net` (no root required)
- **Top processes** — top 5 by CPU usage

### Optional

- **Tailscale** — VPN state, Tailscale IP/DNS, peer count, active peers, and relay breakdown
- **Docker** — container state

**Requirement for Docker panel:** the user running the script must be in the `docker` group:

```bash
sudo usermod -aG docker $USER
```

## Output

A self-contained HTML file with light/dark mode toggle (preference persisted in `localStorage`). The only external resource is the Google Fonts stylesheet.

Every generated file also embeds the live-update script: when served over HTTP it keeps itself current in place (no full-page reload, see *Serving the output*), and browsers without JavaScript fall back to a full-page meta-refresh.

The page degrades gracefully: any metric that cannot be collected (e.g. `vcgencmd` not available) shows `N/A` or is hidden rather than crashing the script.

## Serving the output

### Built-in (with `--serve`)

The script's `--serve` mode uses Python's built-in HTTP server and regenerates the page on the configured interval — no other tooling required:

```bash
python3 pi_monitor.py --serve --interval 300 --port 8080
```

The rendered page is held **in memory** and served directly — nothing is written to disk, so even `--interval 1` causes no SD-card wear. The page is generated once before the server starts, so `http://<pi-ip>:8080/` works immediately, then a background thread re-renders it every `--interval` seconds.

The browser keeps itself current **without reloading the page**: a small script inside it re-fetches the page on the same interval and swaps in only what changed — no white flash, no lost scroll position, and the clock in the header updates in place. Unchanged cycles are answered with an `HTTP 304` (each version is tagged with an ETag), so an idle dashboard costs almost nothing. Browsers without JavaScript fall back to the classic full-page meta-refresh.

If you also want the page published as a file for another server on the same box (nginx, etc.):

```bash
python3 pi_monitor.py --serve --also-write /var/www/html/index.html
```

Each update is mirrored to that file atomically.

### Any static file server

Any static file server also works against the generated file. A minimal option using Python itself:

```bash
python3 -m http.server 8080 --directory /var/www/html
```

Or with nginx:

```nginx
server {
    listen 80;
    root /var/www/html;
    index index.html;
}
```

## Developing

A VS Code devcontainer and `Makefile` are included to make it easy to work on the script without a physical Pi.

### Devcontainer

Open the repo in VS Code and choose **Reopen in Container**. The container provides Python, Pylance, and Ruff, plus stub `vcgencmd` and `iw` commands so the script runs on non-Pi hardware.

### Makefile

```bash
make help             # list all available targets
make serve            # serve the live dashboard at http://localhost:8080 (in-memory, auto-regenerates)
make clean            # remove the output directory
make test             # run all tests (unit + integration)
make test-unit        # run unit tests only
make test-integration # run integration tests only
make lint             # run ruff linter
```

### Tests

Unit tests mock all I/O (subprocess calls, `/proc` reads) and run in about 5 seconds — the HTTP handler tests spin up a real server in-process on an ephemeral port. Integration tests run `pi_monitor.py` as a real subprocess and check both the generated HTML and the live server (memory serving, ETag/304, in-place update wiring); they take around 10 seconds thanks to parallel probe collection.

The devcontainer includes stub `iw` and `vcgencmd` commands so both test suites work without Pi hardware.

An `AGENTS.md` file documents the architecture, invariants, and testing conventions for coding agents working in this repo.
