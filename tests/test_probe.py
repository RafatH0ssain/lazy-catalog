import unittest
from pathlib import Path

from lazycatalog import probe, scan

PAYLOAD = {
    "streams": [
        {"codec_type": "video", "codec_name": "hevc", "width": 1920,
         "height": 1080, "color_transfer": "smpte2084"},
        {"codec_type": "audio", "codec_name": "eac3", "channels": 6,
         "disposition": {"default": 1}},
        {"codec_type": "audio", "codec_name": "aac", "channels": 2,
         "disposition": {"default": 0}},
        {"codec_type": "subtitle", "tags": {"language": "eng"}},
        {"codec_type": "subtitle", "tags": {"language": "spa"}},
    ],
    "format": {"duration": "6540.5"},
}


class SummariseTest(unittest.TestCase):
    def test_reads_the_fields_that_matter(self):
        out = probe.summarise(PAYLOAD)
        self.assertEqual(out["resolution"], "1080p")
        self.assertEqual(out["video"], "hevc")
        self.assertEqual(out["audio"], "EAC3")
        self.assertEqual(out["channels"], "5.1")
        self.assertEqual(out["hdr"], "HDR10")
        self.assertEqual(out["subs"], ["eng", "spa"])
        self.assertEqual(out["audio_tracks"], 2)
        self.assertEqual(out["runtime_sec"], 6540)

    def test_default_audio_track_wins_over_the_first(self):
        out = probe.summarise(PAYLOAD)
        self.assertEqual(out["audio"], "EAC3")

    def test_no_subtitles_reports_an_empty_list_not_a_missing_key(self):
        out = probe.summarise({"streams": [
            {"codec_type": "video", "codec_name": "h264", "height": 720}]})
        self.assertEqual(out["subs"], [])
        self.assertEqual(out["resolution"], "720p")

    def test_4k_is_recognised(self):
        out = probe.summarise({"streams": [
            {"codec_type": "video", "codec_name": "hevc", "width": 3840,
             "height": 2160}]})
        self.assertEqual(out["resolution"], "2160p")

    def test_widescreen_1080p_is_not_demoted_by_its_letterboxed_height(self):
        """A 2.35:1 film at 1920 wide is only ~800 tall but is still 1080p."""
        for width, height in ((1920, 800), (1920, 816), (1920, 806), (1916, 788)):
            with self.subTest(dims=(width, height)):
                out = probe.summarise({"streams": [
                    {"codec_type": "video", "codec_name": "h264",
                     "width": width, "height": height}]})
                self.assertEqual(out["resolution"], "1080p")

    def test_narrow_1080p_is_not_demoted_by_its_width(self):
        """A 1.66:1 film is only 1792 wide but is a full 1080 tall."""
        out = probe.summarise({"streams": [
            {"codec_type": "video", "codec_name": "h264",
             "width": 1792, "height": 1080}]})
        self.assertEqual(out["resolution"], "1080p")

    def test_either_dimension_can_carry_the_tier(self):
        cases = [((1920, 800), "1080p"), ((1792, 1080), "1080p"),
                 ((1918, 1080), "1080p"), ((1920, 1040), "1080p"),
                 ((1280, 528), "720p"), ((1280, 688), "720p"),
                 ((1024, 576), "576p"), ((720, 480), "480p")]
        for (width, height), expected in cases:
            with self.subTest(dims=(width, height)):
                out = probe.summarise({"streams": [
                    {"codec_type": "video", "codec_name": "h264",
                     "width": width, "height": height}]})
                self.assertEqual(out["resolution"], expected)

    def test_widescreen_720p_stays_720p(self):
        for width, height in ((1280, 688), (1280, 528), (1280, 720)):
            with self.subTest(dims=(width, height)):
                out = probe.summarise({"streams": [
                    {"codec_type": "video", "codec_name": "h264",
                     "width": width, "height": height}]})
                self.assertEqual(out["resolution"], "720p")

    def test_ultrawide_4k_is_recognised_by_width(self):
        out = probe.summarise({"streams": [
            {"codec_type": "video", "codec_name": "hevc", "width": 3840,
             "height": 1600}]})
        self.assertEqual(out["resolution"], "2160p")

    def test_standard_definition_is_not_called_hd(self):
        out = probe.summarise({"streams": [
            {"codec_type": "video", "codec_name": "h264", "width": 720,
             "height": 480}]})
        self.assertEqual(out["resolution"], "480p")

    def test_five_channel_audio_is_named_5_0(self):
        out = probe.summarise({"streams": [
            {"codec_type": "audio", "codec_name": "aac", "channels": 5}]})
        self.assertEqual(out["channels"], "5.0")

    def test_unreadable_duration_is_dropped(self):
        out = probe.summarise({"streams": [], "format": {"duration": "N/A"}})
        self.assertNotIn("runtime_sec", out)


class DescribeTest(unittest.TestCase):
    def _entry(self, kind, sizes):
        entry = scan.Entry(key="k", path=Path("/tmp/k"), kind=kind,
                           parsed=None)
        for index, size in enumerate(sizes):
            entry.videos.append(
                scan.VideoFile(Path("/tmp/k/{}.mkv".format(index)), size))
        return entry

    def test_probes_the_largest_file(self):
        seen = {}

        def runner(path):
            seen["path"] = path
            return PAYLOAD

        entry = self._entry("film", [100, 9999, 50])
        probe.describe(entry, runner=runner)
        self.assertEqual(seen["path"].name, "1.mkv")

    def test_series_runtime_is_not_reported_as_the_whole_show(self):
        entry = self._entry("series", [100])
        out = probe.describe(entry, runner=lambda p: PAYLOAD)
        self.assertNotIn("runtime_sec", out)

    def test_no_videos_gives_nothing(self):
        entry = self._entry("film", [])
        self.assertEqual(probe.describe(entry, runner=lambda p: PAYLOAD), {})

    def test_ffprobe_failure_is_not_fatal(self):
        entry = self._entry("film", [100])
        self.assertEqual(probe.describe(entry, runner=lambda p: None), {})


if __name__ == "__main__":
    unittest.main()
