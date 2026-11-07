"""Offline self-tests including a real synthetic source (never the copyrighted show)."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from zipfile import ZipFile,ZIP_DEFLATED

from ldporto_studio.core import CuradoriaPackage, Project,sha256_file
from ldporto_studio.rendering import render_item, probe_media, extract_editorial_assets, binaries

ROOT=Path(__file__).resolve().parents[1]
DEMO=ROOT/'example'/'CURADORIA_R57.zip'


def make_fixture(folder:Path):
    ffmpeg,_=binaries()
    video=folder/'original.mp4'
    p=subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-f','lavfi',
      '-i','testsrc2=size=640x360:rate=30','-f','lavfi','-i','sine=frequency=440:sample_rate=48000',
      '-t','4','-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p',
      '-c:a','aac','-b:a','128k','-y',str(video)],capture_output=True,text=True,timeout=90)
    if p.returncode:raise RuntimeError(p.stderr)
    sha=sha256_file(video)
    png=(ROOT/'example'/'CURADORIA_R57.zip')
    from PIL import Image
    from io import BytesIO
    buf=BytesIO();Image.new('RGB',(200,356),'#292d38').save(buf,format='PNG')
    image=buf.getvalue()
    ass=b'[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,Arial,60,&H00FFFFFF,&H0000E1FF,&H00101010,&H88000000,-1,0,0,0,100,100,0,0,1,5,2,2,100,100,335,1\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\nDialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,Teste de legenda\n'
    assets={}
    clips=[]
    for cid,kind,a,b in [('REEL_01','reels',.5,2.7),('STORY_01','stories',0.,4.)]:
        prefix=('REELS' if kind=='reels' else 'STORIES')+'/'+cid
        thumb=prefix+'/CAPA.png'
        sub=prefix+'/KARAOKE.ass';srt=prefix+'/LEGENDA.srt'
        assets[thumb]=image;assets[sub]=ass;assets[srt]=b'1\n00:00:00,000 --> 00:00:01,000\nTeste\n'
        clips.append({'id':cid,'source_start':a,'source_end':b,'duration_seconds':round(b-a,3),
                      'title':'Teste de cinema do video', 'thumbnail':thumb,'caption_ass':sub,'caption_srt':srt})
    def js(name,value):assets[name]=json.dumps(value,ensure_ascii=False).encode('utf-8')
    js('EXECUTION_PLAN.json',{'source_sha256':sha,'source_video_id':'aUgESZsOGmY','source_duration_seconds':4.,
                              'reels':clips[:1],'stories':clips[1:]})
    js('REELS_EDIT_PLAN.json',{'source_sha256':sha,'clips':[{'id':'REEL_01'}]})
    js('STORIES_SEQUENCIAIS_REVISAR.json',{'source_sha256':sha})
    js('QUALITY_GATES.json',{'original_source_sha256':sha})
    manifest={'files':[{'path':k,'bytes':len(v),'sha256':hashlib.sha256(v).hexdigest()} for k,v in assets.items()]}
    js('MANIFEST_SHA256.json',manifest)
    z=folder/'fixture.zip'
    with ZipFile(z,'w',ZIP_DEFLATED) as out:
        for k,v in assets.items():out.writestr(k,v)
    return z,video

class RealR57ContractTests(unittest.TestCase):
    def test_original_package_integrity_and_counts(self):
        z=CuradoriaPackage(DEMO)
        self.assertEqual(len(z.items('reels')),12)
        self.assertEqual(len(z.items('stories')),60)
        self.assertEqual(len(z.clips),72)
        self.assertEqual(z.source_sha,'f8b424b9fc26c79141fb2288fee3354d5f02c1c773523f87f95b1191252283ea')
        self.assertFalse(z.quality_gates['preview_human_approved'])
        self.assertEqual(z.caption_status('REEL_01')['status'],'ASR_DRAFT_NOT_VERIFIED')


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg + FFprobe necessários')
class SyntheticRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix='ldporto_studio_test_')
        cls.folder=Path(cls.tmp.name)
        cls.archive,cls.media=make_fixture(cls.folder)
        cls.project=Project.create(cls.archive,cls.folder/'project')

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def test_10_untrusted_media_is_rejected(self):
        wrong=self.folder/'incorrect.mp4'
        wrong.write_bytes(b'not same source')
        with self.assertRaisesRegex(ValueError,'SHA256'):self.project.set_media(wrong)
        self.assertFalse(self.project.state['media_path'])

    def test_20_approval_requires_preview(self):
        with self.assertRaisesRegex(ValueError,'prévia'):self.project.approve('REEL_01',human_reviewed=True,
            verified_audio=True,verified_camera=True)
        with self.assertRaisesRegex(ValueError,'Final bloqueado'):render_item(self.project,'REEL_01',preview=False)

    def test_30_verify_original(self):
        info=self.project.set_media(self.media)
        self.assertTrue(info['has_audio'])
        self.assertEqual(info['width'],640)

    def test_40_caption_review_gate(self):
        with self.assertRaisesRegex(ValueError,'não revisadas'):
            self.project.update('REEL_01',subtitles=True,captions_verified=False)

    def test_50_render_preview(self):
        self.project.update('REEL_01',title_overlay=True,layout='preserve',subtitles=False)
        file,report=render_item(self.project,'REEL_01',preview=True)
        self.assertTrue(file.is_file())
        self.assertEqual(report['media']['width'],540)
        self.assertEqual(report['media']['height'],960)
        self.assertTrue(report['media']['has_audio'])
        self.assertEqual(self.project.status('REEL_01'),'PREVIEW_READY_REVIEW')

    def test_60_review_approve_final(self):
        self.project.update('REEL_01',audio_reviewed=True,camera_reviewed=True)
        self.assertTrue(self.project.preview_record('REEL_01'))
        with self.assertRaisesRegex(ValueError,'confirme áudio'):
            self.project.approve('REEL_01',human_reviewed=True,verified_audio=True,verified_camera=False)
        self.project.approve('REEL_01',human_reviewed=True,verified_audio=True,verified_camera=True)
        self.assertTrue(self.project.approval_matches('REEL_01'))
        final,report=render_item(self.project,'REEL_01',preview=False)
        self.assertEqual(probe_media(final)['width'],1080)
        self.assertEqual(probe_media(final)['height'],1920)
        self.assertFalse(report['publication_ready'])
        self.assertEqual(self.project.status('REEL_01'),'FINAL_READY_REVIEW_RIGHTS')

    def test_70_changing_video_settings_invalidates_approval(self):
        self.project.update('REEL_01',title='Novo título de teste')
        self.assertFalse(self.project.approval_matches('REEL_01'))
        with self.assertRaisesRegex(ValueError,'Final bloqueado'):
            render_item(self.project,'REEL_01',preview=False)

    def test_80_stories_fixed_boundaries_and_assets(self):
        with self.assertRaisesRegex(ValueError,'Stories preservam intervalo'):
            self.project.update('STORY_01',source_end=3.)
        folder,count=extract_editorial_assets(self.project)
        self.assertEqual(count,2)
        self.assertTrue((folder/'stories'/'STORY_01'/'CAPA.png').is_file())


    def test_90_manual_crop_story_preview(self):
        self.project.update('STORY_01',layout='center_crop',center_x=.25,title_overlay=False)
        file,report=render_item(self.project,'STORY_01',preview=True)
        self.assertEqual(report['media']['width'],540)
        self.assertEqual(report['media']['height'],960)
        self.assertEqual(report['mode'],'center_crop')

    def test_95_explicitly_reviewed_karaoke_ass(self):
        self.project.update('REEL_01',subtitles=True,captions_verified=True,title_overlay=True)
        output,report=render_item(self.project,'REEL_01',preview=True)
        self.assertTrue(report['captions_included'])
        self.assertTrue((output.parent/'captions.ass').is_file())
        self.assertEqual(probe_media(output)['width'],540)

    def test_98_manifest_and_cover(self):
        from ldporto_studio.rendering import create_cover_from_frame
        cover=self.folder/'alternate_cover.png'
        create_cover_from_frame(self.project,'REEL_01',cover)
        self.assertTrue(cover.is_file())
        self.assertGreater(cover.stat().st_size,1000)
        manifest=self.project.export_manifest()
        self.assertEqual(len(manifest['items']),2)
        self.assertTrue((self.project.dir/'EXPORT_MANIFEST.json').is_file())
        self.assertFalse(manifest['items'][0]['publication_ready'])


    def test_99_corrected_ass_replaces_draft_only_after_review(self):
        clip=self.project.package.clips['REEL_01']
        target=self.folder/'corrigida.ass'
        target.write_bytes(self.project.package.data(clip.caption_ass).replace(b'Teste de legenda',b'Teste revisado no audio'))
        imported=self.project.import_caption('REEL_01',target)
        self.assertTrue(imported.is_file())
        self.assertFalse(self.project.settings('REEL_01')['subtitles'])
        self.assertFalse(self.project.settings('REEL_01')['captions_verified'])
        with self.assertRaisesRegex(ValueError,'não revisadas'):
            self.project.update('REEL_01',subtitles=True)
        self.project.update('REEL_01',captions_verified=True,subtitles=True)
        file,report=render_item(self.project,'REEL_01',preview=True)
        from ldporto_studio.subtitle_style import make_yellow_ass
        self.assertEqual((file.parent/'captions.ass').read_bytes(),
                         make_yellow_ass(target.read_bytes()))
        self.assertEqual(self.project.caption_payload('REEL_01'),target.read_bytes(),
                         'Imported ASS original must never be overwritten')
        self.assertEqual(report['caption_presentation']['preset'],
                         'YELLOW_HIGH_CONTRAST_V1')
        self.assertTrue(report['captions_included'])

    def test_zz_reject_manifest_tampering(self):
        fake=self.folder/'corrupted.zip'
        with ZipFile(self.archive) as initial, ZipFile(fake,'w',ZIP_DEFLATED) as altered:
            for name in initial.namelist():
                content=initial.read(name)
                if name=='REELS/REEL_01/LEGENDA.srt':content+=b'modified after signature'
                altered.writestr(name,content)
        with self.assertRaisesRegex(ValueError,'SHA256 divergente'):
            CuradoriaPackage(fake)


if __name__=='__main__':unittest.main()
