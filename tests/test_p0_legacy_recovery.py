"""Regression evidence for the locally completed zd_wjssZ7mc legacy project.

All writes target pytest temporary copies. Missing source is an explicit result,
never a reason to substitute the existing preview for an original full video.
"""
from copy import deepcopy
from pathlib import Path
import shutil

import pytest

from ldporto_curator.config import load_config
from ldporto_curator.pipeline import Pipeline
from ldporto_curator.source_video import SourceUnavailable
from scripts.validate_render_p0 import (
    EVIDENCE, REAL_PROJECT, ROOT, audit_real_cached_preview, original_hashes,
    read_json, recompute_legacy_signature,
)


@pytest.fixture
def cached_legacy():
    required = [EVIDENCE / 'LEGACY_INPUTS_RECOVERED.json', EVIDENCE / 'P0_BASELINE_AUDIT.json',
                ROOT / 'output/curation' / REAL_PROJECT / 'EDIT_DECISIONS.json']
    if not all(path.is_file() for path in required):
        pytest.skip('Pacote legado real concluído não está incluído neste checkout')
    return read_json(required[0]), read_json(required[1])


@pytest.fixture
def complete_legacy_originals(cached_legacy):
    _, baseline = cached_legacy
    missing = [name for name in baseline['original_files_before']
               if not (ROOT / name).is_file()]
    if missing:
        pytest.skip('Auditoria legada exige originais históricos ausentes: ' + ', '.join(missing))
    return cached_legacy


def test_refined_preview_matches_archived_renderer_identity_and_basic_plan_does_not(cached_legacy):
    recovered, baseline = cached_legacy
    preview = recovered['source_preview']
    settings = baseline['legacy_signatures']['settings_and_renderer_hash_inputs']
    restored = deepcopy(recovered['editorial_plan']['approved_clips'])
    basic = read_json(ROOT / 'output/curation' / REAL_PROJECT / 'EDIT_DECISIONS.json')['approved_clips']
    assert recompute_legacy_signature(restored, settings, preview['reviewed_clip_id']) == preview['plan_signature']
    assert recompute_legacy_signature(basic, settings, preview['reviewed_clip_id']) != preview['plan_signature']
    restored[0]['source_end'] += .01
    assert recompute_legacy_signature(restored, settings, preview['reviewed_clip_id']) != preview['plan_signature']


def test_real_preview_verification_does_not_claim_unavailable_original_or_human_review(complete_legacy_originals):
    recovered, baseline = complete_legacy_originals
    if not Path(recovered['source_preview']['path']).is_file():
        pytest.skip('Preview real não está presente nesta máquina')
    before = original_hashes()
    report = audit_real_cached_preview()
    assert report['preview']['sha256'] == 'd20972bfc76b364b8008354cad396caee7ad5d66be151e5ee664113bcbf4c40a'
    assert report['recovered_segment_count'] == 46
    assert report['words_available'] == 0
    assert report['original_source_sha256'] is None
    assert report['human_approval_claimed'] is False
    assert report['analyzer_accessed'] is False
    video = next(stream for stream in report['preview']['ffprobe']['streams'] if stream['codec_type'] == 'video')
    assert (video['width'], video['height']) == (540, 960)
    assert original_hashes() == before == baseline['original_files_before']


def test_local_legacy_recovery_is_non_destructive_and_missing_source_cannot_be_approved(tmp_path, monkeypatch, complete_legacy_originals):
    recovered, _ = complete_legacy_originals
    original = ROOT / 'output/curation' / REAL_PROJECT
    copied = tmp_path / 'output/curation' / REAL_PROJECT
    shutil.copytree(original, copied)
    before = original_hashes()
    cfg = load_config(ROOT / 'config.yaml')
    cfg['paths'].update(output_root=str(tmp_path / 'output'), analysis_root=str(tmp_path / 'NO_ANALYZER'),
                        source_cache=str(tmp_path / 'NO_SOURCE_CACHE'))
    cfg['source_media'] = {'allow_download': False}

    def forbidden(*_args, **_kwargs):
        raise AssertionError('Recuperação local não deve chamar curadoria nem Analyzer')

    for name in ('curate', 'find_analysis', 'load_bundle'):
        monkeypatch.setattr('ldporto_curator.pipeline.' + name, forbidden)
    bundle, clips, base = Pipeline(cfg, ROOT, log=lambda _: None).recover_legacy(REAL_PROJECT)
    persisted = read_json(base / 'EDIT_DECISIONS.json')
    assert len(clips) == 3
    assert len(bundle.segments) == 46 and bundle.words == []
    assert bundle.captions == bundle.segments
    assert all(not caption.get('words') for caption in bundle.captions)
    assert persisted['approval_state'] == 'NEEDS_REVIEW'
    assert persisted['plan_revision']
    assert not (base / 'FIRST_TEST_APPROVED.flag').exists()
    assert any('legacy_archive' in path.parts for path in (base / 'revisions').rglob('EDIT_DECISIONS.json'))
    # Existing media is a historical preview, not a verified original source.
    with pytest.raises(SourceUnavailable):
        Pipeline(cfg, ROOT, log=lambda _: None).test_one(REAL_PROJECT)
    with pytest.raises((ValueError, RuntimeError)):
        Pipeline(cfg, ROOT, log=lambda _: None).approve_test(REAL_PROJECT)
    assert read_json(base / 'EDIT_DECISIONS.json')['approval_state'] != 'TEST_APPROVED'
    assert original_hashes() == before
    assert recovered['source_original_sha256'] is None
