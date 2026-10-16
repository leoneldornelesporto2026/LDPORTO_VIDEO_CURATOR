"""Headless callback tests: no Tk root, desktop, media decoder or mainloop."""
from pathlib import Path
import queue
import threading
from types import SimpleNamespace

import pytest

from ldporto_curator import local_player, series_review


class FakeVar:
    def __init__(self, value=""):
        self.value = value
        self.forbid_get = False

    def get(self):
        assert not self.forbid_get, "Worker accessed a Tk variable instead of its captured value"
        return self.value

    def set(self, value):
        self.value = value


class FakeText:
    def __init__(self):
        self.text = ""

    def delete(self, *_):
        self.text = ""

    def insert(self, _, text):
        self.text += text


class FakeProject:
    def __init__(self, episodes=None):
        self.rows = episodes if episodes is not None else [{
            "episode_id": "PROP_1", "order": 1, "story_order": 1,
            "source_start": 1.234, "source_end": 61.234, "duration": 60,
            "status": "REVIEW_REQUIRED", "title_text": "Fala literal.",
            "thumbnail_title": "Fala literal.", "duration_preset": "from_60_to_89",
            "subtitle_preset": "LDP_DOCUMENTARIO", "camera_mode": "SOURCE_PRESERVE",
            "duration_within_target": True,
        }]
        self.calls = []
        self.evidence = {"source": {"sha256": "HASH", "duration": 200},
                         "segments": [], "scenes": []}
        self.plan = {"episodes": self.rows, "extras": [], "coverage": {}, "story_map": {}}
        self.directory = Path("unused-test-project")

    def episodes(self):
        return self.rows

    def episode(self, key):
        return next(e for e in self.rows if e["episode_id"] == key)

    def edit(self, key, **changes):
        self.calls.append(("edit", key, changes))

    def reject(self, key):
        self.calls.append(("reject", key))

    def approve(self, key, **changes):
        self.calls.append(("approve", key, changes))

    def export(self):
        self.calls.append(("export",))

    def render(self, key, media):
        self.calls.append(("render", key, media))

    def render_approved(self, media):
        self.calls.append(("batch", media))


def reviewer(project=None):
    # Allocating a Python object calls no Tk/Tcl or window constructor.
    view = object.__new__(series_review.SeriesReview)
    view.project = project if project is not None else FakeProject()
    view.busy, view.page = False, 0
    view.fields = {"source_start": FakeVar("1.234"), "source_end": FakeVar("61.234"),
                   "title_text": FakeVar("Fala literal."), "thumbnail_title": FakeVar("Fala literal."),
                   "order": FakeVar("1")}
    view.episode_duration = FakeVar("60s~89s")
    view.duration = FakeVar("Auto (<90s)")
    view.mode = FakeVar("SERIE_CRONOLOGICA")
    view.camera_mode = FakeVar("SOURCE_PRESERVE")
    view.subtitle_preset = FakeVar("LDP_DOCUMENTARIO")
    view.subtitle_custom = FakeVar('{"font_size": 52}')
    view.media = FakeVar("fixture.mp4")
    view.cfg = {"paths": {"output_root": "unused-test-output"}}
    view.cancel, view.events = threading.Event(), queue.Queue()
    view._selected = lambda: view.project.rows[0]["episode_id"] if view.project.rows else None
    view.scheduled = []
    view._task = view.scheduled.append
    view._refresh = lambda: None
    return view


def dialogs(monkeypatch, answers):
    asked, errors = [], []
    choices = iter(answers)
    def ask(title, text, **kwargs):
        asked.append((title, text))
        return next(choices)
    monkeypatch.setattr(series_review.messagebox, "askyesno", ask)
    monkeypatch.setattr(series_review.messagebox, "showerror", lambda *args, **kwargs: errors.append(args))
    return asked, errors


def test_gui_duration_labels_and_keys_preserve_eight_options_and_add_stories():
    assert series_review.PRESET_LABELS == ("Auto (<90s)", "<30s", "30s~59s", "60s~89s",
                                           "90s~3m", "3m~5m", "5m~10m", "10m~15m", "Stories (até 60s)")
    assert series_review.PRESET_KEYS == ("auto_under_90", "under_30", "from_30_to_59", "from_60_to_89",
                                         "from_90_to_180", "from_180_to_300", "from_300_to_600", "from_600_to_900", "story_upto_60")


