"""Main GUI operation isolation with actual worker threads and a real Tk smoke."""
from copy import deepcopy
import json
from pathlib import Path
import queue
import threading
from types import MethodType, SimpleNamespace

import pytest

from ldporto_curator import gui
from ldporto_curator.source_video import SourceUnavailable


class MainThreadVar:
    def __init__(self, value):
        self.value = value
        self.owner = threading.get_ident()

    def get(self):
        assert threading.get_ident() == self.owner, 'worker accessed Tk variable'
        return self.value

    def set(self, value):
        assert threading.get_ident() == self.owner, 'worker changed Tk variable'
        self.value = value


class MainThreadWidget:
    def __init__(self):
        self.state = 'normal'
        self.owner = threading.get_ident()

    def configure(self, **kwargs):
        assert threading.get_ident() == self.owner
        self.state = kwargs['state']


class MainThreadLog:
    def __init__(self):
        self.text = ''
        self.owner = threading.get_ident()

    def insert(self, _, text):
        assert threading.get_ident() == self.owner
        self.text += text

    def see(self, _):
        assert threading.get_ident() == self.owner


def make_view(tmp_path):
    main_thread = threading.get_ident()
    scheduled = []

    def after(delay, callback):
        assert threading.get_ident() == main_thread, 'worker scheduled a Tk callback'
        scheduled.append((delay, callback))
        return len(scheduled)

    cfg = {'paths': {'analysis_root': str(tmp_path / 'analysis'),
                     'output_root': str(tmp_path / 'output')},
           'ollama': {'enabled': True}, 'subtitles': {'font': 'Arial'}}
    view = SimpleNamespace(rootp=tmp_path, cfg=cfg, q=queue.Queue(), busy=False,
        _active_operation=None, _last_finished_operation=None,
        _pending_source_unavailable=None, src=MainThreadVar('source-one'),
        rank=MainThreadVar(2), analysis_root=MainThreadVar(cfg['paths']['analysis_root']),
        output_root=MainThreadVar(cfg['paths']['output_root']),
        use_ollama=MainThreadVar(True), status=MainThreadVar('ready'),
        curation_source=MainThreadVar('FIRST_PASS'), plan_state=MainThreadVar('SEM_PLANO'),
        action_buttons=[MainThreadWidget()], mutating_widgets=[MainThreadWidget()],
        log=MainThreadLog(), after=after, scheduled=scheduled, progress_events=[],
        dialogs=[], _reset_progress=lambda _: None)
    view._handle_progress = view.progress_events.append
    view.missing_media_dialog = view.dialogs.append
    for name in ('work', '_sync', '_set_buttons', '_poll', '_show_missing_media',
                 '_remember_session', '_restore_session', '_refresh_plan_state',
                 'select_media', 'open_series_review', 'write', 'progress'):
        setattr(view, name, MethodType(getattr(gui.App, name), view))
    return view


def capture_threads(monkeypatch):
    threads = []
    thread_class = threading.Thread

    def start_thread(*args, **kwargs):
        thread = thread_class(*args, **kwargs)
        threads.append(thread)
        return thread

    monkeypatch.setattr(gui.threading, 'Thread', start_thread)
    return threads


class RecordingPipeline:
    def __init__(self, cfg, root, log, progress=None, *, calls, enter, release):
        self.cfg, self.root, self.log, self.progress = cfg, root, log, progress
        self.calls, self.enter, self.release = calls, enter, release

    def record(self, action, source, rank=None):
        self.enter.set()
        assert self.release.wait(5), 'test worker was not released'
        self.calls.append((action, source, rank, deepcopy(self.cfg)))
        self.progress({'event': 'plan_state', 'approval_state': 'PLAN_READY',
                       'project_id': 'P', 'plan_revision': 'R1', 'plan_fingerprint': 'HASH'})
        self.log('recorded: ' + source)

    def curate_only(self, source):
        self.record('curate', source)

    def test_one(self, source, rank):
        self.record('test', source, rank)
        return Path('preview.mp4'), []

    def approve_test(self, source):
        self.record('approve', source)

    def revise_plan(self, source, render_config=None):
        assert render_config == self.cfg
        self.record('revise', source)
        return {'plan_revision': 'NEW_REVISION'}

    def render_all(self, source, preview=False):
        assert preview is False
        self.record('all', source)


