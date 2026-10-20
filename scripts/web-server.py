#!/usr/bin/env python3
"""
GTA Router - the app page server that run.sh starts on :8081.

It serves web/ exactly like `python3 -m http.server` did, plus one more job:
it passes the Reach map's questions (/otp/traveltime/*) on to the Reach
engine at :8090, and only keeps that engine running while it is being used.

Why: the Reach engine holds about 3.3 GB. On a 16 GB Mac, keeping it loaded
all day pushed the main engine into compressed memory until searches timed
out (2026-10-04). It loads in about 10 seconds, so starting it on the first
tap and stopping it after IDLE_MIN quiet minutes costs one short wait.

While it loads, Reach requests get a 503 with {"state": "starting"} and the
page retries. /reach-engine/wake starts it early (the page calls it when the
Reach panel is switched on). Hosted, none of this runs: Caddy serves the
page and passes /otp/traveltime/* to an always-on Reach engine.

Standard library only.
"""

import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")
PORT = 8081
REACH_PORT = 8090
IDLE_MIN = float(os.environ.get("REACH_IDLE_MIN", 15))   # env: for testing
# after a failed start, wait this long before trying again, so a broken
# engine doesn't get relaunched on every single tap
RETRY_SEC = 60
REACH_CMD = ["java", "-Xmx3G", "-jar", "engine/otp25.jar",
             "--load", "engine/reach-engine",
             "--port", str(REACH_PORT), "--bindAddress", "127.0.0.1"]
REACH_LOG = os.path.join(ROOT, "engine", "reach-engine", "reach.log")


def say(msg):
    print(time.strftime("%H:%M"), msg, flush=True)


class Reach:
    """The Reach engine process: started on demand, stopped when idle."""

    def __init__(self):
        self.lock = threading.Lock()
        self.proc = None
        self.last_used = 0.0
        self.failed_at = 0.0

    def listening(self):
        try:
            with socket.create_connection(("127.0.0.1", REACH_PORT), timeout=0.5):
                return True
        except OSError:
            return False

    def wake(self):
        """Returns "ready", "starting" or "failed", starting it if needed."""
        with self.lock:
            self.last_used = time.time()
            if self.listening():          # ours, or one started by hand
                return "ready"
            if self.proc and self.proc.poll() is None:
                return "starting"
            if self.proc:                 # it was starting and died
                self.proc = None
                self.failed_at = time.time()
                say("The Reach map engine failed to start. See " + REACH_LOG)
            if time.time() - self.failed_at < RETRY_SEC:
                return "failed"
            say("Starting the Reach map engine (about 10 seconds)...")
            try:
                with open(REACH_LOG, "w") as log:
                    self.proc = subprocess.Popen(
                        REACH_CMD, cwd=ROOT, stdin=subprocess.DEVNULL,
                        stdout=log, stderr=subprocess.STDOUT)
            except OSError as e:          # no java, say
                self.failed_at = time.time()
                say("Couldn't start the Reach map engine: " + str(e))
                return "failed"
            return "starting"

    def touch(self):
        with self.lock:
            self.last_used = time.time()

    def stop(self):
        with self.lock:
            proc, self.proc = self.proc, None
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(20)
            except subprocess.TimeoutExpired:
                proc.kill()

    def reaper(self):
        while True:
            time.sleep(30)
            with self.lock:
                idle = (self.proc and self.proc.poll() is None
                        and time.time() - self.last_used > IDLE_MIN * 60)
            if idle:
                self.stop()
                say(f"Stopped the Reach map engine after {IDLE_MIN:g} quiet "
                    "minutes. It starts again on the next tap.")


reach = Reach()


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *args):         # http.server ran silent too
        pass

    def do_GET(self):
        if self.path.startswith("/otp/traveltime/"):
            return self.pass_to_reach()
        if self.path == "/reach-engine/wake":
            return self.send_json(200, {"state": reach.wake()})
        return super().do_GET()

    def send_json(self, code, obj, headers=()):
        self.send_body(code, "application/json", json.dumps(obj).encode(), headers)

    def send_body(self, code, ctype, body, headers=()):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def pass_to_reach(self):
        state = reach.wake()
        if state == "starting":
            return self.send_json(503, {"state": state}, [("Retry-After", "2")])
        if state == "failed":
            return self.send_json(502, {"state": state})
        url = f"http://127.0.0.1:{REACH_PORT}{self.path}"
        try:
            # a full ten-band bloom takes 11-13 s on a laptop
            with urllib.request.urlopen(url, timeout=90) as r:
                code, ctype, body = r.status, r.headers.get("Content-Type"), r.read()
        except urllib.error.HTTPError as e:   # e.g. a tap in the lake
            code, ctype, body = e.code, e.headers.get("Content-Type"), e.read()
        except OSError:
            return self.send_json(502, {"state": "failed"})
        finally:
            reach.touch()                     # the idle clock starts after the answer
        self.send_body(code, ctype or "application/json", body)


def main():
    # run.sh stops this with SIGTERM; turn it into a normal exit so the
    # finally below takes the Reach engine down with it
    signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))
    server = ThreadingHTTPServer(("127.0.0.1", PORT), partial(Handler, directory=WEB))
    threading.Thread(target=reach.reaper, daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        reach.stop()


if __name__ == "__main__":
    main()