def test_save_schedules_and_executes_valid_controller_edit(monkeypatch):
    view = reviewer()
    asked, errors = dialogs(monkeypatch, [])
    series_review.SeriesReview._save(view)
    assert len(view.scheduled) == 1 and errors == [] and asked == []
    view.scheduled[0]()
    kind, key, changes = view.project.calls[0]
    assert kind == "edit" and key == "PROP_1"
    assert changes["source_start"] == 1.234 and changes["source_end"] == 61.234
    assert changes["duration_preset"] == "from_60_to_89"
    assert changes["subtitle_overrides"] == {"font_size": 52}
    assert changes["order"] == 1


@pytest.mark.parametrize("state", ["PREVIEW_APPROVED", "FINAL_RENDERED", "PUBLISH_READY"])
@pytest.mark.parametrize("confirmed", [True, False])
def test_save_requires_confirmation_before_invalidating_approved_state(monkeypatch, state, confirmed):
    view = reviewer()
    view.project.rows[0]["status"] = state
    asked, errors = dialogs(monkeypatch, [confirmed])
    series_review.SeriesReview._save(view)
    assert len(asked) == 1 and errors == []
    assert len(view.scheduled) == int(confirmed)
    if confirmed:
        view.scheduled[0]()
        assert view.project.calls[0][2]["confirm_invalidation"] is True


@pytest.mark.parametrize("field,value", [("source_start", "invalid"), ("order", "1.5")])
def test_save_rejects_invalid_number_without_task(monkeypatch, field, value):
    view = reviewer()
    view.fields[field].set(value)
    _, errors = dialogs(monkeypatch, [])
    series_review.SeriesReview._save(view)
    assert errors and view.scheduled == [] and view.project.calls == []


def test_save_rejects_malformed_subtitle_json_without_task(monkeypatch):
    view = reviewer()
    view.subtitle_custom.set("{invalid}")
    _, errors = dialogs(monkeypatch, [])
    series_review.SeriesReview._save(view)
    assert errors and view.scheduled == []


def test_save_busy_does_not_read_editor_or_schedule(monkeypatch):
    view = reviewer()
    view.busy = True
    for var in view.fields.values():
        var.forbid_get = True
    dialogs(monkeypatch, [])
    series_review.SeriesReview._save(view)
    assert view.scheduled == []


def test_save_confirm_invalidation_even_when_approval_state_is_inconsistent(monkeypatch):
    view = reviewer()
    view.project.rows[0]["human_approval"] = {"preview_approved_by_human": True}
    asked, _ = dialogs(monkeypatch, [False])
    series_review.SeriesReview._save(view)
    assert len(asked) == 1 and view.scheduled == []


@pytest.mark.parametrize("deviation", [True, False])
def test_approve_uses_top_level_duration_metadata(monkeypatch, deviation):
    view = reviewer()
    view.project.rows[0]["duration_within_target"] = not deviation
    # Opposite legacy metadata must not override the canonical top-level field.
    view.project.rows[0]["duration_compliance"] = {"within_target": deviation}
    asked, errors = dialogs(monkeypatch, [True, True] if deviation else [True])
    series_review.SeriesReview._approve(view)
    assert len(asked) == (2 if deviation else 1) and not errors
    assert len(view.scheduled) == 1
    view.scheduled[0]()
    assert view.project.calls == [("approve", "PROP_1", {"human_reviewed": True,
                                                         "duration_deviation_accepted": deviation})]


def test_declined_duration_deviation_does_not_approve(monkeypatch):
    view = reviewer()
    view.project.rows[0]["duration_within_target"] = False
    dialogs(monkeypatch, [True, False])
    series_review.SeriesReview._approve(view)
    assert view.scheduled == [] and view.project.calls == []


def test_reject_calls_controller_and_never_mutates_ui_episode(monkeypatch):
    view = reviewer()
    series_review.SeriesReview._reject(view)
    assert view.project.rows[0]["status"] == "REVIEW_REQUIRED"
    assert len(view.scheduled) == 1
    view.scheduled[0]()
    assert view.project.calls == [("reject", "PROP_1")]


