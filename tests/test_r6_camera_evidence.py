"""Strict source-bound use of Analyzer R6 camera recommendations for Studio."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile, ZIP_DEFLATED

from ldporto_studio.r6_camera_evidence import read_safe_r6_camera
from test_r6_review import make_valid_r6_delivery


class R6CameraEvidenceTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(prefix="r6_camera_handoff_")
        self.addCleanup(tmp.cleanup)
        self.folder=Path(tmp.name)/"input"/"analyzer"/"VIDEO"/"R6_SYNTHETIC"
        self.zip=make_valid_r6_delivery(self.folder)

    def _rewrite_camera(self, segments):
        camera={
            "schema_version":"1.0",
            "renderer_owner":"VIDEO_CURATOR",
            "execution_scope":"recommendation_not_render_or_approval",
            "preview_approved":False,"publish_ready":False,
            "segments":segments
        }
        member="camera/shared_camera_handoff.json"
        with ZipFile(self.zip,"r") as z:
            members={name:z.read(name) for name in z.namelist()
                     if name!="SECOND_CURATION_MANIFEST.json"}
            manifest=json.loads(z.read("SECOND_CURATION_MANIFEST.json"))
        raw=json.dumps(camera,ensure_ascii=False,sort_keys=True).encode("utf-8")
        members[member]=raw
        manifest["files"]=[
            {"path":name,"sha256":sha256(data).hexdigest(),"bytes":len(data)}
            for name,data in sorted(members.items())]
        with ZipFile(self.zip,"w",ZIP_DEFLATED) as z:
            for name,data in members.items():
                z.writestr(name,data)
            z.writestr("SECOND_CURATION_MANIFEST.json",
                       json.dumps(manifest).encode("utf-8"))
        receipt=self.folder/"ANALYZER_TO_CURATOR_HANDOFF.json"
        data=json.loads(receipt.read_text(encoding="utf-8"))
        data["zip"]["sha256"]=sha256(self.zip.read_bytes()).hexdigest()
        data["zip"]["bytes"]=self.zip.stat().st_size
        receipt.write_text(json.dumps(data),encoding="utf-8")

    @staticmethod
    def _safe(a=12.,b=22.):
        return {"start":a,"end":b,"director_id":"SHOT_1",
                "recommended_composition":"FOCUS_PERSON_9X16",
                "crop":{"rect_end":{"x":.42,"y":.1,"width":.12,"height":.65}},
                "evidence":{"crop_geometrically_valid":True}}

    def test_camera_safe_focus_is_clipped_to_reel_and_source_bound(self):
        self._rewrite_camera([self._safe()])
        report=read_safe_r6_camera(self.folder,"a"*64,14.,28.,1920,1080)
        self.assertEqual(report["evidence_status"],"SAFE_SOURCE_BOUND_SEGMENTS")
        self.assertEqual(len(report["trusted_regions"]),1)
        row=report["trusted_regions"][0]
        self.assertEqual((row["start"],row["end"]),(0.,8.))
        self.assertTrue(0<=row["x"]<=1)
        self.assertEqual(row["source"],"ANALYZER_R6_SAFE_SOLO")
        self.assertEqual(len(report["source_zip_sha256"]),64)

    def test_camera_handoff_tracks_safe_person_with_real_keyframe_times(self):
        row=self._safe(12,22)
        row["camera"]={"keyframes":[
            {"time":12.,"center":[.30,.5],"zoom":1.0},
            {"time":17.,"center":[.49,.5],"zoom":1.0},
            {"time":22.,"center":[.67,.5],"zoom":1.0},
        ]}
        self._rewrite_camera([row])
        info=read_safe_r6_camera(self.folder,"a"*64,12.,22.,1920,1080)
        region=info["trusted_regions"][0]
        self.assertEqual(region["tracking"],
                         "SOURCE_DIRECTOR_HORIZONTAL_KEYFRAMES")
        self.assertEqual([x["t"] for x in region["camera_points"]],
                         [0.,5.,10.])
        self.assertNotEqual(region["camera_points"][0]["x"],
                            region["camera_points"][-1]["x"])

    def test_unsafe_wide_scene_remains_uncropped(self):
        unsafe=self._safe()
        unsafe["evidence"]["crop_geometrically_valid"]=False
        self._rewrite_camera([unsafe])
        report=read_safe_r6_camera(self.folder,"a"*64,12,28,1920,1080)
        self.assertEqual(report["trusted_regions"],[])
        self.assertEqual(report["evidence_status"],"NO_VERIFIED_R6_SOLO_REGIONS")

    def test_single_person_uncertified_geometry_is_review_only_guidance(self):
        unsafe=self._safe()
        unsafe["recommended_composition"]="SOURCE_FIT_BLUR"
        unsafe["layout"]="single_person"
        unsafe["evidence"]["crop_geometrically_valid"]=False
        self._rewrite_camera([unsafe])
        plan=read_safe_r6_camera(self.folder,"a"*64,12,28,1920,1080)
        self.assertEqual(plan["trusted_regions"],[])
        self.assertEqual(len(plan["review_regions"]),1)
        self.assertEqual(plan["evidence_status"],"SOLO_REVIEW_PROPOSALS_ONLY")
        self.assertEqual(plan["review_regions"][0]["source"],
                         "ANALYZER_R6_SOLO_REVIEW_REQUIRED")

    def test_mismatched_source_sha_is_fatal(self):
        self._rewrite_camera([self._safe()])
        with self.assertRaisesRegex(ValueError,"outra mídia"):
            read_safe_r6_camera(self.folder,"b"*64,12,28,1920,1080)

    def test_missing_camera_handoff_is_not_fake_detection(self):
        report=read_safe_r6_camera(self.folder,"a"*64,12,28,1920,1080)
        self.assertEqual(report["trusted_regions"],[])
        self.assertEqual(report["evidence_status"],"NO_R6_CAMERA_HANDOFF_MEMBER")

    def test_conflicting_director_solo_regions_require_review(self):
        self._rewrite_camera([self._safe(12,20),self._safe(18,24)])
        report=read_safe_r6_camera(self.folder,"a"*64,12,28,1920,1080)
        self.assertEqual(report["trusted_regions"],[])
        self.assertEqual(report["evidence_status"],"OVERLAPPING_R6_REGIONS_REVIEW")

    def test_tampered_camera_zip_is_rejected(self):
        self._rewrite_camera([self._safe()])
        self.zip.write_bytes(self.zip.read_bytes()+b"bad")
        with self.assertRaisesRegex(ValueError,"zip_bytes_mismatch"):
            read_safe_r6_camera(self.folder,"a"*64,12,28,1920,1080)


if __name__=="__main__":
    unittest.main()
