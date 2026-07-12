#!/usr/bin/env python3
"""Local web server for doctor-match: serves the UI and exposes the matching
logic from doctor_match.py as a JSON endpoint. No API key required."""
import http.server
import json
import os
import urllib.parse

from doctor_match import search_npi, search_trials, match

PORT = 8768


class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/match":
            self.handle_match(urllib.parse.parse_qs(parsed.query))
            return
        super().do_GET()

    def handle_match(self, params):
        first_name = params.get("first_name", [""])[0].strip()
        last_name = params.get("last_name", [""])[0].strip()
        state = params.get("state", [""])[0].strip() or None
        min_confidence = params.get("min_confidence", ["low"])[0]

        if not first_name or not last_name:
            self.send_json({"error": "first_name and last_name are required"}, status=400)
            return

        try:
            providers = search_npi(first_name, last_name, state=state, limit=20)
            trials = search_trials(first_name, last_name, max_results=50)
            profiles = match(providers, trials, min_confidence=min_confidence)
            self.send_json({"profiles": profiles})
        except Exception as e:
            self.send_json({"error": str(e)}, status=500)

    def send_json(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    print(f"Doctor Match running at http://localhost:{PORT}")
    http.server.HTTPServer(("", PORT), Handler).serve_forever()