@pytest.mark.parametrize("count,start,direction,expected", [
    (201, 0, -1, 0), (201, 0, 1, 1), (201, 1, 1, 2), (201, 2, 1, 2),
    (100, 0, 1, 0), (0, 2, 1, 0), (101, 1, -1, 0),
])
def test_episode_page_bounds(count, start, direction, expected):
    view = reviewer(FakeProject([{"episode_id": str(i)} for i in range(count)]))
    view.page = start
    refreshes = []
    view._refresh = lambda: refreshes.append(True)
    series_review.SeriesReview._page(view, direction)
    assert view.page == expected and refreshes == [True]


def test_import_captures_tk_vars_before_worker(monkeypatch):
    view, captures = reviewer(), []
    view.mode.set("COMBINADO")
    view.duration.set("10m~15m")
    monkeypatch.setattr("ldporto_curator.evidence_source.load_evidence", lambda path, canonical_dir=None: {"loaded": path})
    monkeypatch.setattr(series_review.SeriesProject, "create", staticmethod(
        lambda *args, **kwargs: captures.append((args, kwargs)) or "created"))
    series_review.SeriesReview._import(view, "completed-package.zip")
    assert len(view.scheduled) == 1
    view.mode.value, view.duration.value = "DOSSIER_ONLY", "<30s"
    view.mode.forbid_get = view.duration.forbid_get = True
    assert view.scheduled[0]() == "created"
    assert captures[0][0][0] == {"loaded": "completed-package.zip"}
    assert captures[0][0][3:5] == ("from_600_to_900", "COMBINADO")


def test_replan_captures_preference_and_evidence_before_worker(monkeypatch):
    view, captures = reviewer(), []
    original_evidence = view.project.evidence
    view.duration.set("5m~10m")
    monkeypatch.setattr(series_review.SeriesProject, "create", staticmethod(
        lambda *args, **kwargs: captures.append((args, kwargs)) or "created"))
    series_review.SeriesReview._replan(view)
    view.mode.forbid_get = view.duration.forbid_get = True
    view.project = FakeProject()
    view.scheduled[0]()
    assert captures[0][0][0] is original_evidence
    assert captures[0][0][3:5] == ("from_300_to_600", "SERIE_CRONOLOGICA")


@pytest.mark.parametrize("operation,expected", [("export", ("export",)),
                                               ("preview", ("render", "PROP_1", "fixture.mp4")),
                                               ("batch", ("batch", "fixture.mp4"))])
def test_render_and_export_capture_media_before_worker(operation, expected):
    view = reviewer()
    series_review.SeriesReview._operate(view, operation)
    view.media.forbid_get = True
    view.scheduled[0]()
    assert view.project.calls == [expected]


@pytest.mark.parametrize("callback", ["_save", "_approve", "_reject"])
def test_editor_workers_keep_original_project_target(monkeypatch, callback):
    view = reviewer()
    original = view.project
    dialogs(monkeypatch, [True])
    getattr(series_review.SeriesReview, callback)(view)
    assert len(view.scheduled) == 1
    view.project = FakeProject()
    view.scheduled[0]()
    assert original.calls and view.project.calls == []


def test_resume_cannot_replace_project_while_worker_is_busy(monkeypatch):
    view = reviewer()
    original = view.project
    view.busy = True
    monkeypatch.setattr(series_review.filedialog, "askopenfilename", lambda **kwargs:
                        pytest.fail("Busy window opened a project selector"))
    series_review.SeriesReview._resume(view)
    assert view.project is original


def test_save_style_handles_malformed_json_without_creating_file(monkeypatch, tmp_path):
    view = reviewer()
    view.rootp = tmp_path
    view.subtitle_custom.set("{invalid}")
    target = tmp_path / "saved-model.json"
    monkeypatch.setattr(series_review.filedialog, "asksaveasfilename", lambda **kwargs: str(target))
    _, errors = dialogs(monkeypatch, [])
    series_review.SeriesReview._save_style(view)
    assert errors and not target.exists()


@pytest.mark.parametrize("contents", ["[]", '"scalar"', '{"preset":"LDP_CLEAN","overrides":[]}'])
def test_load_style_handles_invalid_model_shape(monkeypatch, tmp_path, contents):
    view = reviewer()
    target = tmp_path / "invalid-model.json"
    target.write_text(contents, encoding="utf-8")
    monkeypatch.setattr(series_review.filedialog, "askopenfilename", lambda **kwargs: str(target))
    _, errors = dialogs(monkeypatch, [])
    series_review.SeriesReview._load_style(view)
    assert errors


