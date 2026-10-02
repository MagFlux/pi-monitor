"""Unit tests for pi_monitor.py — pure functions and mocked card data-collection."""
import pathlib
import time
from unittest.mock import patch

import pi_monitor


# ── Colour helpers ─────────────────────────────────────────────────────────────

def test_pct_color_ok():
    assert pi_monitor.pct_color(0) == "ok"
    assert pi_monitor.pct_color(59) == "ok"

def test_pct_color_warn():
    assert pi_monitor.pct_color(60) == "warn"
    assert pi_monitor.pct_color(84) == "warn"

def test_pct_color_crit():
    assert pi_monitor.pct_color(85) == "crit"
    assert pi_monitor.pct_color(100) == "crit"


def test_temp_color_none_is_ok():
    assert pi_monitor.temp_color(None) == "ok"

def test_temp_color_ok():
    assert pi_monitor.temp_color(0) == "ok"
    assert pi_monitor.temp_color(64) == "ok"

def test_temp_color_warn():
    assert pi_monitor.temp_color(65) == "warn"
    assert pi_monitor.temp_color(79) == "warn"

def test_temp_color_crit():
    assert pi_monitor.temp_color(80) == "crit"
    assert pi_monitor.temp_color(95) == "crit"


def test_invert_pct_color_ok():
    assert pi_monitor.invert_pct_color(100) == "ok"

def test_invert_pct_color_warn():
    assert pi_monitor.invert_pct_color(95) == "warn"
    assert pi_monitor.invert_pct_color(90) == "warn"

def test_invert_pct_color_crit():
    assert pi_monitor.invert_pct_color(89) == "crit"
    assert pi_monitor.invert_pct_color(0) == "crit"


# ── bar / status_dot ───────────────────────────────────────────────────────────

def test_bar_class_and_width():
    result = pi_monitor.bar(50, "ok")
    assert 'class="bar-fill ok"' in result
    assert "width:50%" in result

def test_bar_clamps_low():
    assert "width:0%" in pi_monitor.bar(-10, "ok")

def test_bar_clamps_high():
    assert "width:100%" in pi_monitor.bar(150, "crit")


def test_status_dot_ok():
    assert "dot-ok" in pi_monitor.status_dot(True)

def test_status_dot_crit():
    assert "dot-crit" in pi_monitor.status_dot(False)


# ── _safe_iface ────────────────────────────────────────────────────────────────

def test_safe_iface_valid():
    assert pi_monitor._safe_iface("wlan0") == "wlan0"
    assert pi_monitor._safe_iface("eth0") == "eth0"
    assert pi_monitor._safe_iface("enp3s0") == "enp3s0"

def test_safe_iface_rejects_injection():
    assert pi_monitor._safe_iface("wlan0; rm -rf /") is None
    assert pi_monitor._safe_iface("$(evil)") is None

def test_safe_iface_rejects_empty_and_none():
    assert pi_monitor._safe_iface("") is None
    assert pi_monitor._safe_iface(None) is None

def test_safe_iface_rejects_too_long():
    assert pi_monitor._safe_iface("a" * 16) is None


# ── get_uptime ─────────────────────────────────────────────────────────────────

def test_get_uptime_hours_and_minutes():
    with patch("pi_monitor.read", return_value="7262.5 1234.0"):
        assert pi_monitor.get_uptime() == "2h 1m"

def test_get_uptime_days_hours_minutes():
    with patch("pi_monitor.read", return_value="90061.0 0.0"):
        assert pi_monitor.get_uptime() == "1d 1h 1m"

def test_get_uptime_minutes_only():
    with patch("pi_monitor.read", return_value="300.0 0.0"):
        assert pi_monitor.get_uptime() == "5m"


# ── MemoryCard ────────────────────────────────────────────────────────────────

_MEMINFO = """\
MemTotal:        4096000 kB
MemFree:          512000 kB
MemAvailable:    1024000 kB
Buffers:          128000 kB
Cached:           512000 kB
SwapTotal:       1048576 kB
SwapFree:        1048576 kB
"""

