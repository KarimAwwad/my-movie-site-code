#!/usr/bin/env python3
"""Offline unit test harness for Phase 1 verification gates in grab.py v1.5.0."""

import importlib.util
import pathlib
import sys

spec = importlib.util.spec_from_file_location(
    "grab", pathlib.Path(__file__).with_name("grab.py")
)
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)

g.CFG = {
    "verify_runtime_tolerance_min": 10,
    "verify_runtime_long_tolerance_min": 20,
    "verify_size_tolerance_pct": 5,
    "verify_audio_language": True,
    "staging_root": r"D:\movies\staging",
    "library_root": r"D:\movies\library",
    "jobs_file": "",
    "min_file_mb": 20,
    "auto_delete_rejected": True,
    "auto_scan": False,
    "max_quality": "1080p",
    "min_seeds": 3,
}

BASE_JOB = {
    "id": "j1",
    "state": "handed_off",
    "tmdb": 280092,
    "tmdb_id": 280092,
    "imdb_id": "tt3195644",
    "title": "Insidious: Chapter 3",
    "original_title": "Insidious: Chapter 3",
    "original_language": "en",
    "alternative_titles": [],
    "year": "2015",
    "runtime": 97,
    "quality": "1080p",
    "size": 2_000_000_000,
    "dir": "Insidious Chapter 3 (2015) [1080p] [YTS]",
}


def run_eval(
    name: str,
    seconds: int,
    width: int,
    height: int,
    folder: str,
    filename: str,
    size: int,
    container_title: str = "",
    audio_langs: list[str] | None = None,
    probe_ok: bool = True,
    temp_active: bool = False,
    job_override: dict | None = None,
    expect: str | None = "file",
) -> bool:
    g.JOBS.clear()
    job = dict(BASE_JOB)
    if job_override:
        job.update(job_override)
    g.JOBS["j1"] = job
    g.SEEN.clear()
    g.REVIEWED.clear()
    g.PROBE_CACHE.clear()
    g.find_video = lambda p: None
    g.staging_temp_active = lambda: temp_active
    g.ffprobe_media = lambda p: {
        "ok": probe_ok,
        "seconds": seconds,
        "width": width,
        "height": height,
        "title": container_title,
        "audio_langs": audio_langs if audio_langs is not None else ["eng"],
        "error": "" if probe_ok else "probe failed",
    }

    fake_path = pathlib.Path(r"D:\movies\staging") / folder / f"{filename}.mp4"
    res = g.evaluate(fake_path, folder, size)
    verdict = res[1] if res else None
    ok = verdict == expect
    print(("PASS" if ok else "FAIL"), name, "->", verdict, f"(expected {expect})")
    return ok


