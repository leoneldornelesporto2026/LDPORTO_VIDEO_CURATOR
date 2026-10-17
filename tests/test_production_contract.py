"""Production containers are inert, bounded proposals; all writes use tmp_path."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import stat
import zipfile

import pytest

from ldporto_curator import production_contract as contract

SOURCE = 'a' * 64


def encode(value):
    return json.dumps(value, ensure_ascii=False).encode('utf-8')


def digest(payload):
    return hashlib.sha256(payload).hexdigest()


def inventory(root):
    return {p.relative_to(root).as_posix(): digest(p.read_bytes())
            for p in root.rglob('*') if p.is_file()}


def archive(path, files):
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as output:
        for name, payload in files.items():
            output.writestr(name, payload)
    return path


def manifest_rows(files):
    return [{'path': name, 'bytes': len(payload), 'sha256': digest(payload)}
            for name, payload in files.items()]


def native_files():
    files = {
        'source/metadata.json': encode({'sha256': SOURCE, 'duration': 10., 'width': 1920,
            'height': 1080, 'fps': 24., 'source': {'type': 'local', 'filename': 'original.mp4'}}),
        'editorial/candidate_catalog.json': encode({'candidates': [
            {'candidate_id': 'C1', 'start': 1., 'end': 9., 'segment_ids': ['S1']}]}),
        'editorial/default_shortlist.json': encode({'candidate_ids': ['C1']}),
        'transcript/relevant_segments.jsonl': encode({'segment_id': 'S1', 'start': 1.,
            'end': 9., 'text': 'Fala original.'}) + b'\n',
    }
    files['SECOND_CURATION_MANIFEST.json'] = encode({'source_hash': SOURCE, 'files': manifest_rows(files)})
    return files


def ready_files(*, kind='reel'):
    metadata = {'source_sha256': SOURCE, 'duration': 10., 'width': 1920, 'height': 1080, 'fps': 24.}
    evidence = {'source': {'sha256': SOURCE, 'duration': 10., 'width': 1920, 'height': 1080},
        'segments': [{'segment_id': 'S1', 'start': 1., 'end': 9., 'text': 'Fala original.'}],
        'words': [{'word_id': 'W1', 'segment_id': 'S1', 'word': 'Fala', 'start': 1., 'end': 2.}],
        'candidates': [{'candidate_id': 'C1', 'start': 1., 'end': 9.}]}
    files = {'media_reference.json': encode(metadata),
        'editorial_revision.json': encode({'provider': 'ChatGPT', 'state': 'HUMAN_REVIEW_REQUIRED'}),
        'evidence/evidence.json': encode(evidence)}
    folder = 'REELS/REEL_001' if kind == 'reel' else 'STORIES/SERIE_001/PARTE_01'
    docs = {'editorial.json': {'piece_id': 'R1' if kind == 'reel' else 'ST1', 'candidate_id': 'C1', 'title_text': 'Fala original'},
        'source_segments.json': {'segments': [{'start': 1., 'end': 9., 'segment_ids': ['S1']}]},
        'camera_timeline.json': {'timebase': 'clip_relative', 'coordinate_space': 'normalized',
            'segments': [{'start': 0., 'end': 8., 'mode': 'FULL_VERTICAL_9X16',
                          'center_x': .5, 'center_y': .4, 'zoom': 1.03}]},
        'caption_plan.json': {'state': 'ALIGNMENT_REVIEW_REQUIRED', 'word_ids': ['W1']},
        'safe_areas.json': {'regions': [{'x_start': .4, 'x_end': .6, 'y_start': .2, 'y_end': .6}]},
        'title_overlay.json': {'text': 'Fala original'}, 'camera_keyframes.json': {'keyframes': []},
        'audio_plan.json': {'mode': 'original'}, 'thumbnail_plan.json': {},
        'visual_evidence_refs.json': {'refs': []}}
    for name, value in docs.items():
        files[folder + '/' + name] = encode(value)
    manifest = {'contract': 'LDPORTO_CURATOR_READY_V1', 'version': 1, 'source_sha256': SOURCE,
        'reels': [{'path': folder}] if kind == 'reel' else [],
        'stories': [] if kind == 'reel' else [{'path': 'STORIES/SERIE_001'}]}
    if kind == 'story':
        files['STORIES/SERIE_001/series_manifest.json'] = encode({'series_id': 'S01', 'parts': [{'path': 'PARTE_01'}]})
    return files, manifest, folder


def finalize(files, manifest):
    files = {k: v for k, v in files.items() if k not in {'manifest.json', 'checksums.sha256'}}
    manifest = {**manifest, 'files': manifest_rows(files)}
    files['manifest.json'] = encode(manifest)
    files['checksums.sha256'] = ''.join(digest(payload) + '  ' + name + '\n'
                                       for name, payload in files.items()).encode()
    return files


def test_native_uses_existing_validator_and_preserves_source_identity(tmp_path, monkeypatch):
    from ldporto_curator import second_curation_import
    path = archive(tmp_path / 'native.zip', native_files())
    original = second_curation_import.read_package
    calls = []
    def existing(path):
        calls.append(path)
        return original(path)
    monkeypatch.setattr(second_curation_import, 'read_package', existing)
    before = inventory(tmp_path)
    loaded = contract.read_production_archive(path)
    assert loaded['format'] == 'ANALYZER_NATIVE' and calls == [path.resolve()]
    assert loaded['metadata']['sha256'] == SOURCE and not loaded['metadata']['source'].get('id')
    assert loaded['publication_ready'] is False and inventory(tmp_path) == before


@pytest.mark.parametrize('kind', ['reel', 'story'])
def test_ready_proposals_normalize_existing_modes_without_approval_or_writes(tmp_path, kind):
    files, manifest, folder = ready_files(kind=kind)
    path = archive(tmp_path / 'ready.zip', finalize(files, manifest))
    before = inventory(tmp_path)
    loaded = contract.read_production_archive(path)
    piece = loaded['pieces'][0]
    assert loaded['format'] == 'CURATOR_READY' and piece['camera_plan']['segments'][0]['mode'] == 'crop'
    assert piece['source_start'] == 1. and piece['duration'] == 8.
    assert piece['state'] == 'HUMAN_REVIEW_REQUIRED' and piece['human_approval'] is None
    assert loaded['evidence']['words'][0]['start'] == 1. and inventory(tmp_path) == before


@pytest.mark.parametrize('member', ['../outside.json', '/absolute.json', 'a\\escape.json',
    'C:/escape.json', 'dup/../escape.json', 'a//b.json', 'CON.json', 'trailing./b.json', 'script.py', 'run.ps1'])
def test_unsafe_or_executable_members_are_rejected_before_extraction(tmp_path, member):
    path = archive(tmp_path / 'unsafe.zip', {member: b'{}'})
    before = inventory(tmp_path)
    with pytest.raises(ValueError):
        contract.read_production_archive(path)
    assert inventory(tmp_path) == before


def test_case_collision_and_zip_symlink_are_rejected(tmp_path):
    path = archive(tmp_path / 'case.zip', {'A.json': b'{}', 'a.json': b'{}'})
    with pytest.raises(ValueError, match='case-colliding'):
        contract.read_production_archive(path)
    with zipfile.ZipFile(tmp_path / 'linked.zip', 'w') as output:
        info = zipfile.ZipInfo('linked.json'); info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        output.writestr(info, 'outside.json')
    with pytest.raises(ValueError, match='Linked'):
        contract.read_production_archive(tmp_path / 'linked.zip')


@pytest.mark.parametrize('field', ['MAX_BYTES', 'MAX_FILES', 'MAX_COMPRESSION_RATIO'])
def test_resource_limits_fail_closed(tmp_path, monkeypatch, field):
    path = archive(tmp_path / 'limit.zip', {'data.json': b'0' * 2000, 'other.json': b'{}'})
    monkeypatch.setattr(contract, field, 1)
    with pytest.raises(ValueError, match='limit'):
        contract.read_production_archive(path)


@pytest.mark.parametrize('tamper', ['source_hash', 'approval', 'caption_approval', 'timestamp', 'overflow', 'unknown_word',
    'caption_word', 'discontinuous', 'crop_missing_center', 'zoom_unsupported', 'gap',
    'unknown_mode', 'region', 'missing_file', 'keyframe', 'asset'])
def test_ready_rejects_unsupported_or_unfaithful_decisions(tmp_path, tamper):
    files, manifest, folder = ready_files()
    def edit(name, function):
        value = json.loads(files[name]); function(value); files[name] = encode(value)
    if tamper == 'source_hash':
        edit('media_reference.json', lambda d: d.update(source_sha256='b' * 64))
    elif tamper == 'approval':
        edit('editorial_revision.json', lambda d: d.update(approved=True))
    elif tamper == 'caption_approval':
        edit(folder + '/caption_plan.json', lambda d: d.update(preview_approved=True))
    elif tamper == 'timestamp':
        edit(folder + '/source_segments.json', lambda d: d['segments'][0].update(end=float('nan')))
    elif tamper == 'overflow':
        files[folder + '/source_segments.json'] = b'{"segments":[{"start":1,"end":1e400}]}'
    elif tamper == 'unknown_word':
        edit(folder + '/caption_plan.json', lambda d: d.update(word_ids=['NOT_SOURCE_WORD']))
    elif tamper == 'caption_word':
        edit(folder + '/caption_plan.json', lambda d: d.update(words=[{'word_id': 'W1', 'start': 1.5}]))
    elif tamper == 'discontinuous':
        edit(folder + '/source_segments.json', lambda d: d.update(segments=[{'start': 1., 'end': 3.}, {'start': 4., 'end': 9.}]))
    elif tamper == 'crop_missing_center':
        edit(folder + '/camera_timeline.json', lambda d: d['segments'][0].pop('center_y'))
    elif tamper == 'zoom_unsupported':
        edit(folder + '/camera_timeline.json', lambda d: d['segments'][0].update(zoom_start=1., zoom_end=1.1))
    elif tamper == 'gap':
        edit(folder + '/camera_timeline.json', lambda d: d['segments'][0].update(start=1.))
    elif tamper == 'unknown_mode':
        edit(folder + '/camera_timeline.json', lambda d: d['segments'][0].update(mode='MAGIC_CROP'))
    elif tamper == 'region':
        edit(folder + '/safe_areas.json', lambda d: d['regions'][0].update(x_end=1.1))
    elif tamper == 'missing_file':
        files.pop(folder + '/caption_plan.json')
    elif tamper == 'keyframe':
        edit(folder + '/camera_keyframes.json', lambda d: d.update(keyframes=[{'time': 9., 'center_x': .5, 'center_y': .4}]))
    else:
        edit(folder + '/visual_evidence_refs.json', lambda d: d.update(refs=['VISUAL_EVIDENCE/missing.png']))
    path = archive(tmp_path / 'bad.zip', finalize(files, manifest))
    before = inventory(tmp_path)
    with pytest.raises(ValueError):
        contract.read_production_archive(path)
    assert inventory(tmp_path) == before


def test_checksum_and_schema_cannot_be_bypassed(tmp_path):
    files, manifest, _ = ready_files()
    complete = finalize(files, manifest)
    complete['media_reference.json'] += b' '
    path = archive(tmp_path / 'corrupt.zip', complete)
    with pytest.raises(ValueError, match='checksum'):
        contract.read_production_archive(path)
    manifest['version'] = 2
    with pytest.raises(ValueError, match='schema'):
        contract.read_production_archive(archive(tmp_path / 'future.zip', finalize(files, manifest)))


def test_editorial_directory_and_archive_validate_native_binding(tmp_path):
    nested_path = archive(tmp_path / 'native.zip', native_files())
    nested = nested_path.read_bytes()
    files = {'06_SEGUNDA_CURADORIA/SECOND_CURATION_READY.zip': nested, 'REPORTS/report.pdf': b'%PDF inert fixture'}
    manifest = {'contract': 'ldporto.project_dossier', 'schema_version': '1.0',
        'source_sha256': SOURCE, 'source_duration': 10., 'package_sha256': digest(nested),
        'title': 'Projeto audiovisual', 'preview_approved': False, 'publication_ready': False,
        'files': manifest_rows(files)}
    files['PROJECT_MANIFEST.json'] = encode(manifest)
    directory = tmp_path / 'dossier'
    for name, payload in files.items():
        target = directory / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(payload)
    before = inventory(tmp_path)
    loaded = contract.read_editorial_handoff(directory, SOURCE, digest(nested))
    assert loaded['format'] == 'EDITORIAL_HANDOFF' and loaded['metadata']['width'] == 1920
    assert loaded['source_package_sha256'] == digest(nested) and inventory(tmp_path) == before
    with pytest.raises(ValueError, match='source SHA256'):
        contract.read_editorial_handoff(directory, 'c' * 64)
    with pytest.raises(ValueError, match='package SHA256'):
        contract.read_editorial_handoff(directory, SOURCE, 'd' * 64)
    package = archive(tmp_path / 'dossier.zip', files)
    assert contract.read_production_archive(package)['metadata']['sha256'] == SOURCE
