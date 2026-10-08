#!/usr/bin/env python3
"""Run Plumbline locally with one command.

    python run.py            build the frontend if needed, serve app + API on :5000
    python run.py --dev      hot-reload frontend on :5173 + API on :5000, one terminal
    python run.py --port 8000 --no-browser

What it does, in order (each step is skipped when already done):
  1. installs missing Python packages from backend/requirements.txt
  2. creates backend/.env from backend/.env.example on first run
  3. runs `npm ci` when frontend/node_modules is missing or out of date
  4. builds the React app into frontend/dist when the source has changed
  5. starts Flask, which serves the built app and the API from one origin
Ctrl+C stops everything.
"""
import argparse
import importlib.util
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser

ROOT = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.join(ROOT, "backend")
FRONTEND = os.path.join(ROOT, "frontend")
DIST_INDEX = os.path.join(FRONTEND, "dist", "index.html")
IS_WINDOWS = os.name == "nt"

# import names checked for a fast "is anything missing?" test
PY_MODULES = ["flask", "flask_cors", "dotenv", "sqlalchemy", "google.genai", "fpdf"]
FRONTEND_INPUTS = ["src", "public", "index.html", "vite.config.js", "package.json",
                   "package-lock.json"]


def say(msg):
    print(f"\033[32m[plumbline]\033[0m {msg}", flush=True)


def fail(msg):
    print(f"\033[31m[plumbline] {msg}\033[0m", file=sys.stderr, flush=True)
    sys.exit(1)


def run(cmd, cwd):
    if subprocess.call(cmd, cwd=cwd) != 0:
        fail(f"command failed: {' '.join(cmd)}")


def newest_mtime(base, names):
    newest = 0.0
    for name in names:
        path = os.path.join(base, name)
        if os.path.isfile(path):
            newest = max(newest, os.path.getmtime(path))
        for dirpath, _, files in os.walk(path):
            for f in files:
                newest = max(newest, os.path.getmtime(os.path.join(dirpath, f)))
    return newest


# ------------------------------------------------------------------ setup --
def ensure_python_deps():
    def missing():
        out = []
        for m in PY_MODULES:
            try:
                if importlib.util.find_spec(m) is None:
                    out.append(m)
            except ModuleNotFoundError:
                out.append(m)
        return out

    if missing():
        say("installing Python packages (first run only)...")
        run([sys.executable, "-m", "pip", "install", "-q", "-r",
             os.path.join(BACKEND, "requirements.txt")], ROOT)
        importlib.invalidate_caches()
        if missing():
            fail(f"still missing after install: {', '.join(missing())}")


def ensure_env_file():
    env, example = os.path.join(BACKEND, ".env"), os.path.join(BACKEND, ".env.example")
    if not os.path.exists(env) and os.path.exists(example):
        with open(example, encoding="utf-8") as f:
            text = f.read()
        # Blank the placeholder so health honestly reports "offline" until a
        # real key is added (a fake key would show "live" and then fail).
        text = text.replace("GEMINI_API_KEY=your_key_here", "GEMINI_API_KEY=")
        with open(env, "w", encoding="utf-8") as f:
            f.write(text)
        say("created backend/.env -- add GEMINI_API_KEY there for live AI "
            "(the app works without it)")


def npm():
    exe = shutil.which("npm.cmd" if IS_WINDOWS else "npm") or shutil.which("npm")
    if not exe:
        fail("Node.js is needed to build the frontend. Install the LTS version from "
             "https://nodejs.org, then run this again.")
    return exe


def ensure_node_modules():
    modules = os.path.join(FRONTEND, "node_modules")
    marker = os.path.join(modules, ".package-lock.json")  # written by npm itself
    lock = os.path.join(FRONTEND, "package-lock.json")
    stale = (not os.path.exists(marker)
             or os.path.getmtime(lock) > os.path.getmtime(marker))
    if stale:
        say("installing frontend packages (first run only)...")
        run([npm(), "ci", "--no-audit", "--no-fund"], FRONTEND)


def ensure_build(force=False):
    if (not force and os.path.exists(DIST_INDEX)
            and os.path.getmtime(DIST_INDEX) >= newest_mtime(FRONTEND, FRONTEND_INPUTS)):
        say("frontend build is up to date")
        return
    if not shutil.which("npm") and not shutil.which("npm.cmd") and os.path.exists(DIST_INDEX):
        say("Node.js not found -- serving the existing frontend build")
        return
    ensure_node_modules()
    say("building frontend...")
    env = dict(os.environ)
    env.pop("VITE_API_URL", None)  # same-origin build: API is served by this Flask
    if subprocess.call([npm(), "run", "build"], cwd=FRONTEND, env=env) != 0:
        fail("frontend build failed (see the error above)")


# -------------------------------------------------------------- processes --
def start(cmd, cwd, env):
    kwargs = {"cwd": cwd, "env": env}
    if IS_WINDOWS:
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(cmd, **kwargs)


def stop(proc):
    if proc.poll() is not None:
        return
    if IS_WINDOWS:  # kill the whole tree (npm.cmd -> node, flask reloader child)
        subprocess.call(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def wait_for(url, procs, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if any(p.poll() is not None for p in procs):
            return False
        try:
            with urllib.request.urlopen(url, timeout=2):
                return True
        except Exception:  # noqa: BLE001 - not up yet
            time.sleep(0.5)
    return False


def _raise_interrupt(*_):
    raise KeyboardInterrupt


def main():
    ap = argparse.ArgumentParser(description="Run Plumbline locally.")
    ap.add_argument("--dev", action="store_true",
                    help="hot-reload frontend (Vite on :5173) alongside the API")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 5000)))
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--rebuild", action="store_true", help="force a fresh frontend build")
    args = ap.parse_args()

    # Refuse to start against a port someone else holds; otherwise the health
    # check would pass against the *other* server and report a false "ready".
    for port, what in [(args.port, "API")] + ([(5173, "Vite dev server")] if args.dev else []):
        if port_in_use(port):
            fail(f"port {port} ({what}) is already in use -- is Plumbline already running? "
                 f"Stop it, or use --port to pick another API port.")

    # Closing the window / `kill` sends SIGTERM: clean up like Ctrl+C does.
    signal.signal(signal.SIGTERM, _raise_interrupt)

    ensure_python_deps()
    ensure_env_file()
    if args.dev:
        ensure_node_modules()
    else:
        ensure_build(force=args.rebuild)

    env = dict(os.environ, PORT=str(args.port), PYTHONUNBUFFERED="1",
               PLUMBLINE_API_PORT=str(args.port))
    procs = [start([sys.executable, "app.py"], BACKEND, env)]
    url = f"http://localhost:{args.port}"
    if args.dev:
        vite_env = dict(env)
        vite_env.pop("VITE_API_URL", None)  # use the Vite proxy, not a baked URL
        procs.append(start([npm(), "run", "dev", "--", "--strictPort"], FRONTEND, vite_env))
        url = "http://localhost:5173"

    try:
        if not wait_for(f"http://127.0.0.1:{args.port}/api/health", procs):
            fail("the API did not start -- see the error above")
        if args.dev and not wait_for("http://127.0.0.1:5173", procs):
            fail("the Vite dev server did not start -- see the error above")
        say(f"ready -> {url}   (Ctrl+C to stop)")
        if not args.no_browser:
            webbrowser.open(url)
        while all(p.poll() is None for p in procs):
            time.sleep(0.5)
        fail("a server exited unexpectedly -- see the error above")
    except KeyboardInterrupt:
        print()
        say("stopping...")
    finally:
        for p in procs:
            stop(p)


if __name__ == "__main__":
    main()
