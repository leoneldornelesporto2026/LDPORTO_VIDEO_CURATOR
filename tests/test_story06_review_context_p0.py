"""GUI recovery restores signed settings; every artifact stays in tmp_path."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ldporto_curator import series_review
from ldporto_curator.series_workflow import SeriesProject
from ldporto_curator.utils import write_json
from test_story06_signature_resume_p0 import case, inventory, STORY06


def test_pinned_review_restores_exact_settings_and_callbacks_without_writes(case):
    child = case.recover()
    changed_cfg = deepcopy(case.cfg)
    changed_cfg['render']['audio_lufs'] = -18
    before = inventory(case.root)
    log, progress, cancel = Mock(), Mock(), object()
    loaded, source = series_review._load_review_project(child.directory,
        changed_cfg, case.source, log=log, progress=progress, cancel=cancel)
    assert loaded.cfg == case.cfg
    assert loaded.signature(loaded.episode(STORY06)) == child.episode(STORY06)['preview']['plan_hash']
    assert loaded.log is log and loaded.progress is progress and loaded.cancel is cancel
    assert source == case.source.resolve()
    assert not loaded.episode(STORY06).get('human_approval')
    assert inventory(case.root) == before


def test_legacy_review_restores_source_context_and_requires_exact_signature(case):
    child = case.recover()
    recovery = child.plan['story06_recovery']
    recovery.pop('render_settings')
    recovery.pop('render_settings_sha256')
    child.save()
    gui_cfg = deepcopy(case.cfg)
    gui_cfg.pop('source_media')
    before = inventory(case.root)
    loaded, _ = series_review._load_review_project(child.directory, gui_cfg, case.source)
    assert loaded.cfg == case.cfg
    assert loaded.signature(loaded.episode(STORY06)) == child.episode(STORY06)['preview']['plan_hash']
    gui_cfg['render']['audio_lufs'] = -18
    with pytest.raises(ValueError, match='Assinatura'):
        series_review._load_review_project(child.directory, gui_cfg, case.source)
    assert inventory(case.root) == before


def test_missing_legacy_source_requests_selection_and_preserves_project(case):
    child = case.recover()
    child.plan['story06_recovery'].pop('render_settings')
    child.plan['story06_recovery'].pop('render_settings_sha256')
    child.save()
    cfg = deepcopy(case.cfg)
    cfg.pop('source_media')
    before = inventory(case.root)
    with pytest.raises(ValueError, match='Selecione a mídia original'):
        series_review._load_review_project(child.directory, cfg)
    assert inventory(case.root) == before


def test_active_reel_source_reference_is_verified_before_gui_reuse(case):
    child = case.recover()
    child.plan['story06_recovery'].pop('render_settings')
    child.plan['story06_recovery'].pop('render_settings_sha256')
    cfg = deepcopy(case.cfg)
    output_root = case.root / 'output'
    cfg['paths'] = {'output_root': str(output_root)}
    # This is the exact GUI configuration originally signed by this fixture.
    child.cfg = deepcopy(cfg)
    child.episode(STORY06).pop('preview')
    child.episode(STORY06)['state'] = child.episode(STORY06)['status'] = 'REVIEW_REQUIRED'
    from test_story06_signature_resume_p0 import record_fixture_preview
    record_fixture_preview(child, STORY06)
    cfg.pop('source_media')
    write_json(output_root / 'curation' / 'P0_FIXTURE' / 'EDIT_DECISIONS.json',
               {'source_media_path': str(case.source)})
    loaded, source = series_review._load_review_project(child.directory, cfg)
    assert source == case.source.resolve()
    assert loaded.signature(loaded.episode(STORY06)) == child.episode(STORY06)['preview']['plan_hash']
    wrong_source = case.root / 'wrong.mp4'
    wrong_source.write_bytes(b'not the Analyzer source')
    with pytest.raises(ValueError, match='Fonte SHA256'):
        series_review._load_review_project(child.directory, cfg, wrong_source)


def test_recovery_approval_still_requires_explicit_gui_confirmation(case, monkeypatch):
    child = case.recover()
    loaded, _ = series_review._load_review_project(child.directory, case.cfg, case.source)
    tasks = []
    view = SimpleNamespace(project=loaded, busy=False,
        _selected=lambda: STORY06, _task=tasks.append)
    before = inventory(case.root)
    monkeypatch.setattr(series_review.messagebox, 'askyesno', lambda *a, **k: False)
    series_review.SeriesReview._approve(view)
    assert not tasks and inventory(case.root) == before
    monkeypatch.setattr(series_review.messagebox, 'askyesno', lambda *a, **k: True)
    series_review.SeriesReview._approve(view)
    assert len(tasks) == 1 and inventory(case.root) == before
    tasks[0]()
    assert loaded.episode(STORY06)['human_approval']['preview_approved_by_human'] is True
    assert not case.parent.episode(STORY06).get('human_approval')


def test_regular_project_resume_keeps_gui_configuration(case):
    loaded, source = series_review._load_review_project(case.parent.directory, case.cfg)
    assert isinstance(loaded, SeriesProject) and loaded.cfg == case.cfg
    assert source is None


def test_gui_resume_uses_verified_project_and_pinned_source(case, monkeypatch):
    child = case.recover()
    cfg = deepcopy(case.cfg)
    cfg.pop('source_media')
    cfg['render']['audio_lufs'] = -18
    view = SimpleNamespace(busy=False, cfg=cfg, cancel=object(), events=Mock(),
        project=None, media=Mock(), mode=Mock(), duration=Mock(), status=Mock(), _refresh=Mock())
    view.media.get.return_value = ''
    monkeypatch.setattr(series_review.filedialog, 'askopenfilename',
                        lambda **kwargs: str(child.directory / 'series_index.json'))
    before = inventory(case.root)
    series_review.SeriesReview._resume(view)
    assert view.project.cfg == case.cfg
    assert view.project.cancel is view.cancel
    view.project.progress(.5, 'same callback')
    view.events.put.assert_called_once_with(('progress', (.5, 'same callback')))
    view.media.set.assert_called_once_with(str(case.source.resolve()))
    view._refresh.assert_called_once_with()
    assert inventory(case.root) == before


def test_gui_resume_keeps_previous_project_when_source_is_unavailable(case, monkeypatch):
    child = case.recover()
    child.plan['story06_recovery'].pop('render_settings')
    child.plan['story06_recovery'].pop('render_settings_sha256')
    child.save()
    cfg = deepcopy(case.cfg)
    cfg.pop('source_media')
    previous = object()
    view = SimpleNamespace(busy=False, cfg=cfg, cancel=object(), events=Mock(),
        project=previous, media=Mock(), status=Mock(), _refresh=Mock())
    view.media.get.return_value = ''
    monkeypatch.setattr(series_review.filedialog, 'askopenfilename',
                        lambda **kwargs: str(child.directory / 'series_index.json'))
    error = Mock()
    monkeypatch.setattr(series_review.messagebox, 'showerror', error)
    before = inventory(case.root)
    series_review.SeriesReview._resume(view)
    assert view.project is previous
    assert error.call_count == 1 and not view._refresh.called
    assert 'Selecione a mídia original' in view.status.set.call_args.args[0]
    assert inventory(case.root) == before
