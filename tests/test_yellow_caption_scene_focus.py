"""Scene-aware camera and yellow subtitle regressions (no media original changed)."""
from __future__ import annotations

import unittest

from ldporto_studio.scene_focus import plan_shot_focus, pick_dominant_face
from ldporto_studio.subtitle_style import make_yellow_ass
from ldporto_studio.editorial_camera_fill import build_editorial_fill


SAMPLE_ASS=(
    "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n"
    "[V4+ Styles]\n"
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
    "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
    "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
    "Alignment, MarginL, MarginR, MarginV, Encoding\n"
    "Style: Default,Arial,48,&H00FFFFFF,&H000000FF,&H00000000,"
    "&H80000000,0,0,0,0,100,100,0,0,1,2,0,2,30,30,70,1\n"
    "[Events]\n"
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    r"Dialogue: 0,0:00:00.00,0:00:02.50,Default,,0,0,0,,{\k20\c&H00FF00&}"
    "Finally, a couple of milestones in 3D printing\n"
).encode("utf-8")


class YellowCaptionTests(unittest.TestCase):
    def test_high_contrast_yellow_with_safe_bottom_margin(self):
        source=bytes(SAMPLE_ASS)
        result=make_yellow_ass(source)
        doc=result.decode("utf-8")
        self.assertIn("PrimaryColour",doc)
        self.assertIn("&H0000FFFF",doc)
        self.assertIn("OutlineColour",doc)
        self.assertIn("Style: Default,Arial,68",doc)
        self.assertIn(",1,5,2,2,94,94,244,1",doc)
        self.assertIn("Finally, a couple of milestones in 3D printing",doc)
        self.assertIn(r"{\k20}",doc,"Karaoke timing must be preserved")
        self.assertNotIn(r"\c&H00FF00&",doc,"Inline colors cannot override yellow")
        self.assertIn("0:00:00.00,0:00:02.50",doc)
        self.assertEqual(source,SAMPLE_ASS,"Never alter the original ASS")

    def test_invalid_ass_is_rejected(self):
        with self.assertRaisesRegex(ValueError,"seções"):
            make_yellow_ass(b"no styles")
        with self.assertRaises(ValueError):
            make_yellow_ass(b"\xff\xfe")

    def test_yellow_style_is_idempotent(self):
        styled=make_yellow_ass(SAMPLE_ASS)
        self.assertEqual(make_yellow_ass(styled),styled)


class SmartFramePositionTests(unittest.TestCase):
    @staticmethod
    def right_presenter():
        return [
            *[{"t":float(i)*1.5,"shot":0,"kind":"FACE_FRONT","cx":.87+i*.002}
              for i in range(6)],
            *[{"t":9.+i*1.5,"shot":1,"kind":"UNKNOWN"} for i in range(5)],
            *[{"t":17.+i*1.5,"shot":2,"kind":"FACE_PROFILE","cx":.12+i*.003}
              for i in range(4)],
        ]

    def test_woman_on_right_is_reframed_inside_vertical_crop(self):
        scenes=plan_shot_focus(self.right_presenter(),24.,1920,1080)
        self.assertEqual(len(scenes),2)
        self.assertGreater(scenes[0]["x"],.85,
                           "Presenters at the right edge need a right-hand crop")
        self.assertLess(scenes[1]["x"],.15,
                        "Next shot may have a subject on the opposite side")
        self.assertLess(scenes[0]["end"],scenes[1]["start"],
                        "Never track a person across a different shot")
        self.assertEqual(scenes[0]["source"],"OPENCV_FACE_FOCUS_REVIEW_REQUIRED")

    def test_face_scene_overrides_blind_center_but_not_certified_r6(self):
        plan={
            "decision":"dynamic","requested":"smart_zoom",
            "camera_regions":[{"start":4.,"end":5.,"x":.3,
                               "source":"ANALYZER_R6_SAFE_SOLO"}],
            "scene_focus_regions":[{"start":0.,"end":8.,"x":.95,
                                    "source":"OPENCV_FACE_FOCUS_REVIEW_REQUIRED"}],
        }
        filled=build_editorial_fill(plan,12.)
        face=[r for r in filled["camera_regions"]
              if r["source"]=="OPENCV_FACE_FOCUS_REVIEW_REQUIRED"]
        verified=[r for r in filled["camera_regions"]
                  if r["source"]=="ANALYZER_R6_SAFE_SOLO"]
        self.assertEqual(len(face),2)
        self.assertEqual(len(verified),1)
        self.assertEqual(verified[0]["x"],.3)
        self.assertTrue(all(r["x"]==.95 for r in face))
        self.assertGreater(filled["scene_face_focus_percent"],50)
        self.assertEqual(filled["verified_portrait_coverage_percent"],8.3)
        self.assertGreater(filled["center_fallback_percent"],0)

    def test_multiple_faces_do_not_produce_auto_focus(self):
        observations=[
            {"t":i*2.,"shot":0,"kind":"GROUP"} for i in range(5)]
        self.assertEqual(plan_shot_focus(observations,10.,1920,1080),[])

    def test_moving_face_gets_smoothed_keyframes(self):
        observations=[
            {"t":float(i),"shot":0,"kind":"FACE_FRONT","cx":.52+.025*i}
            for i in range(8)]
        frame=plan_shot_focus(observations,8.,1920,1080)[0]
        self.assertEqual(frame["tracking"],"SMOOTH_FACE_WITHIN_SHOT_REVIEW_REQUIRED")
        self.assertGreaterEqual(len(frame["camera_points"]),2)
        self.assertLess(frame["camera_points"][0]["x"],frame["camera_points"][-1]["x"])

    def test_background_monitor_faces_do_not_steal_presenter_frame(self):
        boxes=[(30,20,35,35),(550,50,94,95),(165,34,30,28)]
        self.assertEqual(pick_dominant_face(boxes,960),(550,50,94,95))
        crowded=[(120,20,80,80),(320,35,75,77)]
        self.assertIsNone(pick_dominant_face(crowded,960))
        small_screen=[(10,20,28,32)]
        self.assertIsNone(pick_dominant_face(small_screen,960))

    def test_no_subject_does_not_invent_one(self):
        observations=[
            {"t":float(i),"shot":0,"kind":"UNKNOWN"} for i in range(6)]
        self.assertEqual(plan_shot_focus(observations,6.,1920,1080),[])


if __name__=="__main__":
    unittest.main()
