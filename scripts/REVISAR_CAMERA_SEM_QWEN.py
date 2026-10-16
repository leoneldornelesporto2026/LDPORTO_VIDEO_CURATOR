"""Explicit new camera-only revision; never modifies an approved historical revision.

Usage: python scripts/REVISAR_CAMERA_SEM_QWEN.py --source zd_wjssZ7mc --rank 1 --apply
Without --apply: read-only checks only. Keep GUI closed while running.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _existing_metadata(base, document, clip):
    """Read only the evidence bound to this revision; never search other clips."""
    root = Path(base).absolute()
    relative = document.get('planning_evidence')
    if not relative:
        raise ValueError('Revisao sem planning_evidence; nao sera executada nova analise.')
    path = root / Path(str(relative).replace('\\','/')) / 'clips' / clip['clip_id'] / 'clip_micro_perception.json'
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('Metadados de camera existentes ausentes ou fora do projeto: ' + clip['clip_id'])
    from ldporto_curator.camera_metadata import load_existing_camera_metadata
    micro = load_existing_camera_metadata(path, document.get('source_media_sha256'),
                                         source_plan=root/'EDIT_DECISIONS.json')
    return path, micro


def camera_revision(source: str, rank: int | None, apply: bool = False, *, existing_metadata: bool = True,
                    prefer_visual_focus: bool = False):
    from ldporto_curator.config import load_config
    from ldporto_curator.pipeline import Pipeline
    from ldporto_curator.persisted_plan import PlanStore, project_lock, compare_settings
    from ldporto_curator.final_camera import refine_from_existing_metadata
    from ldporto_curator.approval import file_hash
    from ldporto_curator.review import write_handoff
    from ldporto_curator.utils import write_json

    if not existing_metadata:
        raise ValueError('Revisao de camera exige --existing-metadata; nova analise nao autorizada neste fluxo.')

    installed_cfg = load_config(ROOT / 'config.yaml')
    pipe = Pipeline(installed_cfg, ROOT)
    base = pipe._project_dir(source)
    with project_lock(base):
        store = PlanStore(base)
        old, bundle = store.load(check_settings=False)
        # Use the render settings stored in this revision; do not accidentally
        # change audio, subtitles or titles while updating camera.
        pinned_cfg = deepcopy(old['render_config'])
        pinned_cfg['paths'] = deepcopy(installed_cfg['paths'])
        compare_settings(old, pinned_cfg)
        all_clips = deepcopy(old['approved_clips'])
        selected = [clip for clip in all_clips if rank is None or int(clip['rank']) == rank]
        if not selected:
            raise ValueError('Rank informado nao existe neste plano.')
        existing = {clip['clip_id']:_existing_metadata(base, old, clip) for clip in selected}
        print('Projeto:', old['project_id'])
        print('Revisao anterior:', old['plan_revision'])
        print('Cortes que receberao nova camera:', len(selected))
        print('Titulos/legendas/intervalos permanecem inalterados.')
        if not apply:
            print('SOMENTE CONSULTA. Para criar nova revisao, acrescente --apply.')
            return {'status': 'checked', 'old_revision': old['plan_revision']}
        # SHA validation must happen before generating or publishing plans.
        video, sha = pipe._video(bundle, source, old)
        if old.get('source_media_sha256') and sha != old['source_media_sha256']:
            raise ValueError('Midia original divergente; nenhuma revisao criada.')
        if not pinned_cfg.get('camera', {}).get('v44_refinement', True):
            raise ValueError('camera.v44_refinement esta desativado no plano salvo.')
        # Staging is unique and outside existing approved revisions/renders.
        staging = base / 'planning' / ('camera_only_' + uuid.uuid4().hex)
        for idx, clip in enumerate(selected, 1):
            print('Refinando camera de', clip['clip_id'], f'({idx}/{len(selected)})')
            folder = staging / 'clips' / clip['clip_id']
            metadata_path, micro = existing[clip['clip_id']]
            clip['camera_plan'] = refine_from_existing_metadata(clip, bundle.analysis['metadata'],
                micro=micro, director=getattr(bundle, 'director', []), cfg=pinned_cfg,
                prefer_visual_focus=prefer_visual_focus)
            folder.mkdir(parents=True, exist_ok=False)
            write_json(folder / 'clip_micro_perception.json', micro)
            write_json(folder / 'FINAL_CAMERA_PLAN_V44.json', clip['camera_plan'])
            write_json(folder / 'CAMERA_ONLY_PROVENANCE.json', {
                'metadata_source':str(metadata_path), 'metadata_sha256':file_hash(metadata_path),
                'existing_metadata_only':True, 'new_analysis_executed':False,
                'editorial_decisions_recomputed':False, 'approval_required':True,
                'safe_visual_reframe_requested':prefer_visual_focus,
                'effective_crop_segments':sum(x.get('mode') == 'crop' for x in clip['camera_plan'].get('segments', []))})
        if file_hash(video) != sha:
            raise ValueError('O video original mudou durante o refinamento; sem publicacao.')
        # PlanStore creates a new revision with immutable snapshot and history.
        doc, frozen = store.create(bundle, all_clips, pinned_cfg, source)
        doc.update(previous_revision=old['plan_revision'],
                   source_media_path=str(video), source_media_sha256=sha,
                   planning_evidence=str(staging.relative_to(base)),
                   invalidation_reason=('Refinamento explicito somente de camera; antiga revisao ' +
                                        old['plan_revision'] + ' preservada. Nova previa e aprovacao obrigatorias.'))
        doc = store.save_state(doc)
        write_handoff(frozen, all_clips, store.revision_dir(doc))
        print('NOVA REVISAO:', doc['plan_revision'])
        print('ESTADO:', doc['approval_state'])
        print('Preservada revisao anterior:', old['plan_revision'])
        print('Abra a GUI: TESTAR 1 CORTE > revisar MP4 > APROVAR TESTE.')
        return {'status': 'created', 'old_revision': old['plan_revision'], 'new_revision': doc['plan_revision']}


def main():
    p = argparse.ArgumentParser(description='Cria nova revisao somente de camera, sem Qwen e sem mexer no editorial.')
    p.add_argument('--source', required=True, help='ID ou URL da midia ja analisada')
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument('--rank', type=int, help='Rank do Reel para refinar')
    group.add_argument('--all', action='store_true', help='Todos os Reels do plano')
    p.add_argument('--apply', action='store_true', help='Confirma a criacao de uma NOVA revisao')
    p.add_argument('--existing-metadata', action='store_true', default=True,
                   help='Reutiliza somente planning_evidence existente (padrao; nunca executa nova percepcao)')
    p.add_argument('--safe-visual-focus', action='store_true', help='Reenquadrar somente cenas com rosto medido; nova revisao, sem Qwen')
    args = p.parse_args()
    if args.rank is not None and args.rank < 1:
        p.error('--rank deve ser maior que zero')
    camera_revision(args.source, None if args.all else args.rank, args.apply,
                    existing_metadata=args.existing_metadata, prefer_visual_focus=args.safe_visual_focus)


if __name__ == '__main__':
    main()
