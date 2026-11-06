"""Explicit local asset bindings for R6 -> R57. No generated assets or approval."""
from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import re
import stat

from .core import atomic_write, fingerprint, sha256_file
from .r6_r57_bridge import prepare_r57_bridge
from .workspace import application_root

SCHEMA = 'ldporto-r6-r57-assets-1.0'
FIELDS = ('thumbnail', 'caption_ass', 'caption_srt')
MAX_BYTES = {'thumbnail': 20*1024**2, 'caption_ass': 5*1024**2, 'caption_srt': 5*1024**2}
SUFFIXES = {'thumbnail': ('.png', '.jpg', '.jpeg'),
            'caption_ass': ('.ass',), 'caption_srt': ('.srt',)}


def _not_linked(path):
    if (path.is_symlink() or getattr(path.lstat(), 'st_file_attributes', 0)
            & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 1024)):
        raise ValueError('Link/junction proibido no asset')


def asset_template(inbox, draft, story_proposal):
    proposal = Path(story_proposal).expanduser()
    if not proposal.is_file() or proposal.is_symlink():
        raise ValueError('Proposta de Stories obrigatória')
    plan = prepare_r57_bridge(inbox, draft, story_proposal_path=proposal)
    clips = [{'id': row['id'], 'kind': kind, 'assets': {key: None for key in FIELDS}}
             for kind, rows in (('reels', plan['r57_reel_slots']),
                                ('stories', plan['r57_story_boundary_proposals']))
             for row in rows]
    return {'schema_version': SCHEMA,
            'provenance': dict(plan['provenance'], story_proposal_sha256=sha256_file(proposal)),
            'clips': clips, 'clip_count': len(clips),
            'human_approved': False, 'r57_import_ready': False,
            'render_ready': False, 'publication_ready': False}


def save_asset_template(inbox, draft, story_proposal, destination_root=None):
    template = asset_template(inbox, draft, story_proposal)
    root = (Path(destination_root).expanduser().resolve() if destination_root
            else application_root() / 'output' / 'r6_bridge')
    output = (root / template['provenance']['source_sha256'][:16] /
              ('R6_ASSETS_' + fingerprint(template)[:20] + '.json'))
    if output.exists():
        original = json.loads(output.read_text(encoding='utf-8'))
        if fingerprint(original) != fingerprint(template):
            raise ValueError('Template existente divergente')
        return output
    atomic_write(output, template)
    return output


def _verify_asset(root, raw, kind):
    if not isinstance(raw, str) or not raw or len(raw) > 250 or '\\' in raw or ':' in raw:
        raise ValueError('Caminho relativo inválido')
    relative = PurePosixPath(raw)
    if (relative.is_absolute() or relative.as_posix() != raw
            or any(part in ('.', '..') or part.endswith((' ', '.')) for part in relative.parts)
            or relative.suffix.lower() not in SUFFIXES[kind]):
        raise ValueError('Path traversal ou extensão inválida')
    root = Path(root).expanduser()
    if not root.is_dir():
        raise ValueError('Pasta de assets inexistente')
    _not_linked(root)
    anchor = root.resolve(strict=True)
    target = anchor
    for part in relative.parts:
        target = target / part
        if target.exists() or target.is_symlink():
            _not_linked(target)
    if not target.is_file() or not target.resolve(strict=True).is_relative_to(anchor):
        raise ValueError('Asset fora da pasta ou ausente')
    if not 0 < target.stat().st_size <= MAX_BYTES[kind]:
        raise ValueError('Asset vazio ou grande demais')
    if kind == 'thumbnail':
        from PIL import Image
        try:
            with Image.open(target) as image:
                if (image.format not in ('PNG', 'JPEG') or not 1 <= image.width <= 10000
                        or not 1 <= image.height <= 10000):
                    raise ValueError('Capa incompatível')
                image.verify()
        except OSError as exc:
            raise ValueError('Capa inválida') from exc
    else:
        try:
            data = target.read_bytes().decode('utf-8-sig')
        except UnicodeDecodeError as exc:
            raise ValueError('Legenda não é UTF-8') from exc
        if '\x00' in data:
            raise ValueError('Legenda contém NUL')
        if kind == 'caption_ass' and not all(x in data for x in ('[Script Info]', '[Events]', 'Dialogue:')):
            raise ValueError('ASS sem eventos')
        if kind == 'caption_srt' and not re.search(
                r'\d\d:\d\d:\d\d,\d{3}\s*-->\s*\d\d:\d\d:\d\d,\d{3}', data):
            raise ValueError('SRT sem timestamps')
    return {'relative_path': raw, 'bytes': target.stat().st_size,
            'sha256': sha256_file(target), 'format_checked': True,
            'caption_alignment_verified': False}


def audit_asset_bindings(inbox, draft, story_proposal, bindings_path, assets_root):
    expected = asset_template(inbox, draft, story_proposal)
    source = Path(bindings_path).expanduser()
    if (not source.is_file() or source.is_symlink()
            or not 0 < source.stat().st_size <= 1024*1024):
        raise ValueError('Manifesto de assets ausente ou inseguro')
    digest = sha256_file(source)
    binding = json.loads(source.read_text(encoding='utf-8'))
    if not isinstance(binding, dict):
        raise ValueError('Manifesto de assets deve ser objeto')
    for key in ('schema_version', 'provenance', 'clip_count'):
        if binding.get(key) != expected[key]:
            raise ValueError('Proveniência divergente: ' + key)
    for key in ('human_approved', 'r57_import_ready', 'render_ready', 'publication_ready'):
        if binding.get(key) is not False:
            raise ValueError('Aprovação falsa em bindings: ' + key)
    rows = binding.get('clips')
    if not isinstance(rows, list) or len(rows) != len(expected['clips']):
        raise ValueError('Contagem dos cortes não corresponde ao R6')
    verified, missing = [], []
    for row, canonical in zip(rows, expected['clips']):
        if (not isinstance(row, dict) or row.get('id') != canonical['id']
                or row.get('kind') != canonical['kind']):
            raise ValueError('Cortes reordenados ou divergentes')
        assets = row.get('assets')
        if not isinstance(assets, dict) or set(assets) != set(FIELDS):
            raise ValueError('Campos de assets inválidos')
        checked = {}
        for kind in FIELDS:
            value = assets[kind]
            if value is None or value == '':
                missing.append(row['id'] + ':' + kind)
                checked[kind] = None
            else:
                checked[kind] = _verify_asset(assets_root, value, kind)
        verified.append({'id': row['id'], 'kind': row['kind'], 'assets': checked})
    if sha256_file(source) != digest:
        raise ValueError('Bindings modificados durante verificação')
    return {'schema_version': 'ldporto-r6-r57-asset-audit-1.0',
            'status': 'STRUCTURAL_ASSETS_VERIFIED_REVIEW_PENDING' if not missing else 'ASSETS_MISSING',
            'clips': verified, 'missing_assets': missing,
            'assets_verified': sum(bool(v) for row in verified for v in row['assets'].values()),
            'bindings_sha256': digest, 'source_provenance': expected['provenance'],
            'r57_zip_generated': False, 'r57_import_ready': False,
            'human_approved': False, 'render_ready': False, 'publication_ready': False,
            'caption_alignment_verified': False, 'story_review_verified': False}
