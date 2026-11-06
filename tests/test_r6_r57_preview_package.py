"""R6 -> true R57 preview-draft assembler tests, never publication approval."""
from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from ldporto_studio.core import CuradoriaPackage, Project, sha256_file
from ldporto_studio.r6_review import read_analyzer_review, export_editorial_draft
from ldporto_studio.r6_story_timeline import export_story_proposal
from ldporto_studio.r6_asset_bindings import asset_template
from ldporto_studio.r6_r57_preview_package import (
    prepare_preview_archive, build_preview_archive)
from test_r6_review import make_valid_r6_delivery


class R57PreviewDraftTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='ldporto_r57_preview_draft_')
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.inbox = self.folder/'input'/'analyzer'/'VIDEO123'/'RUN_1'
        self.r6_zip = make_valid_r6_delivery(self.inbox)
        self.draft = export_editorial_draft(
            read_analyzer_review(self.inbox), ['CAND_001'],
            destination_root=self.folder/'output'/'scripts')
        self.proposal = export_story_proposal(
            self.inbox,self.draft,destination_root=self.folder/'output'/'r6_bridge')
        self.assets = self.folder/'assets'
        self.assets.mkdir()
        self.binding = self.folder/'bindings.json'
        self.preview_root = self.folder/'output'/'preview'
        self.create_files()

    def create_files(self):
        template = asset_template(self.inbox, self.draft, self.proposal)
        for row in template['clips']:
            location = self.assets/row['kind']/row['id']
            location.mkdir(parents=True)
            with Image.new('RGB',(20,20),'white') as im:
                im.save(location/'cover.png')
            (location/'real.ass').write_text(
                '[Script Info]\n[Events]\nDialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,Transcript for review\n',
                encoding='utf-8')
            (location/'real.srt').write_text(
                '1\n00:00:00,000 --> 00:00:01,000\nTranscript for review\n',
                encoding='utf-8')
            row['assets'] = {
                'thumbnail': f"{row['kind']}/{row['id']}/cover.png",
                'caption_ass': f"{row['kind']}/{row['id']}/real.ass",
                'caption_srt': f"{row['kind']}/{row['id']}/real.srt",
            }
        self.binding.write_text(json.dumps(template,ensure_ascii=False),encoding='utf-8')

    def _assemble(self):
        return build_preview_archive(
            self.inbox,self.draft,self.proposal,self.binding,self.assets,
            destination_root=self.preview_root,confirm_preview_only=True)

    def test_prepare_only_no_zip_and_source_preserved(self):
        before = sha256_file(self.r6_zip)
        files, summary = prepare_preview_archive(
            self.inbox,self.draft,self.proposal,self.binding,self.assets)
        self.assertEqual(summary['reels'],1)
        self.assertEqual(summary['technical_stories'],2)
        self.assertEqual(summary['asset_files'],9)
        self.assertEqual(len(files),17)  # 3 cuts x 4 entries + 5 R57 root JSONs
        self.assertFalse(summary['human_approved'])
        self.assertFalse(self.preview_root.exists())
        self.assertEqual(sha256_file(self.r6_zip),before)

    def test_true_r57_loader_accepts_preview_draft_and_keeps_review_gates(self):
        result=self._assemble()
        archive=CuradoriaPackage(result['zip_path'])
        self.assertEqual(len(archive.items('reels')),1)
        self.assertEqual(len(archive.items('stories')),2)
        self.assertEqual(archive.source_sha,result['source_sha256'])
        self.assertEqual(archive.caption_status('REEL_01')['status'],
                         'ASR_DRAFT_NOT_VERIFIED')
        self.assertFalse(archive.quality_gates['preview_human_approved'])
        self.assertFalse(archive.quality_gates['story_boundaries_reviewed'])
        self.assertTrue(result['r57_importable_for_preview'])
        self.assertFalse(result['r57_imported'])
        self.assertFalse(result['publication_ready'])
        project=Project.create(result['zip_path'],self.folder/'project')
        self.assertEqual(project.state['project_status'],'REVIEW_REQUIRED')
        self.assertIsNone(project.state['media_path'])
        self.assertFalse(project.state['publication_ready'])

    def test_idempotence_no_overwrite_and_source_integrity(self):
        before={p:sha256_file(p) for p in (self.r6_zip,self.draft,self.proposal,self.binding)}
        first=self._assemble()
        second=self._assemble()
        self.assertEqual(first['zip_path'],second['zip_path'])
        self.assertEqual(first['zip_sha256'],second['zip_sha256'])
        self.assertEqual(before,{p:sha256_file(p) for p in before})
        self.assertEqual(len(list(self.preview_root.rglob('R57_PREVIEW_DRAFT_*.zip'))),1)

    def test_missing_asset_refuses_zip_without_any_output(self):
        doc=json.loads(self.binding.read_text(encoding='utf-8'))
        doc['clips'][0]['assets']['caption_srt']=None
        self.binding.write_text(json.dumps(doc),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'Assets obrigatórios ausentes'):
            self._assemble()
        self.assertFalse(self.preview_root.exists())

    def test_tampering_asset_fails_before_zip(self):
        file=self.assets/'reels'/'REEL_01'/'cover.png'
        file.write_bytes(b'not an image')
        with self.assertRaises(ValueError):
            self._assemble()
        self.assertFalse(self.preview_root.exists())

    def test_preview_confirmation_is_required(self):
        with self.assertRaisesRegex(ValueError,'confirm-preview-only'):
            build_preview_archive(self.inbox,self.draft,self.proposal,
                                  self.binding,self.assets,
                                  destination_root=self.preview_root)
        self.assertFalse(self.preview_root.exists())

    def test_incompatible_r6_receipt_fails_before_zip(self):
        self.r6_zip.write_bytes(self.r6_zip.read_bytes()+b'tamper')
        with self.assertRaises(ValueError):
            self._assemble()
        self.assertFalse(self.preview_root.exists())

    def test_cli_inspection_does_not_save_and_explicit_save_builds_preview_only(self):
        from ldporto_studio.__main__ import main
        output=StringIO()
        args=['r6-r57-preview-package','--inbox',str(self.inbox),
              '--draft',str(self.draft),'--story-proposal',str(self.proposal),
              '--bindings',str(self.binding),'--assets-root',str(self.assets)]
        with redirect_stdout(output):
            code=main(args)
        self.assertEqual(code,0)
        report=json.loads(output.getvalue())
        self.assertEqual(report['asset_files'],9)
        self.assertFalse(report['human_approved'])
        self.assertIsNone(report['zip_path'])
        self.assertFalse(self.preview_root.exists())
        # Explicit save and preview-only confirmation are mandatory for any ZIP.
        with self.assertRaisesRegex(ValueError,'confirm-preview-only'):
            main(args + ['--save'])
        self.assertFalse((self.folder/'output'/'projects').exists())

    def test_asset_from_untrusted_path_is_refused(self):
        doc=json.loads(self.binding.read_text(encoding='utf-8'))
        doc['clips'][0]['assets']['thumbnail']='../outside.png'
        self.binding.write_text(json.dumps(doc),encoding='utf-8')
        with self.assertRaises(ValueError):
            self._assemble()
        self.assertFalse(self.preview_root.exists())


if __name__ == '__main__':
    unittest.main()
