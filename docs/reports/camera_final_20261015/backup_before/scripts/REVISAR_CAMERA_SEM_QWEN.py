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


def camera_revision(source: str, rank: int | None, apply: bool = False):
    from ldporto_curator.config import load_config
    from ldporto_curator.pipeline import Pipeline
    from ldporto_curator.persisted_plan import PlanStore, project_lock, compare_settings
    from ldporto_curator.camera import build_camera_plan
    from ldporto_curator.final_camera import refine_clip
    from ldporto_curator.approval import file_hash
    from ldporto_curator.review import write_handoff

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
            clip['camera_plan'] = build_camera_plan(bundle, clip, pinned_cfg)
            folder = staging / 'clips' / clip['clip_id']
            folder.mkdir(parents=True, exist_ok=False)
            refine_clip(bundle, clip, video, folder, pinned_cfg)
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
    args = p.parse_args()
    if args.rank is not None and args.rank < 1:
        p.error('--rank deve ser maior que zero')
    camera_revision(args.source, None if args.all else args.rank, args.apply)


if __name__ == '__main__':
    main()
