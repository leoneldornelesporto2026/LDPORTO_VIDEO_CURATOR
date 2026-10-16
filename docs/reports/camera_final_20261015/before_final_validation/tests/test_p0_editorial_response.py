"""Retain the actual first model response, including rejected candidates."""
from copy import deepcopy
from dataclasses import fields
import hashlib
import json
from types import SimpleNamespace

from ldporto_curator.analysis_loader import AnalysisBundle
from ldporto_curator import pipeline, ollama_client
from ldporto_curator.persisted_plan import PlanStore


def test_explicit_curation_archives_full_response_and_restores_without_model(tmp_path, monkeypatch):
    values = {f.name: ({} if f.name in {'analysis', 'insights', 'review', 'second_package', 'second_decisions'}
                       else []) for f in fields(AnalysisBundle)}
    values.update(root=tmp_path / 'completed', video_id='response_fixture',
                  analysis={'metadata': {'duration': 120, 'source': {'id': 'response_fixture'}}},
                  editorial=[{'moment_id': 'M1', 'start': 0, 'end': 30, 'text': 'Fala existente 1'},
                             {'moment_id': 'M2', 'start': 60, 'end': 90, 'text': 'Fala existente 2'}])
    bundle = AnalysisBundle(**values)
    data = {'ranking': [
        {'clip_id': 'CLIP_001', 'approve': True, 'title': 'TÍTULO FIEL', 'editorial_score': 85,
         'hook': 'Fala existente 1', 'why': 'Trecho completo'},
        {'clip_id': 'CLIP_002', 'approve': False, 'title': 'DESCARTADO', 'editorial_score': 10,
         'hook': '', 'why': 'Contexto insuficiente'}]}
    raw = json.dumps(data, ensure_ascii=False)
    calls = []
    def post(*args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {'response': raw})
    monkeypatch.setattr(ollama_client.requests, 'post', post)
    monkeypatch.setattr(pipeline, 'find_analysis', lambda *_: bundle.root)
    monkeypatch.setattr(pipeline, 'load_bundle', lambda *_: deepcopy(bundle))
    monkeypatch.setattr(pipeline, 'build_camera_plan', lambda *_: {'mode': 'full_frame_blur'})
    cfg = {'paths': {'analysis_root': str(bundle.root), 'output_root': str(tmp_path / 'output'),
                     'source_cache': str(tmp_path / 'no_media')}, 'ollama': {'enabled': True},
           'camera': {'v44_refinement': False}, 'render': {}, 'subtitles': {}, 'title': {}}
    _, selected, folder = pipeline.Pipeline(cfg, tmp_path, log=lambda *_: None).curate_only('response_fixture')
    assert len(calls) == 1 and len(selected) == 1
    store = PlanStore(folder)
    doc, frozen = store.load(cfg)
    evidence = json.loads((store.revision_dir(doc) / 'EDITORIAL_RESPONSE.json').read_text(encoding='utf-8'))
    assert evidence['editorial_response'] == data
    assert evidence['raw_editorial_response'] == raw
    assert evidence['response_sha256'] == hashlib.sha256(raw.encode()).hexdigest()
    assert evidence['returned'] == 2 and evidence['approved'] == 1
    assert frozen.review['curator_phase2_response'] == evidence
    monkeypatch.setattr(ollama_client.requests, 'post', lambda *_a, **_k: (_ for _ in ()).throw(AssertionError('Qwen reread')))
    monkeypatch.setattr(pipeline, 'load_bundle', lambda *_: (_ for _ in ()).throw(AssertionError('Analyzer reread')))
    reopened = pipeline.Pipeline(cfg, tmp_path, log=lambda *_: None).read_state('response_fixture')
    assert reopened['plan_revision'] == doc['plan_revision']
    assert reopened['approved_clips'] == selected
