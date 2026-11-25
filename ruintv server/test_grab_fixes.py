#!/usr/bin/env python3
"""Checks the three grab.py fixes. Read-only apart from two API calls per check."""

import inspect
import sys

import grab
import source

FAILS = []
PASSES = []


def check(name, ok, detail=""):
    (PASSES if ok else FAILS).append(name)
    print(("PASS  " if ok else "FAIL  ") + name + (f"   [{detail}]" if detail else ""))


grab.CFG = grab.load_config("grab.json")
grab.CFG["client"] = "drop"

FILM = (631842, "Knock at the Cabin", "2023")


def cand(quality, seeds, cam=False, size=1_900_000_000):
    return {"quality": quality, "type": "cam" if cam else "web", "cam": cam,
            "size": size, "seeds": seeds, "peers": 0, "hash": quality + str(seeds),
            "url": "", "magnet": f"magnet:x-{quality}-{seeds}-{cam}",
            "title": "Knock at the Cabin (2023)", "year": 2023}


print("--- version ---")
check("VERSION is 1.9.3", grab.VERSION == "1.9.3", grab.VERSION)

print("\n--- fix 3: below_floor is marked, never silent ---")
below = grab.rank([cand("1080p", 0), cand("720p", 1)])
check("all-under-floor picks are flagged", all(c["below_floor"] for c in below))
ok_floor = grab.rank([cand("1080p", 50)])
check("a healthy pick is not flagged", not ok_floor[0]["below_floor"])

print("\n--- quality ladder and cam preference ---")
mix = grab.rank([cand("720p", 50), cand("1080p", 50, cam=True)])
check("720p WEB beats 1080p cam", mix[0]["quality"] == "720p", mix[0]["quality"])
tiers = grab.rank([cand("720p", 50), cand("1080p", 5)])
check("1080p WEB beats 720p WEB", tiers[0]["quality"] == "1080p", tiers[0]["quality"])
floor = grab.rank([cand("1080p", 1), cand("720p", 10)])
check("min_seeds drops the 1-seed 1080p", floor[0]["quality"] == "720p", floor[0]["quality"])
same_q = grab.rank([cand("1080p", 20, cam=True), cand("1080p", 20)])
check("cam loses the tie at equal quality and seeds", not same_q[0]["cam"])

print("\n--- fix 1: rejected magnets are filtered out ---")
tmdb, title, year = FILM
full = grab.yts_candidates("", title, year)
check("baseline returns candidates", len(full) > 0, str(len(full)))
if full:
    top = full[0]["magnet"]
    fewer = grab.yts_candidates("", title, year, [top])
    check("the rejected magnet is gone", top not in [c["magnet"] for c in fewer])
    check("the rest are untouched", len(fewer) == len(full) - 1,
          f"{len(fewer)} of {len(full)}")
    every = [c["magnet"] for c in full]
    check("rejecting everything returns nothing",
          grab.yts_candidates("", title, year, every) == [])

    print("\n--- fix 1: the job fails cleanly when nothing is untried ---")
    job = grab.new_job(tmdb)
    job.update(title=title, year=year, runtime=6000, rejected=every)
    out, code = grab.yts_path(job, tmdb, {})
    check("all-rejected returns 404", code == 404, str(code))
    check("with an honest reason", out["error"] == "no untried torrent", out["error"])
    check("job does not sit in a busy state", out["state"] == "failed", out["state"])

print("\n--- fix 2: cam upgrades run in every client mode ---")
check("cam_loop exists", hasattr(grab, "cam_loop"))
check("cam_loop is callable", callable(getattr(grab, "cam_loop", None)))
watcher_src = inspect.getsource(grab.watcher_loop)
check("watcher_loop no longer drives cam_pass", "cam_pass()" not in watcher_src)
main_src = inspect.getsource(grab.main)
check("main starts cam_loop", "cam_loop" in main_src)

print("\n--- regression: the decision still lands on yts ---")
plan = source.choose(str(tmdb))
check("631842 still routes to yts", plan.get("rung") == "yts", plan.get("rung"))
check("still 1080p", plan.get("quality") == "1080p", plan.get("quality"))

print(f"\n{len(PASSES)} passed, {len(FAILS)} failed")
for name in FAILS:
    print("  FAILED: " + name)
sys.exit(1 if FAILS else 0)