def run_predownload_tests() -> list[bool]:
    out = []

    meta = {
        "tmdb": 280092,
        "imdb": "tt3195644",
        "title": "Insidious: Chapter 3",
        "original_title": "Insidious: Chapter 3",
        "original_language": "en",
        "alternatives": [],
        "year": "2015",
        "runtime": 97,
        "poster": "",
    }
    g.tmdb_meta = lambda tid: meta
    g.yts_query = lambda term: [
        {
            "imdb_code": "tt9999999",
            "title": "Insidious: Chapter 3",
            "title_long": "Insidious: Chapter 3 (2015)",
            "year": 2015,
            "runtime": 97,
            "torrents": [
                {"quality": "1080p", "size_bytes": 2_000_000_000, "seeds": 20, "peers": 5, "hash": "abc123"}
            ],
        }
    ]
    _, cands, why = g.resolve(280092)
    ok12 = len(cands) == 0 and "no yts torrent" in why
    print(("PASS" if ok12 else "FAIL"), "U12 pre-download imdb mismatch ->", why)
    out.append(ok12)

    meta_long = dict(meta, runtime=120)
    g.tmdb_meta = lambda tid: meta_long
    g.yts_query = lambda term: [
        {
            "imdb_code": "tt3195644",
            "title": "Insidious: Chapter 3",
            "title_long": "Insidious: Chapter 3 (2015)",
            "year": 2015,
            "runtime": 120,
            "torrents": [
                {"quality": "1080p", "size_bytes": 150 * 1024 * 1024, "seeds": 20, "peers": 5, "hash": "def456"}
            ],
        }
    ]
    _, cands, why = g.resolve(280092)
    ok13 = len(cands) == 0 and "size sanity" in why
    print(("PASS" if ok13 else "FAIL"), "U13 pre-download size outlier ->", why)
    out.append(ok13)

    # U14: Stale TMDB IMDb fallback via normalized title + exact year + YTS runtime
    meta_cabin = {
        "tmdb": 631842,
        "imdb": "tt8272064",
        "title": "Knock at the Cabin",
        "original_title": "Knock at the Cabin",
        "original_language": "en",
        "alternatives": [],
        "year": "2023",
        "runtime": 100,
        "poster": "",
    }
    g.tmdb_meta = lambda tid: meta_cabin
    g.yts_query = lambda term: (
        [] if term == "tt8272064" else [
            {
                "imdb_code": "tt15679400",
                "title": "Knock at the Cabin",
                "title_long": "Knock at the Cabin (2023)",
                "year": 2023,
                "runtime": 100,
                "torrents": [
                    {"quality": "1080p", "size_bytes": 1_800_000_000, "seeds": 80, "peers": 10, "hash": "cab123"}
                ],
            }
        ]
    )
    _, cands, why = g.resolve(631842)
    ok14 = len(cands) == 1 and why == ""
    print(("PASS" if ok14 else "FAIL"), "U14 stale tmdb imdb exact title+year fallback ->", len(cands), "cand")
    out.append(ok14)

    # U15: Hard 1080p ceiling blocks 2160p-only movies
    g.tmdb_meta = lambda tid: meta
    g.yts_query = lambda term: [
        {
            "imdb_code": "tt3195644",
            "title": "Insidious: Chapter 3",
            "title_long": "Insidious: Chapter 3 (2015)",
            "year": 2015,
            "runtime": 97,
            "torrents": [
                {"quality": "2160p", "size_bytes": 6_000_000_000, "seeds": 50, "peers": 10, "hash": "uhd999"}
            ],
        }
    ]
    _, cands, why = g.resolve(280092)
    ok15 = len(cands) == 0 and "1080p" in why
    print(("PASS" if ok15 else "FAIL"), "U15 hard 1080p ceiling blocks 2160p ->", why)
    out.append(ok15)

    # U16: Uncut / Extended release priority over standard 1080p
    g.yts_query = lambda term: [
        {
            "imdb_code": "tt3195644",
            "title": "Insidious: Chapter 3",
            "title_long": "Insidious: Chapter 3 (2015)",
            "year": 2015,
            "runtime": 97,
            "torrents": [
                {"quality": "1080p", "size_bytes": 1_600_000_000, "seeds": 120, "peers": 10, "hash": "std111"}
            ],
        },
        {
            "imdb_code": "tt3195644",
            "title": "Insidious: Chapter 3 Unrated Extended Cut",
            "title_long": "Insidious: Chapter 3 Unrated Extended Cut (2015)",
            "year": 2015,
            "runtime": 110,
            "torrents": [
                {"quality": "1080p", "size_bytes": 1_850_000_000, "seeds": 45, "peers": 5, "hash": "ext222"}
            ],
        },
    ]
    _, cands, why = g.resolve(280092)
    ok16 = len(cands) == 2 and cands[0]["hash"] == "ext222"
    print(("PASS" if ok16 else "FAIL"), "U16 uncut/extended priority ->", cands[0]["title"] if cands else "none")
    out.append(ok16)

    # U17: Hard min_seeds floor rejects dead 0-seed torrents
    g.yts_query = lambda term: [
        {
            "imdb_code": "tt3195644",
            "title": "Insidious: Chapter 3",
            "title_long": "Insidious: Chapter 3 (2015)",
            "year": 2015,
            "runtime": 97,
            "torrents": [
                {"quality": "1080p", "size_bytes": 1_600_000_000, "seeds": 0, "peers": 0, "hash": "dead00"}
            ],
        }
    ]
    _, cands, why = g.resolve(280092)
    ok17 = len(cands) == 0 and "min_seeds" in why
    print(("PASS" if ok17 else "FAIL"), "U17 hard min_seeds floor blocks dead torrent ->", why)
    out.append(ok17)

    # U18: IMDb fallback normalized punctuation + pre-download YTS runtime gate
    meta_mi = {
        "tmdb": 575264,
        "imdb": "tt0000000",
        "title": "Mission: Impossible - Dead Reckoning Part One",
        "original_title": "Mission: Impossible - Dead Reckoning Part One",
        "original_language": "en",
        "alternatives": [],
        "year": "2023",
        "runtime": 163,
        "poster": "",
    }
    g.tmdb_meta = lambda tid: meta_mi
    g.yts_query = lambda term: (
        [] if term == "tt0000000" else [
            {
                "imdb_code": "tt9603212",
                "title": "Mission: Impossible – Dead Reckoning",
                "title_long": "Mission: Impossible – Dead Reckoning (2023)",
                "year": 2023,
                "runtime": 163,
                "torrents": [
                    {"quality": "1080p", "size_bytes": 2_800_000_000, "seeds": 90, "peers": 10, "hash": "mi2023"}
                ],
            },
            {
                "imdb_code": "tt8888888",
                "title": "Mission: Impossible - Dead Reckoning",
                "title_long": "Mission: Impossible - Dead Reckoning (2023)",
                "year": 2023,
                "runtime": 45,
                "torrents": [
                    {"quality": "1080p", "size_bytes": 900_000_000, "seeds": 90, "peers": 10, "hash": "fake45"}
                ],
            },
        ]
    )
    _, cands, why = g.resolve(575264)
    ok18 = len(cands) == 1 and cands[0]["hash"] == "mi2023"
    print(("PASS" if ok18 else "FAIL"), "U18 normalized fallback + YTS runtime gate ->", len(cands), "cand")
    out.append(ok18)

    # U19: Duplicate active job guard allows retries on failed jobs
    g.JOBS.clear()
    g.JOBS["j_active"] = {"id": "j_active", "tmdb": 631842, "state": "handed_off", "size": 1_800_000_000}
    g.JOBS["j_failed"] = {"id": "j_failed", "tmdb": 157336, "state": "failed", "size": 2_000_000_000}
    ok19 = (g.find_active_job(631842) is not None) and (g.find_active_job(157336) is None) and (g.reserved_bytes() == 1_800_000_000)
    print(("PASS" if ok19 else "FAIL"), "U19 duplicate active guard + failed retry + reserved bytes ->", ok19)
    out.append(ok19)

    return out


