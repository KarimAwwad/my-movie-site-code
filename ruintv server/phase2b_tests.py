#!/usr/bin/env python3
"""
phase2b_tests.py — Offline unit & HTTP test suite for grab.py v1.6.2 (Phase 2B YouTube multi-audio)

Run:
    python phase2b_tests.py
"""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

import grab


class Phase2BTests(unittest.TestCase):
    def setUp(self):
        self.old_cfg = dict(grab.CFG)
        self.old_ytdlp = grab.YTDLP
        self.old_ffmpeg = grab.FFMPEG
        self.old_ffprobe = grab.FFPROBE
        grab.CFG.update(grab.DEFAULTS)
        grab.CFG["max_quality"] = "1080p"
        grab.CFG["yt_fallback"] = True
        grab.CFG["yt_search"] = True
        grab.CFG["yt_min_unknown_secs"] = 90
        grab.YTDLP = "yt-dlp"
        grab.FFMPEG = "ffmpeg"
        grab.FFPROBE = "ffprobe"

    def tearDown(self):
        grab.CFG.clear()
        grab.CFG.update(self.old_cfg)
        grab.YTDLP = self.old_ytdlp
        grab.FFMPEG = self.old_ffmpeg
        grab.FFPROBE = self.old_ffprobe

    def test_u01_youtube_title_and_trailer_filtering(self):
        meta = {"title": "Remain Calm", "original_title": "Remain Calm", "alternatives": [], "year": "2024"}
        self.assertTrue(grab.yt_title_acceptable("Remain Calm (2024) | Full Movie", meta)[0])
        self.assertFalse(grab.yt_title_acceptable("Remain Calm (2024) Official Trailer", meta)[0])
        self.assertFalse(grab.yt_title_acceptable("Remain Calm Ending Explained & Review", meta)[0])
        self.assertFalse(grab.yt_title_acceptable("Remain Calm (2019) Full Movie", meta)[0])
        self.assertFalse(grab.yt_title_acceptable("Completely Unrelated Film 2024", meta)[0])

    def test_u02_youtube_duration_and_unknown_runtime_floor(self):
        meta_unknown = {"title": "Remain Calm", "runtime": 0}
        self.assertFalse(grab.yt_duration_acceptable(45, meta_unknown)[0])
        self.assertTrue(grab.yt_duration_acceptable(900, meta_unknown)[0])

        meta_known = {"title": "Test Film", "runtime": 100}
        self.assertFalse(grab.yt_duration_acceptable(1200, meta_known)[0])
        self.assertTrue(grab.yt_duration_acceptable(6100, meta_known)[0])

    def test_u03_select_yt_streams_m3u8_priority_fallbacks_regional_and_desc(self):
        meta = {"title": "Remain Calm", "original_language": "en"}
        info = {
            "language": "en",
            "duration": 1000,
            "formats": [
                # 2160p blocked by 1080p ceiling; 270 (m3u8) beats 137 (https) with 137 stored as fallback
                {"format_id": "313", "vcodec": "vp9", "acodec": "none", "height": 2160, "protocol": "https", "tbr": 15000, "filesize": 900_000_000},
                {"format_id": "270", "vcodec": "avc1.640028", "acodec": "none", "height": 1080, "protocol": "m3u8", "tbr": 4700, "filesize_approx": 863_000_000},
                {"format_id": "137", "vcodec": "avc1.640028", "acodec": "none", "height": 1080, "protocol": "https", "tbr": 3046, "filesize": 559_000_000},
                {"format_id": "136", "vcodec": "avc1.4d401f", "acodec": "none", "height": 720, "protocol": "https", "tbr": 1062, "filesize": 195_000_000},
                # Original English: 234-23 (m3u8 high) beats 233-23 (m3u8 low) and 140-23 (https), with 140-23 as fallback
                {"format_id": "233-23", "vcodec": "none", "acodec": "unknown", "language": "en-US", "protocol": "m3u8",
                 "format_note": "American English - original", "language_preference": 10, "abr": 0},
                {"format_id": "234-23", "vcodec": "none", "acodec": "unknown", "language": "en-US", "protocol": "m3u8",
                 "format_note": "American English - original", "language_preference": 10, "abr": 0},
                {"format_id": "140-23", "vcodec": "none", "acodec": "mp4a.40.2", "language": "en-US", "protocol": "https",
                 "format_note": "English (US) original", "language_preference": 10, "abr": 129, "filesize": 24_000_000},
                # Audio Description track stays separate from primary English
                {"format_id": "234-24", "vcodec": "none", "acodec": "unknown", "language": "en-US-desc", "protocol": "m3u8",
                 "format_note": "English (US) audio description", "language_preference": -5, "abr": 0},
                # Regional French & Spanish dubs + Arabic, Punjabi, Marathi
                {"format_id": "234-0", "vcodec": "none", "acodec": "unknown", "language": "fr-FR", "protocol": "m3u8",
                 "format_note": "French (France) dubbed", "language_preference": -10, "abr": 0},
                {"format_id": "234-1", "vcodec": "none", "acodec": "unknown", "language": "fr-CA", "protocol": "m3u8",
                 "format_note": "French (Canada) dubbed", "language_preference": -10, "abr": 0},
                {"format_id": "234-2", "vcodec": "none", "acodec": "unknown", "language": "es-419", "protocol": "m3u8",
                 "format_note": "Spanish (Latin America) dubbed", "language_preference": -10, "abr": 0},
                {"format_id": "234-3", "vcodec": "none", "acodec": "unknown", "language": "es-ES", "protocol": "m3u8",
                 "format_note": "Spanish (Spain) dubbed", "language_preference": -10, "abr": 0},
                {"format_id": "234-4", "vcodec": "none", "acodec": "unknown", "language": "ar", "protocol": "m3u8",
                 "format_note": "Arabic dubbed", "language_preference": -10, "abr": 0},
                {"format_id": "140-18", "vcodec": "none", "acodec": "mp4a.40.2", "language": "ar", "protocol": "https",
                 "format_note": "Arabic, medium", "language_preference": -10, "abr": 129, "filesize": 24_000_000},
                {"format_id": "234-5", "vcodec": "none", "acodec": "unknown", "language": "pa", "protocol": "m3u8",
                 "format_note": "Punjabi dubbed", "language_preference": -10, "abr": 0},
                {"format_id": "234-6", "vcodec": "none", "acodec": "unknown", "language": "mr", "protocol": "m3u8",
                 "format_note": "Marathi dubbed", "language_preference": -10, "abr": 0},
            ],
        }
        vpick, atracks, why = grab.select_yt_streams(info, meta)
        self.assertEqual(why, "")
        self.assertEqual(vpick["format_id"], "270")
        self.assertEqual(vpick["protocol"], "m3u8")
        self.assertIn("137", vpick["fallback_format_ids"])
        self.assertEqual(len(atracks), 9)
        self.assertEqual(atracks[0]["format_id"], "234-23")
        self.assertIn("140-23", atracks[0]["fallback_format_ids"])
        self.assertTrue(atracks[0]["original"])
        self.assertTrue(atracks[0]["default"])

        ar_track = next(t for t in atracks if t["lang"] == "ar")
        self.assertEqual(ar_track["format_id"], "234-4")
        self.assertEqual(ar_track["fallback_format_ids"], ["140-18"])

        self.assertEqual(
            [t["label"] for t in atracks],
            [
                "English (US)",
                "Arabic",
                "English (US) (Audio Description)",
                "French (Canada)",
                "French (France)",
                "Marathi",
                "Punjabi",
                "Spanish (Latin America)",
                "Spanish (Spain)",
            ],
        )

    def test_u04_build_yt_mux_cmd_metadata_and_codecs(self):
        audio_items = [
            (Path("a0.mp4"), {"iso3": "eng", "label": "English (US)", "acodec": "unknown"}),
            (Path("a1.mp4"), {"iso3": "fra", "label": "French (Canada)", "acodec": "unknown"}),
            (Path("a2.mp4"), {"iso3": "ara", "label": "Arabic", "acodec": "unknown"}),
        ]
        cmd = grab.build_yt_mux_cmd(Path("v.mp4"), audio_items, Path("muxed.mp4"), vcodec="avc1.640028")
        self.assertEqual(cmd[cmd.index("-c:v") + 1], "copy")
        self.assertEqual(cmd[cmd.index("-c:a") + 1], "aac")
        self.assertIn("language=fra", cmd)
        self.assertIn("title=French (Canada)", cmd)
        self.assertIn("language=ara", cmd)
        self.assertIn("title=Arabic", cmd)
        self.assertEqual(cmd[cmd.index("-disposition:a:0") + 1], "default")
        self.assertEqual(cmd[cmd.index("-disposition:a:1") + 1], "0")

    def test_u05_dry_endpoint_youtube_fallback_when_yts_misses(self):
        fake_meta = {
            "tmdb": 1796809,
            "imdb": "tt49058294",
            "title": "Remain Calm",
            "original_title": "Remain Calm",
            "original_language": "en",
            "alternatives": [],
            "year": "2026",
            "runtime": 13,
            "poster": "",
        }
        fake_search = {
            "entries": [
                {"id": "3ETZmhzURfQ", "title": "REMAIN CALM - A Horror Short", "duration": 864,
                 "webpage_url": "https://www.youtube.com/watch?v=3ETZmhzURfQ"},
            ]
        }
        fake_video = {
            "id": "3ETZmhzURfQ",
            "title": "REMAIN CALM - A Horror Short",
            "webpage_url": "https://www.youtube.com/watch?v=3ETZmhzURfQ",
            "uploader": "The Lewis Brothers",
            "duration": 864,
            "language": "en",
            "formats": [
                {"format_id": "270", "vcodec": "avc1.640028", "acodec": "none", "height": 1080, "protocol": "m3u8"},
                {"format_id": "234-0", "vcodec": "none", "acodec": "unknown", "language": "en", "protocol": "m3u8",
                 "format_note": "English original", "language_preference": 10},
                {"format_id": "234-1", "vcodec": "none", "acodec": "unknown", "language": "es-419", "protocol": "m3u8",
                 "format_note": "Spanish (Latin America) dubbed", "language_preference": -10},
                {"format_id": "234-2", "vcodec": "none", "acodec": "unknown", "language": "ar", "protocol": "m3u8",
                 "format_note": "Arabic dubbed", "language_preference": -10},
            ],
        }

        def fake_ytdlp_json(args, timeout=60):
            if "--flat-playlist" in args:
                return fake_search
            return fake_video

        with tempfile.TemporaryDirectory() as tmp:
            grab.CFG["staging_root"] = tmp
            grab.CFG["library_root"] = str(Path(tmp) / "lib")
            Path(grab.CFG["library_root"]).mkdir()
            srv = grab.Server(("127.0.0.1", 0), grab.Handler)
            port = srv.server_address[1]
            t = threading.Thread(target=srv.serve_forever, daemon=True)
            t.start()
            try:
                with mock.patch.object(grab, "tmdb_meta", return_value=fake_meta), \
                     mock.patch.object(grab, "yts_query", return_value=[]), \
                     mock.patch.object(grab, "ytdlp_json", side_effect=fake_ytdlp_json):
                    resp = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/dry?tmdb=1796809").read())

                self.assertEqual(resp["source"], "youtube")
                self.assertEqual(resp["rejected"], "")
                self.assertEqual(len(resp["candidates"]), 1)
                c0 = resp["candidates"][0]
                self.assertEqual(c0["quality"], "1080p")
                self.assertEqual(len(c0["audio_tracks"]), 3)
                self.assertEqual(
                    [a["label"] for a in c0["audio_tracks"]],
                    ["English", "Arabic", "Spanish (Latin America)"],
                )
            finally:
                srv.shutdown()
                srv.server_close()

    def test_u06_fallback_and_nonfatal_dub_skip(self):
        with tempfile.TemporaryDirectory() as tmp:
            grab.CFG["staging_root"] = tmp
            grab.CFG["library_root"] = str(Path(tmp) / "lib")
            Path(grab.CFG["library_root"]).mkdir()
            grab.CFG["auto_scan"] = False

            job = grab.new_job(1796809)
            job.update(title="Remain Calm", year="2026", runtime=13, original_language="en", dir="yt_test_u06")
            cand = {
                "webpage_url": "https://www.youtube.com/watch?v=test",
                "title": "Remain Calm",
                "quality": "1080p",
                "video_format": {"format_id": "270", "fallback_format_ids": ["137"], "vcodec": "avc1.640028", "label": "1080p video"},
                "audio_tracks": [
                    {"index": 0, "lang": "en", "iso3": "eng", "label": "English", "original": True,
                     "format_id": "234-0", "fallback_format_ids": ["140-0"], "acodec": "unknown"},
                    {"index": 1, "lang": "ar", "iso3": "ara", "label": "Arabic", "original": False,
                     "format_id": "234-1", "fallback_format_ids": ["140-1"], "acodec": "unknown"},
                    {"index": 2, "lang": "fr", "iso3": "fra", "label": "French", "original": False,
                     "format_id": "234-2", "fallback_format_ids": ["140-2"], "acodec": "unknown"},
                ],
            }

            def fake_dl(url, fid, out_tpl):
                # English primary 234-0 fails -> falls back to 140-0 and succeeds
                # French fails on both 234-2 and 140-2 -> skipped non-fatally
                if fid in ("234-0", "234-2", "140-2"):
                    raise RuntimeError(f"simulated 403 on {fid}")
                p = Path(str(out_tpl).replace("%(ext)s", "mp4"))
                p.write_bytes(b"fake")
                return p

            def fake_subproc(cmd, capture_output=True, timeout=1800):
                out_file = Path(cmd[-1])
                out_file.write_bytes(b"muxed")
                res = mock.Mock()
                res.returncode = 0
                res.stderr = b""
                return res

            fake_probe = {"ok": True, "seconds": 800, "width": 1920, "height": 1080, "title": "", "audio_langs": ["eng", "ara"]}
            with mock.patch.object(grab, "_yt_download_stream", side_effect=fake_dl), \
                 mock.patch.object(grab.subprocess, "run", side_effect=fake_subproc), \
                 mock.patch.object(grab, "ffprobe_media", return_value=fake_probe):
                grab.run_yt_job(job, cand)

            self.assertEqual(job["state"], "done")
            self.assertEqual([t["label"] for t in job["audio_tracks"]], ["English", "Arabic"])
            self.assertFalse((Path(tmp) / "yt_test_u06").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)