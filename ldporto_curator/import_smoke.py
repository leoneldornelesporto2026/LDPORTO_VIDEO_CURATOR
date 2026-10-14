"""Cheap read-only import qualification; media is resolved only by operator choice."""
from pathlib import Path
from .approval import file_hash
from .evidence_source import load_evidence
from .series_planner import plan_series


def inspect_media(evidence, selected_path=None):
    source=evidence.get('source') or {}
    result={'status':'referenced_only','source_sha256':source.get('sha256'),
            'duration':source.get('duration'),'location_inferred':False}
    if not selected_path:
        return result
    path=Path(selected_path)
    if not path.is_file() or path.is_symlink():
        return {**result,'status':'missing'}
    actual=file_hash(path)
    return {**result,'status':'available_verified' if actual==source.get('sha256') else 'hash_mismatch',
            'filename':path.name,'selected_sha256':actual,'bytes':path.stat().st_size}


def smoke_import(package_path, media_path=None, *, duration_preset='auto_under_90'):
    """No models or rendering. Return evidence/plan and a bounded review report."""
    path=Path(package_path)
    before=file_hash(path) if path.is_file() else None
    evidence=load_evidence(path)
    plan=plan_series(evidence,duration_preset,mode='COMBINADO')
    if before is not None and file_hash(path)!=before:
        raise ValueError('Pacote mudou durante o smoke; selecione uma cópia concluída')
    report={'operation':'read_only_import_and_proposals','input_package_sha256':before,
            'source':evidence['source'],'provenance':evidence.get('provenance'),
            'availability':evidence.get('availability'),'media':inspect_media(evidence,media_path),
            'candidates':len(evidence.get('candidates',[])),
            'review_queue':len(evidence.get('review_queue',[])),
            'official_shortlist':len(evidence.get('shortlist',[])),
            'series_episodes':len(plan['episodes']),'extras':len(plan['extras']),
            'review_sample':[{'episode_id':e['episode_id'],'source_start':e['source_start'],
                             'source_end':e['source_end'],'status':e['status']} for e in plan['episodes'][:3]],
            'coverage':plan.get('coverage'), 'approved_count':0,
            'models_executed':False,'render_executed':False,'source_modified':False,
            'limits':['Coverage is measured against available speech, not assumed full-source transcription.',
                      'Import/proposals do not constitute audiovisual or editorial homologation.']}
    return evidence,plan,report