if __name__ == "__main__":
    results = [
        run_eval("U1 wrong runtime", 70 * 60, 1920, 1080, "x", "x", 2_000_000_000, expect="reject"),
        run_eval("U2 wrong resolution", 97 * 60, 854, 480, "x", "x", 2_000_000_000, expect="reject"),
        run_eval("U3 widescreen 1920x800", 97 * 60, 1920, 800, "Insidious Chapter 3 (2015) [1080p] [YTS]", "Insidious.Chapter.3.2015.1080p", 2_000_000_000, expect="file"),
        run_eval("U4 generic filename", 97 * 60, 1920, 1080, "Downloads", "movie", 2_000_000_000, expect="review"),
        run_eval("U5 wrong year (+3)", 97 * 60, 1920, 1080, "Insidious 3 2018 1080p", "x", 2_000_000_000, expect="review"),
        run_eval("U6 connector strip", 97 * 60, 1920, 1080, "Insidious 3 2015", "x", 2_000_000_000, expect="file"),
        run_eval("U7 short title no substring false hit", 97 * 60, 1920, 1080, "The Incredibles 2004", "incredibles", 2_000_000_000, job_override={"title": "Red", "original_title": "Red", "year": "2010"}, expect="review"),
        run_eval("U8 size 40% under", 97 * 60, 1920, 1080, "Insidious Chapter 3 2015", "x", 1_200_000_000, expect="review"),
        run_eval("U9 tmdb runtime 0", 97 * 60, 1920, 1080, "Insidious Chapter 3 2015", "x", 2_000_000_000, job_override={"runtime": 0}, expect="review"),
        run_eval("U10 ffprobe fails", 0, 0, 0, "Insidious Chapter 3 2015", "x", 2_000_000_000, probe_ok=False, expect="review"),
        run_eval("U11 container title", 97 * 60, 1920, 1080, "Downloads", "abc", 2_000_000_000, container_title="Insidious Chapter 3", expect="file"),
    ]
    results.extend(run_predownload_tests())
    results.extend([
        run_eval("U20 extended cut +15 min passes asymmetric runtime", 112 * 60, 1920, 800, "Insidious Chapter 3 Extended 2015", "x", 2_000_000_000, expect="file"),
        run_eval("U21 dub-only audio mismatch rejects", 97 * 60, 1920, 1080, "Insidious Chapter 3 2015", "x", 2_000_000_000, audio_langs=["rus"], expect="reject"),
        run_eval("U22 untagged audio stream passes", 97 * 60, 1920, 1080, "Insidious Chapter 3 2015", "x", 2_000_000_000, audio_langs=["und"], expect="file"),
        run_eval("U23 dual audio with original passes", 97 * 60, 1920, 1080, "Insidious Chapter 3 2015", "x", 2_000_000_000, audio_langs=["spa", "eng"], expect="file"),
        run_eval("U24 bonus clip deferred while .temp active", 8 * 60, 1920, 1080, "Insidious Chapter 3 (2015) [1080p] [YTS]", "featurette", 50_000_000, temp_active=True, expect=None),
    ])
    sys.exit(0 if all(results) else 1)