def _memory_card_collected(meminfo=_MEMINFO):
    card = pi_monitor.MemoryCard()
    with patch("pi_monitor.read", return_value=meminfo):
        card.collect()
    return card

def test_memory_card_percentage():
    assert _memory_card_collected().mem_pct == 75.0

def test_memory_card_units():
    card = _memory_card_collected()
    assert "GB" in card.mem_total
    assert "GB" in card.mem_used
    assert "MB" in card.mem_avail  # 1024000 kB < 1 GB threshold

def test_memory_card_swap_all_free():
    assert _memory_card_collected().swap_pct == 0.0

def test_memory_card_swap_no_swap():
    no_swap = "SwapTotal:       0 kB\nSwapFree:        0 kB\n"
    assert _memory_card_collected(no_swap).swap_pct == 0


# ── CpuCard — collect and load average ───────────────────────────────────────

def test_cpu_card_collect_sets_attributes():
    card = pi_monitor.CpuCard()
    with patch.object(card, "_get_cpu_percent", return_value=(42.5, 3.2)), \
         patch.object(card, "_get_load_avg",    return_value=("0.5", "0.6", "0.7")), \
         patch.object(card, "_get_cpu_freq",    return_value="1500 MHz"), \
         patch.object(card, "_get_voltage",     return_value="1.2V"):
        card.collect()
    assert card.cpu_pct    == 42.5
    assert card.iowait_pct == 3.2
    assert card.load       == ("0.5", "0.6", "0.7")
    assert card.cpu_freq   == "1500 MHz"
    assert card.voltage    == "1.2V"

def test_cpu_card_load_avg():
    card = pi_monitor.CpuCard()
    with patch("pi_monitor.read", return_value="0.50 0.75 1.00 2/500 12345"):
        la1, la5, la15 = card._get_load_avg()
    assert la1 == "0.50"
    assert la5 == "0.75"
    assert la15 == "1.00"

def test_cpu_card_percent_counts_iowait_as_not_busy():
    # /proc/stat line: user nice system idle iowait irq softirq steal guest guest_nice
    # over the 500-tick window: 200 busy, 300 idle+iowait → 40% busy, 20% iowait.
    card = pi_monitor.CpuCard()
    with patch("pi_monitor.time.sleep"), \
         patch("pi_monitor.Path") as path:
        path.return_value.read_text.side_effect = [
            "cpu  1000 0 500 4000 0   100 0 0 0 0\n",
            "cpu  1200 0 500 4200 100 100 0 0 0 0\n",
        ]
        busy, iowait = card._get_cpu_percent()
    assert busy   == 40.0
    assert iowait == 20.0

def test_cpu_card_percent_stat_without_iowait_field():
    card = pi_monitor.CpuCard()
    with patch("pi_monitor.time.sleep"), \
         patch("pi_monitor.Path") as path:
        path.return_value.read_text.side_effect = [
            "cpu  1000 0 500 4000\n",
            "cpu  1200 0 500 4000\n",
        ]
        busy, iowait = card._get_cpu_percent()
    assert busy   == 100.0
    assert iowait == 0.0

def test_cpu_card_percent_zero_delta_returns_zeroes():
    card = pi_monitor.CpuCard()
    with patch("pi_monitor.time.sleep"), \
         patch("pi_monitor.Path") as path:
        path.return_value.read_text.side_effect = [
            "cpu  1000 0 500 4000 0 0 0 0 0 0\n",
            "cpu  1000 0 500 4000 0 0 0 0 0 0\n",
        ]
        assert card._get_cpu_percent() == (0.0, 0.0)

def test_cpu_card_voltage_na_when_unavailable():
    card = pi_monitor.CpuCard()
    with patch("pi_monitor.run", return_value="N/A"):
        assert card._get_voltage() == "N/A"


# ── TemperatureCard — collect and throttle ────────────────────────────────────

