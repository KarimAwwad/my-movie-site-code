"""
RUIN.TO static server.

Serves the site folder only, with:
  * threading, so assets don't queue behind each other
  * clean URLs (/watch -> watch.html, /x -> x/index.html)
  * correct MIME types (Windows otherwise serves .js as text/plain)
  * byte ranges, so local media can seek
  * .sql / .py / .vbs / .bat / .cmd / .ps1 / .toml / .log hidden
  * dot- and underscore-prefixed files and folders hidden (.well-known excepted)
  * path traversal blocked
  * port 80, falling back to 8080 if 80 is taken
"""

import argparse
import mimetypes
import os
import sys
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

# Absolute, so the working directory doesn't matter.
SITE_DIR = r"D:\my development work\unfinished and finished development projects\movie site"
ROOT = os.path.abspath(SITE_DIR)

DEFAULT_PORT = 80
FALLBACK_PORT = 8080

BLOCKED_EXT = {
    ".py", ".pyc", ".sql", ".vbs", ".bat", ".cmd", ".ps1",
    ".toml", ".log", ".ini", ".bak", ".swp", ".map",
}

MIME = {
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".webmanifest": "application/manifest+json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
    ".avif": "image/avif",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".ttf": "font/ttf",
    ".ico": "image/x-icon",
    ".vtt": "text/vtt; charset=utf-8",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
}

CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://unpkg.com "
    "https://esm.sh https://www.youtube.com https://s.ytimg.com; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com data:; "
    "img-src 'self' data: blob: https://image.tmdb.org https://i.ytimg.com https://*.supabase.co "
    "https://lh3.googleusercontent.com; "
    "media-src 'self' data: blob: http://127.0.0.1:8787 http://localhost:8787 http://192.168.1.2:8787 http://ruintv.to:8787 "
    "http://127.0.0.1:8788 http://localhost:8788 http://192.168.1.2:8788 http://ruintv.to:8788 https://*.supabase.co; "
    "connect-src 'self' http://127.0.0.1:8787 http://localhost:8787 http://192.168.1.2:8787 http://ruintv.to:8787 "
    "http://127.0.0.1:8788 http://localhost:8788 http://192.168.1.2:8788 http://ruintv.to:8788 "
    "http://127.0.0.1:8789 http://localhost:8789 http://192.168.1.2:8789 http://ruintv.to:8789 "
    "https://api.themoviedb.org https://*.supabase.co wss://*.supabase.co https://cdn.jsdelivr.net "
    "https://cdnjs.cloudflare.com https://sub.wyzie.io https://*.wyzie.io https://lh3.googleusercontent.com https://discord.com; "
    # 'self' and https: are both needed: an embed builds its own nested frames, and the parent policy is
    # inherited by them, so a host-by-host list blocks the player's own inner frames.
    "frame-src 'self' https: data: blob:; "
    "frame-ancestors 'self'; "
    "base-uri 'self'; "
    "object-src 'none'"
)

CHUNK = 256 * 1024  # files are sent in pieces: a "bytes=0-" request for a big video must not be read into memory whole

CACHE_ASSET = "public, max-age=604800"
CACHE_PAGE = "no-cache"


