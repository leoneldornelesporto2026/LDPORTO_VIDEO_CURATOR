"""Regression for NASA 8.9%-only safe framing, never claiming 100% verified."""
from __future__ import annotations

import unittest

from ldporto_studio.editorial_camera_fill import build_editorial_fill


class EditorialFillTests(unittest.TestCase):
    @staticmethod
    def _nasa():
        return {
            "requested":"smart_zoom","decision":"dynamic",
            "camera_points":[],"sample_count":42,"valid_samples":2,
            "camera_regions":[
                {"start":19.518,"end":21.741,"x":.738679,
                 "source":"ANALYZER_R6_SAFE_SOLO",
                 "camera_points":[{"t":19.518,"x":.738679},
                                  {"t":21.741,"x":.738679}]},
                {"start":42.424,"end":46.783,"x":.486621,
                 "source":"ANALYZER_R6_SAFE_SOLO",
                 "camera_points":[{"t":42.424,"x":.486621},
                                  {"t":46.783,"x":.486621}]},
            ],
        }

    def test_real_nasa_diagnostic_8_9_verified_and_100_proposed(self):
        duration=74.266667
        original=self._nasa()
        result=build_editorial_fill(original,duration)
        self.assertEqual(result["decision"],"dynamic")
        self.assertEqual(result["verified_portrait_coverage_percent"],8.9)
        self.assertEqual(result["editorial_unverified_coverage_percent"],91.1)
        self.assertEqual(result["portrait_coverage_percent"],100)
        self.assertTrue(result["review_required"])
        self.assertTrue(result["draft_editorial_fill"])
        self.assertEqual(len(result["camera_regions"]),5)
        self.assertEqual(result["camera_regions"][0]["source"],
                         "CENTER_CROP_REVIEW_REQUIRED")
        self.assertEqual(result["camera_regions"][-1]["source"],
                         "CENTER_CROP_REVIEW_REQUIRED")
        self.assertEqual(result["camera_regions"][1]["x"],.738679)
        self.assertEqual(result["camera_regions"][3]["x"],.486621)
        self.assertEqual(result["camera_regions"][0]["start"],0.)
        self.assertAlmostEqual(result["camera_regions"][-1]["end"],duration,places=3)
        self.assertEqual(len(original["camera_regions"]),2,
                         "Original safe regions must remain unmodified")

    def test_uncertified_r6_person_guides_position_before_center_fallback(self):
        source=self._nasa()
        source["r6_review_regions"]=[
            {"start":26.,"end":32.,"x":.80,
             "source":"ANALYZER_R6_SOLO_REVIEW_REQUIRED",
             "crop_geometrically_valid":False}
        ]
        result=build_editorial_fill(source,74.266667)
        guided=[r for r in result["camera_regions"]
                if r["source"]=="ANALYZER_R6_SOLO_REVIEW_REQUIRED"]
        self.assertEqual(len(guided),1)
        self.assertEqual((guided[0]["start"],guided[0]["end"]),(26.,32.))
        self.assertEqual(guided[0]["x"],.80)
        self.assertGreater(result["r6_unverified_guidance_percent"],0)
        self.assertEqual(result["verified_portrait_coverage_percent"],8.9)

    def test_no_safe_detection_cannot_be_claimed_as_verified_person(self):
        original={"requested":"smart_zoom","decision":"preserve","camera_points":[]}
        result=build_editorial_fill(original,10.)
        self.assertEqual(result["verified_portrait_coverage_percent"],0)
        self.assertEqual(result["editorial_unverified_coverage_percent"],100)
        self.assertEqual(result["camera_regions"],[
            {"start":0.,"end":10.,"x":.5,"source":"CENTER_CROP_REVIEW_REQUIRED"}])
        self.assertTrue(result["review_required"])

    def test_rejects_overlapping_or_invalid_regions(self):
        original=self._nasa()
        original["camera_regions"][1]["start"]=20.
        with self.assertRaisesRegex(ValueError,"sobrepostas"):
            build_editorial_fill(original,74.266667)

    def test_fails_for_invalid_decisions(self):
        with self.assertRaises(ValueError):
            build_editorial_fill({"decision":"publication_ready"},12)

    def test_region_cap_blocks_unreviewable_graph(self):
        source={"requested":"smart_zoom","decision":"dynamic","camera_regions":[
            {"start":float(i*2+1),"end":float(i*2+2),
             "x":.5,"source":"ANALYZER_R6_SAFE_SOLO"}
            for i in range(16)
        ]}
        with self.assertRaisesRegex(ValueError,"Muitas regiões"):
            build_editorial_fill(source,34.,max_regions=24)


if __name__ == "__main__":
    unittest.main()
