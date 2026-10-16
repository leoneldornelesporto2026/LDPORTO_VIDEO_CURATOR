from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from ldporto_curator.episode_approval import (
    approve_episode_preview, episode_approval_matches, episode_signature,
    record_episode_preview,
)
from ldporto_curator.series_workflow import SeriesProject, conservative_camera


def _episode():
    return {"episode_id":"E001", "series_id":"SERIE_001", "story_order":1,"order":1,"source_start":0.,"source_end":20.,"duration":20.,
            "title_text":"Uma fala literal", "subtitle_preset":"LDP_CLEAN", "subtitle_overrides":{},
            "camera_mode":"SOURCE_PRESERVE", "camera_plan":{"mode":"full_frame_blur"},
            "thumbnail_title":"Uma fala", "thumbnail_overrides":{}, "audio_mode":"original", "status":"REVIEW_REQUIRED"}


def _reviewed(tmp_path, episode=None):
    episode=episode or _episode()
    directory=tmp_path/"review"
    directory.mkdir(exist_ok=True)
    media=directory/"PREVIEW.mp4"
    media.write_bytes(b"controlled preview bytes")
    assets=[]
    for name in ("CAPTIONS.ass","camera_plan.json","CAPA.png","audio.json"):
        asset=directory/name
        asset.write_bytes(("controlled fixture: "+name).encode())
        assets.append(asset)
    signature=episode_signature(episode,"source-hash")
    record_episode_preview(directory,media,signature,{"status":"validated","visual_human_review":"pending"},assets)
    return directory,media,signature


@pytest.mark.parametrize("human_reviewed", [False,None,0,1,"true"])
def test_approval_needs_explicit_human_boolean(tmp_path,human_reviewed):
    directory,_,signature=_reviewed(tmp_path)
    with pytest.raises(ValueError,match="explícita"):
        approve_episode_preview(directory,signature,human_reviewed=human_reviewed)
    assert not episode_approval_matches(directory,signature)


def test_recording_preview_does_not_approve_or_authorize_publication(tmp_path):
    directory,_,signature=_reviewed(tmp_path)
    assert not episode_approval_matches(directory,signature)
    approved=approve_episode_preview(directory,signature,human_reviewed=True)
    assert approved["preview_approved_by_human"] is True
    assert approved["publication_approved"] is False
    assert episode_approval_matches(directory,signature)


@pytest.mark.parametrize("field,value", [
    ("title_text","Novo título"), ("subtitle_preset","LDP_IMPACTO"),
    ("subtitle_overrides",{"font_size_final":80}), ("camera_mode","AUTO_CONSERVADOR"),
    ("camera_plan",{"mode":"crop","normalized_center_x":.4}),
    ("thumbnail_title","Outra capa"), ("thumbnail_selection","CAPA_02"),
    ("thumbnail_overrides",{"brand":"L.D.PORTO OFICIAL"}), ("audio_mode","normalize"),
    ("audio",{"mode":"normalize"}), ("source_start",.5), ("source_end",19.5),
])
def test_each_editorial_or_visual_input_invalidates_only_its_approval(tmp_path,field,value):
    episode=_episode()
    directory,_,signature=_reviewed(tmp_path,episode)
    approve_episode_preview(directory,signature,human_reviewed=True)
    changed=deepcopy(episode); changed[field]=value
    new_signature=episode_signature(changed,"source-hash")
    assert new_signature!=signature
    assert not episode_approval_matches(directory,new_signature)
    assert episode_approval_matches(directory,signature)


@pytest.mark.parametrize("asset", ["PREVIEW.mp4","CAPTIONS.ass","camera_plan.json","CAPA.png","audio.json"])
def test_tampered_preview_or_rendering_asset_invalidates_approval(tmp_path,asset):
    directory,_,signature=_reviewed(tmp_path)
    approve_episode_preview(directory,signature,human_reviewed=True)
    (directory/asset).write_bytes(b"modified after review")
    assert not episode_approval_matches(directory,signature)
    with pytest.raises(ValueError,match="mudaram"):
        approve_episode_preview(directory,signature,human_reviewed=True)


def test_source_config_and_renderer_changes_invalidate_fingerprint(monkeypatch):
    episode=_episode()
    original=episode_signature(episode,"source-hash",{"render":{"audio_lufs":-14}})
    assert episode_signature(episode,"different-source",{"render":{"audio_lufs":-14}})!=original
    assert episode_signature(episode,"source-hash",{"render":{"audio_lufs":-18}})!=original
    monkeypatch.setattr("ldporto_curator.episode_approval.renderer_fingerprint",lambda:"changed-renderer")
    assert episode_signature(episode,"source-hash",{"render":{"audio_lufs":-14}})!=original


