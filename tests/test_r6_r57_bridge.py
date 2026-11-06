"""R6 -> R57 readiness bridge: only real selected R6 data; never fake assets."""
from __future__ import annotations

from contextlib import redirect_stdout
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from ldporto_studio.__main__ import main
from ldporto_studio.r6_r57_bridge import prepare_r57_bridge, export_r57_bridge
from ldporto_studio.r6_review import export_editorial_draft, read_analyzer_review
from test_r6_review import make_valid_r6_delivery


class R6R57BridgeTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix='ldporto_r6_r57_bridge_')
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.inbox=self.root/'input'/'analyzer'/'VIDEO123'/'RUN_1'
        self.archive=make_valid_r6_delivery(self.inbox)
        self.review=read_analyzer_review(self.inbox)
        self.draft=export_editorial_draft(
            self.review,['CAND_001'],
            overrides={'CAND_001':{'title':'TÍTULO PROPOSTO','layout':'preserve'}},
            destination_root=self.root/'output'/'scripts')

    def test_requires_real_selection_and_never_invents_stories(self):
        before_zip=sha256(self.archive.read_bytes()).hexdigest()
        before_draft=sha256(self.draft.read_bytes()).hexdigest()
        plan=prepare_r57_bridge(self.inbox,self.draft)
        self.assertEqual(plan['provenance']['source_zip_sha256'],before_zip)
        self.assertEqual(plan['provenance']['r6_draft_sha256'],before_draft)
        self.assertEqual(plan['r57_expected_contract']['story_count_created'],0)
        self.assertEqual(plan['r57_story_slots'],[])
        self.assertEqual(plan['r57_expected_contract']['reel_count'],1)
        row=plan['r57_reel_slots'][0]
        self.assertEqual(row['r6_candidate_id'],'CAND_001')
        self.assertEqual(row['id'],'REEL_01')
        self.assertEqual(row['source_start'],12.0)
        self.assertEqual(row['source_end'],28.0)
        self.assertEqual(row['title_for_review'],'TÍTULO PROPOSTO')
        self.assertEqual(row['assets_required_not_generated']['thumbnail'],'REELS/REEL_01/CAPA.png')
        self.assertIn('R57_STORIES_CONTIGUOUS_FULL_SOURCE_TIMELINE_NOT_PROVIDED',
                      plan['blocking_reasons'])
        for key in ('human_approved','r57_import_ready','r57_zip_generated',
                    'render_ready','publication_ready','contains_media'):
            self.assertIs(plan[key],False)
        self.assertEqual(sha256(self.archive.read_bytes()).hexdigest(),before_zip)
        self.assertEqual(sha256(self.draft.read_bytes()).hexdigest(),before_draft)
        self.assertFalse((self.root/'output'/'projects').exists())

    def test_export_is_idempotent_and_never_creates_zip_or_project(self):
        location=self.root/'output'/'r6_bridge'
        original=sha256(self.archive.read_bytes()).hexdigest()
        a=export_r57_bridge(self.inbox,self.draft,destination_root=location)
        b=export_r57_bridge(self.inbox,self.draft,destination_root=location)
        self.assertEqual(a,b)
        self.assertEqual(len(list(location.rglob('R6_TO_R57_PLAN_*.json'))),1)
        self.assertFalse(list(location.rglob('*.zip')))
        self.assertFalse((self.root/'output'/'projects').exists())
        exported=json.loads(a.read_text(encoding='utf-8'))
        self.assertFalse(exported['r57_import_ready'])
        self.assertNotIn(str(self.inbox),a.read_text(encoding='utf-8'))
        self.assertNotIn(str(self.draft),a.read_text(encoding='utf-8'))
        self.assertEqual(sha256(self.archive.read_bytes()).hexdigest(),original)

    def test_modified_source_zip_is_refused(self):
        self.archive.write_bytes(self.archive.read_bytes()+b'bad')
        with self.assertRaises(ValueError):
            prepare_r57_bridge(self.inbox,self.draft)

    def test_forged_approval_is_refused(self):
        doc=json.loads(self.draft.read_text(encoding='utf-8'))
        doc['selected_reels'][0]['preview_approved']=True
        self.draft.write_text(json.dumps(doc),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'aprovação indevida'):
            prepare_r57_bridge(self.inbox,self.draft)

    def test_changed_source_timestamps_are_refused(self):
        doc=json.loads(self.draft.read_text(encoding='utf-8'))
        doc['selected_reels'][0]['source_start']=13.0
        self.draft.write_text(json.dumps(doc),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'Timestamp diverge'):
            prepare_r57_bridge(self.inbox,self.draft)

    def test_fake_story_selection_is_refused(self):
        doc=json.loads(self.draft.read_text(encoding='utf-8'))
        doc['selected_stories']=[{'id':'STORY_01','source_start':0,'source_end':120}]
        doc['selected_story_count']=1
        self.draft.write_text(json.dumps(doc),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'Stories não podem ser declarados'):
            prepare_r57_bridge(self.inbox,self.draft)

    def test_wrong_media_sha_never_becomes_exact_source(self):
        media=self.root/'some.mp4'
        media.write_bytes(b'This is not an actual video')
        plan=prepare_r57_bridge(self.inbox,self.draft,media)
        self.assertEqual(plan['media_identity']['status'],
                         'DIFFERENT_SOURCE_SHA256_REVIEW_REQUIRED')
        self.assertIn('ORIGINAL_MEDIA_SHA256_NOT_CONFIRMED_FOR_BRIDGE',
                      plan['blocking_reasons'])
        self.assertFalse(plan['render_ready'])

    def test_cli_inspects_read_only_then_explicit_save(self):
        stdout=StringIO()
        with redirect_stdout(stdout):
            code=main(['r6-r57-plan','--inbox',str(self.inbox),
                       '--draft',str(self.draft)])
        self.assertEqual(code,0)
        info=json.loads(stdout.getvalue())
        self.assertEqual(info['selected_reels'],1)
        self.assertIsNone(info['saved_plan'])
        self.assertFalse(info['r57_import_ready'])
        self.assertFalse((self.root/'output'/'r6_bridge').exists())

    def test_gui_button_exists_only_after_explicit_export(self):
        source=(Path(__file__).resolve().parents[1] /
                'ldporto_studio'/'r6_review_gui.py').read_text(encoding='utf-8')
        self.assertIn('PLANO R6 → R57 (PENDÊNCIAS)',source)
        self.assertIn('if self.last_exported_path is None:',source)
        self.assertIn("self.review['inbox_folder'],self.last_exported_path",source)


if __name__=='__main__':
    unittest.main()
