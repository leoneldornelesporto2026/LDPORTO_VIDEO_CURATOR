"""Regression tests for the approved LIVE card and safe concert framing."""
from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from ldporto_studio.smart_camera import BodyObservation, decide_framing, decide_scene_regions, crop_x_expression
from ldporto_studio.visual_style import editorial_card, premium_cover, footer_for_project
from ldporto_studio.core import Project
from ldporto_studio.rendering import generate_premium_covers, render_item
from test_studio import make_fixture


class VisualStyleTests(unittest.TestCase):
    def test_white_live_card_with_gold_border(self):
        card=editorial_card('SE NÃO EU, QUEM VAI FAZER VOCÊ FELIZ?',540,960)
        self.assertEqual(card.size,(540,960))
        self.assertEqual(card.mode,'RGBA')
        self.assertEqual(card.getpixel((270,350))[3],0)
        center=card.getpixel((270,135))
        self.assertGreater(center[0],230)
        self.assertGreater(center[1],230)
        self.assertGreater(center[2],220)

    def test_future_show_does_not_inherit_cbjr_branding(self):
        from types import SimpleNamespace
        project=SimpleNamespace(package=SimpleNamespace(
            source_sha='b'*64,plan={'source_artist':'CPM 22','genre':'Rock nacional'}))
        self.assertEqual(footer_for_project(project,'reels'),'ROCK NACIONAL · CPM 22')
        unknown=SimpleNamespace(package=SimpleNamespace(source_sha='c'*64,plan={}))
        self.assertNotIn('CBJR',footer_for_project(unknown,'stories'))

    def test_premium_cover_keeps_horizontal_reference(self):
        sample=Image.new('RGB',(640,360),(30,80,90))
        cover=premium_cover(sample,'UM MOMENTO HISTÓRICO','reels')
        self.assertEqual(cover.size,(1080,1920))
        self.assertEqual(cover.mode,'RGB')


