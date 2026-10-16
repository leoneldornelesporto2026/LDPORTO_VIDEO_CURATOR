"""Camera-only forks reuse the signed caption timeline and historical assets.

This is an explicit operation. Loading, approving and rendering a project never
calls a detector, changes editorial windows or updates another project.
"""
from copy import deepcopy
from pathlib import Path
import shutil
import os
import stat

from .approval import file_hash
from .utils import load_json, safe_name


def derive_camera_revision(parent, destination, *, micro_by_episode, episode_ids=None):
    from .final_camera import refine_from_existing_metadata
    from .series_workflow import _canonical_hash, _caption_editorial_inputs, _inside_file

    selected = set(episode_ids) if episode_ids is not None else set(micro_by_episode)
    known = {episode['episode_id'] for episode in parent.episodes()}
    if not selected or not selected <= known or set(micro_by_episode) != selected:
        raise ValueError('Seleção explícita e metadados por episódio são obrigatórios')
    destination = Path(os.path.abspath(destination))
    for node in (destination, *destination.parents):
        if node.exists() and (node.is_symlink() or getattr(node.lstat(), 'st_file_attributes', 0)
                & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0)):
            raise ValueError('Destino de revisão não permite links/junctions')
    destination = destination.resolve()
    if destination.exists() or destination.is_relative_to(parent.directory):
        raise ValueError('Revisão de câmera exige uma nova pasta fora do projeto original')
    # Validate everything before the existing fork mechanism creates any files.
    plans, captions, references = {}, {}, {}
    asset_names = [safe_name(identifier).casefold() for identifier in sorted(selected)]
    if len(set(asset_names)) != len(asset_names):
        raise ValueError('IDs de episódios colidem no diretório de assets')
    metadata = parent.evidence.get('metadata') or parent.evidence.get('source') or {}
    for identifier in sorted(selected):
        episode = parent.episode(identifier)
        review_folder = (episode.get('preview') or {}).get('review_folder')
        if not review_folder:
            raise ValueError('Revisão somente de câmera exige prévia histórica com legendas verificáveis')
        folder = _inside_file(parent.directory, Path(review_folder) / 'PREVIEW_REVIEW_V5.json').parent
        record = load_json(folder / 'PREVIEW_REVIEW_V5.json', {})
        assets = {row['path']: row['sha256'] for row in record.get('assets', [])}
        frozen = {}
        for key, name in [('ass', 'CAPTIONS.ass'), ('srt', 'CAPTIONS.srt'), ('sync_metadata', 'SUBTITLE_SYNC.json')]:
            path = _inside_file(folder, name)
            digest = file_hash(path)
            if assets.get(name) != digest:
                raise ValueError('Legenda histórica sem SHA256 válido: ' + name)
            frozen[key] = {'path': path, 'sha256': digest}
        sync = load_json(frozen['sync_metadata']['path'], {})
        if (not sync.get('canonical_timeline_sha256') or sync.get('renderable') is not True
                or sync.get('source_start') != episode['source_start']
                or sync.get('source_end') != episode['source_end']):
            raise ValueError('Timeline histórica não é canônica ou diverge da janela do episódio')
        micro = micro_by_episode[identifier]
        if not isinstance(micro, dict):
            raise ValueError('Metadados visuais existentes devem ser um objeto')
        from .camera_metadata import verify_existing_camera_metadata
        verify_existing_camera_metadata(micro, parent.evidence['source']['sha256'])
        # API is pure; the historical plan and micro evidence stay byte-identical.
        candidate = deepcopy(episode)
        candidate.pop('caption_revision', None)
        plans[identifier] = refine_from_existing_metadata(candidate, metadata, micro=micro, cfg=parent.cfg)
        captions[identifier] = (frozen, sync['canonical_timeline_sha256'])
        references[identifier] = {'micro_sha256': _canonical_hash(micro),
            'parent_camera_sha256': _canonical_hash(episode.get('camera_plan')),
            'camera_sha256': _canonical_hash(plans[identifier])}

    # Reuse the audited fork: it verifies media, title and cover hashes, copies
    # parent snapshots, invalidates approvals in the copy, and never encodes.
    derived = parent.derive_caption_revision(destination, episode_ids=selected, _defer_save=True)
    revision = {'schema': 'LDP_CAMERA_ONLY_REVISION_V1',
        'revision_id': derived.plan['caption_revision']['revision_id'],
        'parent_project': str(parent.directory), 'episodes': references,
        'editorial_decisions_recomputed': False, 'analysis_executed': False,
        'transcription_executed': False, 'approval_required': True}
    derived.plan['camera_revision'] = revision
    derived.plan['plan_id'] = str(parent.plan.get('plan_id', 'PLAN')) + '_CAMERA_' + revision['revision_id'][:12]
    for episode in derived.episodes():
        identifier = episode['episode_id']
        episode['camera_plan'] = deepcopy(plans[identifier])
        frozen_revision = episode['caption_revision']
        frozen_revision['revision_kind'] = 'camera_only'
        frozen_revision['camera_plan_sha256'] = _canonical_hash(episode['camera_plan'])
        frozen_revision['frozen_episode_sha256'] = _canonical_hash(_caption_editorial_inputs(episode))
        files, canonical_hash = captions[identifier]
        timeline = {'canonical_timeline_sha256': canonical_hash, 'hashes': {}}
        for key, row in files.items():
            path = Path('camera_caption_assets') / safe_name(identifier) / row['path'].name
            target = destination / path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(row['path'], target)
            if file_hash(target) != row['sha256'] or file_hash(row['path']) != row['sha256']:
                raise ValueError('Legenda mudou durante a cópia; revisão incompleta preservada')
            timeline[key] = path.as_posix()
            timeline['hashes'][key] = row['sha256']
        episode['caption_timeline'] = timeline
        frozen_revision['caption_timeline_sha256'] = _canonical_hash(timeline)
    derived.plan.setdefault('audit_trail', []).append({'action': 'derive_camera_only_revision',
        'episode_ids': sorted(selected), 'automatic_approval': False,
        'captions_copied_by_sha256': True, 'titles_and_covers_copied_by_sha256': True})
    derived.save()
    (destination / 'CAMERA_REVISION_INCOMPLETE.json').rename(destination / 'CAMERA_REVISION_COMPLETE.json')
    return derived
