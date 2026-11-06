"""Technical R6 Story proposals: provenanced, coverage-safe, never approved."""
from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from ldporto_studio.__main__ import main
from ldporto_studio.r6_review import read_analyzer_review, export_editorial_draft
from ldporto_studio.r6_r57_bridge import prepare_r57_bridge, export_r57_bridge
from ldporto_studio.r6_story_timeline import (
    technical_story_windows, make_story_proposal, export_story_proposal,
    validate_story_proposal,
)
from ldporto_studio.r6_workflow import preflight_editorial_draft
from test_r6_review import make_valid_r6_delivery


class R6StoryProposalTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix='ldporto_r6_stories_')
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.inbox=self.root/'input'/'analyzer'/'VIDEO123'/'RUN_1'
        self.archive=make_valid_r6_delivery(self.inbox)
        review=read_analyzer_review(self.inbox)
        self.draft=export_editorial_draft(
            review,['CAND_001'],destination_root=self.root/'output'/'scripts')
        self.review=review
        self.preflight=preflight_editorial_draft(self.draft,self.inbox)

    def _validated(self,path):
        from ldporto_studio.core import sha256_file
        return validate_story_proposal(
            path,preflight=self.preflight,review=self.review,
            draft_sha256=sha256_file(self.draft))

    def _edited(self,transform):
        path=self.root/'edited.json'
        doc=make_story_proposal(self.inbox,self.draft)
        transform(doc)
        path.write_text(json.dumps(doc,ensure_ascii=False),encoding='utf-8')
        return path

    def test_nasa_duration_yields_three_contiguous_technical_windows(self):
        rows=technical_story_windows(158.654)
        self.assertEqual(len(rows),3)
        self.assertEqual(rows[0]['source_start'],0)
        self.assertEqual(rows[-1]['source_end'],158.654)
        self.assertTrue(all(0 < r['duration_seconds'] <= 60 for r in rows))
        self.assertEqual([r['id'] for r in rows],['STORY_01','STORY_02','STORY_03'])
        self.assertTrue(all(r['editorial_review_required'] and not r['approval'] for r in rows))

    def test_valid_source_creates_suggestions_not_editorial_stories(self):
        before=self.archive.read_bytes()
        proposed=make_story_proposal(self.inbox,self.draft)
        self.assertEqual(proposed['proposed_story_count'],2)
        self.assertEqual(proposed['provenance']['analyzer_story_candidate_count'],0)
        self.assertEqual(proposed['story_slots'][0]['source_start'],0)
        self.assertEqual(proposed['story_slots'][-1]['source_end'],120.0)
        self.assertFalse(proposed['human_approved'])
        self.assertFalse(proposed['r57_import_ready'])
        self.assertEqual(self.archive.read_bytes(),before)
        self.assertFalse((self.root/'output'/'projects').exists())

    def test_export_is_idempotent_and_r57_plan_only_consumes_review_pending_proposals(self):
        out=self.root/'output'/'r6_bridge'
        original=self.archive.read_bytes()
        first=export_story_proposal(self.inbox,self.draft,destination_root=out)
        second=export_story_proposal(self.inbox,self.draft,destination_root=out)
        self.assertEqual(first,second)
        windows=self._validated(first)
        self.assertEqual(len(windows),2)
        plan=prepare_r57_bridge(self.inbox,self.draft,story_proposal_path=first)
        self.assertEqual(len(plan['r57_story_boundary_proposals']),2)
        self.assertEqual(plan['r57_expected_contract']['story_count_created'],0)
        self.assertEqual(plan['r57_story_slots'],[])
        self.assertIn('R57_STORY_BOUNDARIES_NOT_EDITORIALLY_REVIEWED',plan['blocking_reasons'])
        self.assertNotIn('R57_STORIES_CONTIGUOUS_FULL_SOURCE_TIMELINE_NOT_PROVIDED',
                         plan['blocking_reasons'])
        self.assertFalse(plan['r57_zip_generated'])
        exported=export_r57_bridge(
            self.inbox,self.draft,destination_root=out,story_proposal_path=first)
        self.assertTrue(exported.is_file())
        self.assertFalse(list(out.rglob('*.zip')))
        self.assertEqual(self.archive.read_bytes(),original)

    def test_gap_or_overlap_is_refused(self):
        # Three 40-second windows leave room to test BOTH errors while
        # staying inside the independent 60-second duration limit.
        for value in (39.0,41.0):
            def modify(doc):
                template=doc['story_slots'][0]
                doc['story_slots']=[]
                for i,(start,end) in enumerate(((0,40),(40,80),(80,120)),1):
                    row=dict(template)
                    row.update(id=f'STORY_{i:02d}',source_start=float(start),
                               source_end=float(end),duration_seconds=float(end-start))
                    doc['story_slots'].append(row)
                doc['story_slots'][1]['source_start']=value
                doc['story_slots'][1]['duration_seconds']=80.0-value
                doc['proposed_story_count']=3
            path=self._edited(modify)
            with self.assertRaisesRegex(ValueError,'gap ou overlap'):
                self._validated(path)

    def test_story_longer_than_60_seconds_is_refused(self):
        path=self._edited(lambda doc: doc['story_slots'][0].update(
            source_end=60.9,duration_seconds=60.9))
        with self.assertRaisesRegex(ValueError,'fora do contrato'):
            self._validated(path)

    def test_forged_story_approval_is_refused(self):
        path=self._edited(lambda doc: doc['story_slots'][0].update(
            approval=True))
        with self.assertRaisesRegex(ValueError,'aprovação indevida'):
            self._validated(path)

    def test_forged_source_or_draft_provenance_is_refused(self):
        for key in ('source_zip_sha256','r6_draft_sha256'):
            path=self._edited(lambda doc: doc['provenance'].update(**{key:'f'*64}))
            with self.assertRaisesRegex(ValueError,'Proveniência'):
                self._validated(path)

    def test_boundaries_out_of_source_are_refused(self):
        path=self._edited(lambda doc: doc['story_slots'][-1].update(
            source_end=125.0,duration_seconds=65.0))
        with self.assertRaisesRegex(ValueError,'fora do contrato'):
            self._validated(path)

    def test_nonfinite_duration_and_too_many_stories_rejected(self):
        for value in (float('nan'),float('inf'),0,False,-1):
            with self.assertRaises(ValueError):
                technical_story_windows(value)
        with self.assertRaisesRegex(ValueError,'Limite de Stories'):
            technical_story_windows(300*60 + 60)

    def test_cli_can_preview_without_creating_any_files(self):
        s=StringIO()
        with redirect_stdout(s):
            exit_code=main(['r6-story-propose','--inbox',str(self.inbox),
                            '--draft',str(self.draft)])
        result=json.loads(s.getvalue())
        self.assertEqual(exit_code,0)
        self.assertEqual(result['proposed_story_count'],2)
        self.assertIsNone(result['saved_proposal'])
        self.assertFalse(result['human_approved'])
        self.assertFalse((self.root/'output'/'r6_bridge').exists())

    def test_readonly_bridge_existing_behavior_remains_blocked_without_story_proposal(self):
        plan=prepare_r57_bridge(self.inbox,self.draft)
        self.assertEqual(plan['r57_story_boundary_proposals'],[])
        self.assertIn('R57_STORIES_CONTIGUOUS_FULL_SOURCE_TIMELINE_NOT_PROVIDED',
                      plan['blocking_reasons'])

    def test_gui_requires_export_before_story_proposal(self):
        text=(Path(__file__).resolve().parents[1] /
              'ldporto_studio'/'r6_review_gui.py').read_text(encoding='utf-8')
        self.assertIn('PROPOR STORIES (SEM APROVAR)',text)
        self.assertIn('if self.last_exported_path is None:',text)
        self.assertIn('story_proposal_path=self.last_story_proposal_path',text)


if __name__=='__main__':
    unittest.main()
