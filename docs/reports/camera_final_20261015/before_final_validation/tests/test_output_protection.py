"""Exercise destructive paths only against disposable pytest temporary files."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from ldporto_curator import storage


def snapshot(root):
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in Path(root).rglob('*') if path.is_file() and not path.is_symlink()}


def put(root, name, value=b'user data must survive'):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)
    return path


def register(root, paths):
    """Synthetic producer receipt, never a registration of existing user files."""
    rows = [{'path': path.relative_to(root).as_posix(), 'purpose': 'regenerable_scratch',
             'bytes': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in paths]
    (root / storage.CLEANUP_MANIFEST).write_text(json.dumps({
        'schema': 'LDP_GENERATED_SCRATCH_V1', 'files': rows}), encoding='utf-8')


def scratch(root):
    path = put(root, 'render_staging/generated.tmp', b'controlled generated scratch')
    register(root, [path])
    return path


def test_preview_is_read_only_and_unproven_legacy_files_are_preserved(tmp_path):
    root = tmp_path / 'workspace'
    for name in ('output/preview.mp4', 'output/series_index.json',
                 'output/revisions/frozen.json', 'output/APPROVAL.json',
                 'output/FIRST_TEST_APPROVED.flag', 'output/source_manifest.json',
                 'backups/before.bin', '.cache/detection.npz', 'source_cache/original.mp4',
                 '.venv/pyvenv.cfg', 'analyzer/temporary_frames/evidence.png',
                 'audio/analyzer.wav', 'temporary_frames/uncertain.png',
                 'render_staging/interrupted.tmp', 'render_staging/unfinished.mp4'):
        put(root, name)
    before = snapshot(root)
    plan = storage.cleanup_preview(root, root / 'source_cache/original.mp4', include_source=True)
    assert plan['removable'] == [] and plan['reclaimable_bytes'] == 0
    assert plan['source_removal_disabled'] is True
    assert len(plan['preserved_candidates']) >= 4
    assert snapshot(root) == before
    # Even an explicitly confirmed maintenance action cannot remove these files.
    assert storage.execute_cleanup(plan, confirmed=True)['removed'] == []
    assert snapshot(root) == before


@pytest.mark.parametrize('folder', [
    'output', 'OUTPUT', '.cache', 'source_cache', '.venv', 'backups',
    'backup_before', 'projects', 'revisions', 'editing_history', 'approvals',
    'evidence', 'analyzer', 'original_media',
])
def test_registered_scratch_inside_protected_tree_stays_immutable(tmp_path, folder):
    root = tmp_path / folder
    path = scratch(root)
    before = snapshot(root)
    plan = storage.cleanup_preview(root)
    assert plan['removable'] == []
    assert storage.execute_cleanup(plan, confirmed=True)['removed'] == []
    assert path.is_file() and snapshot(root) == before


@pytest.mark.parametrize('marker', [
    'series_index.json', 'EDIT_DECISIONS.json', 'APPROVAL.json',
    'FIRST_TEST_APPROVED.flag', 'SECOND_CURATION_MANIFEST.json',
    'analysis.json', 'completion.json',
])
def test_project_and_analyzer_markers_protect_unusually_named_directories(tmp_path, marker):
    root = tmp_path / 'custom_named_directory'
    scratch(root)
    put(root, marker)
    before = snapshot(root)
    plan = storage.cleanup_preview(root)
    assert plan['removable'] == []
    assert snapshot(root) == before


@pytest.mark.parametrize('kind', ['video', 'registered_audio'])
def test_original_source_never_becomes_cleanup_candidate(tmp_path, kind):
    root = tmp_path / 'scratch_workspace'
    root.mkdir()
    if kind == 'video':
        source = put(tmp_path, 'outside_original.mp4')
    else:
        source = put(root, 'render_staging/original.wav')
        register(root, [source])
    before = source.read_bytes()
    plan = storage.cleanup_preview(root, source, include_source=True)
    assert plan['removable'] == []
    assert storage.execute_cleanup(plan, confirmed=True)['removed'] == []
    assert source.read_bytes() == before


def test_registered_scratch_requires_confirmation_and_preserves_other_files(tmp_path):
    root = tmp_path / 'scratch_workspace'
    path = scratch(root)
    protected = put(root, 'output/preview.mp4')
    plan = storage.cleanup_preview(root)
    assert [row['path'] for row in plan['removable']] == [str(path.resolve())]
    before = snapshot(root)
    with pytest.raises(ValueError, match='Confirme'):
        storage.execute_cleanup(plan)
    assert snapshot(root) == before
    result = storage.execute_cleanup(plan, confirmed=True)
    assert result['removed_bytes'] == len(b'controlled generated scratch')
    assert not path.exists() and protected.read_bytes() == b'user data must survive'
    assert (root / storage.CLEANUP_MANIFEST).is_file()


@pytest.mark.parametrize('location', ['output/render_staging/preview.tmp',
    'render_staging/source.mp4', 'render_staging/APPROVAL.json', 'external.tmp'])
def test_forged_preview_cannot_delete_user_artifacts(tmp_path, location):
    root = tmp_path / 'scratch_workspace'
    scratch(root)
    target = put(tmp_path if location == 'external.tmp' else root, location)
    plan = storage.cleanup_preview(root)
    info = target.stat()
    plan['removable'] = [{'path': str(target), 'bytes': info.st_size,
        'mtime_ns': info.st_mtime_ns, 'sha256': hashlib.sha256(target.read_bytes()).hexdigest()}]
    before = snapshot(tmp_path)
    result = storage.execute_cleanup(plan, confirmed=True)
    assert result['removed'] == [] and result['skipped'] == [str(target)]
    assert snapshot(tmp_path) == before


def test_legacy_cleanup_plan_is_rejected_before_any_mutation(tmp_path):
    path = scratch(tmp_path / 'scratch_workspace')
    plan = storage.cleanup_preview(path.parent.parent)
    del plan['policy']
    with pytest.raises(ValueError, match='Preview antigo'):
        storage.execute_cleanup(plan, confirmed=True)
    assert path.is_file()


def test_file_changed_with_identical_size_and_mtime_is_preserved_by_sha256(tmp_path):
    root = tmp_path / 'scratch_workspace'
    path = scratch(root)
    plan = storage.cleanup_preview(root)
    info = path.stat()
    changed = b'X' * info.st_size
    path.write_bytes(changed)
    os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
    result = storage.execute_cleanup(plan, confirmed=True)
    assert result['removed'] == []
    assert result['skipped'] == [str(path.resolve())]
    assert path.read_bytes() == changed


@pytest.mark.parametrize('state', ['manifest_interrupted', 'manifest_changed',
    'RUNNING.lock', '.PLAN_OPERATION.lock', '.PLAN_STATE.lock', 'series_index.json'])
def test_stale_preview_preserves_files_after_interruption_or_new_operation(tmp_path, state):
    root = tmp_path / 'scratch_workspace'
    path = scratch(root)
    plan = storage.cleanup_preview(root)
    if state == 'manifest_interrupted':
        (root / storage.CLEANUP_MANIFEST).write_text('{interrupted', encoding='utf-8')
    elif state == 'manifest_changed':
        register(root, [])
    else:
        put(root, state, b'unknown or active owner')
    before = snapshot(root)
    result = storage.execute_cleanup(plan, confirmed=True)
    assert result['removed'] == [] and path.is_file()
    assert snapshot(root) == before


def test_active_media_lease_and_failed_render_never_remove_original_or_scratch(tmp_path):
    root = tmp_path / 'scratch_workspace'
    path = scratch(root)
    original = put(root, 'source.mp4')
    before = snapshot(root)
    with pytest.raises(RuntimeError, match='interrupted render'):
        with storage.media_lease(path):
            assert storage.cleanup_preview(root)['removable'] == []
            raise RuntimeError('interrupted render')
    assert snapshot(root) == before
    assert original.read_bytes() == b'user data must survive'
    assert storage.cleanup_preview(root)['removable']


@pytest.mark.parametrize('marker', ['{interrupted', '[]', '{}', '{"pid":null}'])
def test_interrupted_or_unknown_media_lease_preserves_registered_scratch(tmp_path, marker):
    root = tmp_path / 'scratch_workspace'
    path = scratch(root)
    plan = storage.cleanup_preview(root)
    marker_path = path.parent / '.ldporto_media_use_interrupted.json'
    if marker == '{"pid":null}':
        marker = json.dumps({'path': str(path.resolve()), 'pid': None})
    marker_path.write_text(marker, encoding='utf-8')
    before = snapshot(root)
    assert storage.cleanup_preview(root)['removable'] == []
    assert storage.execute_cleanup(plan, confirmed=True)['removed'] == []
    assert snapshot(root) == before


def directory_link(link, destination):
    if os.name == 'nt':
        command = shutil.which('cmd')
        result = subprocess.run([command, '/c', 'mklink', '/J', str(link), str(destination)],
                                capture_output=True, text=True)
        if result.returncode:
            pytest.skip('Junction unavailable: ' + result.stderr)
    else:
        link.symlink_to(destination, target_is_directory=True)


def test_junction_root_is_rejected_and_external_data_never_enumerated(tmp_path):
    root = tmp_path / 'scratch_workspace'
    root.mkdir()
    external = tmp_path / 'private'
    path = scratch(external)
    link = root / 'redirected'
    directory_link(link, external)
    plan = storage.cleanup_preview(root)
    assert plan['removable'] == [] and plan['skipped_links'] == [str(link)]
    assert path.is_file()
    with pytest.raises(ValueError, match='Links/junctions'):
        storage.cleanup_preview(link)


def test_directory_replaced_by_junction_after_preview_cannot_redirect_deletion(tmp_path):
    root = tmp_path / 'scratch_workspace'
    path = scratch(root)
    plan = storage.cleanup_preview(root)
    external = tmp_path / 'private'
    external_path = put(external, 'generated.tmp', path.read_bytes())
    info = path.stat()
    os.utime(external_path, ns=(info.st_atime_ns, info.st_mtime_ns))
    path.parent.rename(root / 'original_staging')
    directory_link(root / 'render_staging', external)
    result = storage.execute_cleanup(plan, confirmed=True)
    assert result['removed'] == []
    assert external_path.is_file() and (root / 'original_staging/generated.tmp').is_file()


@pytest.mark.parametrize('change', ['traversal', 'duplicate', 'wrong_hash', 'persistent_media'])
def test_invalid_scratch_manifest_never_authorizes_deletion(tmp_path, change):
    root = tmp_path / 'scratch_workspace'
    path = scratch(root)
    manifest_path = root / storage.CLEANUP_MANIFEST
    document = json.loads(manifest_path.read_text(encoding='utf-8'))
    if change == 'traversal':
        document['files'][0]['path'] = 'render_staging/../../outside.tmp'
    elif change == 'duplicate':
        document['files'].append(deepcopy(document['files'][0]))
    elif change == 'wrong_hash':
        document['files'][0]['sha256'] = '0' * 64
    else:
        document['files'][0]['path'] = 'render_staging/preview.mp4'
    manifest_path.write_text(json.dumps(document), encoding='utf-8')
    before = snapshot(root)
    assert storage.cleanup_preview(root)['removable'] == []
    assert path.is_file() and snapshot(root) == before