class SafeCameraTests(unittest.TestCase):
    def test_no_detection_keeps_source_full(self):
        plan=decide_framing([None]*8,1920,1080,'smart_zoom',16)
        self.assertEqual(plan['decision'],'preserve')

    def test_multi_subject_never_crops(self):
        single=[BodyObservation(float(i)*2,.48,.12,.12,.72) for i in range(8)]
        single[4]=BodyObservation(8,.52,.14,.2,.71,people=2)
        plan=decide_framing(single,1920,1080,'solo_fit',16)
        self.assertEqual(plan['decision'],'preserve')

    def test_solo_subject_with_margins_can_be_framed(self):
        single=[BodyObservation(float(i)*2,.48+.004*i,.12,.12,.72) for i in range(8)]
        plan=decide_framing(single,1920,1080,'solo_fit',16)
        self.assertEqual(plan['decision'],'crop')
        self.assertEqual(len(plan['camera_points']),1)
        self.assertTrue(0<=plan['camera_points'][0]['x']<=1)

    def test_single_visible_face_without_full_body_can_be_cropped(self):
        interview=[BodyObservation(float(i)*2,.46+.003*i,.085,.12,.09,
                                  people=1,faces=1,face_only=True) for i in range(8)]
        plan=decide_framing(interview,1920,1080,'smart_zoom',16)
        self.assertEqual(plan['decision'],'crop')
        self.assertGreater(len(plan['camera_points']),3)

    def test_solo_regions_keep_surrounding_wide_scene_untouched(self):
        single=lambda t: BodyObservation(float(t),.48,.08,.12,.09,
                                          people=1,faces=1,face_only=True)
        frames=[None,single(2),single(4),single(6),single(8),
                None,BodyObservation(12,.5,.3,.1,.5,people=2,faces=2),None]
        plan=decide_scene_regions(frames,1920,1080,16)
        self.assertEqual(plan['decision'],'dynamic')
        self.assertEqual(len(plan['camera_regions']),1)
        window=plan['camera_regions'][0]
        self.assertGreater(window['start'],0)
        self.assertLess(window['end'],12)
        self.assertTrue(0<=window['x']<=1)

    def test_uncertain_or_two_faces_never_trigger_dynamic_crop(self):
        observations=[
            BodyObservation(float(i)*2,.5,.08,.1,.1,people=1,faces=2,face_only=True)
            for i in range(8)]
        plan=decide_scene_regions(observations,1920,1080,16)
        self.assertEqual(plan['decision'],'preserve')
        self.assertEqual(plan['camera_regions'],[])

    def test_smart_zoom_tracks_smoothly(self):
        single=[BodyObservation(float(i)*2,.40+.005*i,.12,.12,.72) for i in range(8)]
        plan=decide_framing(single,1920,1080,'smart_zoom',16)
        self.assertEqual(plan['decision'],'crop')
        self.assertGreater(len(plan['camera_points']),3)
        self.assertIn('if(lt(t,',crop_x_expression(plan['camera_points']))


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg required')
class RenderFeatureTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='ldporto_visual_')
        self.addCleanup(self.tmp.cleanup)
        base=Path(self.tmp.name)
        archive,media=make_fixture(base)
        self.p=Project.create(archive,base/'project')
        self.p.set_media(media)

    def test_premium_cover_from_real_video_frame(self):
        target,count=generate_premium_covers(self.p,'reels')
        self.assertEqual(count,1)
        images=list(target.glob('reels/REEL_01/*/CAPA_PREMIUM.png'))
        self.assertEqual(len(images),1)
        with Image.open(images[0]) as image:self.assertEqual(image.size,(1080,1920))

    def test_smart_crop_preview_and_approved_final_reuse_camera_plan(self):
        self.p.update('REEL_01',layout='smart_zoom')
        plan={'requested':'smart_zoom','decision':'crop','reason':'unit simulated track',
              'sample_count':6,'valid_samples':6,
              'camera_points':[{'t':0.,'x':.3},{'t':1.0,'x':.52},{'t':2.2,'x':.44}]}
        with patch('ldporto_studio.smart_camera.analyze_camera',return_value=plan):
            preview,report=render_item(self.p,'REEL_01',preview=True)
        self.assertEqual(report['camera_plan'],plan)
        self.assertTrue(preview.is_file())
        self.p.update('REEL_01',audio_reviewed=True,camera_reviewed=True)
        self.p.approve('REEL_01',human_reviewed=True,verified_audio=True,verified_camera=True)
        with patch('ldporto_studio.smart_camera.analyze_camera',
                   side_effect=AssertionError('reanalysis forbidden')):
            final,report=render_item(self.p,'REEL_01',preview=False)
        self.assertTrue(final.is_file())
        self.assertEqual(report['camera_plan'],plan)

    def test_dynamic_solo_overlay_with_wide_scene_produces_real_preview(self):
        self.p.update('REEL_01',layout='smart_zoom')
        plan={'requested':'smart_zoom','decision':'dynamic',
              'reason':'unit simulated solo regions',
              'camera_points':[],
              'camera_regions':[{'start':.6,'end':1.9,'x':.35,'samples':3}],
              'sample_count':8,'valid_samples':3}
        with patch('ldporto_studio.smart_camera.analyze_camera',return_value=plan):
            preview,report=render_item(self.p,'REEL_01',preview=True)
        self.assertTrue(preview.is_file())
        self.assertEqual(report['camera_plan']['decision'],'dynamic')
        self.assertEqual(report['media']['width'],540)
        self.assertEqual(report['media']['height'],960)
        self.assertFalse(report['publication_ready'])
        self.assertFalse(report['captions_included'])

    def test_solo_fit_ambiguous_falls_back_to_16_by_9(self):
        self.p.update('REEL_01',layout='solo_fit')
        plan={'requested':'solo_fit','decision':'preserve','reason':'no reliable solo body',
              'sample_count':7,'valid_samples':0,'camera_points':[]}
        with patch('ldporto_studio.smart_camera.analyze_camera',return_value=plan):
            preview,report=render_item(self.p,'REEL_01',preview=True)
        self.assertTrue(preview.is_file())
        self.assertEqual(report['camera_plan']['decision'],'preserve')


if __name__=='__main__':unittest.main()
