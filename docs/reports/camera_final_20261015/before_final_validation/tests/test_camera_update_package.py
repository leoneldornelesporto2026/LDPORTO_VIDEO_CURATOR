"""Camera packages and the real PowerShell installer use only disposable roots."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import zipfile

import pytest

from scripts import build_camera_update as builder

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/INSTALL_CAMERA_FINAL.ps1'
POWERSHELL = shutil.which('powershell') or shutil.which('pwsh')
shell = pytest.mark.skipif(not POWERSHELL, reason='PowerShell ausente')


def digest(content):
    return hashlib.sha256(content).hexdigest()


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / 'project'
    for folder in ('ldporto_curator', 'scripts', 'tests', 'docs/reports/camera_final_20261015'):
        (root / folder).mkdir(parents=True)
    (root / 'ldporto_curator/final_camera.py').write_bytes(b'new-camera')
    (root / 'ldporto_curator/subtitles.py').write_bytes(b'preexisting-caption-fix')
    (root / 'scripts/INSTALL_CAMERA_FINAL.ps1').write_bytes(SCRIPT.read_bytes())
    (root / 'docs/reports/old_report.md').write_bytes(b'old-report-excluded')
    baseline = {'files': [
        {'path': 'ldporto_curator/final_camera.py', 'sha256': digest(b'old-camera')},
        {'path': 'ldporto_curator/subtitles.py', 'sha256': digest(b'preexisting-caption-fix')},
    ]}
    (root / builder.BASELINE).write_text(json.dumps(baseline), encoding='utf-8')
    monkeypatch.setattr(builder, 'ROOT', root)
    return root


def test_package_is_only_session_delta_and_hashes_actual_copied_bytes(project):
    for name in ('output/render.mp4', 'source_cache/original.mp4', 'tests/__pycache__/x.py',
                 'scripts/history/old.py', 'docs/reports/camera_final_20261015/backup_before/old.py'):
        path = project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'protected')
    document = project / 'docs/reports/camera_final_20261015/RELATORIO.md'
    document.write_text('camera report', encoding='utf-8')
    destination = project / 'docs/reports/camera_package/update_package'
    archive = builder.build(destination, documentation=[document])
    manifest = json.loads((destination / 'UPDATE_MANIFEST.json').read_text(encoding='utf-8'))
    rows = {row['path']: row for row in manifest['files']}
    assert set(rows) == {'ldporto_curator/final_camera.py', 'scripts/INSTALL_CAMERA_FINAL.ps1',
                         'docs/reports/camera_final_20261015/RELATORIO.md'}
    assert rows['ldporto_curator/final_camera.py']['before_sha256'] == digest(b'old-camera')
    assert rows['scripts/INSTALL_CAMERA_FINAL.ps1']['before_sha256'] is None
    with zipfile.ZipFile(archive) as package:
        for name, row in rows.items():
            payload = package.read('payload/' + name)
            assert digest(payload) == row['sha256']
            assert len(payload) == row['bytes']
        assert all(not name.endswith('.mp4') for name in package.namelist())
    assert archive.with_suffix('.zip.sha256').read_text().split()[0] == digest(archive.read_bytes())
    assert not manifest['approval_granted'] and not manifest['automatic_batch_render']
    assert (project / 'output/render.mp4').read_bytes() == b'protected'


@pytest.mark.parametrize('name', ['output/x.py', 'scripts/source/x.py', 'tests/history/old.json',
                                'docs/reports/backup_before/x.md', 'tests/../escape.py',
                                'scripts/CON.py', 'scripts/x.py.', 'scripts/x.py ',
                                'scripts/x:stream.py', 'scripts//x.py', 'scripts/x.mp4'])
def test_allowlist_rejects_protected_media_and_windows_aliases(name):
    assert not builder.allowed_path(name)


@pytest.mark.parametrize('kind', ['outside', 'output', 'baseline_overlap', 'code', 'old_doc', 'media'])
def test_builder_unsafe_inputs_fail_before_creating_files(project, tmp_path, kind):
    destination = project / 'docs/reports/package/update_package'
    docs = []
    if kind == 'outside':
        destination = tmp_path / 'external'
    elif kind == 'output':
        destination = project / 'output/package'
    elif kind == 'baseline_overlap':
        destination = project / 'docs/reports/camera_final_20261015/package'
    elif kind == 'code':
        destination = project / 'scripts/package'
    elif kind == 'old_doc':
        docs = ['docs/reports/camera_final_20261015/backup_before/x.md']
    elif kind == 'media':
        docs = ['docs/reports/demo.mp4']
    paths = set(project.rglob('*'))
    with pytest.raises(ValueError):
        builder.build(destination, documentation=docs)
    assert set(project.rglob('*')) == paths


def test_source_mutation_during_copy_never_publishes_manifest_or_zip(project, monkeypatch):
    copy = builder.shutil.copy2

    def mutate(source, target, *args, **kwargs):
        result = copy(source, target, *args, **kwargs)
        if Path(source).name == 'final_camera.py':
            Path(source).write_bytes(b'concurrent-edit')
        return result

    monkeypatch.setattr(builder.shutil, 'copy2', mutate)
    destination = project / 'docs/reports/package/update_package'
    with pytest.raises(RuntimeError, match='mudou durante'):
        builder.build(destination)
    assert not (destination / 'UPDATE_MANIFEST.json').exists()
    assert not (destination.parent / 'UPDATE_CAMERA_FINAL.zip').exists()


def directory_link(link, destination):
    if os.name == 'nt':
        result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(destination)],
                                capture_output=True, text=True)
        if result.returncode:
            pytest.skip('Junction indisponivel: ' + result.stderr)
    else:
        link.symlink_to(destination, target_is_directory=True)


def test_builder_rejects_link_without_collecting_external_content(project, tmp_path):
    outside = tmp_path / 'private'
    outside.mkdir()
    (outside / 'secret.py').write_bytes(b'private')
    directory_link(project / 'scripts/linked', outside)
    destination = project / 'docs/reports/package/update_package'
    with pytest.raises(ValueError, match='Links/junctions'):
        builder.build(destination)
    assert not destination.exists()


def installer_fixture(tmp_path, extra=()):
    target, package = tmp_path / 'target', tmp_path / 'package'
    (target / 'ldporto_curator').mkdir(parents=True)
    rows = [('ldporto_curator/final_camera.py', b'new-camera', b'old-camera'),
            ('scripts/new_camera_tool.py', b'new-tool', None), *extra]
    manifest = []
    for name, new, old in rows:
        if old is not None:
            path = target / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(old)
        payload = package / 'payload' / name
        payload.parent.mkdir(parents=True, exist_ok=True)
        payload.write_bytes(new)
        manifest.append({'path': name, 'sha256': digest(new), 'before_sha256': digest(old) if old is not None else None})
    protected = ['output/video.mp4', 'output/project.json', 'output/APPROVAL.json', 'output/MANIFEST.json',
                 'output/history/revision.json', '.cache/x', 'source_cache/source.mp4', '.venv/x',
                 'backups/old/saved.mp4', 'config.yaml']
    for name in protected:
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(('preserve-' + name).encode())
    (package / 'UPDATE_MANIFEST.json').write_text(json.dumps({'schema': 'LDP_CAMERA_PATCH_V1', 'files': manifest}), encoding='utf-8')
    return target, package, {name: (target / name).read_bytes() for name in protected}


def invoke(target, package, *args, script=SCRIPT):
    return subprocess.run([POWERSHELL, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script),
                           '-TargetRoot', str(target), '-PackageRoot', str(package), *args],
                          capture_output=True, text=True, timeout=40)


def journal(target):
    return next((target / 'backups').glob('camera_final_*/TRANSACTION.json'))


def assert_protected(target, expected):
    assert {name: (target / name).read_bytes() for name in expected} == expected


@shell
def test_real_verify_install_idempotence_and_rollback_preserve_all_user_data(tmp_path):
    target, package, protected = installer_fixture(tmp_path, [('docs/architecture/CAMERA.md', b'new-doc', None)])
    before = {path.relative_to(target).as_posix(): path.read_bytes() for path in target.rglob('*') if path.is_file()}
    result = invoke(target, package, '-VerifyOnly')
    assert result.returncode == 0, result.stderr
    assert {path.relative_to(target).as_posix(): path.read_bytes() for path in target.rglob('*') if path.is_file()} == before
    result = invoke(target, package)
    assert result.returncode == 0, result.stderr
    transaction = journal(target)
    state = json.loads(transaction.read_text(encoding='utf-8-sig'))
    assert state['status'] == 'INSTALLED'
    assert all(row['state'] == 'APPLIED' for row in state['files'])
    assert invoke(target, package).returncode == 0
    assert len(list((target / 'backups').glob('camera_final_*'))) == 1
    relative = transaction.relative_to(target).as_posix()
    (target / 'scripts/new_camera_tool.py').write_bytes(b'local-edit')
    assert invoke(target, package, '-Rollback', relative).returncode != 0
    assert (target / 'ldporto_curator/final_camera.py').read_bytes() == b'new-camera'
    (target / 'scripts/new_camera_tool.py').write_bytes(b'new-tool')
    assert invoke(target, package, '-Rollback', relative, '-VerifyOnly').returncode == 0
    result = invoke(target, package, '-Rollback', relative)
    assert result.returncode == 0, result.stderr
    assert (target / 'ldporto_curator/final_camera.py').read_bytes() == b'old-camera'
    assert not (target / 'scripts/new_camera_tool.py').exists()
    assert not (target / 'docs/architecture/CAMERA.md').exists()
    assert invoke(target, package, '-Rollback', relative).returncode == 0
    assert_protected(target, protected)


@shell
@pytest.mark.parametrize('kind', ['payload', 'local', 'traversal', 'output', 'source', 'backup',
                                'duplicate', 'case_alias', 'reserved', 'media', 'bad_hash'])
def test_installer_preflight_is_atomic_for_tampering_aliases_and_protected_paths(tmp_path, kind):
    target, package, protected = installer_fixture(tmp_path)
    manifest_path = package / 'UPDATE_MANIFEST.json'
    manifest = json.loads(manifest_path.read_text())
    original = b'old-camera'
    if kind == 'payload':
        (package / 'payload/scripts/new_camera_tool.py').write_bytes(b'corrupt')
    elif kind == 'local':
        original = b'local-edited-camera'
        (target / 'ldporto_curator/final_camera.py').write_bytes(original)
    elif kind in {'duplicate', 'case_alias'}:
        row = dict(manifest['files'][0])
        if kind == 'case_alias':
            row['path'] = row['path'].upper()
        manifest['files'].append(row)
    elif kind == 'bad_hash':
        manifest['files'][1]['sha256'] = 'bad'
    else:
        manifest['files'][1]['path'] = {'traversal': 'scripts/../../escape.py',
                                     'output': 'output/APPROVAL.json', 'source': 'scripts/source/original.py',
                                     'backup': 'docs/reports/backup_before/old.md',
                                     'reserved': 'scripts/NUL.py', 'media': 'tests/demo.mp4'}[kind]
    manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
    assert invoke(target, package).returncode != 0
    assert not list((target / 'backups').glob('camera_final_*'))
    assert (target / 'ldporto_curator/final_camera.py').read_bytes() == original
    assert not (target / 'scripts/new_camera_tool.py').exists()
    assert_protected(target, protected)


@shell
def test_abrupt_process_exit_after_replace_is_recoverable_from_per_file_journal(tmp_path):
    target, package, protected = installer_fixture(tmp_path)
    interrupted = tmp_path / 'interrupted_install.ps1'
    interrupted.write_text(SCRIPT.read_text(encoding='utf-8').replace("$row.state = 'APPLIED'", "[Environment]::Exit(91)\n        $row.state = 'APPLIED'"), encoding='utf-8')
    result = invoke(target, package, script=interrupted)
    assert result.returncode == 91, result.stderr
    transaction = journal(target)
    state = json.loads(transaction.read_text(encoding='utf-8-sig'))
    assert state['status'] == 'INSTALLING' and state['files'][0]['state'] == 'APPLYING'
    assert (target / 'ldporto_curator/final_camera.py').read_bytes() == b'new-camera'
    assert invoke(target, package).returncode != 0
    relative = transaction.relative_to(target).as_posix()
    result = invoke(target, package, '-Rollback', relative)
    assert result.returncode == 0, result.stderr
    assert (target / 'ldporto_curator/final_camera.py').read_bytes() == b'old-camera'
    assert not (target / 'scripts/new_camera_tool.py').exists()
    assert_protected(target, protected)


@shell
def test_interruption_during_backup_copy_needs_no_partial_backup_to_restore_original(tmp_path):
    target, package, protected = installer_fixture(tmp_path)
    interrupted = tmp_path / 'interrupted_backup.ps1'
    interrupted.write_text(SCRIPT.read_text(encoding='utf-8').replace(
        'if ((Hash-File $backup) -ne $row.before_sha256)',
        "[IO.File]::WriteAllText($backup, 'partial-backup'); [Environment]::Exit(93)\n            if ((Hash-File $backup) -ne $row.before_sha256)"), encoding='utf-8')
    result = invoke(target, package, script=interrupted)
    assert result.returncode == 93, result.stderr
    transaction = journal(target)
    assert json.loads(transaction.read_text(encoding='utf-8-sig'))['status'] == 'PREPARING'
    assert (target / 'ldporto_curator/final_camera.py').read_bytes() == b'old-camera'
    result = invoke(target, package, '-Rollback', transaction.relative_to(target).as_posix())
    assert result.returncode == 0, result.stderr
    assert (target / 'ldporto_curator/final_camera.py').read_bytes() == b'old-camera'
    assert not (target / 'scripts/new_camera_tool.py').exists()
    assert_protected(target, protected)


@shell
def test_abrupt_rollback_exit_can_resume_after_restoration_before_journal_update(tmp_path):
    target, package, protected = installer_fixture(tmp_path)
    assert invoke(target, package).returncode == 0
    transaction = journal(target)
    relative = transaction.relative_to(target).as_posix()
    interrupted = tmp_path / 'interrupted_rollback.ps1'
    interrupted.write_text(SCRIPT.read_text(encoding='utf-8').replace("$row.state = 'RESTORED'", "[Environment]::Exit(92)\n        $row.state = 'RESTORED'"), encoding='utf-8')
    result = invoke(target, package, '-Rollback', relative, script=interrupted)
    assert result.returncode == 92, result.stderr
    assert (target / 'ldporto_curator/final_camera.py').read_bytes() == b'old-camera'
    assert json.loads(transaction.read_text(encoding='utf-8-sig'))['status'] == 'ROLLING_BACK'
    result = invoke(target, package, '-Rollback', relative)
    assert result.returncode == 0, result.stderr
    assert not (target / 'scripts/new_camera_tool.py').exists()
    assert_protected(target, protected)


@shell
def test_mid_install_failure_automatically_restores_prior_files(tmp_path):
    target, package, protected = installer_fixture(tmp_path, [('scripts/blocked/file.py', b'new', None)])
    (target / 'scripts').mkdir()
    (target / 'scripts/blocked').write_bytes(b'parent-file')
    result = invoke(target, package)
    assert result.returncode != 0
    assert (target / 'ldporto_curator/final_camera.py').read_bytes() == b'old-camera'
    assert not (target / 'scripts/new_camera_tool.py').exists()
    assert json.loads(journal(target).read_text(encoding='utf-8-sig'))['status'] == 'FAILED_ROLLED_BACK'
    assert_protected(target, protected)


@shell
@pytest.mark.parametrize('kind', ['backup_hash', 'backup_redirect', 'other_target'])
def test_corrupt_or_redirected_rollback_journal_changes_nothing(tmp_path, kind):
    target, package, protected = installer_fixture(tmp_path)
    assert invoke(target, package).returncode == 0
    transaction = journal(target)
    state = json.loads(transaction.read_text(encoding='utf-8-sig'))
    if kind == 'backup_hash':
        (target / state['files'][0]['backup']).write_bytes(b'corrupt')
    elif kind == 'backup_redirect':
        state['files'][0]['backup'] = 'output/video.mp4'
    else:
        state['target_root'] = str(tmp_path / 'different')
    transaction.write_text(json.dumps(state), encoding='utf-8')
    assert invoke(target, package, '-Rollback', transaction.relative_to(target).as_posix()).returncode != 0
    assert (target / 'ldporto_curator/final_camera.py').read_bytes() == b'new-camera'
    assert (target / 'scripts/new_camera_tool.py').read_bytes() == b'new-tool'
    assert_protected(target, protected)


@shell
@pytest.mark.parametrize('scope', ['target', 'payload', 'package_root', 'target_root'])
def test_installer_rejects_junctions_even_when_root_itself_is_a_link(tmp_path, scope):
    target, package, protected = installer_fixture(tmp_path)
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'new_camera_tool.py').write_bytes(b'new-tool')
    actual_target = target
    if scope == 'target':
        directory_link(target / 'scripts', outside)
    elif scope == 'payload':
        (package / 'payload/scripts').rename(package / 'payload/scripts_original')
        directory_link(package / 'payload/scripts', outside)
    elif scope == 'package_root':
        linked = tmp_path / 'linked_package'
        directory_link(linked, package)
        package = linked
    else:
        linked = tmp_path / 'linked_target'
        directory_link(linked, target)
        actual_target = linked
    assert invoke(actual_target, package).returncode != 0
    assert (target / 'ldporto_curator/final_camera.py').read_bytes() == b'old-camera'
    assert (outside / 'new_camera_tool.py').read_bytes() == b'new-tool'
    assert_protected(target, protected)


@shell
def test_packaged_installer_native_invocation_resolves_its_package_root(tmp_path):
    target, package, protected = installer_fixture(tmp_path)
    packaged_script = package / SCRIPT.name
    shutil.copy2(SCRIPT, packaged_script)
    result = subprocess.run([POWERSHELL, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(packaged_script),
                             '-TargetRoot', str(target), '-VerifyOnly'], capture_output=True, text=True, timeout=40)
    assert result.returncode == 0, result.stderr
    assert not list((target / 'backups').glob('camera_final_*'))
    assert_protected(target, protected)
