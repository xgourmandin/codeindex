#!/usr/bin/env python3
"""
server.py — Minimal HTTP server for repo-viz-explorer.
Usage: python server.py --repo ./myapp [--port 8080] [--watch]
"""
import argparse
import importlib.util
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HERE = Path(__file__).parent


def run_analysis(repo_path: str, output: str = "repo_graph.json") -> bool:
    analyzer = HERE / "analyze_repo.py"
    result = subprocess.run(
        [sys.executable, str(analyzer), repo_path, "--output", output],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"[analyzer error]\n{result.stderr}", file=sys.stderr)
        return False
    print(result.stderr, end="", file=sys.stderr)
    return True


REPO_PATH = "."
GRAPH_FILE = HERE / "repo_graph.json"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"  {self.address_string()} {fmt % args}")

    def send_json(self, data: dict, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path: Path, content_type: str):
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", len(data))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?")[0]

        if path == "/" or path == "/index.html":
            self.send_file(HERE / "repo-viz-explorer.html", "text/html; charset=utf-8")

        elif path == "/graph":
            if GRAPH_FILE.exists():
                self.send_file(GRAPH_FILE, "application/json")
            else:
                self.send_json({"error": "repo_graph.json not found — run analysis first"}, 404)

        elif path == "/refresh":
            ok = run_analysis(REPO_PATH, str(GRAPH_FILE))
            self.send_json({"ok": ok})

        else:
            self.send_error(404)


def start_watcher(repo_path: str):
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler
    except ImportError:
        print("watchdog not installed — run: pip install watchdog", file=sys.stderr)
        return

    WATCHED_EXTS = {
        ".py", ".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs",
        ".rb", ".go", ".rs", ".java", ".kt", ".php",
        ".yml", ".yaml", ".sql", ".prisma",
    }

    class PyHandler(FileSystemEventHandler):
        def __init__(self):
            self._timer = None

        def _debounced(self):
            print("[watch] change detected, re-analyzing…", file=sys.stderr)
            run_analysis(repo_path, str(GRAPH_FILE))

        def on_modified(self, event):
            if not event.is_directory:
                ext = str(event.src_path).rsplit(".", 1)
                if len(ext) > 1 and f".{ext[-1]}" in WATCHED_EXTS:
                    if self._timer:
                        self._timer.cancel()
                    self._timer = threading.Timer(1.0, self._debounced)
                    self._timer.start()

    observer = Observer()
    observer.schedule(PyHandler(), repo_path, recursive=True)
    observer.start()
    print(f"[watch] watching {repo_path} for .py changes", file=sys.stderr)
    return observer


def main():
    global REPO_PATH, GRAPH_FILE

    parser = argparse.ArgumentParser(description="Serve repo-viz-explorer with live data")
    parser.add_argument("--repo", default=os.environ.get("REPO_PATH", "."), help="Repo path to analyze")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--watch", action="store_true", help="Watch for file changes and auto-refresh")
    parser.add_argument("--output", default=str(HERE / "repo_graph.json"))
    args = parser.parse_args()

    REPO_PATH = args.repo
    GRAPH_FILE = Path(args.output)

    print(f"Analyzing {REPO_PATH} …", file=sys.stderr)
    run_analysis(REPO_PATH, str(GRAPH_FILE))

    if args.watch:
        start_watcher(REPO_PATH)

    server = HTTPServer(("", args.port), Handler)
    print(f"\nServing at http://localhost:{args.port}/\n  repo: {REPO_PATH}\n  graph: {GRAPH_FILE}\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
