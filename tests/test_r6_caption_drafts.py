"""Real source-ASR slicing into review-only SRT/ASS; no automatic approval."""
from __future__ import annotations

from contextlib import redirect_stdout
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZIP_DEFLATED, ZipFile

from ldporto_studio.core import sha256_file
from ldporto_studio.r6_review import export_editorial_draft, read_analyzer_review
from ldporto_studio.r6_story_timeline import export_story_proposal
from ldporto_studio.r6_caption_drafts import (
    parse_original_srt, prepare_caption_drafts, export_caption_drafts)
from test_r6_review import make_valid_r6_delivery


class R6CaptionDraftTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix='ldporto_r6_caption_')
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.inbox=self.root/'input'/'analyzer'/'VIDEO123'/'R6'
        self.zip=make_valid_r6_delivery(self.inbox)
        self.output=self.root/'output'/'captions'

    def _add_srt(self, text=None):
        if text is None:
            text=(
                '1\n00:00:11,500 --> 00:00:12,500\n'
                'Primeira fala de teste\n\n'
                '2\n00:00:20,000 --> 00:00:21,000\n'
                'Segunda fala\n\n'
                '3\n00:01:00,000 --> 00:01:01,000\n'
                'Última fala\n'
            )
        with ZipFile(self.zip) as source:
            payloads={name:source.read(name) for name in source.namelist()}
        payloads['transcript/transcript.srt']=text.encode('utf-8')
        manifest=json.loads(payloads['SECOND_CURATION_MANIFEST.json'])
        manifest['files']=[
            {'path':name,'bytes':len(data),'sha256':sha256(data).hexdigest()}
            for name,data in payloads.items() if name!='SECOND_CURATION_MANIFEST.json']
        payloads['SECOND_CURATION_MANIFEST.json']=json.dumps(
            manifest,sort_keys=True).encode('utf-8')
        with ZipFile(self.zip,'w',ZIP_DEFLATED) as archive:
            for name,blob in payloads.items():
                archive.writestr(name,blob)
        receipt_path=self.inbox/'ANALYZER_TO_CURATOR_HANDOFF.json'
        receipt=json.loads(receipt_path.read_text(encoding='utf-8'))
        receipt['zip']['bytes']=self.zip.stat().st_size
        receipt['zip']['sha256']=sha256_file(self.zip)
        receipt_path.write_text(json.dumps(receipt),encoding='utf-8')

    def _plan(self):
        review=read_analyzer_review(self.inbox)
        draft=export_editorial_draft(
            review,['CAND_001'],destination_root=self.root/'output'/'scripts')
        proposal=export_story_proposal(
            self.inbox,draft,destination_root=self.root/'output'/'story_plans')
        return draft,proposal

    def test_rebases_real_asr_and_clips_boundary_cues(self):
        self._add_srt()
        draft,proposal=self._plan()
        original_sha=sha256_file(self.zip)
        files,report=prepare_caption_drafts(self.inbox,draft,proposal)
        self.assertEqual(report['clips_total'],3)
        self.assertEqual(report['clips_with_draft'],3)
        self.assertEqual(report['original_cue_count'],3)
        reel=files['reels/REEL_01/captions_unverified.srt'].decode('utf-8')
        self.assertIn('00:00:00,000 --> 00:00:00,500',reel)
        self.assertIn('00:00:08,000 --> 00:00:09,000',reel)
        self.assertNotIn('Última fala',reel)
        story=files['stories/STORY_02/captions_unverified.srt'].decode('utf-8')
        self.assertIn('00:00:00,000 --> 00:00:01,000',story)
        self.assertEqual(report['clips'][0]['boundary_clipped_cues'],1)
        self.assertFalse(report['captions_verified'])
        self.assertFalse(report['human_approved'])
        self.assertEqual(original_sha,sha256_file(self.zip))
        self.assertFalse(self.output.exists())

    def test_generated_ass_is_plain_style_and_contains_only_source_words(self):
        self._add_srt()
        draft,proposal=self._plan()
        files,report=prepare_caption_drafts(self.inbox,draft,proposal)
        ass=files['reels/REEL_01/captions_unverified.ass'].decode('utf-8')
        self.assertIn('[Script Info]',ass)
        self.assertIn('[Events]',ass)
        self.assertIn('Dialogue: 0,0:00:00.00,0:00:00.50',ass)
        self.assertIn('Primeira fala de teste',ass)
        self.assertNotIn('Karaoke',ass)
        self.assertFalse(report['r57_import_ready'])

    def test_idempotent_save_isolated_from_originals(self):
        self._add_srt()
        draft,proposal=self._plan()
        inputs={file:sha256_file(file) for file in (self.zip,draft,proposal)}
        a=export_caption_drafts(self.inbox,draft,proposal,destination_root=self.output)
        b=export_caption_drafts(self.inbox,draft,proposal,destination_root=self.output)
        self.assertEqual(a,b)
        self.assertEqual(inputs,{file:sha256_file(file) for file in inputs})
        self.assertTrue((a/'CAPTION_DRAFT_MANIFEST.json').is_file())
        self.assertFalse(list(self.output.rglob('*.mp4')))
        self.assertFalse(list(self.output.rglob('*.zip')))
        self.assertFalse((self.root/'output'/'projects').exists())

    def test_modified_previous_draft_cannot_be_silently_overwritten(self):
        self._add_srt()
        draft,proposal=self._plan()
        folder=export_caption_drafts(self.inbox,draft,proposal,destination_root=self.output)
        tampered=folder/'reels/REEL_01/captions_unverified.srt'
        tampered.write_text('modified by user',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'modificada'):
            export_caption_drafts(self.inbox,draft,proposal,destination_root=self.output)
        self.assertEqual(tampered.read_text(encoding='utf-8'),'modified by user')

    def test_without_source_srt_reports_missing_and_does_not_generate_blanks(self):
        draft,proposal=self._plan()
        files,report=prepare_caption_drafts(self.inbox,draft,proposal)
        self.assertEqual(files,{})
        self.assertEqual(report['status'],'SOURCE_SRT_NOT_PRESENT')
        self.assertEqual(report['clips_without_cues'],3)
        with self.assertRaisesRegex(ValueError,'Nenhuma legenda'):
            export_caption_drafts(self.inbox,draft,proposal,destination_root=self.output)
        self.assertFalse(self.output.exists())

    def test_malformed_or_out_of_range_srt_rejected_before_any_write(self):
        for invalid in (
            '1\nnot a timestamp\nTexto\n',
            '1\n00:00:12,000 --> 00:00:11,000\nTexto\n',
            '1\n00:03:00,000 --> 00:03:01,000\nFora da fonte\n',
        ):
            self._add_srt(invalid)
            draft,proposal=self._plan()
            with self.assertRaises(ValueError):
                export_caption_drafts(self.inbox,draft,proposal,destination_root=self.output)
            self.assertFalse(self.output.exists())

    def test_existing_zip_tampering_is_refused(self):
        self._add_srt()
        draft,proposal=self._plan()
        self.zip.write_bytes(self.zip.read_bytes()+b'changed')
        with self.assertRaises(ValueError):
            export_caption_drafts(self.inbox,draft,proposal,destination_root=self.output)

    def test_relative_paths_and_speech_preserved_even_for_multiline(self):
        self._add_srt(
            '1\r\n00:00:12,000 --> 00:00:13,000\r\n'
            'Primeira linha\r\nSegunda linha\r\n')
        draft,proposal=self._plan()
        files,report=prepare_caption_drafts(self.inbox,draft,proposal)
        reel=files['reels/REEL_01/captions_unverified.srt'].decode('utf-8')
        self.assertIn('Primeira linha\nSegunda linha',reel)
        ass=files['reels/REEL_01/captions_unverified.ass'].decode('utf-8')
        self.assertIn(r'Primeira linha\NSegunda linha',ass)
        self.assertGreater(report['clips_without_cues'],0)

    def test_cli_is_read_only_by_default_and_rejects_unsafe_destinations(self):
        from ldporto_studio.__main__ import main
        self._add_srt()
        draft,proposal=self._plan()
        command=['r6-caption-drafts','--inbox',str(self.inbox),'--draft',str(draft),
                 '--story-proposal',str(proposal)]
        output=StringIO()
        with redirect_stdout(output):
            status=main(command)
        self.assertEqual(status,0)
        data=json.loads(output.getvalue())
        self.assertEqual(data['clips_with_draft'],3)
        self.assertIsNone(data['saved_drafts_dir'])
        self.assertFalse(self.output.exists())
        with self.assertRaisesRegex(ValueError,'sobrepõe'):
            export_caption_drafts(
                self.inbox,draft,proposal,destination_root=self.inbox)

    def test_gui_never_pretends_caption_approval(self):
        gui=(Path(__file__).resolve().parents[1]/
             'ldporto_studio'/'r6_review_gui.py').read_text(encoding='utf-8')
        self.assertIn('RASCUNHOS DE LEGENDAS ASR',gui)
        self.assertIn('export_caption_drafts(',gui)
        self.assertIn('self.last_story_proposal_path is None',gui)


if __name__=='__main__':
    unittest.main()