def test_controller_edit_recovers_changed_proposal_identity_from_disk(tmp_path):
    from ldporto_curator.series_workflow import SeriesProject
    evidence = {"source": {"sha256": "HASH", "duration": 40, "video_id": "headless-fixture"},
                "segments": [{"segment_id": "S1", "start": 0, "end": 40, "text": "Uma fala literal completa."}],
                "availability": {"segments": {"status": "available"}}}
    project = SeriesProject.create(evidence, tmp_path)
    original_id = project.episodes()[0]["episode_id"]
    changed = project.edit(original_id, source_start=1, confirm_invalidation=True)
    assert changed["episode_id"] != original_id and changed["revision_of"] == original_id
    resumed = SeriesProject(project.directory)
    assert resumed.episodes()[0]["episode_id"] == changed["episode_id"]
    assert resumed.episodes()[0]["source_start"] == 1
    assert list((project.directory / "revisions").glob("*.json"))


def player():
    widget = object.__new__(local_player.LocalPlayer)
    widget.session, widget.audio = 4, None
    widget.stop_event = threading.Event()
    widget.caption = FakeVar()
    widget.frames = queue.Queue(maxsize=2)
    widget.width, widget.height = 400, 200
    return widget


def test_player_missing_media_stops_old_audio_without_decoder(monkeypatch, tmp_path):
    widget, terminated = player(), []
    widget.audio = SimpleNamespace(poll=lambda: None, terminate=lambda: terminated.append(True))
    monkeypatch.setattr(local_player.threading, "Thread", lambda **kwargs: pytest.fail("Missing file started a decoder"))
    local_player.LocalPlayer.show(widget, tmp_path / "absent.mp4", 1, 2)
    assert terminated == [True] and widget.session == 5 and widget.stop_event.is_set()
    assert widget.audio is None and "indisponível" in widget.caption.value


def test_player_launches_hidden_bounded_audio_and_queued_decoder(monkeypatch, tmp_path):
    widget, launched, decoders = player(), [], []
    media = tmp_path / "sample.mp4"
    media.write_bytes(b"test-only-placeholder-never-decoded")
    class FakeThread:
        def __init__(self, target, daemon):
            decoders.append((target, daemon))
        def start(self):
            pass
    monkeypatch.setattr(local_player.threading, "Thread", FakeThread)
    monkeypatch.setattr(local_player.shutil, "which", lambda executable: "installed-ffplay")
    monkeypatch.setattr(local_player.subprocess, "CREATE_NO_WINDOW", 123, raising=False)
    monkeypatch.setattr(local_player.subprocess, "Popen", lambda args, **kwargs:
                        launched.append((args, kwargs)) or SimpleNamespace(poll=lambda: None, terminate=lambda: None))
    local_player.LocalPlayer.show(widget, media, 10.125, 12.625, play=True)
    command, options = launched[0]
    assert command[command.index("-ss") + 1] == "10.125"
    assert command[command.index("-t") + 1] == "2.5"
    assert options["creationflags"] == 123
    assert len(decoders) == 1 and decoders[0][1] is True
    assert "áudio via FFplay" in widget.caption.value


def test_player_without_ffplay_does_not_claim_audio(monkeypatch, tmp_path):
    widget = player()
    media = tmp_path / "sample.mp4"
    media.write_bytes(b"test-only-placeholder-never-decoded")
    monkeypatch.setattr(local_player.shutil, "which", lambda executable: None)
    monkeypatch.setattr(local_player.threading, "Thread", lambda **kwargs: SimpleNamespace(start=lambda: None))
    monkeypatch.setattr(local_player.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("No ffplay installed"))
    local_player.LocalPlayer.show(widget, media, play=True)
    assert widget.audio is None and "sem áudio" in widget.caption.value


def test_player_poll_discards_stale_session_without_creating_image():
    widget, scheduled = player(), []
    widget.frames.put((widget.session - 1, 1., object()))
    widget.winfo_exists = lambda: True
    widget.after = lambda delay, callback: scheduled.append((delay, callback))
    local_player.LocalPlayer._poll(widget)
    assert widget.frames.empty() and scheduled[0][0] == 50


def test_player_destroy_only_stops_its_own_widget():
    widget, stops = player(), []
    widget.stop = lambda: stops.append(True)
    local_player.LocalPlayer._destroy(widget, SimpleNamespace(widget=object()))
    assert stops == []
    local_player.LocalPlayer._destroy(widget, SimpleNamespace(widget=widget))
    assert stops == [True]