def stamp():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def say(message):
    print("[%s] %s" % (stamp(), message), flush=True)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "ruin"
    timeout = 60  # recycle idle keep-alive connections instead of holding a thread forever

    def log_message(self, fmt, *args):
        pass

    # ---------------------------------------------------------------- helpers

    def _resolve(self, raw_path):
        """Map a URL path to a file under SITE_DIR, or None if it's blocked."""
        path = unquote(urlparse(raw_path).path)
        if "\x00" in path:
            return None

        raw_parts = path.split("/")
        if any(p == ".." for p in raw_parts):
            return None

        parts = [p for p in raw_parts if p not in ("", ".")]
        if parts and any(p.startswith(".") or p.startswith("_") for p in parts):
            if parts[0] != ".well-known":  # lets ACME / verification files through
                return None

        target = os.path.normpath(os.path.join(ROOT, *parts))
        try:
            if os.path.commonpath([os.path.abspath(target), ROOT]) != ROOT:
                return None
        except ValueError:
            return None

        if os.path.splitext(target)[1].lower() in BLOCKED_EXT:
            return None

        if os.path.isdir(target):
            index = os.path.join(target, "index.html")
            return index if os.path.isfile(index) else None

        if os.path.isfile(target):
            return target

        # clean URLs
        if os.path.isfile(target + ".html"):
            return target + ".html"
        nested = os.path.join(target, "index.html")
        if os.path.isfile(nested):
            return nested
        return None

    def _parse_range(self, size):
        """'bytes=0-99' -> (0, 99). None when absent or unusable."""
        header = self.headers.get("Range")
        if not header or not header.startswith("bytes="):
            return None
        spec = header[6:].split(",")[0].strip()
        if "-" not in spec:
            return None
        start_s, end_s = spec.split("-", 1)
        try:
            if start_s == "":
                if end_s == "":
                    return None
                length = int(end_s)
                if length <= 0:
                    return None
                start, end = max(0, size - length), size - 1
            else:
                start = int(start_s)
                end = int(end_s) if end_s else size - 1
        except ValueError:
            return None
        if start > end or start >= size:
            return None
        return start, min(end, size - 1)

    def _send_headers(self, status, ctype, length, cache, extra=None):
        self._headers_sent = True  # after this a 500 page can no longer be sent: the response is already under way
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", cache)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Content-Security-Policy", CSP)
        for name, value in (extra or {}).items():
            self.send_header(name, value)
        self.end_headers()

    def _send_body(self, status, body, ctype, cache, extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8", "replace")
        self._send_headers(status, ctype, len(body), cache, extra)
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_file(self, status, path, start, end, ctype, cache, extra=None):
        length = end - start + 1
        self._send_headers(status, ctype, length, cache, extra)
        if self.command == "HEAD":
            return
        with open(path, "rb") as handle:
            handle.seek(start)
            remaining = length
            while remaining > 0:
                chunk = handle.read(min(CHUNK, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def _serve(self):
        self._headers_sent = False
        try:
            target = self._resolve(self.path)
            if not target:
                page = os.path.join(ROOT, "404.html")
                if os.path.isfile(page):
                    with open(page, "rb") as handle:
                        body = handle.read()
                    self._send_body(404, body, "text/html; charset=utf-8", CACHE_PAGE)
                else:
                    self._send_body(404, "<h1>404</h1>", "text/html; charset=utf-8", CACHE_PAGE)
                say("404 %s" % self.path)
                return

            ext = os.path.splitext(target)[1].lower()
            ctype = MIME.get(ext) or mimetypes.guess_type(target)[0] or "application/octet-stream"
            cache = CACHE_PAGE if ext in (".html", "", ".js", ".css", ".json", ".webmanifest") else CACHE_ASSET

            size = os.path.getsize(target)
            span = self._parse_range(size)

            if span:
                start, end = span
                self._send_file(206, target, start, end, ctype, cache,
                                {"Content-Range": "bytes %d-%d/%d" % (start, end, size)})
            elif size == 0:
                self._send_body(200, b"", ctype, cache)
            else:
                self._send_file(200, target, 0, size - 1, ctype, cache)
            say("200 %s" % self.path)

        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            if not self._headers_sent:  # a second status line on a half-sent response would be malformed
                try:
                    self._send_body(500, "<h1>500</h1>", "text/html; charset=utf-8", CACHE_PAGE)
                except Exception:
                    pass
            say("500 %s\n%s" % (self.path, traceback.format_exc()))

    def do_GET(self):
        self._serve()

    def do_HEAD(self):
        self._serve()


class Server(ThreadingHTTPServer):
    # set as class attributes so they are in force before server_bind() runs.
    # On Windows, SO_REUSEADDR lets a SECOND copy bind the same port without any error (the classic "hidden duplicate
    # server" bug), so it stays off there and a busy port is reported properly. On Linux/macOS it only skips TIME_WAIT.
    allow_reuse_address = os.name != "nt"
    daemon_threads = True


def bind(port):
    return Server(("0.0.0.0", port), Handler)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    if not os.path.isdir(SITE_DIR):
        say("site folder missing: %s" % SITE_DIR)
        sys.exit(1)

    server = None
    for port in (args.port, FALLBACK_PORT):
        try:
            server = bind(port)
            break
        except PermissionError:  # must come before OSError, it is a subclass
            say("port %d needs elevation" % port)
        except OSError as exc:
            say("port %d unavailable (%s)" % (port, exc))

    if server is None:
        say("could not bind any port, giving up")
        sys.exit(2)

    say("serving %s on http://localhost:%d" % (SITE_DIR, server.server_address[1]))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        say("stopping")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
