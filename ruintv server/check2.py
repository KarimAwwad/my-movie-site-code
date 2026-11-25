#!/usr/bin/env python3
"""check2.py — read-only. Script order, required shell, and why providers answer 48 bytes."""

import json
import re
import urllib.error
import urllib.request
from pathlib import Path

SITE = Path(r"D:\my development work\unfinished and finished development projects\movie site")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0 Safari/537.36"
API_PATH_RE = re.compile(
    r"[\"'`](/[a-z0-9_\-./]*(?:api|stream|source|playlist|manifest|prorcp|srcrcp|server)[a-z0-9_\-./?=&]*)",
    re.I)


def get(url, ref=None, timeout=25):
    h = {"User-Agent": UA, "Accept": "text/html,application/json,*/*"}
    if ref:
        h["Referer"] = ref
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, str(e)


watch = SITE / "watch.html"
print("1. script order")
if watch.is_file():
    html = watch.read_text(encoding="utf-8", errors="replace")
    js = re.findall(r'<script[^>]+src="([^"]+)"', html)
    for i, src in enumerate(js, 1):
        print(f"   {i}. {src}")
    order = {s: i for i, s in enumerate(js)}
    si = next((v for k, v in order.items() if "script.js" in k), None)
    pi = next((v for k, v in order.items() if "player-ui.js" in k), None)
    print(f"   -> script.js at {si}, player-ui.js at {pi}")
    print("   PASS" if si is not None and pi is not None and pi > si
          else "   FAIL  player-ui.js must load AFTER script.js")
else:
    print("   FAIL  watch.html missing")

print("\n2. shell elements components.js must provide")
comp = SITE / "components.js"
if comp.is_file():
    text = comp.read_text(encoding="utf-8", errors="replace")
    for needle, why in (('class="pl-controls"', "control bar root"),
                        ('id="pl-bigplay"', "big play"),
                        ('id="pl-toast"', "status pill"),
                        ('id="pl-quality"', "quality menu"),
                        ('id="pl-subs"', "subtitle menu")):
        print(f"   {'PASS' if needle in text else 'FAIL'}  {why}")
else:
    print("   FAIL  components.js missing")

print("\n3. what the 48-byte answers say")
for label, url, ref in (
        ("vidsrc.xyz", "https://vidsrc.xyz/embed/movie/tt0133093", "https://vidsrc.xyz/"),
        ("embedsu", "https://embed.su/embed/movie/603", "https://embed.su/"),
        ("videasy seed", "https://api.wecollege.net/seed?mediaId=603", "https://vidy.st/")):
    status, body = get(url, ref)
    print(f"   {label}: HTTP {status}, {len(body)} bytes -> {body.strip()[:160]!r}")

print("\n4. API_PATH_RE on vidsrcto (first 8 matches)")
status, page = get("https://vidsrc.to/embed/movie/603", "https://vidsrc.to/")
print(f"   page HTTP {status}, {len(page)} bytes")
for hit in list(dict.fromkeys(API_PATH_RE.findall(page)))[:8]:
    print(f"   {hit}")