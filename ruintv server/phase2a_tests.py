#!/usr/bin/env python3
"""
phase2a_tests.py — Offline unit & HTTP handler test suite for library.py v1.3.0 (Phase 2A)

Run:
    python phase2a_tests.py
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

import library


class Phase2ATests(unittest.TestCase):
    def test_u01_regional_french_and_spanish_disambiguation(self):
        streams = [
            {"codec_type": "audio", "codec_name": "aac", "channels": 2,
             "disposition": {"default": 1}, "tags": {"language": "eng", "title": "English"}},
            {"codec_type": "audio", "codec_name": "ac3", "channels": 6,
             "disposition": {"default": 0}, "tags": {"language": "fre", "title": "French (France)"}},
            {"codec_type": "audio", "codec_name": "ac3", "channels": 6,
             "disposition": {"default": 0}, "tags": {"language": "fra", "title": "French (Canada)"}},
            {"codec_type": "audio", "codec_name": "eac3", "channels": 6,
             "disposition": {"default": 0}, "tags": {"language": "spa", "title": "Spanish (Latin America)"}},
            {"codec_type": "audio", "codec_name": "eac3", "channels": 6,
             "disposition": {"default": 0}, "tags": {"language": "spa", "title": "Spanish (Spain)"}},
        ]
        out = library.normalize_audio_streams(streams)
        self.assertEqual([t["lang"] for t in out], ["en", "fr-FR", "fr-CA", "es-419", "es-ES"])
        self.assertEqual(
            [t["label"] for t in out],
            ["English", "French (France)", "French (Canada)", "Spanish (Latin America)", "Spanish (Spain)"],
        )
        self.assertEqual([t["index"] for t in out], [0, 1, 2, 3, 4])
        self.assertTrue(out[0]["default"])
        self.assertFalse(out[2]["default"])

    def test_u02_duplicate_untagged_language_collision_guard(self):
        streams = [
            {"codec_type": "audio", "codec_name": "aac", "channels": 2,
             "tags": {"language": "fre", "title": "SoundHandler"}},
            {"codec_type": "audio", "codec_name": "aac", "channels": 2,
             "tags": {"language": "fra", "title": "Stereo"}},
        ]
        out = library.normalize_audio_streams(streams)
        self.assertEqual([t["label"] for t in out], ["French (Track 1)", "French (Track 2)"])
        self.assertEqual(len({t["label"] for t in out}), 2)

    def test_u03_commentary_and_portuguese_regional_labels(self):
        streams = [
            {"codec_type": "audio", "codec_name": "aac", "channels": 2,
             "tags": {"language": "eng", "title": "Director's Commentary"}},
            {"codec_type": "audio", "codec_name": "aac", "channels": 2,
             "tags": {"language": "por", "title": "Brazilian Portuguese"}},
            {"codec_type": "audio", "codec_name": "aac", "channels": 2,
             "tags": {"language": "pt-PT"}},
        ]
        out = library.normalize_audio_streams(streams)
        self.assertEqual(out[0]["label"], "English (Director's Commentary)")
        self.assertEqual(out[1]["lang"], "pt-BR")
        self.assertEqual(out[1]["label"], "Portuguese (Brazil)")
        self.assertEqual(out[2]["lang"], "pt-PT")
        self.assertEqual(out[2]["label"], "Portuguese (Portugal)")

    def test_u04_probe_routes_single_mp4_direct_and_multi_mp4_hls(self):
        single_payload = json.dumps({
            "format": {"duration": "6006.2"},
            "streams": [
                {"codec_type": "video", "codec_name": "h264", "pix_fmt": "yuv420p", "height": 1080},
                {"codec_type": "audio", "codec_name": "aac", "channels": 2, "tags": {"language": "eng"}},
            ],
        }).encode()
        multi_payload = json.dumps({
            "format": {"duration": "6006.2"},
            "streams": [
                {"codec_type": "video", "codec_name": "h264", "pix_fmt": "yuv420p", "height": 1080},
                {"codec_type": "audio", "codec_name": "aac", "channels": 2, "tags": {"language": "eng"}},
                {"codec_type": "audio", "codec_name": "aac", "channels": 2, "tags": {"language": "ara"}},
            ],
        }).encode()

        with mock.patch.object(library, "FFPROBE", "ffprobe"):
            with mock.patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0, stdout=single_payload)):
                direct1, h1, s1, tracks1, copy1 = library.probe_details(Path("Movie (2024) [tmdb-1].mp4"))
            with mock.patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0, stdout=multi_payload)):
                direct2, h2, s2, tracks2, copy2 = library.probe_details(Path("Movie (2024) [tmdb-1].mp4"))

        self.assertTrue(direct1)
        self.assertEqual((h1, s1, len(tracks1), copy1), (1080, 6006, 1, True))
        self.assertFalse(direct2)
        self.assertEqual((h2, s2, len(tracks2), copy2), (1080, 6006, 2, True))

    def test_u05_build_ffmpeg_cmd_and_write_master_multi_audio(self):
        tracks = [
            {"index": 0, "lang": "en", "label": "English", "codec": "aac", "channels": 2, "default": True},
            {"index": 1, "lang": "fr-CA", "label": "French (Canada)", "codec": "ac3", "channels": 6, "default": False},
            {"index": 2, "lang": "ar", "label": "Arabic", "codec": "aac", "channels": 2, "default": False},
        ]
        cmd_copy = library.build_ffmpeg_cmd(Path("test.mkv"), audio_tracks=tracks, can_copy_h264=True)
        self.assertIn("-c:v", cmd_copy)
        self.assertEqual(cmd_copy[cmd_copy.index("-c:v") + 1], "copy")
        self.assertIn("0:a:0", cmd_copy)
        self.assertIn("0:a:1", cmd_copy)
        self.assertIn("0:a:2", cmd_copy)
        self.assertIn("v:0,agroup:aud,name:v a:0,agroup:aud,name:a0 a:1,agroup:aud,name:a1 a:2,agroup:aud,name:a2", cmd_copy)

        cmd_hevc = library.build_ffmpeg_cmd(Path("test_hevc.mkv"), audio_tracks=tracks, can_copy_h264=False)
        self.assertEqual(cmd_hevc[cmd_hevc.index("-c:v") + 1], "libx264")

        with tempfile.TemporaryDirectory() as tmp:
            old_cache = library.CACHE
            try:
                library.CACHE = Path(tmp)
                key = "abc123def4567890"
                out = library.cache_dir(key)
                self.assertFalse(library.outputs_present(key, tracks))
                (out / "stream_v.m3u8").write_text("#EXTM3U\n", encoding="utf-8")
                (out / "init_v.mp4").write_bytes(b"ftyp")
                (out / "seg_v_00000.m4s").write_bytes(b"moof")
                for i in range(3):
                    (out / f"stream_a{i}.m3u8").write_text("#EXTM3U\n", encoding="utf-8")
                    (out / f"init_a{i}.mp4").write_bytes(b"ftyp")
                    (out / f"seg_a{i}_00000.m4s").write_bytes(b"moof")

                self.assertTrue(library.outputs_present(key, tracks))
                library.write_master(key, height=1080, audio_tracks=tracks)
                self.assertTrue(library.build_complete(key, tracks))

                master_disk = (out / "master.m3u8").read_text(encoding="utf-8")
                self.assertIn('#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aud",NAME="French (Canada)",LANGUAGE="fr-CA",DEFAULT=NO,AUTOSELECT=YES,URI="stream_a1.m3u8"', master_disk)
                self.assertIn('CODECS="avc1.640028,mp4a.40.2",AUDIO="aud"', master_disk)

                rewritten = library.rewrite_master_uris(master_disk, "0")
                self.assertIn('URI="0/stream_a0.m3u8"', rewritten)
                self.assertIn('URI="0/stream_a1.m3u8"', rewritten)
                self.assertIn('URI="0/stream_a2.m3u8"', rewritten)
                self.assertIn("\n0/stream_v.m3u8\n", rewritten)
            finally:
                library.CACHE = old_cache

    def test_u06_http_endpoints_index_probe_and_stream_renditions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "lib"
            cache = Path(tmp) / "cache"
            root.mkdir()
            cache.mkdir()
            movie = root / "Test Film (2024) [tmdb-999999].mp4"
            movie.write_bytes(b"0" * 1024)
            (root / "Test Film (2024) [tmdb-999999].ar.srt").write_text(
                "1\n00:00:01,000 --> 00:00:03,000\nمرحبا\n", encoding="utf-8"
            )

            tracks = [
                {"index": 0, "lang": "en", "raw_lang": "eng", "label": "English", "codec": "aac", "channels": 2, "default": True},
                {"index": 1, "lang": "fr-CA", "raw_lang": "fre", "label": "French (Canada)", "codec": "aac", "channels": 2, "default": False},
            ]

            old_root, old_cache, old_ffprobe = library.ROOT, library.CACHE, library.FFPROBE
            library.ROOT = root
            library.CACHE = cache
            library.FFPROBE = "ffprobe"
            srv = library.Server(("127.0.0.1", 0), library.Handler)
            port = srv.server_address[1]
            t = threading.Thread(target=srv.serve_forever, daemon=True)
            t.start()

            try:
                with mock.patch.object(library, "probe_details", return_value=(False, 1080, 5400, tracks, True)):
                    library.scan()

                # Pre-populate HLS cache artifacts to verify HTTP master & rendition serving
                st = movie.stat()
                key = library.cache_key(movie, st.st_mtime, st.st_size)
                out = library.cache_dir(key)
                (out / "stream_v.m3u8").write_text("#EXTM3U\n#EXT-X-MAP:URI=\"init_v.mp4\"\nseg_v_00000.m4s\n", encoding="utf-8")
                (out / "init_v.mp4").write_bytes(b"vinit")
                (out / "seg_v_00000.m4s").write_bytes(b"vseg0")
                for i in range(2):
                    (out / f"stream_a{i}.m3u8").write_text(f"#EXTM3U\n#EXT-X-MAP:URI=\"init_a{i}.mp4\"\nseg_a{i}_00000.m4s\n", encoding="utf-8")
                    (out / f"init_a{i}.mp4").write_bytes(f"ainit{i}".encode())
                    (out / f"seg_a{i}_00000.m4s").write_bytes(f"aseg{i}".encode())
                library.write_master(key, height=1080, audio_tracks=tracks)

                base = f"http://127.0.0.1:{port}"
                health = json.loads(urllib.request.urlopen(f"{base}/health").read())
                self.assertEqual(health["version"], "1.3.0")
                self.assertTrue(health["multi_audio"])

                idx = json.loads(urllib.request.urlopen(f"{base}/index.json?tmdb=999999").read())
                f0 = idx["files"][0]
                self.assertFalse(f0["direct"])
                self.assertEqual(f0["kind"], "hls")
                self.assertEqual(len(f0["audio_tracks"]), 2)
                self.assertEqual(f0["audio_tracks"][1]["label"], "French (Canada)")
                self.assertEqual(len(f0["subtitles"]), 1)
                self.assertEqual(f0["subtitles"][0]["lang"], "ar")

                master_http = urllib.request.urlopen(f"{base}/stream/999999/0").read().decode("utf-8")
                self.assertIn('URI="0/stream_a0.m3u8"', master_http)
                self.assertIn('URI="0/stream_a1.m3u8"', master_http)
                self.assertIn('NAME="French (Canada)"', master_http)
                self.assertIn("\n0/stream_v.m3u8\n", master_http)

                a1_pl = urllib.request.urlopen(f"{base}/stream/999999/0/stream_a1.m3u8").read().decode("utf-8")
                self.assertIn("seg_a1_00000.m4s", a1_pl)
                a1_seg = urllib.request.urlopen(f"{base}/stream/999999/0/seg_a1_00000.m4s").read()
                self.assertEqual(a1_seg, b"aseg1")

                probe_html = urllib.request.urlopen(f"{base}/probe").read().decode("utf-8")
                self.assertIn("2 audio (English, French (Canada))", probe_html)
            finally:
                srv.shutdown()
                srv.server_close()
                library.ROOT, library.CACHE, library.FFPROBE = old_root, old_cache, old_ffprobe


if __name__ == "__main__":
    unittest.main(verbosity=2)