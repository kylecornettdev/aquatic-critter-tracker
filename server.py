"""
Aquatic Critter Tracker — Local Web Server
Run this script, then open http://localhost:8765 in your browser.
"""

from http.server import HTTPServer, SimpleHTTPRequestHandler
import json
import os
import threading
import urllib.parse

PORT = 8765
DATA_FILE = "fish_data.json"


class TrackerHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        # Suppress default access logs for cleaner output
        pass

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)

        # API: return fish data as JSON
        if parsed.path == "/api/data":
            self.serve_json_data()

        # API: trigger a scrape
        elif parsed.path == "/api/scrape":
            self.trigger_scrape()

        # Serve static files (index.html etc.)
        else:
            super().do_GET()

    def serve_json_data(self):
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                content = f.read()
        else:
            content = json.dumps({"fish": {}, "scrape_log": [], "pages_scraped": []})

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(content.encode())

    def trigger_scrape(self):
        """Run the scraper in a background thread and return status."""
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        def run():
            try:
                from scraper import run_scrape
                run_scrape()
            except Exception as e:
                print(f"[Scrape error] {e}")

        t = threading.Thread(target=run, daemon=True)
        t.start()

        self.wfile.write(json.dumps({"status": "started"}).encode())


def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    server = HTTPServer(("localhost", PORT), TrackerHandler)
    print(f"\n🐟  Aquatic Critter Tracker running at http://localhost:{PORT}")
    print(f"    Press Ctrl+C to stop.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")


if __name__ == "__main__":
    main()
