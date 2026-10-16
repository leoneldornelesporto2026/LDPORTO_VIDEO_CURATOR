"""Derive selected Stories from existing visual metadata, with no new analysis.

Example (read-only until --apply):
python scripts/REFINAR_CAMERA_EXISTENTE.py --project <folder> --episode <id> --micro <json> --destination <new-folder>
"""
from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--episode', required=True)
    parser.add_argument('--micro', type=Path, required=True, help='JSON visual já existente do mesmo intervalo')
    parser.add_argument('--metadata-project', type=Path, help='EDIT_DECISIONS.json que vincula as observações à fonte')
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--render-preview', action='store_true')
    parser.add_argument('--source', type=Path)
    args = parser.parse_args(argv)
    if args.render_preview and (not args.apply or not args.source):
        parser.error('--render-preview exige --apply e --source')
    from ldporto_curator.approval import file_hash
    from ldporto_curator.series_workflow import SeriesProject
    from ldporto_curator.final_camera import refine_from_existing_metadata
    parent = SeriesProject(args.project)
    episode = parent.episode(args.episode)
    from ldporto_curator.camera_metadata import load_existing_camera_metadata
    micro = load_existing_camera_metadata(args.micro, parent.evidence['source']['sha256'],
                                         source_plan=args.metadata_project)
    # Source validation precedes creating a review project, if encode is requested.
    if args.source and file_hash(args.source) != parent.evidence['source']['sha256']:
        raise ValueError('SHA256 do vídeo original diverge; nenhuma revisão criada')
    plan = refine_from_existing_metadata(episode, parent.evidence.get('metadata') or parent.evidence['source'],
                                        micro=micro, cfg=parent.cfg)
    print(json.dumps({'episode': args.episode, 'source_start': episode['source_start'],
        'source_end': episode['source_end'], 'micro_sha256': file_hash(args.micro),
        'camera_segments': len(plan.get('segments', [])), 'new_analysis': False,
        'approved': False, 'apply': args.apply}, ensure_ascii=False, indent=2))
    if not args.apply:
        return 0
    derived = parent.derive_camera_revision(args.destination,
        micro_by_episode={args.episode: micro}, episode_ids={args.episode})
    print('Nova revisão sem aprovação:', derived.directory)
    if args.render_preview:
        print('Prévia para revisão humana:', derived.render(args.episode, args.source, preview=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