def test_music_bytes_change_invalidates_approval_even_when_episode_json_is_unchanged(tmp_path):
    music=tmp_path/"user_provided.wav"; music.write_bytes(b"user provided music fixture bytes")
    episode=_episode()
    episode["audio"]={"mode":"original","music_path":str(music),"rights_confirmed":True}
    directory,_,signature=_reviewed(tmp_path,episode)
    approve_episode_preview(directory,signature,human_reviewed=True)
    music.write_bytes(b"different track bytes at the same local path")
    new_signature=episode_signature(episode,"source-hash")
    assert new_signature!=signature
    assert not episode_approval_matches(directory,new_signature)


def test_recordkeeping_states_do_not_change_rendering_signature():
    episode=_episode(); signature=episode_signature(episode,"source-hash")
    episode.update(state="PREVIEW_APPROVED",status="PREVIEW_APPROVED",preview={"path":"test"},approval={"human":True},final={"path":"test"})
    assert episode_signature(episode,"source-hash")==signature


def test_asset_reference_cannot_escape_review_folder(tmp_path):
    directory,_,signature=_reviewed(tmp_path)
    outside=tmp_path/"external.png"; outside.write_bytes(b"outside")
    record_path=directory/"PREVIEW_REVIEW_V5.json"
    record=json.loads(record_path.read_text(encoding="utf-8"))
    record["assets"].append({"path":"../external.png","sha256":hashlib.sha256(outside.read_bytes()).hexdigest()})
    record_path.write_text(json.dumps(record),encoding="utf-8")
    with pytest.raises(ValueError):
        approve_episode_preview(directory,signature,human_reviewed=True)


def test_unvalidated_media_cannot_enter_review_gate(tmp_path):
    media=tmp_path/"preview.mp4"; media.write_bytes(b"fixture")
    with pytest.raises(ValueError,match="validado"):
        record_episode_preview(tmp_path,media,"signature",{"status":"unknown"})


def test_project_blocks_final_render_without_valid_preview_approval(tmp_path):
    media=tmp_path/"source.mp4"; media.write_bytes(b"fixture source")
    project=SeriesProject(tmp_path/"project",cfg={"render":{"prefer_nvenc":False}})
    project.evidence={"source":{"sha256":hashlib.sha256(media.read_bytes()).hexdigest()}}
    project.plan={"episodes":[_episode()]}
    with pytest.raises(ValueError,match="aprovação humana"):
        project.render("E001",media,preview=False)


def test_project_does_not_render_rejected_episode(tmp_path):
    media=tmp_path/"source.mp4"; media.write_bytes(b"fixture source")
    project=SeriesProject(tmp_path/"project")
    project.evidence={"source":{"sha256":hashlib.sha256(media.read_bytes()).hexdigest()}}
    rejected=_episode(); rejected["status"]="REJECTED"
    project.plan={"episodes":[rejected]}
    with pytest.raises(ValueError,match="rejeitado"):
        project.render("E001",media)


def test_final_render_cannot_ignore_planner_duration_violation(tmp_path):
    source=tmp_path/"source.mp4"; source.write_bytes(b"fixture source")
    project=SeriesProject(tmp_path/"project")
    project.evidence={"source":{"sha256":hashlib.sha256(source.read_bytes()).hexdigest()}}
    episode=_episode(); episode["duration_within_target"]=False
    episode["duration_deviation_reason"]="menor que o mínimo escolhido"
    directory=project.directory/"review"
    directory.mkdir(parents=True)
    preview=directory/"preview.mp4"; preview.write_bytes(b"review fixture")
    signature=project.signature(episode)
    record_episode_preview(directory,preview,signature,{"status":"validated"})
    approve_episode_preview(directory,signature,human_reviewed=True)
    episode["preview"]={"review_folder":"review"}
    project.plan={"episodes":[episode]}
    with pytest.raises(ValueError,match="[Dd]esvio|[Dd]uração|[Ff]aixa"):
        project.render("E001",source,preview=False)


def test_existing_unvalidated_output_is_not_silently_reused(tmp_path):
    source=tmp_path/"source.mp4"; source.write_bytes(b"fixture source")
    project=SeriesProject(tmp_path/"project")
    project.evidence={"source":{"sha256":hashlib.sha256(source.read_bytes()).hexdigest()}}
    episode=_episode()
    episode["camera_plan"]=conservative_camera(project.evidence,episode,{})
    signature=project.signature(episode)
    directory=project.folder(episode)/signature[:16]/"preview"
    directory.mkdir(parents=True)
    (directory/"PREVIEW_540x960.mp4").write_bytes(b"corrupted or unfinished output")
    project.plan={"episodes":[episode]}
    with pytest.raises((ValueError,RuntimeError)):
        project.render("E001",source)
