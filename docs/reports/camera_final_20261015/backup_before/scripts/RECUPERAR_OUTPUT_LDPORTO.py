"""Reconstruct missing V5 Story *proposals*, not deleted videos or approvals.

Requires existing sha-verified original + Analyzer evidence + editorial decisions.
Default mode is read-only. No Qwen, downloads, Analyzer mutations or Reel rendering.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PROJECT_ID = 'zd_wjssZ7mc'
EXPECTED_SOURCE = 'b2958122415980a8afff4f77c23ead3c31c00345e5df0ab460995eb731efb00f'
STORY06 = 'PROP_f5106b486d19e3c2e8be43ca'
EXPECTED_IDS = (
    'PROP_f654d728d26180f2fb0e5816', 'PROP_0cd8967b4785b114a6b605c0',
    'PROP_812c2557222a7626d29648e5', 'PROP_820da3ee0287202220af0541',
    'PROP_8c4d75f845814355a102e570', STORY06,
    'PROP_c5d036c5bb3221b93dc74e80', 'PROP_357a5b428e187549af18d145',
    'PROP_25dc70b2dc7d735acde2e530', 'PROP_3fc57f8ea450b03956ec1a52',
    'PROP_7d2a4a4e4b06aa96eeb267f3', 'PROP_7accaf6623ef8d9ca9f74e89',
    'PROP_ffbc72dbd1f751a8ab4ec7b5', 'PROP_7945d8231636c7684fdaedbe',
    'PROP_0ebe2d28febbe714d8a86c0e', 'PROP_f47b1a26cfc3a496c457c437',
)


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def assert_safe_file(path: Path, label: str) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f'{label} ausente ou link: {path}')
    return path.resolve()


def safe_json(path: Path, label: str) -> dict:
    data = json.loads(assert_safe_file(path, label).read_text(encoding='utf-8-sig'))
    if not isinstance(data, dict):
        raise ValueError(f'{label} não é JSON objeto')
    return data


def _verified_cache_zip(cache_dir: Path, dest: Path) -> Path:
    """Reassemble ONLY hash-declared original package files, not altered cache additions."""
    manifest = safe_json(cache_dir / 'SECOND_CURATION_MANIFEST.json', 'Manifesto original')
    listed = manifest.get('files')
    if not isinstance(listed, list) or not listed or len(listed) > 5000:
        raise ValueError('Manifesto original inválido')
    if manifest.get('source_hash') != EXPECTED_SOURCE:
        raise ValueError('SHA256 da análise no manifesto é diferente')
    seen = set()
    total = 0
    with zipfile.ZipFile(dest, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=5) as archive:
        archive.write(cache_dir / 'SECOND_CURATION_MANIFEST.json', 'SECOND_CURATION_MANIFEST.json')
        for row in listed:
            name = row.get('path')
            if not isinstance(name, str) or '\\' in name or ':' in name or not name or name.startswith('/'):
                raise ValueError('Caminho inválido no manifesto')
            rel = Path(name)
            if '..' in rel.parts or '.' in rel.parts or name in seen:
                raise ValueError('Caminho ou entrada duplicada no manifesto')
            seen.add(name)
            target = cache_dir / rel
            target = assert_safe_file(target, name)
            if not target.is_relative_to(cache_dir.resolve()):
                raise ValueError('Arquivo externo ao cache original: ' + name)
            size = target.stat().st_size
            total += size
            if size != row.get('bytes') or total > 256 * 1024 ** 2 or sha256(target) != row.get('sha256'):
                raise ValueError('Evidência do cache foi alterada ou está incompleta: ' + name)
            archive.write(target, name)
    return dest


def _load_verified_evidence(root: Path, explicit_package: Path | None):
    from ldporto_curator.evidence_source import load_evidence
    from ldporto_curator.second_curation_import import read_package
    if explicit_package is not None:
        package = assert_safe_file(explicit_package, 'ZIP original')
        meta = read_package(package)
        if meta['metadata'].get('sha256') != EXPECTED_SOURCE:
            raise ValueError('Pacote do Analyzer pertence a outra mídia')
        return load_evidence(package), {'kind': 'archive', 'path': str(package), 'sha256': sha256(package)}
    cached = root / '.cache' / 'imported_second_curation'
    if not cached.is_dir() or cached.is_symlink():
        raise ValueError('Cache da importação não localizado. Use --pacote com ZIP original do Analyzer')
    dirs = [d for d in cached.iterdir() if d.is_dir() and not d.is_symlink() and
            (d / 'SECOND_CURATION_MANIFEST.json').is_file()]
    matching = []
    for directory in dirs:
        doc = safe_json(directory / 'source' / 'metadata.json', 'Metadados da análise')
        if doc.get('sha256') == EXPECTED_SOURCE:
            matching.append(directory)
    if len(matching) != 1:
        raise ValueError('Cache ausente ou ambíguo. Forneça --pacote com o ZIP original verificado')
    with tempfile.TemporaryDirectory(prefix='ldporto_verified_evidence_') as work:
        package = _verified_cache_zip(matching[0], Path(work) / 'validated_package.zip')
        evidence = load_evidence(package)
        # read_package also cross-checks the rebuilt manifest and all its assets.
        read_package(package)
    return evidence, {'kind': 'verified_import_cache', 'path': str(matching[0]),
                      'manifest_sha256': sha256(matching[0] / 'SECOND_CURATION_MANIFEST.json')}


def _settings(root: Path):
    from ldporto_curator.config import load_config
    return load_config(root / 'config.yaml')


def _prepare(args):
    root = args.projeto.resolve()
    if not root.is_dir() or not (root / 'ldporto_curator' / 'series_workflow.py').is_file():
        raise ValueError('A pasta do VIDEO CURATOR não foi encontrada')
    if root.is_symlink():
        raise ValueError('Projeto com symlink não permitido')
    from ldporto_curator.story_import import plan_reviewed_stories
    from ldporto_curator.series_workflow import _verified_supplemental_words
    from ldporto_curator.subtitle_presets import write_episode_subtitles
    output = root / 'output'
    if not output.is_dir() or output.is_symlink():
        raise ValueError('Pasta output ausente ou inválida; inspeção manual necessária')
    source = assert_safe_file(args.midia or root / 'source_cache' / (PROJECT_ID + '.mp4'), 'Vídeo original')
    if sha256(source) != EXPECTED_SOURCE:
        raise ValueError('SHA256 do vídeo não corresponde ao original do Analyzer')

    story_doc_path = args.stories or root / 'docs' / 'second_curation' / PROJECT_ID / 'STORIES_SEQUENCIAIS_REVISAR.json'
    story_doc = safe_json(story_doc_path, 'Propostas editoriais')
    evidence, evidence_origin = _load_verified_evidence(root, args.pacote)
    if evidence['source']['sha256'] != EXPECTED_SOURCE:
        raise ValueError('Identidade das evidências divergiu do vídeo original')
    initial_plan = plan_reviewed_stories(evidence, story_doc)
    if tuple(ep['episode_id'] for ep in initial_plan['episodes']) != EXPECTED_IDS:
        raise ValueError('As 16 partes não coincidem com o plano editorial conferido; PARAR')
    if len({ep['series_id'] for ep in initial_plan['episodes']}) != 3:
        raise ValueError('Quantidade de séries diferente das três originais')

    manifest = args.manifesto or root / 'docs' / 'reports' / 'WORD_EVIDENCE_SEG00163.json'
    added, audit = _verified_supplemental_words(manifest, evidence)
    if len(added) != 12 or {row.get('segment_id') for row in added} != {'SEG_00163'}:
        raise ValueError('Complemento do Story 6 não recuperou as 12 palavras originais')
    enriched = deepcopy(evidence)
    enriched['words'].extend(added)
    enriched['words'].sort(key=lambda row: (float(row['start']), float(row['end']), row.get('word_id', '')))
    enriched.setdefault('provenance', {})['supplemental_word_evidence'] = audit
    final_plan = plan_reviewed_stories(enriched, story_doc)
    if final_plan['plan_id'] != initial_plan['plan_id'] or tuple(ep['episode_id'] for ep in final_plan['episodes']) != EXPECTED_IDS:
        raise ValueError('Complemento alterou decisões narrativas em vez de somente recuperar timestamps')

    # Check every Story's actual subtitle geometry using the installed renderer.
    # Writes only under an OS temporary directory, not to user's output.
    checked = []
    with tempfile.TemporaryDirectory(prefix='ldporto_recover_captions_') as tmp:
        for ep in final_plan['episodes']:
            if not 0 < float(ep['duration']) <= 59.5 + 1e-5 or ep.get('boundary_quality') != 'sentence_or_qa':
                raise ValueError('Story sem limite de frase e duração confiáveis: ' + ep['episode_id'])
            result = write_episode_subtitles(enriched, ep, Path(tmp) / ep['episode_id'],
                                             preset='LDP_REELS_KARAOKE', width=540, height=960)
            sync = result['sync']
            if not sync.get('renderable') or sync.get('alignment') != 'word':
                raise ValueError('Story falha no layout/timestamp da legenda: ' + ep['episode_id'] + ': ' + str(sync.get('diagnostics'))[:300])
            if sync.get('visual_behavior') != 'yellow_phrase_cumulative_white_at_measured_onset':
                raise ValueError('Karaokê amarelo/branco indisponível: ' + ep['episode_id'])
            checked.append({'part': ep.get('episode_part_label'), 'episode_id': ep['episode_id'],
                            'caption_events': len(sync.get('events') or []), 'seconds': ep['duration']})

    cfg = _settings(root)
    output_path = Path(cfg['paths']['output_root']).resolve()
    if output_path != output.resolve():
        raise ValueError('Configuração de saída aponta fora de output; altere manualmente, não reconstruir automaticamente')
    # Name is deterministically computed by installed SeriesProject.create_stories.
    from ldporto_curator.series_workflow import _canonical_hash
    from ldporto_curator.utils import safe_name
    identity = _canonical_hash({'source_sha256': EXPECTED_SOURCE,
        'story_plan_id': final_plan['plan_id'], 'workflow': 'stories_review_v2'})[:16]
    destination = output_path / 'projects' / PROJECT_ID / ('stories_' + identity)
    if destination.exists() or destination.is_symlink():
        raise ValueError('Projeto destino já existe. Preservado. Use V5.2 ou escolha outro procedimento de restauração: ' + str(destination))
    snapshot = root / 'docs' / 'reports' / 'output_recovery_snapshots' / (PROJECT_ID + '_' + final_plan['plan_id'])
    if snapshot.exists() or snapshot.is_symlink():
        raise ValueError('Snapshot de uma recuperação anterior já existe. Não recriar por cima: ' + str(snapshot))
    return dict(root=root, source=source, evidence=enriched, cfg=cfg, document=story_doc,
                plan=final_plan, destination=destination, checked=checked, origin=evidence_origin,
                supplemental=audit, original_manifest=manifest)


def inspection(args):
    data = _prepare(args)
    report = {'schema': 'LDP_OUTPUT_RECOVERY_PRECHECK_V1', 'status': 'SAFE_TO_REBUILD_PROPOSALS',
        'output_current_empty': not any((data['root'] / 'output').iterdir()),
        'old_mp4_restored': False, 'old_approvals_restored': False,
        'original_media_sha256': EXPECTED_SOURCE, 'source_path': str(data['source']),
        'source_evidence': data['origin'], 'supplemental_manifest': str(data['original_manifest']),
        'supplemental_words': 12, 'stories': len(data['checked']), 'series': 3,
        'episodes': data['checked'], 'destination': str(data['destination']),
        'next_step': 'Explicit --reconstruir creates a NEW, unapproved Stories proposal.'}
    return data, report


def rebuild(data, report):
    from ldporto_curator.series_workflow import SeriesProject
    directory = data['destination']
    if directory.exists() or directory.parent.is_symlink():
        raise ValueError('Destino já existe ou caminho pai não confiável; PARAR')
    if sha256(data['source']) != EXPECTED_SOURCE:
        raise ValueError('Vídeo mudou durante a verificação; PARAR')
    project = SeriesProject.create_stories(data['evidence'], data['document'],
                                            data['cfg']['paths']['output_root'], data['cfg'])
    if project.directory != directory:
        raise ValueError('Caminho reconstruído inesperado; PARAR')
    if tuple(ep['episode_id'] for ep in project.episodes()) != EXPECTED_IDS:
        raise ValueError('Projeto reconstruído não corresponde às 16 partes; PARAR')
    if any(ep.get('human_approval') is not None or ep.get('status') not in ('REVIEW_REQUIRED', None)
           for ep in project.episodes()):
        raise ValueError('Reconstrução não pode herdar aprovações antigas; PARAR')
    # A recovery audit is kept INSIDE newly created output; independently keep a copy in docs/reports.
    statement = {'schema': 'LDP_OUTPUT_RECONSTRUCTION_V1', 'source_sha256': EXPECTED_SOURCE,
        'source_package': data['origin'], 'supplemental_evidence': data['supplemental'],
        'editorial_plan_id': project.plan['plan_id'], 'episodes': len(project.episodes()),
        'recreated_from_verifiable_inputs': True,
        'historical_previews_recovered': False, 'historical_final_renders_recovered': False,
        'historical_approvals_recovered': False, 'publication_ready': False}
    from ldporto_curator.utils import write_json
    write_json(directory / 'OUTPUT_RECOVERY_AUDIT.json', statement)
    # Keep the reconstructed planning metadata outside output so future missing
    # output can be diagnosed, but NEVER equate it with backups of videos/approvals.
    snapshot = data['root'] / 'docs' / 'reports' / 'output_recovery_snapshots' / (PROJECT_ID + '_' + project.plan['plan_id'])
    if snapshot.exists():
        raise ValueError('Snapshot externo já existe; revisão preservada: ' + str(snapshot))
    snapshot.mkdir(parents=True, exist_ok=False)
    files = {}
    import shutil
    for name in ('series_index.json', 'evidence.json', 'source_manifest.json', 'OUTPUT_RECOVERY_AUDIT.json'):
        origin = directory / name
        if not origin.is_file() or origin.is_symlink():
            raise ValueError('Arquivo essencial não salvo no novo projeto: ' + name)
        target = snapshot / name
        shutil.copy2(origin, target)
        if sha256(origin) != sha256(target):
            raise ValueError('Snapshot externo divergiu: ' + name)
        files[name] = sha256(target)
    write_json(snapshot / 'HASHES_SNAPSHOT.json', {'files': files, 'media_restored': False,
        'approval_restored': False, 'source_sha256': EXPECTED_SOURCE})
    statement['planning_snapshot'] = str(snapshot)
    return project, statement


def preview_batch(args):
    import shutil
    from ldporto_curator.series_workflow import SeriesProject
    from ldporto_curator.utils import load_json, write_json
    root = args.projeto.resolve()
    cfg = _settings(root)
    source = assert_safe_file(args.midia or root / 'source_cache' / (PROJECT_ID + '.mp4'), 'Mídia')
    if sha256(source) != EXPECTED_SOURCE:
        raise ValueError('Vídeo original mudou')
    if shutil.disk_usage(root).free < 3 * 1024**3:
        raise ValueError('Espaço livre menor que 3 GiB; interrompido para proteger renderizações')
    # Re-validate the project from its actual stored identity.
    project_root = Path(cfg['paths']['output_root']) / 'projects' / PROJECT_ID
    candidates = [p for p in project_root.glob('stories_*/OUTPUT_RECOVERY_AUDIT.json') if p.is_file() and not p.is_symlink()]
    if len(candidates) != 1:
        raise ValueError('Não há exatamente uma recuperação assinada; não renderizar')
    directory = candidates[0].parent.resolve()
    p = SeriesProject(directory, cfg)
    audit = load_json(candidates[0], {}) or {}
    if (audit.get('source_sha256') != EXPECTED_SOURCE
            or p.evidence.get('source', {}).get('sha256') != EXPECTED_SOURCE
            or p.plan.get('source_sha256') != EXPECTED_SOURCE
            or tuple(ep['episode_id'] for ep in p.episodes()) != EXPECTED_IDS
            or audit.get('editorial_plan_id') != p.plan.get('plan_id')):
        raise ValueError('Projeto recuperado não corresponde ao original validado')
    # This is intentionally a review-only path. No final renders without episode approvals.
    results = []
    for count, ep in enumerate(p.episodes(), 1):
        if (ep.get('human_approval') is not None or
                ep.get('status') == 'APPROVED'):
            raise ValueError('Aprovação alterada; interromper e revisar na V5.2')
        print(f'STORY {count}/16: {ep.get("episode_part_label")} {ep["episode_id"]}', flush=True)
        preview = p.render(ep['episode_id'], source, preview=True)
        results.append({'episode_id': ep['episode_id'], 'path': str(preview),
                        'sha256': sha256(preview), 'human_audio_review': 'REQUIRED',
                        'approved': False, 'publication_ready': False})
    manifest = {'schema': 'LDP_RECOVERY_PREVIEW_BATCH_V1', 'source_sha256': EXPECTED_SOURCE,
                'episodes': len(results), 'order': results,
                'old_finals_restored': False, 'publication_approved': False}
    write_json(directory / 'PREVIAS_RECUPERADAS_EM_ORDEM.json', manifest)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--projeto', type=Path, default=ROOT)
    parser.add_argument('--midia', type=Path, default=None)
    parser.add_argument('--pacote', type=Path, default=None)
    parser.add_argument('--stories', type=Path, default=None)
    parser.add_argument('--manifesto', type=Path, default=None)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--reconstruir', action='store_true', help='Novo projeto apenas com propostas, sem renderizar')
    mode.add_argument('--renderizar-previas', action='store_true', help='Renderizar só prévias dos 16 Stories de projeto recuperado')
    args = parser.parse_args(argv)
    try:
        if args.renderizar_previas:
            result = preview_batch(args)
            print(json.dumps({'status': 'PREVIEWS_GENERATED_NEEDS_HUMAN_REVIEW', **result}, ensure_ascii=False, indent=2))
        else:
            data, report = inspection(args)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            if args.reconstruir:
                project, new_report = rebuild(data, report)
                print(json.dumps({'status': 'NEW_UNAPPROVED_PROJECT_CREATED',
                                  'destination': str(project.directory), **new_report}, ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        print('BLOQUEADO:', str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
