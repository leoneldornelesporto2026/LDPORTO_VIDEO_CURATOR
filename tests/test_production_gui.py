"""Production callbacks reuse V5; all writes use pytest's isolated tmp_path."""
from copy import deepcopy
import json
from pathlib import Path
import queue
import sys
import threading
from types import MethodType, SimpleNamespace
from unittest.mock import Mock

import pytest

from ldporto_curator import gui, series_review


class TkValue:
    def __init__(self, value=''):
        self.value, self.owner = value, threading.get_ident()

    def get(self):
        assert threading.get_ident() == self.owner, 'worker accessed a Tk value'
        return self.value

    def set(self, value):
        assert threading.get_ident() == self.owner, 'worker changed a Tk value'
        self.value = value


def production_project(tmp_path):
    return SimpleNamespace(directory=tmp_path / 'external' / 'project',
        cfg={'render': {'quality': 'QUALITY'}},
        evidence={'source': {'sha256': 'a' * 64, 'duration': 100, 'title': 'Título observado'}},
        plan={'production_import': {'package_path': str(tmp_path / 'input.zip'),
                  'render_settings': {'render': {'quality': 'QUALITY'}}},
              'mode': 'COMBINADO', 'duration_preset': 'auto_under_90'})


def production_view(tmp_path):
    view = SimpleNamespace(busy=False, _closed=False, _task_token=None,
        _production_request=None, _pending_production_media=None,
        _frame_generation=0, cfg={'paths': {'output_root': 'legacy'}, 'render': {'quality': 'QUALITY'}},
        project=production_project(tmp_path), cancel=threading.Event(), events=queue.Queue(),
        production_output=TkValue(str(tmp_path / 'external')), production_library=TkValue(str(tmp_path / 'library')),
        production_handoff=TkValue(''), media=TkValue(''), production_summary=TkValue(),
        mode=TkValue(), duration=TkValue(), status=TkValue(), diagnostic=Mock(), progress={},
        camera_context=TkValue(), _refresh=Mock(), _selected=lambda: 'PIECE_1',
        scheduled=[], tasks=[])
    owner = threading.get_ident()
    def after(delay, callback):
        assert threading.get_ident() == owner
        view.scheduled.append((delay, callback))
    view.after = after
    def schedule(function, **kwargs):
        view.tasks.append((function, kwargs))
    view._task = schedule
    for name in ('_import_production', '_request_production_media', '_production_previews',
                 '_accept_production_import', '_show_project', '_poll', '_choose_media', '_resume',
                 '_apply_visual_crop', '_accept_inspection_frame'):
        setattr(view, name, MethodType(getattr(series_review.SeriesReview, name), view))
    return view


def test_main_import_opens_existing_v5_review_without_pipeline(tmp_path, monkeypatch):
    window = SimpleNamespace(_import_production=Mock(), after=Mock())
    constructor = Mock(return_value=window)
    monkeypatch.setattr(series_review, 'SeriesReview', constructor)
    view = SimpleNamespace(busy=False, rootp=tmp_path, cfg={'unchanged': True}, _sync=Mock())
    monkeypatch.setattr(gui, 'Pipeline', Mock(side_effect=AssertionError('No pipeline during production import')))
    gui.App.open_production_review(view)
    constructor.assert_called_once_with(view, tmp_path, view.cfg)
    window.after.assert_called_once_with(0, window._import_production)
    view.busy = True
    gui.App.open_production_review(view)
    assert constructor.call_count == 1


def test_import_captures_settings_before_worker_and_uses_one_zip(tmp_path, monkeypatch):
    view = production_view(tmp_path)
    received = []
    result = {'production_import': True, 'project': view.project, 'source_path': None, 'summary': {}}
    monkeypatch.setitem(sys.modules, 'ldporto_curator.production_package', SimpleNamespace(
        import_production_package=lambda path, **kwargs: received.append((path, kwargs)) or result))
    series_review.SeriesReview._import_production(view, tmp_path / 'single.zip')
    view.production_output.set('changed')
    view.production_library.set('changed')
    view.cfg['render']['quality'] = 'FAST'
    assert len(view.tasks) == 1 and received == []
    assert view.tasks[0][0]() is result
    path, kwargs = received[0]
    assert path == str(tmp_path / 'single.zip')
    assert kwargs['cfg']['render']['quality'] == 'QUALITY'
    assert kwargs['output_root'] == str(tmp_path / 'external')
    assert kwargs['media_library'] == str(tmp_path / 'library')
    assert kwargs['media_path'] is None and kwargs['handoff_dir'] is None
    assert view.cfg['paths'] == {'output_root': 'legacy'}


