"""Package boundaries, immutable baseline hashes and the bytes actually copied."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile

import pytest

from scripts import build_caption_update as builder


def digest(content):
    return hashlib.sha256(content).hexdigest()


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / 'project'
    for folder in ('ldporto_curator', 'tests', 'scripts', 'docs/reports/organizacao_20261015', 'docs/architecture', 'output'):
        (root / folder).mkdir(parents=True)
    (root / 'ldporto_curator/subtitles.py').write_bytes(b'new-caption-engine')
    (root / 'ldporto_curator/final_camera.py').write_bytes(b'preexisting-user-camera-edit')
    (root / 'scripts/INSTALL_CAPTIONS_P0.ps1').write_bytes(b'installer-placeholder')
    (root / 'README.md').write_bytes(b'caption-readme')
    (root / 'docs/architecture/LEGENDAS_WORD_ALIGNED.md').write_bytes(b'caption-contract')
    (root / 'docs/reports/ORGANIZACAO_PROJETO.md').write_text('audited', encoding='utf-8')
    (root / 'output/APPROVAL.json').write_bytes(b'protected-approval')
    baseline = {'files': [
        {'path': 'ldporto_curator/subtitles.py', 'sha256': digest(b'old-caption-engine')},
        {'path': 'ldporto_curator/final_camera.py', 'sha256': digest(b'preexisting-user-camera-edit')},
        {'path': 'README.md', 'sha256': digest(b'old-readme')},
    ]}
    (root / 'docs/reports/organizacao_20261015/inventory_before.json').write_text(json.dumps(baseline), encoding='utf-8')
    monkeypatch.setattr(builder, 'ROOT', root)
    return root


def test_package_hashes_match_payload_and_preserve_preexisting_user_edits(project):
    destination = project / 'docs/reports/package/update_package'
    evidence = project / 'docs/reports/evidence'
    evidence.mkdir()
    (evidence / 'SUBTITLE_SYNC.json').write_text('{"review":"pending"}', encoding='utf-8')
    archive = builder.build(destination, evidence)
    manifest = json.loads((destination / 'UPDATE_MANIFEST.json').read_text(encoding='utf-8'))
    rows = {row['path']: row for row in manifest['files']}
    assert set(rows) == {'ldporto_curator/subtitles.py', 'scripts/INSTALL_CAPTIONS_P0.ps1',
                         'README.md', 'docs/architecture/LEGENDAS_WORD_ALIGNED.md'}
    assert rows['ldporto_curator/subtitles.py']['before_sha256'] == digest(b'old-caption-engine')
    assert rows['scripts/INSTALL_CAPTIONS_P0.ps1']['before_sha256'] is None
    assert rows['README.md']['before_sha256'] == digest(b'old-readme')
    for name, row in rows.items():
        copied = (destination / 'payload' / name).read_bytes()
        assert digest(copied) == row['sha256']
        assert len(copied) == row['bytes']
    with zipfile.ZipFile(archive) as packaged:
        assert 'evidence/SUBTITLE_SYNC.json' in packaged.namelist()
        assert not any(name.startswith(('output/', '.cache/', 'source_cache/')) for name in packaged.namelist())
    assert archive.with_suffix('.zip.sha256').read_text().split()[0] == digest(archive.read_bytes())
    assert (project / 'output/APPROVAL.json').read_bytes() == b'protected-approval'
    assert (project / 'ldporto_curator/final_camera.py').read_bytes() == b'preexisting-user-camera-edit'


def test_package_includes_raw_jsonl_regression_evidence(project):
    raw = project / 'tests/source_words.jsonl'
    raw.write_bytes(b'{"word":"literal","start":1.0,"end":1.5}\n')
    destination = project / 'docs/reports/package/update_package'
    archive = builder.build(destination)
    with zipfile.ZipFile(archive) as packaged:
        assert packaged.read('payload/tests/source_words.jsonl') == raw.read_bytes()


@pytest.mark.parametrize('kind', ['evidence_ancestor', 'evidence_descendant', 'outside_evidence', 'outside_destination', 'protected_destination', 'code_destination'])
def test_builder_rejects_unsafe_scopes_before_creating_package(project, tmp_path, kind):
    destination = project / 'docs/reports/package/update_package'
    evidence = project / 'docs/reports/evidence'
    if kind == 'evidence_ancestor':
        evidence = destination.parent
    elif kind == 'evidence_descendant':
        evidence = destination / 'evidence'
    elif kind == 'outside_evidence':
        evidence = tmp_path / 'outside'
    elif kind == 'outside_destination':
        destination = tmp_path / 'outside_package'
    elif kind == 'protected_destination':
        destination = project / 'output/patch'
    elif kind == 'code_destination':
        destination = project / 'scripts/patch'
    evidence.mkdir(parents=True)
    before_paths = {p.relative_to(project) for p in project.rglob('*')}
    with pytest.raises(ValueError):
        builder.build(destination, evidence)
    assert {p.relative_to(project) for p in project.rglob('*')} == before_paths
    assert (project / 'output/APPROVAL.json').read_bytes() == b'protected-approval'


def test_concurrent_source_edit_cannot_publish_inconsistent_manifest(project, monkeypatch):
    destination = project / 'docs/reports/package/update_package'
    original_copy = builder.shutil.copy2

    def copy_then_edit(source, target, *args, **kwargs):
        result = original_copy(source, target, *args, **kwargs)
        if Path(source).name == 'subtitles.py':
            Path(source).write_bytes(b'concurrent-user-edit')
        return result

    monkeypatch.setattr(builder.shutil, 'copy2', copy_then_edit)
    with pytest.raises(RuntimeError, match='mudou durante'):
        builder.build(destination)
    assert not (destination / 'UPDATE_MANIFEST.json').exists()
    assert not (destination.parent / 'UPDATE_LEGENDAS_STORIES_P0.zip').exists()
    assert (project / 'ldporto_curator/subtitles.py').read_bytes() == b'concurrent-user-edit'


def directory_link(link, destination):
    if os.name == 'nt':
        result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(destination)],
                                capture_output=True, text=True)
        if result.returncode:
            pytest.skip('Junction indisponível: ' + result.stderr)
    else:
        link.symlink_to(destination, target_is_directory=True)


def test_evidence_link_is_rejected_without_following_external_content(project, tmp_path):
    evidence = project / 'docs/reports/evidence'
    evidence.mkdir()
    outside = tmp_path / 'private'
    outside.mkdir()
    (outside / 'private.txt').write_bytes(b'must-not-package')
    directory_link(evidence / 'linked', outside)
    destination = project / 'docs/reports/package/update_package'
    with pytest.raises(ValueError, match='Links/junctions'):
        builder.build(destination, evidence)
    assert not destination.exists()


def test_destination_link_is_rejected_before_resolving_away_its_identity(project, tmp_path):
    outside = tmp_path / 'outside'
    outside.mkdir()
    directory_link(project / 'docs/reports/linked_destination', outside)
    destination = project / 'docs/reports/linked_destination/update_package'
    with pytest.raises(ValueError, match='Links/junctions'):
        builder.build(destination)
    assert not (outside / 'update_package').exists()
