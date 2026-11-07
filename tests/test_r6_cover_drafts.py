"""R6 cover draft gate: exact Analyzer source and isolated review-only PNG frames."""
from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from PIL import Image

from ldporto_studio.core import sha256_file as actual_sha256_file
from ldporto_studio.r6_review import read_analyzer_review, export_editorial_draft
from ldporto_studio.r6_story_timeline import export_story_proposal
from ldporto_studio.r6_cover_drafts import (
    COVER_WIDTH, COVER_HEIGHT, prepare_cover_drafts, export_cover_drafts)
from test_r6_review import make_valid_r6_delivery


class R6CoverDraftTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix='r6_covers_')
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.inbox=self.root/'input'/'analyzer'/'VIDEO123'/'R6'
        self.original_zip=make_valid_r6_delivery(self.inbox)
        source_review=read_analyzer_review(self.inbox)
        self.expected=source_review['source']['source_sha256']
        self.draft=export_editorial_draft(
            source_review,['CAND_001'],
            destination_root=self.root/'output'/'scripts')
        self.proposal=export_story_proposal(
            self.inbox,self.draft,destination_root=self.root/'output'/'story')
        self.video=self.root/'source.mp4'
        self.video.write_bytes(b'fake mp4 bytes: do not decode in unit tests')
        self.out=self.root/'output'/'r6_covers'
        self.ffmpeg_calls=[]

    def _hash(self, path):
        if Path(path).resolve()==self.video.resolve():
            return self.expected
        return actual_sha256_file(path)

    def _fake_ffmpeg(self, args, **kwargs):
        path=Path(args[-1])
        self.ffmpeg_calls.append(args)
        with Image.new('RGB',(COVER_WIDTH,COVER_HEIGHT),'#657891') as image:
            image.save(path,'PNG')
        return SimpleNamespace(returncode=0,stderr='')

    def _mocks(self, ffmpeg=None):
        from contextlib import ExitStack
        stack=ExitStack()
        stack.enter_context(patch('ldporto_studio.r6_cover_drafts.sha256_file',
                                  side_effect=self._hash))
        stack.enter_context(patch('ldporto_studio.r6_cover_drafts.probe_media',
                                  return_value={'has_video':True,
                                                'duration':120.0,
                                                'width':1920,'height':1080}))
        stack.enter_context(patch('ldporto_studio.r6_cover_drafts.binaries',
                                  return_value=('ffmpeg','ffprobe')))
        stack.enter_context(patch('ldporto_studio.r6_cover_drafts.subprocess.run',
                                  side_effect=ffmpeg or self._fake_ffmpeg))
        return stack

    def _render(self, *, kind='all', confirm=True, output=None):
        return export_cover_drafts(
            self.inbox,self.draft,self.proposal,self.video,
            kind=kind,confirm_review_only=confirm,
            destination_root=output or self.out)

    def test_prepare_lists_exact_source_midpoint_without_decoding_frames(self):
        with self._mocks():
            plan=prepare_cover_drafts(
                self.inbox,self.draft,self.proposal,self.video)
        self.assertEqual(plan['clip_count'],3)
        self.assertEqual([x['id'] for x in plan['clips']],
                         ['REEL_01','STORY_01','STORY_02'])
        self.assertTrue(all(x['source_start'] < x['frame_timestamp'] < x['source_end']
                            for x in plan['clips']))
        self.assertEqual(plan['source_sha256'],self.expected)
        self.assertFalse(plan['human_approved'])
        self.assertFalse(plan['render_executed'])
        self.assertEqual(self.ffmpeg_calls,[])
        self.assertFalse(self.out.exists())

    def test_real_source_hash_mismatch_blocks_before_ffmpeg(self):
        with patch('ldporto_studio.r6_cover_drafts.probe_media') as probe:
            with self.assertRaisesRegex(ValueError,'SHA256'):
                prepare_cover_drafts(
                    self.inbox,self.draft,self.proposal,self.video)
        probe.assert_not_called()
        self.assertFalse(self.out.exists())

    def test_explicit_confirmation_is_mandatory_to_write(self):
        with self.assertRaisesRegex(ValueError,'confirm-review-only'):
            self._render(confirm=False)
        self.assertFalse(self.out.exists())

    def test_ffmpeg_drafts_are_png_frames_and_never_touch_source_or_project(self):
        original=self.video.read_bytes()
        original_zip=self.original_zip.read_bytes()
        with self._mocks():
            folder=self._render()
        self.assertEqual(len(self.ffmpeg_calls),3)
        report=json.loads((folder/'COVER_DRAFT_MANIFEST.json').read_text(
            encoding='utf-8'))
        self.assertEqual(report['images_created'],3)
        self.assertTrue(report['frame_extraction_executed'])
        self.assertFalse(report['render_executed'])
        self.assertFalse(report['human_approved'])
        self.assertFalse(report['publication_ready'])
        for clip in report['clips']:
            cover=folder/clip['relative_path']
            with Image.open(cover) as image:
                self.assertEqual(image.size,(COVER_WIDTH,COVER_HEIGHT))
                self.assertEqual(image.format,'PNG')
            self.assertEqual(clip['png_sha256'],actual_sha256_file(cover))
        self.assertEqual(self.video.read_bytes(),original)
        self.assertEqual(self.original_zip.read_bytes(),original_zip)
        self.assertFalse((self.root/'output'/'projects').exists())

    def test_repeat_is_idempotent_and_no_new_frames_are_decoded(self):
        with self._mocks():
            original=self._render()
            second=self._render()
        self.assertEqual(original,second)
        self.assertEqual(len(self.ffmpeg_calls),3)
        self.assertEqual(len(list(self.out.rglob('CAPA_RASCUNHO.png'))),3)

    def test_tampered_existing_png_is_not_overwritten(self):
        with self._mocks():
            folder=self._render()
            corrupted=folder/'reels/REEL_01/CAPA_RASCUNHO.png'
            corrupted.write_bytes(b'edited')
            with self.assertRaisesRegex(ValueError,'modificado'):
                self._render()
        self.assertEqual(corrupted.read_bytes(),b'edited')
        self.assertEqual(len(self.ffmpeg_calls),3)

    def test_missing_or_wrong_frame_dimensions_fail_without_publishing(self):
        def incorrect(args, **kwargs):
            target=Path(args[-1])
            with Image.new('RGB',(10,10),'white') as im:
                im.save(target,'PNG')
            return SimpleNamespace(returncode=0,stderr='')
        with self._mocks(ffmpeg=incorrect):
            with self.assertRaisesRegex(ValueError,'dimensões'):
                self._render()
        self.assertFalse(list(self.out.rglob('COVERS_R6_DRAFT_*')))

    def test_failure_from_ffmpeg_never_publishes_a_partial_folder(self):
        def failed(args, **kwargs):
            return SimpleNamespace(returncode=1,stderr='decoder error')
        with self._mocks(ffmpeg=failed):
            with self.assertRaisesRegex(ValueError,'FFmpeg'):
                self._render()
        self.assertFalse(list(self.out.rglob('COVERS_R6_DRAFT_*')))

    def test_only_selected_kind_is_extracted(self):
        with self._mocks():
            folder=self._render(kind='reels')
        report=json.loads((folder/'COVER_DRAFT_MANIFEST.json').read_text(
            encoding='utf-8'))
        self.assertEqual(report['clip_count'],1)
        self.assertEqual(len(self.ffmpeg_calls),1)
        self.assertEqual(report['clips'][0]['kind'],'reels')

    def test_rejects_output_inside_analyzer_inbox_even_with_correct_media(self):
        with self._mocks():
            with self.assertRaisesRegex(ValueError,'sobrepõe'):
                self._render(output=self.inbox/'not_allowed')
        self.assertFalse((self.inbox/'not_allowed').exists())
        self.assertEqual(self.ffmpeg_calls,[])

    def test_cli_is_read_only_by_default_and_explicit_save_requires_confirm(self):
        from ldporto_studio.__main__ import main
        args=['r6-cover-drafts','--inbox',str(self.inbox),
              '--draft',str(self.draft),
              '--story-proposal',str(self.proposal),
              '--media',str(self.video)]
        stdout=StringIO()
        with self._mocks():
            with redirect_stdout(stdout):
                code=main(args)
            self.assertEqual(code,0)
            report=json.loads(stdout.getvalue())
            self.assertEqual(report['clip_count'],3)
            self.assertIsNone(report['saved_covers_dir'])
            self.assertFalse(self.out.exists())
            with self.assertRaisesRegex(ValueError,'confirm-review-only'):
                main(args+['--save'])
        self.assertEqual(self.ffmpeg_calls,[])

    def test_gui_requires_source_picker_and_human_confirmation(self):
        gui=(Path(__file__).resolve().parents[1]/
             'ldporto_studio'/'r6_review_gui.py').read_text(encoding='utf-8')
        self.assertIn('RASCUNHOS DE CAPAS DA FONTE',gui)
        self.assertIn('export_cover_drafts(',gui)
        self.assertIn('confirm_review_only=True',gui)
        self.assertIn('filedialog.askopenfilename(',gui)


if __name__=='__main__':
    unittest.main()