def test_temperature_card_collect_sets_attributes():
    card = pi_monitor.TemperatureCard()
    with patch.object(card, "_get_temperature", return_value=55.0), \
         patch.object(card, "_get_throttle",    return_value=(True, [])):
        card.collect()
    assert card.temperature    == 55.0
    assert card.throttle_ok    is True
    assert card.throttle_flags == []

def test_temperature_card_throttle_ok():
    card = pi_monitor.TemperatureCard()
    with patch("pi_monitor.run", return_value="throttled=0x0"):
        ok, flags = card._get_throttle()
    assert ok is True
    assert flags == []

def test_temperature_card_throttle_active():
    # 0x50005 → bits 0, 2, 16, 18 (under-voltage, throttled, historical variants)
    card = pi_monitor.TemperatureCard()
    with patch("pi_monitor.run", return_value="throttled=0x50005"):
        ok, flags = card._get_throttle()
    assert ok is False
    assert "Under-voltage detected" in flags
    assert "Currently throttled" in flags
    assert "Under-voltage has occurred" in flags
    assert "Throttling has occurred" in flags

def test_temperature_card_throttle_unavailable():
    card = pi_monitor.TemperatureCard()
    with patch("pi_monitor.run", return_value="N/A"):
        ok, flags = card._get_throttle()
    assert ok is None


# ── DiskCard ──────────────────────────────────────────────────────────────────

_DF_OUTPUT = (
    "Target     Size  Used  Avail  Use%\n"
    "/          30G   10G   20G    33%\n"
    "/boot      256M  50M   206M   20%\n"
)

def _disk_card_collected():
    card = pi_monitor.DiskCard()
    with patch("pi_monitor.run", return_value=_DF_OUTPUT):
        card.collect()
    return card

def test_disk_card_count():
    assert len(_disk_card_collected().disks) == 2

def test_disk_card_root_mount():
    disks = _disk_card_collected().disks
    assert disks[0]["mount"] == "/"
    assert disks[0]["pct"] == 33


# ── PortsCard ─────────────────────────────────────────────────────────────────

_TCP = (
    "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
    "   0: 00000000:0016 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 12345 1 0 0 0\n"
)
_EMPTY = "  sl  local_address rem_address   st\n"

_PROC_FILES = {
    "/proc/net/tcp":  _TCP,
    "/proc/net/tcp6": _EMPTY,
    "/proc/net/udp":  _EMPTY,
    "/proc/net/udp6": _EMPTY,
}

def _make_read_text(files):
    def _read(self, **kwargs):
        content = files.get(str(self))
        if content is None:
            raise OSError(f"Mock: no such file: {self}")
        return content
    return _read

def _ports_card_collected(proc_files=_PROC_FILES):
    card = pi_monitor.PortsCard()
    with patch.object(pathlib.Path, "read_text", _make_read_text(proc_files)):
        card.collect()
    return card

def test_ports_card_parses_ssh():
    ports = _ports_card_collected().ports
    assert any(p["proto"] == "tcp" and p["port"] == "22" for p in ports)

def test_ports_card_result_structure():
    for p in _ports_card_collected().ports:
        assert "proto" in p
        assert "port" in p
        assert "addr" in p

def test_ports_card_skips_non_listen_tcp():
    # State 01 = ESTABLISHED, not LISTEN (0A) — port 80 should not appear
    established = (
        "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
        "   0: 00000000:0050 00000000:0000 01 00000000:00000000 00:00000000 00000000     0        0 12345 1 0 0 0\n"
    )
    ports = _ports_card_collected({**_PROC_FILES, "/proc/net/tcp": established}).ports
    assert not any(p["port"] == "80" for p in ports)

def test_ports_card_sorted_by_port():
    multi = (
        "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
        "   0: 00000000:01BB 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 1 1 0 0 0\n"
        "   1: 00000000:0016 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 2 1 0 0 0\n"
    )
    ports = _ports_card_collected({**_PROC_FILES, "/proc/net/tcp": multi}).ports
    port_nums = [int(p["port"]) for p in ports]
    assert port_nums == sorted(port_nums)