@pytest.mark.parametrize('action', ['curate', 'test', 'approve', 'all', 'revise'])
def test_worker_uses_main_thread_snapshot_and_duplicate_click_is_ignored(tmp_path, monkeypatch, action):
    view = make_view(tmp_path)
    threads = capture_threads(monkeypatch)
    calls, enter, release = [], threading.Event(), threading.Event()
    monkeypatch.setattr(gui, 'Pipeline', lambda *a, **k: RecordingPipeline(
        *a, **k, calls=calls, enter=enter, release=release))
    if action == 'all':
        from ldporto_curator import combined_batch

        def record_combined_batch(pipeline, source):
            pipeline.render_all(source, preview=False)
            return {'finals': 0, 'previews_pending': 0}

        monkeypatch.setattr(combined_batch, 'render_combined_batch', record_combined_batch)
    view.work(action)
    operation = view._active_operation
    assert enter.wait(5)
    assert all(widget.state == 'disabled' for widget in view.action_buttons + view.mutating_widgets)
    view.work(action)
    assert len(threads) == 1
    view.src.set('source-changed')
    view.rank.set(7)
    view.cfg['subtitles']['font'] = 'Changed font'
    view.output_root.set(str(tmp_path / 'other-output'))
    view._sync()
    release.set()
    threads[0].join(5)
    assert not threads[0].is_alive()
    assert calls[0][:3] == (action, 'source-one', 2 if action == 'test' else None)
    assert calls[0][3]['subtitles']['font'] == 'Arial'
    assert calls[0][3]['paths']['output_root'] == str(tmp_path / 'output')
    queued = list(view.q.queue)
    assert queued and all(item['operation_id'] == operation for item in queued)
    view._poll()
    assert not view.busy and view._active_operation is None
    assert view._last_finished_operation == operation
    assert all(widget.state == 'normal' for widget in view.action_buttons + view.mutating_widgets)


def test_late_and_duplicate_worker_messages_cannot_unlock_or_change_current_operation(tmp_path):
    view = make_view(tmp_path)
    view.busy, view._active_operation = True, 'current-operation'
    view._set_buttons(False)
    for kind in ('done', 'log', 'progress', 'imported', 'source_unavailable', 'error', 'preview_ready'):
        view.q.put({'type': kind, 'operation_id': 'previous-operation'})
    view.q.put({'type': 'done'})  # Unidentified callbacks cannot finish a worker.
    view._poll()
    assert view.busy and view._active_operation == 'current-operation'
    assert view.src.get() == 'source-one'
    assert not view.progress_events and not view.log.text
    assert all(widget.state == 'disabled' for widget in view.action_buttons + view.mutating_widgets)
    view.q.put({'type': 'done', 'operation_id': 'current-operation'})
    view.q.put({'type': 'done', 'operation_id': 'current-operation'})
    view._poll()
    assert view._last_finished_operation == 'current-operation'
    assert not view.busy


def test_error_dialog_is_delivered_on_main_thread(tmp_path, monkeypatch):
    view = make_view(tmp_path)
    threads = capture_threads(monkeypatch)
    shown = []
    owner = threading.get_ident()

    class FailingPipeline:
        def __init__(self, *_, **__):
            pass

        def approve_test(self, _):
            raise ValueError('preview hash changed')

    def show_error(title, text, **kwargs):
        assert threading.get_ident() == owner
        shown.append((title, text))

    monkeypatch.setattr(gui, 'Pipeline', FailingPipeline)
    monkeypatch.setattr(gui.messagebox, 'showerror', show_error)
    view.work('approve')
    threads[0].join(5)
    assert not threads[0].is_alive() and not shown
    view._poll()
    assert shown == [('Erro', 'preview hash changed')]
    assert 'preview hash changed' in view.log.text and not view.busy


def test_stale_missing_media_dialog_does_not_open_after_another_action(tmp_path):
    view = make_view(tmp_path)
    view.busy, view._active_operation = True, 'old'
    view.q.put({'type': 'source_unavailable', 'kind': 'test', 'operation_id': 'old'})
    view.q.put({'type': 'done', 'operation_id': 'old'})
    view._poll()
    pending = next(callback for delay, callback in view.scheduled if delay == 200)
    view.busy, view._active_operation = True, 'new'
    pending()
    assert not view.dialogs


