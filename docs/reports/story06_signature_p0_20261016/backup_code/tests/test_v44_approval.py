import pytest
from ldporto_curator.approval import plan_signature, record_preview, approve_preview, approval_matches


def test_approval_is_bound_to_reviewed_plan_and_file(tmp_path):
    decisions = [{'clip_id': 'SECOND_D1', 'source_start': 1, 'source_end': 41, 'title_text': 'Título',
                  'camera_plan': {'mode': 'crop', 'segments': []}}]
    signature = plan_signature(decisions, {'output': {'width': 1080}})
    preview = tmp_path / 'preview.mp4'
    preview.write_bytes(b'validated-render-fixture')
    with pytest.raises(ValueError):
        approve_preview(tmp_path, signature)
    record_preview(tmp_path, preview, signature)
    approve_preview(tmp_path, signature)
    assert approval_matches(tmp_path, signature)
    assert not approval_matches(tmp_path, plan_signature([{**decisions[0], 'source_end': 42}], {'output': {'width': 1080}}))
    preview.write_bytes(b'changed')
    assert not approval_matches(tmp_path, signature)


def test_reviewed_clip_signature_allows_later_refinement_but_binds_all_edit_bounds():
    rows = [{'clip_id': 'A', 'source_start': 0, 'source_end': 30, 'camera_plan': {'mode': 'crop'}},
            {'clip_id': 'B', 'source_start': 40, 'source_end': 70, 'camera_plan': {'mode': 'full'}}]
    signature = plan_signature(rows, {}, 'A')
    rows[1]['camera_plan'] = {'mode': 'split_screen'}
    assert plan_signature(rows, {}, 'A') == signature
    rows[1]['source_end'] = 71
    assert plan_signature(rows, {}, 'A') != signature
    rows[1]['source_end'] = 70
    rows[0]['camera_plan'] = {'mode': 'full'}
    assert plan_signature(rows, {}, 'A') != signature


def test_title_style_configuration_changes_invalidate_preview_approval():
    rows = [{'clip_id':'A','source_start':0,'source_end':30,'camera_plan':{}}]
    assert plan_signature(rows, {'title':{'duration':3.2}}) != plan_signature(rows, {'title':{'duration':5.}})
