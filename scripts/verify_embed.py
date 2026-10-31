"""Cross-origin widget browser acceptance. Requires the local API and web server.

Creates a synthetic QA workspace. Makes no telephony or audio-provider request.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from pathlib import Path
import json
import uuid
import httpx
from playwright.sync_api import sync_playwright, expect

from qa_accounts import bootstrap_account
ROOT = Path(__file__).resolve().parents[1]
WEB = "http://127.0.0.1:3100"
API = "http://127.0.0.1:8100"
EMBED = "http://127.0.0.1:3201"


def main():
    with httpx.Client(base_url=API, timeout=60) as client:
        response = bootstrap_account(client, "/v1/auth/signup", json={"name": "Embed QA", "email": "embed-" + uuid.uuid4().hex[:10] + "@example.test", "password": uuid.uuid4().hex, "workspace_name": "Cross-origin embed QA"})
        assert response.status_code == 200
        ws = response.json()['workspaces'][0]["id"]
        client.headers["X-CSRF-Token"] = client.cookies["studio_csrf"]
        base = "/v1/workspaces/" + ws
        fixture = client.post(base + "/fixtures").json()
        installation = client.get(base + "/installations").json()["items"][0]
        response = client.put(base + "/installations/" + installation["id"], json={"agent_id": fixture["agent_id"], "name": "External embed QA", "allowed_origins": [EMBED], "theme": {"preset": "minimal"}})
        assert response.status_code == 200
        public_id = installation["public_id"]

        class Host(BaseHTTPRequestHandler):
            def do_GET(self):
                body = ("<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'></head><body><h1>Independent store origin</h1><script defer src='" + WEB + "/widget.js' data-installation='" + public_id + "'></script></body></html>").encode()
                self.send_response(200); self.send_header("Content-Type", "text/html"); self.end_headers(); self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 3201), Host)
        thread = Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 390, "height": 844})
                errors = []; page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(EMBED)
                page.get_by_role("button", name="Let’s talk").click()
                expect(page.get_by_label("Chat message")).to_be_enabled(timeout=30000)
                page.get_by_label("Chat message").fill("What is the cufflinks price?")
                page.get_by_role("button", name="Send", exact=True).click()
                expect(page.get_by_text("Personalised cufflinks is INR 999.", exact=False)).to_be_visible(timeout=30000)
                page.get_by_label("Chat message").fill("Please create a support ticket")
                page.get_by_role("button", name="Send", exact=True).click()
                expect(page.get_by_text("recorded", exact=False)).to_be_visible(timeout=30000)
                assert not page.context.cookies(), "Public widget must not receive dashboard cookies"
                assert not errors, errors
                artifacts = ROOT / "artifacts"; artifacts.mkdir(exist_ok=True)
                page.screenshot(path=str(artifacts / "external-embed-mobile.png"), full_page=True)
                browser.close()
            tickets = client.get(base + "/tickets").json()["items"]
            assert len(tickets) == 1
            invalid = client.post("/v1/public/sessions", headers={"Origin": "https://unlisted.example.test"}, json={"installation_public_id": public_id})
            assert invalid.status_code == 403
            result = {"cross_origin_embed": "passed", "catalog_answer": "passed", "durable_ticket": "passed", "unlisted_origin_blocked": "passed", "no_dashboard_cookies": "passed", "page_errors": errors}
            (ROOT / "artifacts/embed-results.json").write_text(json.dumps(result, indent=2))
            print(json.dumps(result))
        finally:
            server.shutdown(); server.server_close()


if __name__ == "__main__":
    main()
