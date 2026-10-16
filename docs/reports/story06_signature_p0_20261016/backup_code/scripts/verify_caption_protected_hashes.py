"""Read every original protected file and report preservation without changing it."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat


ROOT = Path(__file__).resolve().parents[1]
PROTECTED = ('output', '.cache', 'source_cache')


def sha(path):
    before = path.stat()
    with path.open('rb') as handle:
        digest = hashlib.file_digest(handle, 'sha256').hexdigest()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise RuntimeError('Arquivo mudou durante a leitura')
    return digest


def is_link(path):
    return path.is_symlink() or bool(getattr(path.lstat(), 'st_file_attributes', 0)
                                    & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0))


def verify(root, baseline_path, source=None, source_sha256=None):
    root = Path(root).resolve()
    original = json.loads(Path(baseline_path).read_text(encoding='utf-8'))['files']
    after, failures, known = [], [], set()
    for row in original:
        name = row['path']
        relative = PurePosixPath(name)
        if (relative.is_absolute() or '\\' in name or ':' in name or '..' in relative.parts
                or not relative.parts or relative.parts[0] not in PROTECTED
                or name in known or not re.fullmatch('[0-9a-f]{64}', row.get('sha256', ''))):
            raise ValueError(f'Entrada inválida no baseline protegido: {name}')
        known.add(name)
        path = root / name
        try:
            if not path.resolve().is_relative_to(root):
                raise ValueError('Caminho protegido redirecionado para fora do projeto')
            digest = sha(path)
            size = path.stat().st_size
            current = {'path': name, 'sha256': digest, 'bytes': size,
                       'matches_before': digest == row['sha256'] and size == row['bytes']}
            after.append(current)
            if not current['matches_before']:
                failures.append({'path': name, 'reason': 'hash_or_size_mismatch',
                                 'before_sha256': row['sha256'], 'after_sha256': digest})
        except (OSError, ValueError, RuntimeError) as exc:
            failures.append({'path': name, 'reason': str(exc)})
    additions, skipped_links = [], []
    for folder in PROTECTED:
        for directory, dirs, files in os.walk(root / folder, followlinks=False):
            for name in list(dirs):
                path = Path(directory) / name
                if is_link(path):
                    dirs.remove(name)
                    skipped_links.append(path.relative_to(root).as_posix())
            for name in files:
                relative = (Path(directory) / name).relative_to(root).as_posix()
                if relative not in known:
                    additions.append(relative)
    verified_source = None
    if source is not None:
        if not source_sha256 or not re.fullmatch('[0-9a-f]{64}', source_sha256):
            raise ValueError('SHA256 esperado obrigatório para verificar a fonte externa')
        source = Path(source).resolve()
        actual = sha(source)
        verified_source = {'path': str(source), 'expected_sha256': source_sha256,
                           'actual_sha256': actual, 'matches': actual == source_sha256}
        if not verified_source['matches']:
            failures.append({'path': str(source), 'reason': 'source_sha256_mismatch'})
    return {'schema': 'LDP_CAPTION_PROTECTED_INTEGRITY_V1',
            'verified_at_utc': datetime.now(timezone.utc).isoformat(),
            'root': str(root), 'baseline': str(Path(baseline_path).resolve()),
            'method': 'Independent SHA256 of every initial output/.cache/source_cache file; no protected writes.',
            'status': 'UNCHANGED' if not failures else 'MISMATCH',
            'original_count': len(original), 'matched_count': sum(row['matches_before'] for row in after),
            'failures': failures, 'verified_source': verified_source,
            'new_files': sorted(additions), 'new_file_policy': 'New derived files are listed separately; original hashes must all remain identical.',
            'enumeration_skipped_links': sorted(skipped_links), 'files': after}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--baseline', type=Path, default=ROOT / 'docs/reports/organizacao_20261015/protected_hashes_before.json')
    parser.add_argument('--report', type=Path, default=ROOT / 'docs/reports/organizacao_20261015/protected_hashes_after.json')
    parser.add_argument('--source', type=Path)
    parser.add_argument('--source-sha256')
    args = parser.parse_args()
    if bool(args.source) != bool(args.source_sha256):
        parser.error('--source e --source-sha256 devem ser usados juntos')
    report = args.report.resolve()
    if not report.is_relative_to(args.root.resolve() / 'docs/reports'):
        parser.error('O relatório deve permanecer em docs/reports; árvores protegidas são somente leitura')
    result = verify(args.root, args.baseline, args.source, args.source_sha256)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: result[key] for key in ('status', 'original_count', 'matched_count', 'failures')}, ensure_ascii=False))
    return 0 if result['status'] == 'UNCHANGED' else 1


if __name__ == '__main__':
    raise SystemExit(main())
