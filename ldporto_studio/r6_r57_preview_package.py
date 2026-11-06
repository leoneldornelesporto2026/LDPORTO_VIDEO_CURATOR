"""Build a genuine Studio R57 importable PREVIEW DRAFT from real R6-selected assets.

An explicit human R6 Reel selection is required, along with the source-bound
technical Story boundary proposal and actual locally-supplied image/ASS/SRT files.
The output ZIP contains no media, no fabricated caption lines and no approvals.
The existing CuradoriaPackage verifier must accept the assembled archive before
it is published under output/r6_bridge/. Rendering finals remains blocked by
Project's independent preview + human approval + rights checks.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from .core import CuradoriaPackage, fingerprint, json_bytes, sha256_bytes, sha256_file
from .r6_asset_bindings import _verify_asset, audit_asset_bindings
from .r6_r57_bridge import prepare_r57_bridge
from .r6_review import read_analyzer_review
from .workspace import application_root

MAX_R57_FILES = 1500
MAX_TOTAL_BYTES = 256 * 1024 * 1024
REQUIRED_PER_CLIP = ('thumbnail', 'caption_ass', 'caption_srt')
REVIEW_STATUS = 'DRAFT_NOT_HUMAN_REVIEWED'


def _source_bytes(assets_root, info, field):
    """Reopen only audited, relative local files and prove they stayed unchanged."""
    expected = info[field]
    if expected is None:
        raise ValueError('Asset não fornecido: ' + field)
    record = _verify_asset(assets_root, expected['relative_path'], field)
    if (record['sha256'] != expected['sha256']
            or record['bytes'] != expected['bytes']):
        raise ValueError('Asset mudou durante a montagem: ' + expected['relative_path'])
    root = Path(assets_root).expanduser().resolve(strict=True)
    path = root.joinpath(*expected['relative_path'].split('/'))
    data = path.read_bytes()
    if sha256_bytes(data) != record['sha256'] or len(data) != record['bytes']:
        raise ValueError('Asset alterado durante a leitura: ' + expected['relative_path'])
    return data


def prepare_preview_archive(inbox, draft, story_proposal, bindings, assets_root):
    """No output on disk. Revalidate all inputs, then assemble bounded bytes."""
    bridge = prepare_r57_bridge(inbox, draft, story_proposal_path=story_proposal)
    report = audit_asset_bindings(inbox, draft, story_proposal, bindings, assets_root)
    if report['missing_assets']:
        raise ValueError(
            'Assets obrigatórios ausentes: ' + ', '.join(report['missing_assets'][:15]))
    if report['status'] != 'STRUCTURAL_ASSETS_VERIFIED_REVIEW_PENDING':
        raise ValueError('Auditoria de assets não concluída')
    provenance = bridge['provenance']
    if report['source_provenance']['source_zip_sha256'] != provenance['source_zip_sha256']:
        raise ValueError('Origem diverge entre auditoria e R6')
    reels = bridge['r57_reel_slots']
    stories = bridge['r57_story_boundary_proposals']
    if not reels or not stories:
        raise ValueError('Seleção explícita de Reel e proposta de Stories obrigatórias')
    if len(reels) + len(stories) != len(report['clips']):
        raise ValueError('Contagem de cortes e assets divergente')
    if (4 * len(report['clips']) + 5) > MAX_R57_FILES:
        raise ValueError('Número de assets excede limite de entradas do Studio')
    # Bound memory BEFORE reading real images/captions into the ZIP builder.
    total_input_bytes = sum(
        asset['bytes']
        for row in report['clips'] for asset in row['assets'].values()
        if asset is not None)
    if total_input_bytes > MAX_TOTAL_BYTES - (8 * 1024 * 1024):
        raise ValueError('Arquivos de assets excedem o limite de montagem da prévia')

    all_files = {}
    clip_rows = {'reels': [], 'stories': []}
    input_rows = reels + stories
    for clip, audited in zip(input_rows, report['clips']):
        cid = clip['id']
        kind = 'reels' if cid.startswith('REEL_') else 'stories'
        if audited['id'] != cid or audited['kind'] != kind:
            raise ValueError('Associação de asset a corte incorreta: ' + cid)
        prefix = ('REELS' if kind == 'reels' else 'STORIES') + '/' + cid
        # The Studio exporter names covers CAPA.png. Never relabel JPEG bytes
        # as PNG: for this first preview-draft builder require real PNG input.
        image = audited['assets']['thumbnail']['relative_path']
        if not image.lower().endswith('.png'):
            raise ValueError('Capa do pacote preview precisa ser PNG real: ' + cid)
        names = {
            'thumbnail': prefix + '/CAPA.png',
            'caption_ass': prefix + '/KARAOKE.ass',
            'caption_srt': prefix + '/LEGENDA.srt',
        }
        for field, name in names.items():
            all_files[name] = _source_bytes(assets_root, audited['assets'], field)
        review_path = prefix + '/LEGENDA_REVISAO.json'
        all_files[review_path] = json_bytes({
            'status': 'ASR_DRAFT_NOT_VERIFIED',
            'source': 'EXPLICIT_LOCAL_ASSETS_NOT_VERIFIED_AGAINST_AUDIO',
            'captions_verified': False,
            'human_approved': False,
            'audio_alignment_verified': False,
        })
        clip_rows[kind].append({
            'id': cid,
            'source_start': clip['source_start'],
            'source_end': clip['source_end'],
            'duration_seconds': clip['duration_seconds'],
            'title': clip['title_for_review'],
            'thumbnail': names['thumbnail'],
            'caption_ass': names['caption_ass'],
            'caption_srt': names['caption_srt'],
        })

    source = provenance['source_sha256']
    duration = provenance['source_duration_seconds']
    run_id = provenance['r6_run_id']
    source_review = read_analyzer_review(inbox)
    source_metadata = source_review['source']
    if (source_metadata['run_id'] != run_id
            or source_metadata['source_sha256'] != source):
        raise ValueError('Identidade da fonte mudou durante a preparação do R57')
    all_files['EXECUTION_PLAN.json'] = json_bytes({
        'source_title': source_metadata['title'],
        'source_url': source_metadata.get('url', ''),
        'source_sha256': source,
        'source_duration_seconds': duration,
        'run_id': run_id,
        'reels': clip_rows['reels'],
        'stories': clip_rows['stories'],
        'editorial_status': REVIEW_STATUS,
        'r6_source_zip_sha256': provenance['source_zip_sha256'],
        'story_boundary_origin': 'TECHNICAL_DURATION_SPLIT_NOT_ANALYZER_STORY',
        'human_approved': False, 'publication_ready': False,
    })
    all_files['REELS_EDIT_PLAN.json'] = json_bytes({
        'source_sha256': source,
        'clips': [{
            'id': row['id'],
            'r6_candidate_id': original['r6_candidate_id'],
            'layout_for_review': original['layout_for_review'],
            'camera_reviewed': False, 'audio_reviewed': False,
            'rights_verified': False, 'preview_approved': False,
        } for row, original in zip(clip_rows['reels'], reels)],
        'editorial_status': REVIEW_STATUS,
    })
    all_files['STORIES_SEQUENCIAIS_REVISAR.json'] = json_bytes({
        'source_sha256': source,
        'clips': [{
            'id': row['id'],
            'editorial_review_required': True,
            'boundaries_reviewed': False,
            'rights_verified': False,
        } for row in clip_rows['stories']],
        'editorial_status': REVIEW_STATUS,
    })
    all_files['QUALITY_GATES.json'] = json_bytes({
        'original_source_sha256': source,
        'r6_source_zip_sha256': provenance['source_zip_sha256'],
        'r6_draft_sha256': provenance['r6_draft_sha256'],
        'r6_story_proposal_sha256': report['source_provenance']['story_proposal_sha256'],
        'r6_assets_binding_sha256': report['bindings_sha256'],
        'preview_human_approved': False,
        'publication_ready': False,
        'captions_verified': False,
        'camera_reviewed': False,
        'audio_reviewed': False,
        'rights_verified': False,
        'story_boundaries_reviewed': False,
        'status': REVIEW_STATUS,
        'warning': 'R57 preview draft only. Story windows are technical proposals, not inferred editorial scenes.',
    })
    if len(all_files) + 1 > MAX_R57_FILES:
        raise ValueError('R57 excede o limite de entradas')
    if sum(len(data) for data in all_files.values()) > MAX_TOTAL_BYTES:
        raise ValueError('R57 excede o limite seguro de tamanho')
    all_files['MANIFEST_SHA256.json'] = json_bytes({
        'files': [{
            'path': name,
            'bytes': len(data),
            'sha256': sha256_bytes(data),
        } for name, data in sorted(all_files.items())],
    })
    for path, digest in ((draft, provenance['r6_draft_sha256']),
                         (bindings, report['bindings_sha256']),
                         (story_proposal, report['source_provenance']['story_proposal_sha256'])):
        if sha256_file(path) != digest:
            raise ValueError('Arquivo de entrada modificado durante a montagem')
    return all_files, {
        'status': 'PREVIEW_DRAFT_IMPORTABLE_AFTER_SAVE_NOT_APPROVED',
        'source_sha256': source,
        'source_zip_sha256': provenance['source_zip_sha256'],
        'reels': len(reels), 'technical_stories': len(stories),
        'asset_files': len(reels + stories) * 3,
        'preview_review_required': True,
        'story_editorial_review_required': True,
        'human_approved': False, 'render_ready': False,
        'publication_ready': False, 'media_included': False,
    }


def build_preview_archive(inbox, draft, story_proposal, bindings, assets_root, *,
                          destination_root=None, confirm_preview_only=False):
    """Write a content-addressed ZIP and pass the existing strict R57 loader.

    No overwrite, release/main promotion, media, rendering or project creation.
    """
    if confirm_preview_only is not True:
        raise ValueError('Use --confirm-preview-only para gerar rascunho importável sem aprovação')
    files, summary = prepare_preview_archive(
        inbox, draft, story_proposal, bindings, assets_root)
    output_root = (Path(destination_root).expanduser().resolve() if destination_root
                   else application_root() / 'output' / 'r6_bridge')
    directory = output_root / summary['source_sha256'][:16]
    directory.mkdir(parents=True, exist_ok=True)
    filename = 'R57_PREVIEW_DRAFT_' + fingerprint({
        'source': summary['source_sha256'],
        'files': [(k, sha256_bytes(v)) for k, v in sorted(files.items())],
    })[:20] + '.zip'
    target = directory / filename
    fd, stage_name = tempfile.mkstemp(prefix='.r57-preview-staging-', suffix='.zip', dir=directory)
    os.close(fd)
    stage = Path(stage_name)
    try:
        with ZipFile(stage, 'w', compression=ZIP_DEFLATED, compresslevel=6) as archive:
            for name, content in sorted(files.items()):
                # ZipFile.writestr(name, data) uses the current clock. Fix ZIP
                # metadata so same verified inputs produce identical bytes.
                info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = 0o600 << 16
                info.compress_type = ZIP_DEFLATED
                archive.writestr(info, content, compress_type=ZIP_DEFLATED,
                                 compresslevel=6)
        strict = CuradoriaPackage(stage)
        if (strict.source_sha != summary['source_sha256']
                or len(strict.items('reels')) != summary['reels']
                or len(strict.items('stories')) != summary['technical_stories']):
            raise ValueError('Pacote R57 gerado diverge do preflight')
        # Hardlink creation is no-overwrite and atomic on the same filesystem.
        # In particular, do not use os.replace() over an existing R57 draft.
        try:
            os.link(stage, target)
        except FileExistsError:
            if sha256_file(stage) != sha256_file(target):
                raise ValueError('ZIP de mesmo nome existe com bytes diferentes')
        if sha256_file(target) != sha256_file(stage):
            raise ValueError('ZIP publicado não corresponde ao arquivo validado')
        return {**summary,
                'zip_path': str(target),
                'zip_sha256': sha256_file(target),
                'r57_contract': 'VALIDATED_BY_CuradoriaPackage',
                'r57_importable_for_preview': True,
                'r57_imported': False,
                'render_executed': False,
                'finals_executed': False}
    finally:
        stage.unlink(missing_ok=True)