def test_ports_card_handles_ipv6():
    # 32-char hex address → takes the IPv6 branch in hex_to_addr_port
    # All-zeros address = "::" → mapped to "*" by the wildcard check
    tcp6 = (
        "  sl  local_address                         remote_address                        st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
        "   0: 00000000000000000000000000000000:0050 00000000000000000000000000000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 99999 1 0 0 0\n"
    )
    files = {**_PROC_FILES, "/proc/net/tcp6": tcp6}
    ports = _ports_card_collected(files).ports
    assert any(p["proto"] == "tcp" and p["port"] == "80" for p in ports)


# ── _fmt_interval ─────────────────────────────────────────────────────────────

def test_fmt_interval_seconds():
    assert pi_monitor._fmt_interval(1) == "1s"
    assert pi_monitor._fmt_interval(45) == "45s"
    assert pi_monitor._fmt_interval(59) == "59s"

def test_fmt_interval_minutes():
    assert pi_monitor._fmt_interval(60) == "1 min"
    assert pi_monitor._fmt_interval(300) == "5 min"
    assert pi_monitor._fmt_interval(3540) == "59 min"

def test_fmt_interval_fractional_minutes():
    assert pi_monitor._fmt_interval(90) == "1.5 min"

def test_fmt_interval_hours():
    assert pi_monitor._fmt_interval(3600) == "1 hr"
    assert pi_monitor._fmt_interval(7200) == "2 hr"
    assert pi_monitor._fmt_interval(5400) == "1.5 hr"


# ── build_html — refresh marker ───────────────────────────────────────────────

def test_build_html_default_refresh_is_300():
    assert '<meta http-equiv="refresh" content="300">' in _html()

def test_build_html_refresh_matches_interval():
    h = pi_monitor.build_html(_make_cards(), refresh_secs=60, **_PAGE_KWARGS)
    assert '<meta http-equiv="refresh" content="60">' in h
    assert "updates in place every 1 min" in h
    assert 'id="live"' in h
    assert "<noscript>" in h
    # the meta refresh lives inside <noscript> so it only applies without JS
    meta_pos  = h.index('<meta http-equiv="refresh"')
    assert h.index("<noscript>") < meta_pos < h.index("</noscript>")

def test_build_html_refresh_clamps_low():
    h = pi_monitor.build_html(_make_cards(), refresh_secs=0, **_PAGE_KWARGS)
    assert '<meta http-equiv="refresh" content="1">' in h

def test_build_html_live_region_and_header_hooks():
    h = _html()
    assert 'id="live"' in h
    assert 'id="sysline"' in h          # uptime line is updatable without a full swap

def test_build_html_structure_is_well_formed():
    """Layout bugs (e.g. a stray unclosed header nesting the grids) must fail here."""
    h = _html()
    assert h.count("<header") == 1
    assert h.count("</header>") == 1
    assert h.count("<body>") == 1 and h.count("</body>") == 1
    assert h.index("</header>") < h.index('<div id="live">') < h.index("<script>")
    # all three card grids live inside #live, not inside the header
    live_block = h[h.index('<div id="live">'):h.index("<script>")]
    for marker in ('class="grid"', 'class="grid-wide"', 'class="footer"'):
        assert marker in live_block
    assert "<header" not in live_block

    # and the tag soup parses to a balanced tree (void elements self-close)
    from html.parser import HTMLParser
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input",
            "link", "meta", "param", "source", "track", "wbr"}
    stack = []
    class Check(HTMLParser):
        def handle_starttag(self, tag, attrs):
            if tag not in VOID:
                stack.append(tag)
        def handle_endtag(self, tag):
            assert stack and stack[-1] == tag, f"tag mismatch: closing </{tag}> but stack is {stack[-3:]}"
            stack.pop()
    Check().feed(h)
    assert stack == [], f"unclosed tags remain: {stack}"