def test_missing_media_is_requested_on_tk_then_reimported_with_same_options(tmp_path, monkeypatch):
    view = production_view(tmp_path)
    view._import_production(tmp_path / 'single.zip')
    original = deepcopy(view._production_request)
    view._accept_production_import({'production_import': True, 'project': view.project,
        'source_path': None, 'summary': {'format': 'ANALYZER_NATIVE', 'counts': {'reels': 70, 'stories': 86, 'series': 49}}})
    assert view.media.get() == '' and view._pending_production_media == original
    assert '70' in view.production_summary.get() and '49' in view.production_summary.get()
    assert 'não aprova' in view.production_summary.get()
    owner = threading.get_ident()
    def choose(**kwargs):
        assert threading.get_ident() == owner
        return str(tmp_path / 'chosen.mp4')
    monkeypatch.setattr(series_review.filedialog, 'askopenfilename', choose)
    view._import_production = Mock()
    view._request_production_media()
    view._import_production.assert_called_once_with(str(tmp_path / 'single.zip'),
        media_path=str(tmp_path / 'chosen.mp4'), request=original)


def test_cancel_media_selection_preserves_import_and_pending_state(tmp_path, monkeypatch):
    view = production_view(tmp_path)
    original = view.project
    view._pending_production_media = {'path': 'existing.zip'}
    monkeypatch.setattr(series_review.filedialog, 'askopenfilename', lambda **kwargs: '')
    view._request_production_media()
    assert view.project is original and view.media.get() == '' and view.tasks == []
    assert 'pendente' in view.status.get()


def test_reopened_import_retains_saved_options_for_media_selection(tmp_path):
    view = production_view(tmp_path)
    view.project.plan['production_import']['import_options'] = {'output_root': 'saved-external', 'handoff_dir': 'saved-dossier'}
    view._accept_production_import({'production_import': True, 'project': view.project, 'source_path': None, 'summary': {}})
    assert view._pending_production_media['cfg'] == view.project.cfg
    assert view._pending_production_media['output_root'] == 'saved-external'
    assert view._pending_production_media['handoff_dir'] == 'saved-dossier'


def test_stale_worker_cannot_replace_project_or_unlock_current_operation(tmp_path):
    view = production_view(tmp_path)
    original = view.project
    view.busy, view._task_token = True, 'current'
    view.events.put(('result', {'production_import': True, 'project': object()}, 'stale'))
    view.events.put(('error', 'stale error', 'stale'))
    view.events.put(('done', None, 'stale'))
    view._poll()
    assert view.project is original and view.busy and view._task_token == 'current'
    assert not view._refresh.called


def test_failed_import_delivers_error_on_tk_and_preserves_previous_project(tmp_path, monkeypatch):
    view = production_view(tmp_path)
    original = view.project
    threads, thread_type = [], threading.Thread
    def start_thread(*args, **kwargs):
        thread = thread_type(*args, **kwargs)
        threads.append(thread)
        return thread
    monkeypatch.setattr(series_review.threading, 'Thread', start_thread)
    owner, shown = threading.get_ident(), []
    def show_error(title, text, **kwargs):
        assert threading.get_ident() == owner
        shown.append(text)
    monkeypatch.setattr(series_review.messagebox, 'showerror', show_error)
    def fail():
        assert threading.get_ident() != owner
        raise ValueError('SHA256 de outra mídia')
    series_review.SeriesReview._task(view, fail)
    threads[0].join(5)
    assert not threads[0].is_alive() and shown == []
    view._poll()
    assert shown == ['SHA256 de outra mídia'] and view.project is original and not view.busy


