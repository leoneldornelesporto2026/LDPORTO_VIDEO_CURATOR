"""R6 filtering and preflight tests; no real media or Tk display required."""
from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from ldporto_studio.__main__ import main
from ldporto_studio.r6_review import read_analyzer_review, export_editorial_draft
from ldporto_studio.r6_workflow import (
    FILTERS,preflight_editorial_draft,select_visible_candidates,summarize_review,
)
from test_r6_review import make_valid_r6_delivery


class R6WorkflowTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(prefix='ldporto_r6_workflow_')
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.inbox=self.root/'input'/'analyzer'/'synthetic'/'R6'
        self.archive=make_valid_r6_delivery(self.inbox)
        self.review=read_analyzer_review(self.inbox)

    def test_reports_real_counts_and_not_approval(self):
        result=summarize_review(self.review)
        self.assertEqual(result['candidate_count'],2)
        self.assertEqual(result['story_candidate_count'],0)
        self.assertEqual(result['shortlist_count'],1)
        self.assertEqual(result['titles_to_review'],1)
        self.assertFalse(result['render_ready'])

    def test_filters_do_not_automatically_mark_or_change_input(self):
        before=json.dumps(self.review,sort_keys=True)
        self.assertEqual(len(select_visible_candidates(self.review)),2)
        self.assertEqual(
            [r['candidate_id'] for r in select_visible_candidates(self.review,'shortlist')],
            ['CAND_001'])
        self.assertEqual(
            [r['candidate_id'] for r in select_visible_candidates(self.review,'with_title')],
            ['CAND_001'])
        self.assertEqual(
            [r['candidate_id'] for r in select_visible_candidates(self.review,'duration_15_90')],
            ['CAND_001','CAND_002'])
        self.assertEqual(
            [r['candidate_id'] for r in select_visible_candidates(self.review,'non_commercial')],
            ['CAND_001'])
        self.assertEqual(
            [r['candidate_id'] for r in select_visible_candidates(self.review,query='HOOK ORIGINAL')],
            ['CAND_001'])
        self.assertEqual(before,json.dumps(self.review,sort_keys=True))
        for key in FILTERS:
            self.assertIsInstance(select_visible_candidates(self.review,key),list)

    def test_deduplication_is_display_only(self):
        duplicate=dict(self.review['candidates'][0],candidate_id='CAND_ALT')
        self.review['candidates'].append(duplicate)
        self.review['candidate_count']+=1
        result=summarize_review(self.review)
        self.assertEqual(result['same_interval_alternates'],1)
        self.assertEqual(result['unique_intervals'],2)
        self.assertEqual(len(select_visible_candidates(self.review,collapse_duplicates=True)),2)
        self.assertEqual(len(select_visible_candidates(self.review)),3)

    def test_preflight_binds_original_source_and_preserves_files(self):
        draft=export_editorial_draft(self.review,['CAND_001'],destination_root=self.root/'output'/'scripts')
        source_before=self.archive.read_bytes()
        doc_before=draft.read_bytes()
        result=preflight_editorial_draft(draft,self.inbox)
        self.assertEqual(result['selected_count'],1)
        self.assertEqual(result['media_identity']['status'],'NOT_CHECKED')
        self.assertEqual(result['source_story_candidate_count'],0)
        self.assertFalse(result['render_ready'])
        self.assertFalse(result['publication_ready'])
        self.assertTrue(result['source_preserved'])
        self.assertIn('camera_requires_source_preservation_or_review',result['review_flag_counts'])
        self.assertEqual(self.archive.read_bytes(),source_before)
        self.assertEqual(draft.read_bytes(),doc_before)
        self.assertFalse((self.root/'output'/'projects').exists())

    def test_preflight_detects_noncanonical_timestamp(self):
        draft=export_editorial_draft(self.review,['CAND_001'],destination_root=self.root/'output'/'scripts')
        document=json.loads(draft.read_text(encoding='utf-8'))
        document['selected_reels'][0]['source_start']=1.0
        draft.write_text(json.dumps(document),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'Timestamp diverge'):
            preflight_editorial_draft(draft,self.inbox)

    def test_preflight_never_accepts_forged_approvals(self):
        draft=export_editorial_draft(self.review,['CAND_001'],destination_root=self.root/'output'/'scripts')
        document=json.loads(draft.read_text(encoding='utf-8'))
        document['selected_reels'][0]['audio_reviewed']=True
        draft.write_text(json.dumps(document),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'revisão/aprovação indevida'):
            preflight_editorial_draft(draft,self.inbox)

    def test_preflight_detects_media_different_from_analyzer_hash(self):
        draft=export_editorial_draft(self.review,['CAND_001'],destination_root=self.root/'output'/'scripts')
        media=self.root/'input'/'videos'/'source.mp4'
        media.parent.mkdir(parents=True)
        media.write_bytes(b'fake binary that definitely does not match analyzer')
        result=preflight_editorial_draft(draft,self.inbox,media)
        self.assertEqual(result['media_identity']['matches_analyzer'],False)
        self.assertEqual(result['media_identity']['status'],'DIFFERENT_SOURCE_SHA256_REVIEW_REQUIRED')
        self.assertIn('timestamps_and_audio_may_not_align_with_alternate_media',result['warnings'])
        self.assertFalse(result['render_ready'])

    def test_preflight_warns_on_duplicate_and_overlap(self):
        review=self.review
        row=dict(review['candidates'][0],candidate_id='CAND_ALT',rank=3)
        review['candidates'].append(row)
        review['candidate_count']+=1
        # The local review is deliberately synthetic; export uses explicit IDs.
        draft=export_editorial_draft(review,['CAND_001','CAND_ALT'],
                                    destination_root=self.root/'output'/'scripts')
        # Both synthetic IDs exist in the original ZIP? No. The preflight MUST reject
        # an ID injected after archive inspection, even when the draft looks valid.
        with self.assertRaisesRegex(ValueError,'inexistente/duplicado'):
            preflight_editorial_draft(draft,self.inbox)

    def test_cli_summary_is_compact_and_read_only(self):
        s=StringIO()
        with redirect_stdout(s):
            code=main(['r6-review','--inbox',str(self.inbox),'--summary'])
        result=json.loads(s.getvalue())
        self.assertEqual(code,0)
        self.assertEqual(result['summary']['candidate_count'],2)
        self.assertLessEqual(len(result['first_ten_candidates']),10)
        self.assertTrue(result['no_automatic_selection'])

    def test_cli_preflight_is_no_render(self):
        draft=export_editorial_draft(self.review,['CAND_001'],destination_root=self.root/'output'/'scripts')
        s=StringIO()
        with redirect_stdout(s):
            code=main(['r6-preflight','--inbox',str(self.inbox),'--draft',str(draft)])
        result=json.loads(s.getvalue())
        self.assertEqual(code,0)
        self.assertFalse(result['render_ready'])
        self.assertEqual(result['selected_count'],1)


if __name__=='__main__':
    unittest.main()