def test_build_html_footer_is_static():
    # The footer lives inside the swapped region; a per-cycle timestamp there
    # would force a full dashboard DOM rebuild every cycle (and scrollbar churn).
    h = _html()
    footer = h[h.index('class="footer"'):]
    footer = footer[:footer.index("</div>")]
    assert "12:00:00" not in footer

def test_css_reserves_scrollbar_gutter():
    css = pi_monitor._css()
    assert "scrollbar-gutter: stable" in css
    assert "minmax(min(100%, 300px), 1fr)" in css  # columns stay fluid on narrow windows

def test_js_ticks_header_without_rebuild():
    js = pi_monitor._js(300)
    assert ".datetime .time" in js
    assert "getElementById('sysline')" in js
    assert "__REFRESH_SECS__" not in js  # placeholder always substituted


# ── _refresh_loop ─────────────────────────────────────────────────────────────

def test_refresh_loop_regenerates_repeatedly(tmp_path):
    import threading
    store = pi_monitor.PageStore()
    calls = []

    with patch.object(pi_monitor, "_collect_and_render",
                      side_effect=lambda make, secs, store=None, output_path=None: calls.append((store, secs))):
        stop = threading.Event()
        thread = threading.Thread(
            target=pi_monitor._refresh_loop,
            args=(stop, 0.05, lambda: {}, store, 300),
            daemon=True,
        )
        thread.start()
        time.sleep(0.4)
        stop.set()
        thread.join(timeout=5)

    assert not thread.is_alive()
    assert len(calls) >= 2
    assert all(call[0] is store for call in calls)
    assert all(call[1] == 300 for call in calls)

def test_refresh_loop_survives_errors(tmp_path):
    import threading
    store = pi_monitor.PageStore()
    calls = []

    def boom(make, secs, store=None, output_path=None):
        calls.append(store)
        if len(calls) == 1:
            raise RuntimeError("transient failure")

    with patch.object(pi_monitor, "_collect_and_render", side_effect=boom):
        stop = threading.Event()
        thread = threading.Thread(
            target=pi_monitor._refresh_loop,
            args=(stop, 0.05, lambda: {}, store, 300),
            daemon=True,
        )
        thread.start()
        time.sleep(0.4)
        stop.set()
        thread.join(timeout=5)

    # loop kept going after the failure and stopped when asked
    assert not thread.is_alive()
    assert len(calls) >= 2

def test_refresh_loop_passes_mirror_path_when_configured(tmp_path):
    import threading
    store = pi_monitor.PageStore()
    output = tmp_path / "mirror.html"
    seen = []

    with patch.object(pi_monitor, "_collect_and_render",
                      side_effect=lambda make, secs, store=None, output_path=None: seen.append(output_path)):
        stop = threading.Event()
        thread = threading.Thread(
            target=pi_monitor._refresh_loop,
            args=(stop, 0.05, lambda: {}, store, 300),
            kwargs={"output_path": output},
            daemon=True,
        )
        thread.start()
        time.sleep(0.3)
        stop.set()
        thread.join(timeout=5)

    assert seen and all(p == output for p in seen)


# ── serve handler ─────────────────────────────────────────────────────────────

def _start_handler(store, filename="pi_monitor.html"):
    """Start an in-process ThreadingHTTPServer on an ephemeral port; return (server, thread, base_url)."""
    import threading
    from http.server import ThreadingHTTPServer

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), pi_monitor._make_handler_class(store, filename))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, thread, f"http://127.0.0.1:{httpd.server_address[1]}"

def _stop_handler(httpd, thread):
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=5)

def test_serve_handler_serves_full_path():
    import urllib.request
    store = pi_monitor.PageStore()
    store.replace("<html>monitor</html>")
    httpd, thread, base = _start_handler(store)
    try:
        with urllib.request.urlopen(f"{base}/pi_monitor.html", timeout=5) as resp:
            body = resp.read().decode()
    finally:
        _stop_handler(httpd, thread)
    assert body == "<html>monitor</html>"

