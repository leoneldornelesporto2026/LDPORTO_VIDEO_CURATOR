"""Exercise the real PowerShell installer against disposable synthetic projects."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/INSTALL_CAPTIONS_P0.ps1'
POWERSHELL = shutil.which('powershell') or shutil.which('pwsh')
pytestmark = pytest.mark.skipif(not POWERSHELL, reason='PowerShell ausente')


def digest(value):
    return hashlib.sha256(value).hexdigest()


def fixture(tmp_path, extra=None):
    target, package = tmp_path / 'target', tmp_path / 'package'
    (target / 'ldporto_curator').mkdir(parents=True)
    (target / 'ldporto_curator/subtitle_presets.py').write_bytes(b'old-code')
    (target / 'output').mkdir()
    (target / 'output/APPROVAL.json').write_bytes(b'protected-approval')
    rows = [('ldporto_curator/subtitle_presets.py', b'new-code', b'old-code'),
            ('scripts/new_tool.py', b'new-tool', None)]
    if extra:
        rows.extend(extra)
    manifest = []
    for name, new, old in rows:
        if old is not None:
            original = target / name
            original.parent.mkdir(parents=True, exist_ok=True)
            original.write_bytes(old)
        path = package / 'payload' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(new)
        manifest.append({'path': name, 'sha256': digest(new), 'before_sha256': digest(old) if old else None})
    (package / 'UPDATE_MANIFEST.json').write_text(json.dumps({'schema': 'LDP_CAPTION_PATCH_V1', 'files': manifest}), encoding='utf-8')
    return target, package


def invoke(target, package, *args):
    return subprocess.run([POWERSHELL, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(SCRIPT),
                           '-TargetRoot', str(target), '-PackageRoot', str(package), *args], capture_output=True, text=True)


def test_real_verify_install_idempotence_and_hash_checked_rollback(tmp_path):
    target, package = fixture(tmp_path)
    result = invoke(target, package, '-VerifyOnly')
    assert result.returncode == 0, result.stderr
    assert not (target / 'backups').exists()
    result = invoke(target, package)
    assert result.returncode == 0, result.stderr
    assert (target / 'ldporto_curator/subtitle_presets.py').read_bytes() == b'new-code'
    transactions = list((target / 'backups').glob('*/TRANSACTION.json'))
    assert len(transactions) == 1
    assert invoke(target, package).returncode == 0
    # Edits after installation prevent rollback BEFORE modifying any file.
    (target / 'scripts/new_tool.py').write_bytes(b'user-edit')
    relative = transactions[0].relative_to(target).as_posix()
    assert invoke(target, package, '-Rollback', relative).returncode != 0
    assert (target / 'ldporto_curator/subtitle_presets.py').read_bytes() == b'new-code'
    (target / 'scripts/new_tool.py').write_bytes(b'new-tool')
    result = invoke(target, package, '-Rollback', relative)
    assert result.returncode == 0, result.stderr
    assert (target / 'ldporto_curator/subtitle_presets.py').read_bytes() == b'old-code'
    assert not (target / 'scripts/new_tool.py').exists()
    assert (target / 'output/APPROVAL.json').read_bytes() == b'protected-approval'
    assert transactions[0].is_file()


@pytest.mark.parametrize('kind', ['payload', 'local', 'traversal'])
def test_real_preflight_rejects_tampering_and_escape_without_mutation(tmp_path, kind):
    target, package = fixture(tmp_path)
    original = b'old-code'
    if kind == 'payload':
        (package / 'payload/scripts/new_tool.py').write_bytes(b'corrupt')
    elif kind == 'local':
        original = b'user-local-code'
        (target / 'ldporto_curator/subtitle_presets.py').write_bytes(original)
    else:
        manifest = json.loads((package / 'UPDATE_MANIFEST.json').read_text())
        manifest['files'][0]['path'] = 'scripts/../../escape.py'
        (package / 'UPDATE_MANIFEST.json').write_text(json.dumps(manifest))
    assert invoke(target, package).returncode != 0
    assert (target / 'ldporto_curator/subtitle_presets.py').read_bytes() == original
    assert not (target / 'backups').exists()
    assert not (target / 'scripts/new_tool.py').exists()


def test_mid_install_failure_restores_already_copied_code(tmp_path):
    target, package = fixture(tmp_path, [('scripts/blocked/file.py', b'new', None)])
    (target / 'scripts').mkdir()
    (target / 'scripts/blocked').write_bytes(b'parent-is-file')
    result = invoke(target, package)
    assert result.returncode != 0
    assert (target / 'ldporto_curator/subtitle_presets.py').read_bytes() == b'old-code'
    assert not (target / 'scripts/new_tool.py').exists()
    assert (target / 'scripts/blocked').read_bytes() == b'parent-is-file'
    transaction = next((target / 'backups').glob('*/TRANSACTION.json'))
    assert json.loads(transaction.read_text(encoding='utf-8-sig'))['status'] == 'FAILED_ROLLED_BACK'


@pytest.mark.parametrize('kind', ['duplicate', 'duplicate_case', 'dot_alias', 'empty_component', 'trailing_dot', 'trailing_space', 'protected_output'])
def test_manifest_scope_and_duplicate_checks_are_atomic(tmp_path, kind):
    target, package = fixture(tmp_path)
    path = package / 'UPDATE_MANIFEST.json'
    manifest = json.loads(path.read_text(encoding='utf-8'))
    if kind == 'protected_output':
        manifest['files'][1]['path'] = 'output/APPROVAL.json'
    else:
        duplicate = dict(manifest['files'][1] if kind in {'dot_alias', 'empty_component', 'trailing_dot', 'trailing_space'} else manifest['files'][0])
        if kind == 'duplicate_case':
            duplicate['path'] = duplicate['path'].upper()
        elif kind == 'dot_alias':
            duplicate['path'] = 'scripts/./new_tool.py'
        elif kind == 'empty_component':
            duplicate['path'] = 'scripts//new_tool.py'
        elif kind == 'trailing_dot':
            duplicate['path'] = 'scripts/new_tool.py.'
        elif kind == 'trailing_space':
            duplicate['path'] = 'scripts/new_tool.py '
        manifest['files'].append(duplicate)
    path.write_text(json.dumps(manifest), encoding='utf-8')
    assert invoke(target, package).returncode != 0
    assert (target / 'ldporto_curator/subtitle_presets.py').read_bytes() == b'old-code'
    assert (target / 'output/APPROVAL.json').read_bytes() == b'protected-approval'
    assert not (target / 'scripts/new_tool.py').exists()
    assert not (target / 'backups').exists()


def test_corrupt_backup_refuses_entire_rollback_before_touching_installed_files(tmp_path):
    target, package = fixture(tmp_path)
    result = invoke(target, package)
    assert result.returncode == 0, result.stderr
    transaction_path = next((target / 'backups').glob('*/TRANSACTION.json'))
    transaction = json.loads(transaction_path.read_text(encoding='utf-8-sig'))
    backed_up = next(row for row in transaction['files'] if row['before_sha256'])
    (target / backed_up['backup']).write_bytes(b'corrupt-backup')
    result = invoke(target, package, '-Rollback', transaction_path.relative_to(target).as_posix())
    assert result.returncode != 0
    assert (target / 'ldporto_curator/subtitle_presets.py').read_bytes() == b'new-code'
    assert (target / 'scripts/new_tool.py').read_bytes() == b'new-tool'
    assert json.loads(transaction_path.read_text(encoding='utf-8-sig'))['status'] == 'INSTALLED'


def directory_link(link, destination):
    if os.name == 'nt':
        result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(destination)],
                                capture_output=True, text=True)
        if result.returncode:
            pytest.skip('Junction indisponível: ' + result.stderr)
    else:
        link.symlink_to(destination, target_is_directory=True)


@pytest.mark.parametrize('scope', ['target', 'payload'])
def test_junction_cannot_redirect_package_or_target_outside_its_root(tmp_path, scope):
    target, package = fixture(tmp_path)
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'new_tool.py').write_bytes(b'new-tool')
    if scope == 'target':
        directory_link(target / 'scripts', outside)
    else:
        (package / 'payload/scripts').rename(package / 'payload/scripts_original')
        directory_link(package / 'payload/scripts', outside)
    assert invoke(target, package).returncode != 0
    assert (target / 'ldporto_curator/subtitle_presets.py').read_bytes() == b'old-code'
    assert (outside / 'new_tool.py').read_bytes() == b'new-tool'
    assert (target / 'output/APPROVAL.json').read_bytes() == b'protected-approval'
    assert not (target / 'backups').exists()


def test_readme_and_caption_architecture_install_and_rollback_with_same_guards(tmp_path):
    target, package = fixture(tmp_path, [
        ('README.md', b'new-readme', b'user-baseline-readme'),
        ('docs/architecture/LEGENDAS_WORD_ALIGNED.md', b'caption-contract', None),
    ])
    result = invoke(target, package)
    assert result.returncode == 0, result.stderr
    assert (target / 'README.md').read_bytes() == b'new-readme'
    assert (target / 'docs/architecture/LEGENDAS_WORD_ALIGNED.md').read_bytes() == b'caption-contract'
    transaction_path = next((target / 'backups').glob('*/TRANSACTION.json'))
    result = invoke(target, package, '-Rollback', transaction_path.relative_to(target).as_posix())
    assert result.returncode == 0, result.stderr
    assert (target / 'README.md').read_bytes() == b'user-baseline-readme'
    assert not (target / 'docs/architecture/LEGENDAS_WORD_ALIGNED.md').exists()
