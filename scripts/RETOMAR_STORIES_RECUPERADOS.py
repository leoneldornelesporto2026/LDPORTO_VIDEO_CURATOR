"""Retoma exclusivamente Stories, usando uma revisão independente validada do Story 6.

Por padrão: somente verifica, não grava arquivos.  --executar: renderiza prévias
pendentes, preserva os episódios anteriores e publica manifesto de revisão.
Não chama CURAR, Qwen, ASR, Analyzer nem altera planos Reels.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import json
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ldporto_curator.approval import file_hash
from ldporto_curator.combined_batch import _verified_recovered_preview, render_stories_review_batch
from ldporto_curator.series_workflow import SeriesProject
from ldporto_curator.subtitle_presets import write_episode_subtitles
from ldporto_curator.config import load_config

STORY06 = 'PROP_f5106b486d19e3c2e8be43ca'


def source_identity_report(project, media):
    """Read-only identity inspection. Never trusts filename/URL over SHA256."""
    from ldporto_curator.utils import load_json
    expected = project.evidence.get('source', {}).get('sha256')
    planned = project.plan.get('source_sha256')
    manifest = load_json(project.directory / 'source_manifest.json', {}) or {}
    recorded = manifest.get('sha256')
    media = Path(media)
    exists = media.is_file() and not media.is_symlink()
    actual = file_hash(media) if exists else None
    same_metadata = bool(isinstance(expected, str) and len(expected) == 64
                         and expected == planned and expected == recorded)
    result = {
        'schema': 'LDP_STORIES_SHA256_DIAGNOSTICO_V1',
        'episode_count': len(project.plan.get('episodes') or []),
        'project': str(project.directory),
        'media_path': str(media.absolute()),
        'media_exists_regular_file': bool(exists),
        'source_sha256_evidence': expected,
        'source_sha256_plan': planned,
        'source_sha256_manifest': recorded,
        'source_sha256_actual_media': actual,
        'metadata_match': same_metadata,
        'media_match': bool(same_metadata and actual == expected),
    }
    if not same_metadata:
        result['reason'] = 'SOURCE_METADATA_MISMATCH'
    elif not exists:
        result['reason'] = 'MEDIA_MISSING_OR_SYMLINK'
    elif actual != expected:
        result['reason'] = 'MEDIA_BYTES_SHA256_MISMATCH'
    else:
        result['reason'] = 'SOURCE_IDENTITY_OK'
    return result


def verify_source_identity(project, media):
    report = source_identity_report(project, media)
    if report['reason'] != 'SOURCE_IDENTITY_OK':
        # Print distinct values to make debugging deterministic; never bypass.
        raise ValueError('Identidade da mídia BLOQUEADA: ' +
                         json.dumps(report, ensure_ascii=False, sort_keys=True))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--projeto', type=Path, required=True)
    parser.add_argument('--midia', type=Path, required=True)
    parser.add_argument('--revisao-story06', type=Path, help='Pasta story06_caption_recovered_*, explícita')
    parser.add_argument('--executar', action='store_true', help='Renderizar prévias ainda pendentes')
    parser.add_argument('--diagnosticar-sha', action='store_true', help='Somente mostrar as quatro identidades SHA256, sem modificar arquivos')
    args = parser.parse_args(argv)
    cfg = load_config(ROOT / 'config.yaml')
    # Match the GUI's selected-source context, including its POSIX path spelling.
    # This is an input to the signed settings, never a hash migration.
    cfg.setdefault('source_media', {})['path'] = args.midia.resolve().as_posix()
    project = SeriesProject(args.projeto, cfg)
    media = args.midia.resolve()
    if args.diagnosticar_sha:
        print(json.dumps(source_identity_report(project, media), ensure_ascii=False, indent=2))
        print('DIAGNOSTICO: somente leitura; nenhum arquivo/projeto alterado.')
        return 0
    verify_source_identity(project, media)
    episodes = project.plan.get('episodes') or []
    if len(episodes) != 16 or len({e['episode_id'] for e in episodes}) != 16:
        raise ValueError('Esperadas as 16 partes únicas da segunda curadoria; não altere o plano')
    if sum(e['episode_id'] == STORY06 for e in episodes) != 1:
        raise ValueError('Story 6 ausente ou repetido')
    problems = []
    with tempfile.TemporaryDirectory(prefix='ldporto_stories_verify_') as tmp:
        for i, ep in enumerate(episodes, 1):
            if not (0 < ep['duration'] <= 60 and ep['boundary_quality'] == 'sentence_or_qa'):
                raise ValueError('Parte sem limite de frase/duração comprovada: ' + ep['episode_id'])
            if ep['episode_id'] == STORY06:
                found = _verified_recovered_preview(project, ep, media,
                    explicit_revision=args.revisao_story06)
                if found is None:
                    raise ValueError('Prévia recuperada do Story 6 não encontrada. Não renderize novamente o Story antigo.')
                continue
            rendered = write_episode_subtitles(project.evidence, ep, Path(tmp) / str(i),
                preset=ep.get('subtitle_preset', 'LDP_REELS_KARAOKE'),
                overrides=ep.get('subtitle_overrides'), width=540, height=960)
            sync = rendered['sync']
            if not sync.get('renderable'):
                problems.append({'part': i, 'id': ep['episode_id'], 'diagnostics': sync.get('diagnostics')})
    if problems:
        raise ValueError('Legendas ainda bloqueadas: ' + json.dumps(problems, ensure_ascii=False))
    print('VERIFICACAO OK: 16 Stories; Story 6 recuperado por hash; outros 15 dentro da área segura.')
    print('Nenhum Reel será reprocessado. Aprovação dos Stories permanece humana.')
    if not args.executar:
        print('Nenhum vídeo/manifesto foi modificado. Use --executar para retomar somente os Stories.')
        return 0
    result = render_stories_review_batch(project, media, log=print,
                                         recovered_revision=args.revisao_story06)
    print('LOTE_STORIES:', result.get('manifest_path', project.directory / 'LOTE_STORIES_EM_ORDEM.json'))
    print('PARTES:', result['total_parts'], 'PREVIAS_PENDENTES:', result['previews_pending'],
          'FINAIS_APROVADOS:', result['finals'])
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print('BLOQUEADO:', str(exc), file=sys.stderr)
        sys.exit(2)