def test_serve_handler_serves_root():
    import urllib.request
    store = pi_monitor.PageStore()
    store.replace("<html>monitor</html>")
    httpd, thread, base = _start_handler(store, "index.html")
    try:
        with urllib.request.urlopen(f"{base}/", timeout=5) as resp:
            assert resp.geturl().endswith("/"), "should be served directly, no redirect"
            body = resp.read().decode()
    finally:
        _stop_handler(httpd, thread)
    assert body == "<html>monitor</html>"

def test_serve_handler_unknown_path_is_404():
    import urllib.error
    import urllib.request
    store = pi_monitor.PageStore()
    store.replace("<html>monitor</html>")
    httpd, thread, base = _start_handler(store)
    try:
        try:
            urllib.request.urlopen(f"{base}/other.html", timeout=5)
            code = 200
        except urllib.error.HTTPError as exc:
            code = exc.code
    finally:
        _stop_handler(httpd, thread)
    assert code == 404

def test_serve_handler_conditional_get_returns_304():
    import urllib.error
    import urllib.request
    store = pi_monitor.PageStore()
    store.replace("<html>monitor</html>")
    httpd, thread, base = _start_handler(store)
    try:
        req = urllib.request.Request(f"{base}/", headers={"If-None-Match": store.snapshot()[1]})
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                code, body = resp.status, resp.read()
        except urllib.error.HTTPError as exc:  # urllib surfaces 304 as an error
            code, body = exc.code, exc.read()
    finally:
        _stop_handler(httpd, thread)
    assert code == 304
    assert body == b""

