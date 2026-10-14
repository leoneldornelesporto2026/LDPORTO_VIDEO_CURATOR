import hashlib
import json
import zipfile
from pathlib import Path
import pytest
from ldporto_curator.second_curation_import import import_second_curation, read_package
from ldporto_curator.analysis_loader import load_bundle
from ldporto_curator.curator import curate


def make_package(path):
    payloads = {
        'source/metadata.json': {'sha256': 'HASH', 'duration': 60, 'width': 1920, 'height': 1080,
                                 'source': {'id': 'VIDEO', 'url': 'https://example.test/video'}},
        'editorial/candidate_catalog.json': {'candidates': [{'candidate_id': 'C1', 'start': 2, 'end': 42,
            'transcript_literal': 'Uma fala completa.', 'segment_ids': ['S1'], 'content_type': 'editorial_content', 'visual_refs': []}]},
        'editorial/default_shortlist.json': {'candidate_ids': ['C1']},
        'transcript/relevant_segments.jsonl': {'segment_id': 'S1', 'start': 2, 'end': 42, 'text': 'Uma fala completa.', 'speaker': 'SP1'},
    }
    files = {name: json.dumps(data).encode() for name, data in payloads.items()}
    manifest = {'source_hash': 'HASH', 'files': [{'path': n, 'bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest()} for n, b in files.items()]}
    files['SECOND_CURATION_MANIFEST.json'] = json.dumps(manifest).encode()
    with zipfile.ZipFile(path, 'w') as archive:
        for name, data in files.items():
            archive.writestr(name, data)


def test_zip_import_is_reviewable_and_decisions_keep_exact_boundaries(tmp_path):
    package = tmp_path / 'SECOND_CURATION_READY.zip'
    make_package(package)
    root = tmp_path / 'curator'
    root.mkdir()
    report = import_second_curation(package, root)
    assert report['curation_source'] == 'FIRST_PASS'
    decision = {'schema_version': '4.4.0', 'source_sha256': 'HASH', 'provider': 'manual_json', 'actions': [
        {'decision_id': 'D1', 'candidate_ids': ['C1'], 'action': 'promote', 'reason': 'Desfecho completo.',
         'windows': [{'start': 3, 'end': 41}], 'title': 'Título da segunda curadoria'}]}
    path = tmp_path / 'SECOND_CURATION_DECISIONS.json'
    path.write_text(json.dumps(decision), encoding='utf-8')
    report = import_second_curation(path, root)
    bundle = load_bundle(report['analysis_dir'])
    clips = curate(bundle, {'ollama': {'enabled': False}}, root)
    assert clips[0]['curation_source'] == 'SECOND_CURATOR'
    assert clips[0]['source_start'] == 3 and clips[0]['source_end'] == 41
    feedback = json.loads(Path(report['feedback_path']).read_text(encoding='utf-8').splitlines()[0])
    assert feedback['before'][0]['start'] == 2 and feedback['after'][0]['start'] == 3
    assert feedback['training_executed'] is False
    assert not (Path(report['analysis_dir']) / 'FIRST_TEST_APPROVED.flag').exists()


def test_tampering_and_archive_traversal_are_rejected(tmp_path):
    path = tmp_path / 'bad.zip'
    make_package(path)
    with zipfile.ZipFile(path, 'a') as archive:
        archive.writestr('../escape.json', '{}')
    with pytest.raises(ValueError):
        read_package(path)
    assert not (tmp_path.parent / 'escape.json').exists()