def test_later_render_rebinds_import_callbacks_to_current_operation(tmp_path, monkeypatch):
    from ldporto_curator.series_workflow import SeriesProject
    view = production_view(tmp_path)
    project = SeriesProject(tmp_path / 'project')
    old = Mock()
    project.progress = old
    view.project = project
    targets = []
    monkeypatch.setattr(series_review.threading, 'Thread', lambda **kwargs:
        SimpleNamespace(start=lambda: targets.append(kwargs['target'])))
    token = series_review.SeriesReview._task(view, lambda: project.progress(.5, 'encode atual'))
    targets[0]()
    assert ('progress', (.5, 'encode atual'), token) in list(view.events.queue)
    old.assert_not_called()


def test_load_production_restores_pinned_configuration_without_legacy_rebuild(tmp_path, monkeypatch):
    directory = tmp_path / 'stored'
    directory.mkdir()
    (directory / 'series_index.json').write_text(json.dumps({'production_import': {'schema': 'production'}}), encoding='utf-8')
    media = tmp_path / 'source.mp4'
    media.write_bytes(b'fixture-not-decoded')
    project = production_project(tmp_path)
    project.plan['production_import']['media_reference'] = {'path': str(media), 'state': 'VERIFIED'}
    loader = Mock(return_value=project)
    monkeypatch.setitem(sys.modules, 'ldporto_curator.production_package', SimpleNamespace(load_production_project=loader))
    log, progress, cancel = Mock(), Mock(), threading.Event()
    before = {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    loaded, source = series_review._load_review_project(directory, {'render': {'quality': 'DIFFERENT'}},
        log=log, progress=progress, cancel=cancel)
    assert loaded is project and loaded.cfg == {'render': {'quality': 'QUALITY'}}
    assert source == media.resolve()
    loader.assert_called_once_with(directory, log=log, progress=progress, cancel=cancel)
    assert {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()} == before


def test_production_resume_is_scheduled_and_preserves_current_view_until_loaded(tmp_path, monkeypatch):
    view = production_view(tmp_path)
    original = view.project
    directory = tmp_path / 'stored'
    directory.mkdir()
    (directory / 'series_index.json').write_text(json.dumps({'production_import': {'schema': 'production'}}), encoding='utf-8')
    loaded = production_project(tmp_path)
    monkeypatch.setattr(series_review.filedialog, 'askopenfilename', lambda **kwargs: str(directory / 'series_index.json'))
    monkeypatch.setattr(series_review, '_load_review_project', lambda *args, **kwargs: (loaded, None))
    view._resume()
    assert len(view.tasks) == 1 and view.project is original
    result = view.tasks[0][0]()
    assert result['project'] is loaded and result['production_import']
    assert view.project is original


def test_batch_preview_uses_production_gate_and_captured_project(tmp_path, monkeypatch):
    view = production_view(tmp_path)
    original = view.project
    view.media.set('original.mp4')
    render = Mock(return_value={'rows': [{'status': 'BLOCKED'}, {'status': 'VALIDATED'}]})
    monkeypatch.setitem(sys.modules, 'ldporto_curator.production_package', SimpleNamespace(render_production_previews=render))
    view._production_previews()
    view.project, view.media.value = object(), 'other.mp4'
    result = view.tasks[0][0]()
    assert result['rows'][1]['status'] == 'VALIDATED'
    assert render.call_args.args == (original, 'original.mp4')


def test_camera_timeline_keeps_absolute_and_relative_time_separate():
    episode = {'duration': 10., 'source_start': 100., 'camera_plan': {'mode': 'adaptive_timeline', 'segments': [
        {'start': 0., 'end': 4., 'mode': 'crop', 'target_id': 'UNKNOWN_PERSON_1', 'zoom_start': 1., 'zoom_end': 1.035},
        {'start': 4., 'end': 10., 'mode': 'full_frame_blur', 'reason': 'instrument geometry unavailable'},
    ]}}
    rows = series_review._camera_inspection_rows(episode)
    assert (rows[0]['start'], rows[0]['source_start'], rows[1]['source_end']) == (0., 100., 110.)
    assert rows[0]['target'] == 'UNKNOWN_PERSON_1' and rows[1]['mode'] == 'full_frame_blur'
    assert episode['camera_plan']['segments'][0].get('crop_safe') is None


def test_inspection_pose_uses_renderer_smoothstep_and_zoom_envelope():
    segment = {'start': 2., 'end': 8., 'center_x_start': .3, 'center_x_end': .7,
        'center_y_start': .4, 'center_y_end': .5, 'motion_easing': 'smoothstep',
        'zoom_start': 1., 'zoom_end': 1.04, 'zoom_transition_start': 1., 'zoom_transition_duration': 4.}
    x, y, zoom, _ = series_review._inspection_pose(segment, 5.)
    assert (x, y, zoom) == pytest.approx((.5, .45, 1.02))
    segment['center_x_start'] = float('nan')
    with pytest.raises(ValueError, match='não finita'):
        series_review._inspection_pose(segment, 5.)


def test_inspection_rejects_media_hash_before_starting_decoder(tmp_path, monkeypatch):
    capture = Mock()
    monkeypatch.setitem(sys.modules, 'cv2', SimpleNamespace(VideoCapture=capture))
    project = SimpleNamespace(episode=lambda _: {'source_start': 10., 'source_end': 20.},
        _media=Mock(side_effect=ValueError('SHA256 diferente')))
    with pytest.raises(ValueError, match='SHA256'):
        series_review._read_inspection_frame(project, 'P', tmp_path / 'wrong.mp4', 12.)
    capture.assert_not_called()


def test_inspection_releases_decoder_and_does_not_claim_pts(tmp_path, monkeypatch):
    cap = SimpleNamespace(isOpened=lambda: True, set=Mock(), read=lambda: (True, object()),
        get=lambda _: 12125., release=Mock())
    cv = SimpleNamespace(VideoCapture=lambda _: cap, CAP_PROP_POS_MSEC=0, COLOR_BGR2RGB=1, cvtColor=lambda frame, _: frame)
    monkeypatch.setitem(sys.modules, 'cv2', cv)
    project = SimpleNamespace(episode=lambda _: {'source_start': 10., 'source_end': 20.}, _media=lambda _: tmp_path / 'source.mp4')
    frame = series_review._read_inspection_frame(project, 'P', 'source.mp4', 12.)
    assert frame['timestamp'] == 12.125 and frame['requested'] == 12.
    assert 'PTS' in frame['pts_status'] and 'não homologado' in frame['pts_status']
    cap.release.assert_called_once_with()


def test_old_frame_cannot_cross_project_or_episode(tmp_path):
    view = production_view(tmp_path)
    view._frame_generation = 3
    view.crop_editor = SimpleNamespace(show_frame=Mock())
    view._accept_inspection_frame({'generation': 2})
    view.crop_editor.show_frame.assert_not_called()


@pytest.mark.parametrize('approved,confirmed', [(False, True), (True, False), (True, True)])
def test_manual_camera_edits_use_existing_revision_and_confirmation(tmp_path, monkeypatch, approved, confirmed):
    view = production_view(tmp_path)
    original = view.project
    original.episode = lambda _: {'human_approval': {'human': True} if approved else None}
    original.edit = Mock()
    monkeypatch.setattr(series_review.messagebox, 'askyesno', lambda *args, **kwargs: confirmed)
    points = [{'time': 0., 'x': .5, 'y': .5, 'zoom': 1.}]
    view._apply_visual_crop(points, 'MANUAL_KEYFRAMES', {'manual_apply_allowed': True})
    if approved and not confirmed:
        assert view.tasks == []
        return
    points[0]['x'] = .1
    view.project = object()
    view.tasks[0][0]()
    original.edit.assert_called_once_with('PIECE_1', camera_mode='MANUAL_KEYFRAMES',
        camera_keyframes=[{'time': 0., 'x': .5, 'y': .5, 'zoom': 1.}], confirm_invalidation=True)


def test_unsafe_manual_crop_does_not_schedule_edit(tmp_path):
    view = production_view(tmp_path)
    view._apply_visual_crop([], 'MANUAL_KEYFRAMES', {'manual_apply_allowed': False})
    assert view.tasks == [] and 'bloqueado' in view.status.get()


@pytest.fixture(scope='module')
def hidden_tk_root():
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip('Tk indisponível neste ambiente: ' + str(exc))
    root.withdraw()
    yield root
    root.destroy()


def close_hidden_review(root, review):
    if review is not None:
        review._close()
    # This interpreter belongs only to these hidden tests. Cancel pending player
    # timers whose widgets were destroyed before reusing it for the next review.
    for job in root.tk.call('after', 'info'):
        root.after_cancel(job)


def test_real_tk_review_build_exposes_production_and_existing_visual_editor(tmp_path, hidden_tk_root):
    from tkinter import ttk
    root = hidden_tk_root
    review = None
    try:
        review = series_review.SeriesReview(root, tmp_path,
            {'paths': {'output_root': str(tmp_path / 'legacy')}, 'render': {'prefer_nvenc': False}})
        review.withdraw()
        root.update_idletasks()
        assert 'Câmera por trecho' in [review.tabs.tab(item, 'text') for item in review.tabs.tabs()]
        assert review.crop_editor.model is None
        labels = []
        def visit(widget):
            if isinstance(widget, ttk.Button):
                labels.append(widget.cget('text'))
            for child in widget.winfo_children():
                visit(child)
        visit(review)
        assert 'IMPORTAR PACOTE DE PRODUÇÃO' in labels
        assert 'Gerar prévias aptas do pacote' in labels and 'Renderizar aprovados' in labels
        assert review.production_output.get() == ''
        assert not list(tmp_path.rglob('*.mp4'))
    finally:
        close_hidden_review(root, review)


def test_ready_fixture_imports_through_real_gui_worker_and_reopens(tmp_path, monkeypatch, hidden_tk_root):
    """Contract V1 fixture uses real staging/import; absent media stays unapproved."""
    import time
    from ldporto_curator.production_package import load_production_project
    from test_production_contract import archive, ready_files, finalize, digest
    files, manifest, _ = ready_files()
    package = archive(tmp_path / 'ready.zip', finalize(files, manifest))
    before = digest(package.read_bytes())
    root = hidden_tk_root
    review = None
    monkeypatch.setattr(series_review.filedialog, 'askopenfilename', lambda **kwargs: '')
    errors = []
    monkeypatch.setattr(series_review.messagebox, 'showerror', lambda *args, **kwargs: errors.append(args))
    try:
        review = series_review.SeriesReview(root, tmp_path,
            {'paths': {'output_root': str(tmp_path / 'legacy')}, 'render': {'prefer_nvenc': False}})
        review.withdraw()
        review.production_output.set(str(tmp_path / 'external'))
        review.production_library.set(str(tmp_path / 'empty-library'))
        review._import_production(package)
        deadline = time.monotonic() + 15
        while review.busy and time.monotonic() < deadline:
            root.update()
            time.sleep(.01)
        root.update()
        assert not review.busy and not errors, errors
        project = review.project
        assert project and project.directory.is_relative_to(tmp_path / 'external')
        assert len(project.episodes()) == 1 and len(review.table.get_children()) == 1
        episode = project.episodes()[0]
        assert episode['piece_kind'] == 'REEL' and not episode.get('human_approval')
        assert review.media.get() == ''
        assert 'CURATOR_READY' in review.production_summary.get()
        assert digest(package.read_bytes()) == before
        stored = {p: digest(p.read_bytes()) for p in project.directory.rglob('*') if p.is_file()}
        reopened = load_production_project(project.directory)
        assert reopened.plan == project.plan and reopened.cfg == project.cfg
        assert {p: digest(p.read_bytes()) for p in project.directory.rglob('*') if p.is_file()} == stored
        assert not list(tmp_path.rglob('*.mp4'))
    finally:
        close_hidden_review(root, review)