def test_serve_handler_conditional_get_returns_200_when_stale():
    import urllib.request
    store = pi_monitor.PageStore()
    store.replace("<html>v1</html>")
    httpd, thread, base = _start_handler(store)
    try:
        req = urllib.request.Request(f"{base}/", headers={"If-None-Match": 'W/"nope"'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            code = resp.status
    finally:
        _stop_handler(httpd, thread)
    assert code == 200

def test_serve_handler_updates_atomically_between_requests():
    import urllib.request
    store = pi_monitor.PageStore()
    store.replace("<html>v1</html>")
    httpd, thread, base = _start_handler(store)
    try:
        with urllib.request.urlopen(f"{base}/", timeout=5) as resp:
            assert resp.read().decode() == "<html>v1</html>"
        store.replace("<html>v2</html>")
        with urllib.request.urlopen(f"{base}/", timeout=5) as resp:
            assert resp.read().decode() == "<html>v2</html>"
    finally:
        _stop_handler(httpd, thread)

def test_serve_handler_confined_to_known_paths():
    import socket as _socket
    store = pi_monitor.PageStore()
    store.replace("<html>monitor</html>")
    httpd, thread = _start_handler(store)[:2]
    port = httpd.server_address[1]
    try:
        # Raw socket so encoded traversal sequences reach the server untranslated;
        # urllib would collapse them client-side. There is no filesystem behind
        # this server — anything that is not "/" or the page name must be rejected.
        sock = _socket.create_connection(("127.0.0.1", port), timeout=5)
        try:
            sock.sendall(b"GET /../pi_monitor.py HTTP/1.1\r\nHost: t\r\nConnection: close\r\n\r\n")
            response = sock.recv(4096).decode("utf-8", "replace")
            sock.sendall(b"GET /%2e%2e/secret.txt HTTP/1.1\r\nHost: t\r\nConnection: close\r\n\r\n")
            response += sock.recv(4096).decode("utf-8", "replace")
        finally:
            sock.close()
    finally:
        _stop_handler(httpd, thread)
    assert "200" not in response.split("\n")[0]


# ── build_html ─────────────────────────────────────────────────────────────────

def _make_cards():
    cpu = pi_monitor.CpuCard()
    cpu.cpu_pct    = 42.5
    cpu.iowait_pct = 3.2
    cpu.load       = ("0.50", "0.60", "0.70")
    cpu.cpu_freq   = "1500 MHz"
    cpu.voltage    = "1.2000V"

    temp = pi_monitor.TemperatureCard()
    temp.temperature    = 45.0
    temp.throttle_ok    = True
    temp.throttle_flags = []

    memory = pi_monitor.MemoryCard()
    memory.mem_total  = "3.9 GB"
    memory.mem_used   = "2.9 GB"
    memory.mem_avail  = "1000 MB"
    memory.mem_pct    = 75.0
    memory.swap_total = "1.0 GB"
    memory.swap_used  = "0 MB"
    memory.swap_pct   = 0.0
    memory.gpu_mem    = "128M"

    connectivity = pi_monitor.ConnectivityCard()
    connectivity.ping_ok   = True
    connectivity.ping_loss = 0
    connectivity.ping_avg  = 15.3
    connectivity.wan_ip    = "1.2.3.4"

    wifi = pi_monitor.WifiCard()
    wifi.wifi = None

    eth = pi_monitor.EthernetCard()
    eth.eth = {"iface": "eth0", "state": "up", "ip": "192.168.1.100", "speed": "1000 Mbps"}

    tailscale = pi_monitor.TailscaleCard()
    tailscale.tailscale = None

    docker = pi_monitor.DockerCard()
    docker.docker = None

    disks = pi_monitor.DiskCard()
    disks.disks = [{"mount": "/", "size": "30G", "used": "10G", "avail": "20G", "pct": 33}]

    ports = pi_monitor.PortsCard()
    ports.ports = [{"proto": "tcp", "port": "22", "addr": "*"}]

    processes = pi_monitor.ProcessesCard()
    processes.processes = [{"pid": "123", "cpu": "5.0", "mem": "2.1", "name": "python3"}]

    return {
        "cpu":          cpu,
        "temp":         temp,
        "memory":       memory,
        "connectivity": connectivity,
        "wifi":         wifi,
        "eth":          eth,
        "tailscale":    tailscale,
        "docker":       docker,
        "disks":        disks,
        "ports":        ports,
        "processes":    processes,
    }

_PAGE_KWARGS = dict(
    hostname  = "test-pi",
    uptime    = "2h 15m",
    pretty_os = "Raspberry Pi OS",
    kernel    = "6.1.21-v8+",
    arch      = "aarch64",
    date_str  = "Monday 25 May 2026",
    time_str  = "12:00:00",
)

def _html():
    return pi_monitor.build_html(_make_cards(), **_PAGE_KWARGS)

def test_build_html_is_valid_html():
    assert _html().startswith("<!DOCTYPE html>")

def test_build_html_contains_hostname():
    assert "test-pi" in _html()

def test_build_html_section_titles():
    h = _html()
    for title in ("CPU Usage", "Memory", "Temperature", "Disk Usage", "Listening Ports", "Top Processes"):
        assert title in h, f"Missing section: {title}"

def test_build_html_cpu_percentage():
    assert "42.5%" in _html()

def test_build_html_cpu_iowait_row():
    h = _html()
    assert "I/O wait" in h
    assert "3.2%" in h

def test_build_html_cpu_voltage_row_always_present():
    assert "Core voltage" in _html()

def test_build_html_ethernet_ip():
    assert "192.168.1.100" in _html()

def test_build_html_no_wifi_when_none():
    assert "Wi-Fi" not in _html()

def test_build_html_port_22():
    assert ">22<" in _html()

def test_build_html_escapes_xss_in_hostname():
    html_out = pi_monitor.build_html(
        _make_cards(),
        hostname="<script>alert('xss')</script>",
        uptime="2h",
        pretty_os="Raspberry Pi OS",
        kernel="6.1.21",
        arch="aarch64",
        date_str="Monday 25 May 2026",
        time_str="12:00:00",
    )
    assert "<script>alert" not in html_out
