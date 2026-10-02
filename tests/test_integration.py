"""Integration tests — run pi_monitor.py as a subprocess and check its output."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


def _run(tmp_path, *extra_args):
    output = tmp_path / "pi_monitor.html"
    result = subprocess.run(
        [sys.executable, str(ROOT / "pi_monitor.py"), "--output", str(output), *extra_args],
        capture_output=True,
        text=True,
    )
    return result, output


def test_exits_zero(tmp_path):
    result, _ = _run(tmp_path)
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"

def test_stdout_confirmation(tmp_path):
    result, _ = _run(tmp_path)
    assert "[pi_monitor] Written to" in result.stdout

def test_output_file_exists(tmp_path):
    _, output = _run(tmp_path)
    assert output.exists()

def test_output_is_html(tmp_path):
    _, output = _run(tmp_path)
    assert output.read_text().startswith("<!DOCTYPE html>")

def test_output_non_trivial_size(tmp_path):
    _, output = _run(tmp_path)
    assert output.stat().st_size > 5_000

def test_output_has_expected_sections(tmp_path):
    _, output = _run(tmp_path)
    content = output.read_text()
    for section in ("CPU Usage", "Memory", "Temperature", "Disk Usage", "Listening Ports", "Top Processes"):
        assert section in content, f"Missing section: {section}"

def test_ping_host_flag(tmp_path):
    result, output = _run(tmp_path, "--ping-host", "127.0.0.1")
    assert result.returncode == 0
    assert "127.0.0.1" in output.read_text()


def _free_port():
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_serve_mode_serves_and_refreshes(tmp_path):
    import time
    import urllib.error
    import urllib.request

    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-u", str(ROOT / "pi_monitor.py"),
         "--serve", "--port", str(port), "--bind", "127.0.0.1",
         "--interval", "2", "--ping-host", "127.0.0.1"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        # Wait for the first generation + server startup
        url = f"http://127.0.0.1:{port}/"
        deadline = time.time() + 120
        first_html, first_etag = None, None
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=3) as resp:
                    first_html = resp.read().decode()
                    first_etag = resp.headers.get("ETag")
                break
            except Exception:
                if proc.poll() is not None:
                    raise AssertionError("server exited early")
                time.sleep(0.5)
        assert first_html is not None, "server never came up"
        assert first_html.startswith("<!DOCTYPE html>")
        assert "updates in place every 2s" in first_html  # header note reflects --interval 2
        assert first_etag, "ETag header missing"

        # Serve mode holds the page in memory: nothing must be written to disk
        assert not (tmp_path / "pi_monitor.html").exists(), "serve mode must not write files"

        # A conditional request with the pre-refresh ETag must get a 304 while
        # the page is unchanged, and a fresh 200 with a new ETag after the
        # background regeneration has run (interval = 2s).
        deadline = time.time() + 60
        regenerated = False
        while time.time() < deadline and not regenerated:
            try:
                req = urllib.request.Request(url, headers={"If-None-Match": first_etag})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    body = resp.read().decode()
                regenerated = resp.status == 200 and resp.headers.get("ETag") != first_etag
                assert body.startswith("<!DOCTYPE html>")
            except urllib.error.HTTPError as exc:
                if exc.code != 304:
                    raise
                time.sleep(0.5)
        assert regenerated, "page was never regenerated after the interval elapsed"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        outs = proc.stdout.read() if proc.stdout else ""
        errs = proc.stderr.read() if proc.stderr else ""

    assert "Serving" in outs, f"stdout: {outs}\nstderr: {errs}"

def test_serve_mode_also_write_mirrors_to_disk(tmp_path):
    import time
    import urllib.request

    mirror = tmp_path / "mirror" / "index.html"
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-u", str(ROOT / "pi_monitor.py"),
         "--serve", "--also-write", str(mirror),
         "--port", str(port), "--bind", "127.0.0.1",
         "--interval", "2", "--ping-host", "127.0.0.1"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        url = f"http://127.0.0.1:{port}/"
        deadline = time.time() + 120
        first_html = None
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=3) as resp:
                    first_html = resp.read().decode()
                break
            except Exception:
                if proc.poll() is not None:
                    raise AssertionError("server exited early")
                time.sleep(0.5)
        assert first_html is not None, "server never came up"

        # the mirror file must exist and match what the server hands out
        assert mirror.exists()
        assert mirror.read_text() == first_html

        # and it must be refreshed on the interval too
        first = mirror.read_text()
        deadline = time.time() + 60
        while time.time() < deadline and mirror.read_text() == first:
            time.sleep(0.5)
        assert mirror.read_text() != first, "mirror file was never refreshed"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        outs = proc.stdout.read() if proc.stdout else ""
        errs = proc.stderr.read() if proc.stderr else ""

    assert "Mirroring each update to" in outs, f"stdout: {outs}\nstderr: {errs}"
