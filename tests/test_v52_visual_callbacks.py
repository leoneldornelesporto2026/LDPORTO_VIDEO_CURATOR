from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from ldporto_curator.series_review import SeriesReview


def fake_view(approved=False):
    project=SimpleNamespace(can_undo=True,can_redo=True,undo=Mock(),redo=Mock(),edit=Mock(),merge=Mock(),
        episode=lambda key:{'episode_id':key,'human_approval':{'human':True} if approved else None},
        plan={'episodes':[{'episode_id':'A'},{'episode_id':'B'}]})
    tasks=[]
    view=SimpleNamespace(project=project,busy=False,_selected=lambda:'A',_task=tasks.append)
    return view,project,tasks


def test_apply_timeline_limits_is_only_explicit_commit(monkeypatch):
    view,project,tasks=fake_view()
    SeriesReview._apply_limits(view,12.125,42.375)
    assert not project.edit.called
    tasks[0]()
    project.edit.assert_called_once_with('A',source_start=12.125,source_end=42.375,confirm_invalidation=True)


def test_declined_invalidation_does_not_schedule_edit(monkeypatch):
    view,project,tasks=fake_view(True)
    monkeypatch.setattr('ldporto_curator.series_review.messagebox.askyesno',lambda *a,**k:False)
    SeriesReview._apply_limits(view,1,10)
    assert tasks==[] and not project.edit.called


@pytest.mark.parametrize('action',['undo','redo'])
def test_history_action_holds_original_project(action):
    view,project,tasks=fake_view()
    SeriesReview._history(view,action)
    view.project=Mock()
    tasks[0]()
    getattr(project,action).assert_called_once_with()


def test_busy_history_action_is_ignored():
    view,project,tasks=fake_view();view.busy=True
    SeriesReview._history(view,'undo')
    assert tasks==[] and not project.undo.called


def test_merge_requires_explicit_ui_confirmation(monkeypatch):
    view,project,tasks=fake_view()
    monkeypatch.setattr('ldporto_curator.series_review.messagebox.askyesno',lambda *a,**k:True)
    SeriesReview._merge_next(view)
    assert not project.merge.called
    tasks[0]()
    project.merge.assert_called_once_with(['A','B'],confirm_invalidation=True)
