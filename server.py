"""
Aquatic Critter Tracker — Local Web Server
http://localhost:8080        — Dashboard
http://localhost:8080/admin  — Admin / Scrape / Queue
http://localhost:8080/library — Fish library / merge tool
"""

from http.server import HTTPServer, SimpleHTTPRequestHandler
import json
import os
import threading
import urllib.parse
from datetime import datetime

PORT = 8080
DATA_FILE = "fish_data.json"
SCRAPE_COOLDOWN_MINUTES = 30


class TrackerHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        routes = {
            "/": "index.html", "/index.html": "index.html",
            "/admin": "admin.html", "/admin/": "admin.html",
            "/library": "library.html", "/library/": "library.html",
            "/planner": "aquascape-planner.html", "/planner/": "aquascape-planner.html"
        }
        if path in routes:
            self.serve_file(routes[path])
        elif path == "/api/data":
            self.serve_json_data()
        elif path == "/api/scrape":
            self.trigger_scrape()
        elif path == "/api/queue":
            self.serve_queue()
        elif path == "/api/library":
            self.serve_library()
        else:
            super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        handlers = {
            "/api/resolve":          self.handle_resolve,
            "/api/merge":            self.handle_merge,
            "/api/create_and_merge": self.handle_create_and_merge,
            "/api/unassociate":      self.handle_unassociate,
            "/api/delete":           self.handle_delete,
            "/api/clear_flag":       self.handle_clear_flag,
        }
        h = handlers.get(parsed.path)
        if h: h()
        else:
            self.send_response(404)
            self.end_headers()

    # ── File serving ──

    def serve_file(self, filename):
        fp = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
        if not os.path.exists(fp):
            self.send_response(404); self.end_headers(); return
        with open(fp, "rb") as f:
            content = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(content))
        self.end_headers()
        self.wfile.write(content)

    # ── API ──

    def serve_json_data(self):
        self._json_response(json.dumps(self._load_data()))

    def serve_queue(self):
        data = self._load_data()
        self._json_response(json.dumps({
            "queue": data.get("pending_queue", []),
            "fish_names": sorted(data.get("fish", {}).keys()),
            "queue_count": len(data.get("pending_queue", [])),
        }))

    def serve_library(self):
        data = self._load_data()
        fish = data.get("fish", {})
        library = []
        for name in sorted(fish.keys()):
            info = fish[name]
            own_occ = sorted(info.get("occurrences", []))
            v_occ = info.get("variant_occurrences", {})
            variants = info.get("variants", [])
            variant_data = [{"name": v, "occurrences": sorted(v_occ.get(v, []))} for v in variants]
            library.append({
                "name": name,
                "occurrences": own_occ,
                "variants": variant_data,
                "flagged_dupe": info.get("flagged_dupe", False),
                "similar_to": info.get("similar_to", []),
            })
        self._json_response(json.dumps({
            "library": library,
            "fish_names": sorted(fish.keys()),
        }))

    def handle_resolve(self):
        try:
            payload = self._read_json()
            raw = payload.get("raw", "").strip()
            action = payload.get("action")  # "individual" or "flag"
            individual_name = payload.get("name", raw).strip()
            if not raw or action not in ("individual", "flag"):
                self._json_response(json.dumps({"status": "error", "message": "Invalid payload"})); return

            data = self._load_data()
            queue_item = next((q for q in data["pending_queue"] if q["raw"] == raw), None)

            # Both actions add the fish as an individual entry
            if individual_name not in data["fish"]:
                data["fish"][individual_name] = {"occurrences": [], "variants": [], "variant_occurrences": {}}
            data["resolution_map"][raw] = {"action": "individual", "name": individual_name}

            # Apply queued occurrence date
            if queue_item and queue_item.get("seen_on"):
                d = queue_item["seen_on"]
                occ = data["fish"][individual_name].setdefault("occurrences", [])
                if d not in occ:
                    occ.append(d); occ.sort()

            # If flagging, mark as potential dupe
            if action == "flag":
                data["fish"][individual_name]["flagged_dupe"] = True
                data["fish"][individual_name]["similar_to"] = queue_item.get("similar_to", []) if queue_item else []

            data["pending_queue"] = [q for q in data["pending_queue"] if q["raw"] != raw]
            self._save_data(data)
            self._json_response(json.dumps({
                "status": "ok",
                "queue_remaining": len(data["pending_queue"]),
                "fish_names": sorted(data["fish"].keys()),
            }))
        except Exception as e:
            self._json_response(json.dumps({"status": "error", "message": str(e)}))

    def handle_merge(self):
        """Merge source_fish INTO target_fish."""
        try:
            payload = self._read_json()
            source = payload.get("source", "").strip()
            target = payload.get("target", "").strip()
            if not source or not target or source == target:
                self._json_response(json.dumps({"status": "error", "message": "Invalid source/target"})); return

            data = self._load_data()
            fish = data.get("fish", {})
            if source not in fish or target not in fish:
                self._json_response(json.dumps({"status": "error", "message": "Fish not found"})); return

            self._do_merge(fish, source, target, data)
            self._save_data(data)
            self._json_response(json.dumps({
                "status": "ok", "merged": source, "into": target,
                "fish_names": sorted(fish.keys()),
            }))
        except Exception as e:
            self._json_response(json.dumps({"status": "error", "message": str(e)}))

    def handle_create_and_merge(self):
        """
        Create a new base fish entry and merge one or more existing fish into it.
        Payload: {new_name: str, sources: [str]}
        """
        try:
            payload = self._read_json()
            new_name = payload.get("new_name", "").strip()
            sources = payload.get("sources", [])
            if not new_name or not sources:
                self._json_response(json.dumps({"status": "error", "message": "Invalid payload"})); return

            data = self._load_data()
            fish = data.get("fish", {})

            # Create the new base entry if it doesn't exist
            if new_name not in fish:
                fish[new_name] = {"occurrences": [], "variants": [], "variant_occurrences": {}}

            # Merge each source into the new entry
            merged = []
            for source in sources:
                if source in fish and source != new_name:
                    self._do_merge(fish, source, new_name, data)
                    merged.append(source)

            self._save_data(data)
            self._json_response(json.dumps({
                "status": "ok",
                "created": new_name,
                "merged": merged,
                "fish_names": sorted(fish.keys()),
            }))
        except Exception as e:
            self._json_response(json.dumps({"status": "error", "message": str(e)}))

    def handle_clear_flag(self):
        try:
            payload = self._read_json()
            name = payload.get("name", "").strip()
            if not name:
                self._json_response(json.dumps({"status": "error", "message": "No name"})); return
            data = self._load_data()
            if name in data.get("fish", {}):
                data["fish"][name].pop("flagged_dupe", None)
                data["fish"][name].pop("similar_to", None)
            self._save_data(data)
            self._json_response(json.dumps({"status": "ok", "cleared": name}))
        except Exception as e:
            self._json_response(json.dumps({"status": "error", "message": str(e)}))

    def handle_delete(self):
        """Permanently delete a fish entry."""
        try:
            payload = self._read_json()
            name = payload.get("name", "").strip()
            if not name:
                self._json_response(json.dumps({"status": "error", "message": "No name provided"})); return
            data = self._load_data()
            fish = data.get("fish", {})
            if name not in fish:
                self._json_response(json.dumps({"status": "error", "message": "Fish not found"})); return
            del fish[name]
            # Also remove from any other fish's variants list
            for fname, finfo in fish.items():
                variants = finfo.get("variants", [])
                if name in variants:
                    variants.remove(name)
                v_occ = finfo.get("variant_occurrences", {})
                if name in v_occ:
                    del v_occ[name]
            # Remove from resolution map if present
            data["resolution_map"] = {k: v for k, v in data.get("resolution_map", {}).items()
                                       if not (v.get("action") == "associate" and v.get("target") == name)}
            self._save_data(data)
            self._json_response(json.dumps({
                "status": "ok",
                "deleted": name,
                "fish_names": sorted(fish.keys()),
            }))
        except Exception as e:
            self._json_response(json.dumps({"status": "error", "message": str(e)}))

    def handle_unassociate(self):
        """Remove a variant from a fish, making it its own entry."""
        try:
            payload = self._read_json()
            primary = payload.get("primary", "").strip()
            variant = payload.get("variant", "").strip()
            if not primary or not variant:
                self._json_response(json.dumps({"status": "error", "message": "Invalid payload"})); return

            data = self._load_data()
            fish = data.get("fish", {})
            if primary not in fish:
                self._json_response(json.dumps({"status": "error", "message": "Primary not found"})); return

            prim = fish[primary]
            variants = prim.get("variants", [])
            if variant in variants: variants.remove(variant)
            v_occ = prim.get("variant_occurrences", {})
            variant_dates = v_occ.pop(variant, [])

            # Create individual entry
            if variant not in fish:
                fish[variant] = {"occurrences": sorted(variant_dates), "variants": [], "variant_occurrences": {}}

            data["resolution_map"][variant] = {"action": "individual", "name": variant}
            self._save_data(data)
            self._json_response(json.dumps({
                "status": "ok", "unassociated": variant, "from": primary,
                "fish_names": sorted(fish.keys()),
            }))
        except Exception as e:
            self._json_response(json.dumps({"status": "error", "message": str(e)}))

    def trigger_scrape(self):
        cooldown = self._get_cooldown_remaining()
        if cooldown > 0:
            self._json_response(json.dumps({"status": "cooldown", "minutes_remaining": cooldown})); return
        self._json_response(json.dumps({"status": "started"}))
        def run():
            try:
                from scraper import run_scrape
                run_scrape()
            except Exception as e:
                print(f"[Scrape error] {e}")
        threading.Thread(target=run, daemon=True).start()

    # ── Helpers ──

    def _do_merge(self, fish, source, target, data):
        """Merge source entry into target entry in-place."""
        src = fish[source]
        tgt = fish[target]

        # Merge own occurrences
        tgt_occ = tgt.setdefault("occurrences", [])
        for d in src.get("occurrences", []):
            if d not in tgt_occ: tgt_occ.append(d)
        tgt_occ.sort()

        # Track source's own dates as variant_occurrences on target
        v_occ = tgt.setdefault("variant_occurrences", {})
        existing = v_occ.get(source, [])
        merged_dates = sorted(set(existing + src.get("occurrences", [])))
        v_occ[source] = merged_dates

        # Adopt source's variants
        tgt_variants = tgt.setdefault("variants", [])
        if source not in tgt_variants: tgt_variants.append(source)
        for v in src.get("variants", []):
            if v not in tgt_variants: tgt_variants.append(v)
            src_v_occ = src.get("variant_occurrences", {}).get(v, [])
            v_occ[v] = sorted(set(v_occ.get(v, []) + src_v_occ))

        # Update resolution map
        data["resolution_map"][source] = {"action": "associate", "target": target}

        # Delete source
        del fish[source]

    def _get_cooldown_remaining(self):
        data = self._load_data()
        log = data.get("scrape_log", [])
        if not log: return 0
        try:
            last_ts = datetime.fromisoformat(log[-1]["timestamp"])
            elapsed = (datetime.now() - last_ts).total_seconds() / 60
            return max(0, round(SCRAPE_COOLDOWN_MINUTES - elapsed))
        except Exception: return 0

    def _load_data(self):
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"fish": {}, "scrape_log": [], "pages_scraped": [], "scraped_dates": [],
                "latest_page_date": None, "resolution_map": {}, "pending_queue": []}

    def _save_data(self, data):
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length))

    def _json_response(self, content):
        if isinstance(content, str): content = content.encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(content)


def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    server = HTTPServer(("localhost", PORT), TrackerHandler)
    print(f"\n🐟  Aquatic Critter Tracker")
    print(f"    Dashboard:  http://localhost:{PORT}")
    print(f"    Admin:      http://localhost:{PORT}/admin")
    print(f"    Library:    http://localhost:{PORT}/library")
    print(f"    Cooldown:   {SCRAPE_COOLDOWN_MINUTES} minutes")
    print(f"    Press Ctrl+C to stop.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")


if __name__ == "__main__":
    main()
