"""Consolidate proven R6 cover/ASR bytes for preview without manufacturing approval."""
from __future__ import annotations

from contextlib import ExitStack, redirect_stdout
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from zipfile import ZIP_DEFLATED, ZipFile

from PIL import Image

from ldporto_studio.core import sha256_file
from ldporto_studio.r6_review import read_analyzer_review, export_editorial_draft
from ldporto_studio.r6_story_timeline import export_story_proposal
from ldporto_studio.r6_cover_drafts import export_cover_drafts
from ldporto_studio.r6_caption_drafts import export_caption_drafts
from ldporto_studio.r6_asset_bindings import audit_asset_bindings
from ldporto_studio.r6_asset_staging import (
    prepare_asset_staging, save_asset_staging,
    BINDINGS_NAME, MANIFEST_NAME)
from test_r6_review import make_valid_r6_delivery


class R6AssetStagingTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory(prefix='ldporto_stage_')
        self.addCleanup(t.cleanup)
        self.root=Path(t.name)
        self.inbox=self.root/'input'/'analyzer'/'VIDEO123'/'RUN1'
        self.zip=make_valid_r6_delivery(self.inbox)
        self.media=self.root/'original.mp4'
        self.media.write_bytes(b'SYNTHETIC ONLY: decoding is always mocked')
        self.output=self.root/'output'/'r6_asset_stage'
        self.covers_root=self.root/'output'/'covers'
        self.captions_root=self.root/'output'/'captions'
        self.calls=[]

    def _add_source_asr(self):
        with ZipFile(self.zip) as archive:
            records={name:archive.read(name) for name in archive.namelist()}
        records['transcript/transcript.srt']=(
            '1\n00:00:11,500 --> 00:00:12,500\n'
            'Primeira fala\n\n'
            '2\n00:01:00,000 --> 00:01:01,000\n'
            'Segunda fala\n').encode('utf-8')
        manifest=json.loads(records['SECOND_CURATION_MANIFEST.json'])
        manifest['files']=[
            {'path':name, 'bytes':len(data), 'sha256':sha256(data).hexdigest()}
            for name,data in records.items() if name!='SECOND_CURATION_MANIFEST.json'
        ]
        records['SECOND_CURATION_MANIFEST.json']=json.dumps(manifest).encode('utf-8')
        with ZipFile(self.zip,'w',ZIP_DEFLATED) as archive:
            for name,data in records.items():
                archive.writestr(name,data)
        receipt_path=self.inbox/'ANALYZER_TO_CURATOR_HANDOFF.json'
        receipt=json.loads(receipt_path.read_text(encoding='utf-8'))
        receipt['zip']['bytes']=self.zip.stat().st_size
        receipt['zip']['sha256']=sha256_file(self.zip)
        receipt_path.write_text(json.dumps(receipt),encoding='utf-8')

    def _plan(self):
        review=read_analyzer_review(self.inbox)
        self.expected_sha=review['source']['source_sha256']
        self.draft=export_editorial_draft(
            review,['CAND_001'],destination_root=self.root/'output'/'scripts')
        self.proposal=export_story_proposal(
            self.inbox,self.draft,destination_root=self.root/'output'/'proposals')

    def _cover_mocks(self):
        stack=ExitStack()
        real_hash=sha256_file
        source_path=self.media.resolve()
        def digest(file):
            if Path(file).resolve() == source_path:
                return self.expected_sha
            return real_hash(file)
        def ffmpeg(command,**kwargs):
            self.calls.append(command)
            with Image.new('RGB',(720,1280),'#8899aa') as image:
                image.save(Path(command[-1]),'PNG')
            return SimpleNamespace(returncode=0,stderr='')
        stack.enter_context(patch('ldporto_studio.r6_cover_drafts.sha256_file',
                                  side_effect=digest))
        stack.enter_context(patch('ldporto_studio.r6_cover_drafts.probe_media',
                                  return_value={'has_video':True,'duration':120.0,
                                                'width':1920,'height':1080}))
        stack.enter_context(patch('ldporto_studio.r6_cover_drafts.binaries',
                                  return_value=('ffmpeg','ffprobe')))
        stack.enter_context(patch('ldporto_studio.r6_cover_drafts.subprocess.run',
                                  side_effect=ffmpeg))
        return stack

    def _source_artifacts(self, *, with_captions=False):
        if with_captions:
            self._add_source_asr()
        self._plan()
        with self._cover_mocks():
            covers=export_cover_drafts(
                self.inbox,self.draft,self.proposal,self.media,
                destination_root=self.covers_root,confirm_review_only=True)
        captions=None
        if with_captions:
            captions=export_caption_drafts(
                self.inbox,self.draft,self.proposal,
                destination_root=self.captions_root)
        return covers,captions

    def _save(self,covers,captions=None,root=None):
        return save_asset_staging(
            self.inbox,self.draft,self.proposal,covers,captions_dir=captions,
            destination_root=root or self.output)

    def test_partial_prefill_preserves_null_captions_and_does_not_write(self):
        covers,_=self._source_artifacts()
        count=len(self.calls)
        report=prepare_asset_staging(self.inbox,self.draft,self.proposal,covers)
        self.assertEqual(report['clip_count'],3)
        self.assertEqual(report['assets_available'],3)
        self.assertEqual(report['assets_required'],9)
        self.assertEqual(len(report['missing_assets']),6)
        self.assertTrue(all(x['assets']['thumbnail'] is not None
                            for x in report['bindings']['clips']))
        self.assertTrue(all(x['assets']['caption_ass'] is None
                            for x in report['bindings']['clips']))
        self.assertEqual(report['status'],'INCOMPLETE_DRAFT_FILES_NO_R57_ZIP')
        self.assertFalse(report['publication_ready'])
        self.assertFalse(report['r57_import_ready'])
        self.assertEqual(len(self.calls),count)
        self.assertFalse(self.output.exists())

    def test_complete_prefill_copies_nine_existing_files_no_fake_approvals(self):
        covers,captions=self._source_artifacts(with_captions=True)
        sha_before={p:sha256_file(p) for p in (self.zip,self.draft,self.proposal)}
        report=prepare_asset_staging(
            self.inbox,self.draft,self.proposal,covers,captions_dir=captions)
        self.assertEqual(report['assets_available'],9)
        self.assertEqual(report['missing_assets'],[])
        saved=self._save(covers,captions)
        self.assertTrue((saved/BINDINGS_NAME).is_file())
        self.assertTrue((saved/MANIFEST_NAME).is_file())
        check=audit_asset_bindings(
            self.inbox,self.draft,self.proposal,saved/BINDINGS_NAME,saved)
        self.assertEqual(check['assets_verified'],9)
        self.assertFalse(check['r57_import_ready'])
        self.assertFalse(check['human_approved'])
        self.assertFalse(report['captions_verified'])
        self.assertFalse((self.root/'output'/'projects').exists())
        self.assertFalse(list(saved.rglob('*.mp4')))
        self.assertFalse(list(saved.rglob('*.zip')))
        self.assertEqual(sha_before,{p:sha256_file(p) for p in sha_before})

    def test_save_idempotence_never_reexecutes_ffmpeg(self):
        covers,captions=self._source_artifacts(with_captions=True)
        before=len(self.calls)
        a=self._save(covers,captions)
        b=self._save(covers,captions)
        self.assertEqual(a,b)
        self.assertEqual(before,len(self.calls))
        self.assertEqual(len(list(self.output.rglob('ASSETS_R6_STAGING_*'))),1)

    def test_original_cover_tampering_is_rejected_before_copy(self):
        covers,_=self._source_artifacts()
        cover=covers/'reels/REEL_01/CAPA_RASCUNHO.png'
        cover.write_bytes(b'changed original')
        with self.assertRaises(ValueError):
            self._save(covers)
        self.assertFalse(self.output.exists())

    def test_original_caption_tampering_is_rejected_before_copy(self):
        covers,captions=self._source_artifacts(with_captions=True)
        subtitle=captions/'reels/REEL_01/captions_unverified.srt'
        subtitle.write_text('changed',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'mudou'):
            self._save(covers,captions)
        self.assertFalse(self.output.exists())

    def test_existing_staging_change_is_preserved_and_not_overwritten(self):
        covers,_=self._source_artifacts()
        folder=self._save(covers)
        png=folder/'reels/REEL_01/CAPA_RASCUNHO.png'
        png.write_bytes(b'human modified file')
        with self.assertRaisesRegex(ValueError,'mudou'):
            self._save(covers)
        self.assertEqual(png.read_bytes(),b'human modified file')

    def test_mismatched_r6_zip_or_reel_selection_cannot_prefill(self):
        covers,_=self._source_artifacts()
        self.zip.write_bytes(self.zip.read_bytes()+b'different original handoff')
        with self.assertRaises(ValueError):
            prepare_asset_staging(self.inbox,self.draft,self.proposal,covers)
        self.assertFalse(self.output.exists())

    def test_destination_over_original_inbox_is_refused(self):
        covers,_=self._source_artifacts()
        unsafe=self.inbox/'unsafe_output'
        with self.assertRaisesRegex(ValueError,'sobrepõe'):
            self._save(covers,root=unsafe)
        self.assertFalse(unsafe.exists())

    def test_cli_default_preview_only_and_gui_exposes_integration(self):
        from ldporto_studio.__main__ import main
        covers,_=self._source_artifacts()
        args=['r6-assets-prefill','--inbox',str(self.inbox),'--draft',str(self.draft),
              '--story-proposal',str(self.proposal),'--covers-dir',str(covers)]
        buf=StringIO()
        with redirect_stdout(buf):
            code=main(args)
        self.assertEqual(code,0)
        result=json.loads(buf.getvalue())
        self.assertEqual(result['assets_available'],3)
        self.assertIsNone(result['saved_staging_dir'])
        self.assertFalse(result['human_approved'])
        self.assertFalse(self.output.exists())
        gui=(Path(__file__).resolve().parents[1] /
             'ldporto_studio'/'r6_review_gui.py').read_text(encoding='utf-8')
        self.assertIn('PREENCHER ASSETS COM RASCUNHOS',gui)
        self.assertIn('save_asset_staging(',gui)
        self.assertIn('R6_ASSET_BINDINGS_DRAFT.json',gui)


if __name__=='__main__':
    unittest.main()