def test_missing_media_callback_keeps_relevant_action(tmp_path, monkeypatch):
    view = make_view(tmp_path)
    threads = capture_threads(monkeypatch)

    class MissingPipeline:
        def __init__(self, *_, **__):
            pass

        def test_one(self, *_):
            raise SourceUnavailable('source original is missing')

    monkeypatch.setattr(gui, 'Pipeline', MissingPipeline)
    view.work('test')
    threads[0].join(5)
    view._poll()
    next(callback for delay, callback in view.scheduled if delay == 200)()
    assert view.dialogs == ['test'] and not view.busy


def test_busy_media_and_series_callbacks_cannot_mutate_config(tmp_path, monkeypatch):
    view = make_view(tmp_path)
    view.busy = True
    monkeypatch.setattr(gui.filedialog, 'askopenfilename', lambda **_: pytest.fail('busy file picker'))
    view.select_media()
    view.open_series_review()
    assert 'source_media' not in view.cfg


def test_reopening_restores_the_selected_project_and_persisted_approval(tmp_path, monkeypatch):
    view = make_view(tmp_path)
    view._remember_session('persisted-project', 3)
    readers = []

    class StoredPipeline:
        def __init__(self, cfg, root, log, progress=None):
            assert cfg is not view.cfg

        def read_state(self, source):
            readers.append(source)
            return {'project_id': 'P', 'plan_revision': 'R_APPROVED',
                    'editorial_plan_fingerprint': 'EDITORIAL_HASH', 'plan_signature': 'BATCH_HASH',
                    'approval_state': 'TEST_APPROVED'}

    monkeypatch.setattr(gui, 'Pipeline', StoredPipeline)
    threads = capture_threads(monkeypatch)
    view._restore_session()
    assert view.src.get() == 'persisted-project' and view.rank.get() == 3
    assert len(threads) == 1
    threads[0].join(5)
    assert not threads[0].is_alive()
    assert readers == ['persisted-project']
    assert not view.progress_events  # Tk must be updated only by the main-thread poll.
    view._poll()
    assert view.progress_events[-1]['approval_state'] == 'TEST_APPROVED'
    assert view.progress_events[-1]['plan_revision'] == 'R_APPROVED'
    assert view.progress_events[-1]['plan_fingerprint'] == 'BATCH_HASH'
    saved = json.loads((tmp_path / '.cache/gui_session_v52.json').read_text(encoding='utf-8'))
    assert set(saved) == {'source_input', 'rank', 'output_root'}


def test_plan_status_shows_revision_fingerprint_and_invalidation_cause(tmp_path):
    view = make_view(tmp_path)
    gui.App._handle_progress(view, {'event': 'plan_state', 'project_id': 'P',
        'plan_revision': 'R1', 'plan_fingerprint': 'HASH',
        'approval_state': 'APPROVAL_INVALIDATED', 'invalidation_reason': 'subtitles.font changed'})
    assert all(text in view.plan_state.get() for text in (
        'APPROVAL_INVALIDATED', 'P', 'R1', 'HASH', 'subtitles.font changed'))


def test_settings_mismatch_retains_revision_and_explains_explicit_configuration_action(tmp_path, monkeypatch):
    view = make_view(tmp_path)
    view._handle_progress = MethodType(gui.App._handle_progress, view)

    class ChangedSettingsPipeline:
        def __init__(self, cfg, root, log, progress):
            self.progress = progress

        def read_state(self, source):
            self.progress({'event': 'plan_state', 'project_id': 'P', 'plan_revision': 'APPROVED_REV',
                'plan_fingerprint': 'HASH', 'approval_state': 'APPROVAL_INVALIDATED',
                'invalidation_reason': 'Configuração de render mudou: subtitles.font'})
            raise ValueError('Configuração de render mudou: subtitles.font')

    monkeypatch.setattr(gui, 'Pipeline', ChangedSettingsPipeline)
    threads = capture_threads(monkeypatch)
    view._refresh_plan_state()
    threads[0].join(5)
    assert not threads[0].is_alive()
    view._poll()
    assert all(text in view.plan_state.get() for text in (
        'APPROVAL_INVALIDATED', 'APPROVED_REV', 'subtitles.font',
        'Aplicar configurações ao plano', 'TESTAR 1 CORTE', 'APROVAR TESTE'))


