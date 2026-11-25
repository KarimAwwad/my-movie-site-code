"""
One-time helper to authorize all your Gmail accounts into gdrive_accounts.json.
Run: python auth_gdrive.py
"""
import json
import os
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_PATH = os.path.join(BASE_DIR, "gdrive_accounts.json")
REDIRECT_URI = "http://127.0.0.1:8789"
SCOPE = "https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/userinfo.email"


def load_cfg():
    if os.path.exists(OUT_PATH):
        with open(OUT_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"client_id": "", "client_secret": "", "accounts": []}


def save_cfg(cfg):
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def main():
    cfg = load_cfg()
    if not cfg.get("client_id") or not cfg.get("client_secret"):
        raw = input("Paste path to your downloaded Google JSON file (or press Enter to paste ID/Secret manually): ").strip().strip('"')
        if raw and os.path.isfile(raw):
            with open(raw, "r", encoding="utf-8") as f:
                data = json.load(f)
            installed = data.get("installed") or data.get("web") or {}
            cfg["client_id"] = installed.get("client_id", "")
            cfg["client_secret"] = installed.get("client_secret", "")
        if not cfg.get("client_id"):
            cfg["client_id"] = input("Paste Google OAuth Client ID: ").strip()
        if not cfg.get("client_secret"):
            cfg["client_secret"] = input("Paste Google OAuth Client Secret: ").strip()
        save_cfg(cfg)

    code_box = {}

    class CallbackHandler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            code_box["code"] = (qs.get("code") or [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<h2>Authorized! Close this tab and check your terminal.</h2>")

    auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": cfg["client_id"],
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent select_account",
    })

    print("\nOpening browser — sign in to one of your Gmail accounts...")
    webbrowser.open(auth_url)
    HTTPServer(("127.0.0.1", 8789), CallbackHandler).handle_request()

    code = code_box.get("code")
    if not code:
        print("Failed to capture authorization code.")
        return

    token_data = urllib.parse.urlencode({
        "code": code,
        "client_id": cfg["client_id"],
        "client_secret": cfg["client_secret"],
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code",
    }).encode()

    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=token_data)
    with urllib.request.urlopen(req, timeout=15) as resp:
        tokens = json.loads(resp.read().decode())

    refresh_token = tokens.get("refresh_token")
    access_token = tokens.get("access_token")
    if not refresh_token:
        print("No refresh_token returned. Remove RUINTV at myaccount.google.com/permissions and re-run.")
        return

    info_req = urllib.request.Request(
        "https://www.googleapis.com/oauth2/v2/userinfo",
        headers={"Authorization": "Bearer " + access_token},
    )
    with urllib.request.urlopen(info_req, timeout=15) as resp:
        email = json.loads(resp.read().decode()).get("email", "unknown@gmail.com")

    cfg["accounts"] = [a for a in cfg["accounts"] if a.get("email") != email]
    cfg["accounts"].append({"email": email, "refresh_token": refresh_token})
    save_cfg(cfg)
    print(f"Saved {email}! Total accounts configured: {len(cfg['accounts'])} ({len(cfg['accounts']) * 15} GB)")


if __name__ == "__main__":
    main()