def test_real_tk_build_exposes_plan_state_and_serializes_mutating_controls(tmp_path):
    (tmp_path / 'config.yaml').write_text(
        'paths:\n  analysis_root: analysis\n  output_root: output\nollama:\n  enabled: false\n', encoding='utf-8')
    try:
        app = gui.App(tmp_path)
    except gui.tk.TclError as exc:
        pytest.skip(f'Tk desktop unavailable: {exc}')
    try:
        app.withdraw()
        app.update_idletasks()
        assert 'SEM_PLANO' in app.plan_state.get()
        assert len(app.action_buttons) == 6 and len(app.mutating_widgets) >= 10
        app._set_buttons(False)
        assert all(widget.instate(['disabled']) for widget in app.action_buttons + app.mutating_widgets)
        app._set_buttons(True)
        assert all(not widget.instate(['disabled']) for widget in app.action_buttons + app.mutating_widgets)
        gui.App._handle_progress(app, {'event': 'plan_state', 'project_id': 'REAL_TK',
            'plan_revision': 'REV', 'plan_fingerprint': 'FP', 'approval_state': 'TEST_APPROVED'})
        assert 'TEST_APPROVED' in app.plan_state.get() and 'REV' in app.plan_state.get()
    finally:
        app.destroy()


def test_plan_status_lookup_does_not_block_tk_and_never_touches_tk_from_worker(tmp_path, monkeypatch):
    view = make_view(tmp_path)
    view._handle_progress = MethodType(gui.App._handle_progress, view)
    entered, release = threading.Event(), threading.Event()
    threads = capture_threads(monkeypatch)

    class SlowPipeline:
        def __init__(self, cfg, root, log, progress):
            self.progress = progress

        def read_state(self, source):
            entered.set()
            assert release.wait(5)
            return {'project_id': source, 'plan_revision': 'REV1',
                    'plan_signature': 'HASH', 'approval_state': 'TEST_APPROVED'}

    monkeypatch.setattr(gui, 'Pipeline', SlowPipeline)
    view._refresh_plan_state()
    assert entered.wait(5)
    # Despite a worker reading a large plan, the GUI remains free to process input.
    assert view.plan_state.get() == 'Estado: verificando revisão salva...'
    assert view.src.get() == 'source-one'
    release.set()
    threads[0].join(5)
    assert not threads[0].is_alive()
    assert 'TEST_APPROVED' not in view.plan_state.get()
    view._poll()
    assert 'TEST_APPROVED' in view.plan_state.get()


def test_old_plan_lookup_must_not_replace_new_url_or_operation(tmp_path, monkeypatch):
    view = make_view(tmp_path)
    view._handle_progress = MethodType(gui.App._handle_progress, view)
    started, release = threading.Event(), threading.Event()
    threads = capture_threads(monkeypatch)

    class SlowPipeline:
        def __init__(self, cfg, root, log, progress):
            pass

        def read_state(self, source):
            started.set()
            assert release.wait(5)
            return {'project_id': source, 'plan_revision': 'OLD_REV',
                    'plan_signature': 'OLD_HASH', 'approval_state': 'TEST_APPROVED'}

    monkeypatch.setattr(gui, 'Pipeline', SlowPipeline)
    view._refresh_plan_state()
    assert started.wait(5)
    # Simulate a URL edit occurring before the slow checksum lookup completes.
    view.src.set('new-video')
    view._state_request_generation += 1
    release.set()
    threads[0].join(5)
    view._poll()
    assert 'OLD_REV' not in view.plan_state.get()
    assert 'OLD_HASH' not in view.plan_state.get()


def test_plan_status_lookup_exception_is_shown_only_after_main_thread_poll(tmp_path, monkeypatch):
    view = make_view(tmp_path)
    threads = capture_threads(monkeypatch)

    class MissingPipeline:
        def __init__(self, cfg, root, log, progress):
            pass

        def read_state(self, source):
            raise FileNotFoundError('Nenhum plano salvo')

    monkeypatch.setattr(gui, 'Pipeline', MissingPipeline)
    view._refresh_plan_state()
    threads[0].join(5)
    assert not threads[0].is_alive()
    view._poll()
    assert view.plan_state.get() == 'Estado: SEM_PLANO | Nenhum plano salvo'
