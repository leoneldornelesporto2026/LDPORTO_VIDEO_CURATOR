"""Versionable, media-free editorial script export for the L.D.PORTO Curator.

Exports the current selection of cuts, timing, captions REVIEW STATE and real
camera decisions. Never exports downloaded source, MP4 preview, local Windows
paths or secrets. The immutable package and local project state remain unchanged.
"""
from __future__ import annotations

from pathlib import Path
import re

from .core import atomic_write, fingerprint, now, sha256_file
from .workspace import application_root

_CBJR_SHA = 'f8b424b9fc26c79141fb2288fee3354d5f02c1c773523f87f95b1191252283ea'


def _name(project):
    if project.package.source_sha == _CBJR_SHA:
        return 'Charlie Brown Jr. — Planeta Atlântida 2012'
    plan = project.package.plan
    for key in ('source_title', 'video_title', 'title', 'source_artist', 'artist'):
        value=plan.get(key)
        if isinstance(value,str) and value.strip():
            return value.strip()[:150]
    return 'Show ' + project.package.source_sha[:12]


def _slug(text):
    import unicodedata
    ascii_text=unicodedata.normalize('NFKD',text).encode('ascii','ignore').decode('ascii')
    simple=re.sub('[^a-z0-9]+','-',ascii_text.casefold()).strip('-')
    return simple[:64] or 'video'


def _clip_script(project, clip):
    s=project.settings(clip.id)
    record=project.preview_record(clip.id)
    camera=(record.get('report') or {}).get('camera_plan') if record else None
    if not isinstance(camera,dict):
        camera=None
    # camera_plan stores only numeric positions and deterministic detector notes.
    camera={key:camera[key] for key in
            ('requested','decision','reason','sample_count','valid_samples',
             'camera_points','crop_fraction','detector')
            if key in camera} if camera else None
    return {
        'id':clip.id, 'kind':clip.kind, 'title':s['title'],
        'source_start_seconds':float(s['source_start']),
        'source_end_seconds':float(s['source_end']),
        'duration_seconds':round(float(s['source_end'])-float(s['source_start']),3),
        'framing':{'mode':s['layout'],'center_x':s['center_x'],
                   'actual_camera_plan':camera},
        'graphics':{'template':'LDPORTO_WHITE_LIVE_R58','title_overlay':s['title_overlay']},
        'captions':{'enabled':s['subtitles'],'verified':s['captions_verified'],
                    'action':'REVIEW_BEFORE_USE' if not s['captions_verified'] else 'REVIEWED_IN_PROJECT'},
        'review':{'status':project.status(clip.id),
                  'audio_checked':s['audio_reviewed'],
                  'camera_checked':s['camera_reviewed'],
                  'rights_checked':s['rights_verified'],
                  'preview_current':bool(record),
                  'requires_human_review':not project.approval_matches(clip.id)},
    }


def build_project_script(project):
    """Construct the reusable text-only editorial plan without filesystem paths."""
    rows=[_clip_script(project,clip) for clip in project.package.items()]
    return {
        'schema_version':'ldporto-curator-editorial-script-1.0',
        'type':'EDITORIAL_PLAN_NOT_PUBLICATION_APPROVAL',
        'created_at':now(),
        'source':{
            'title':_name(project),
            'analyzer_source_sha256':project.package.source_sha,
            'source_duration_seconds':project.package.source_duration,
            'source_video_id':project.package.plan.get('source_video_id'),
            'editorial_package_sha256':project.package.digest,
            # The render_media SHA is only provenance, not a downloadable media file.
            'render_media_sha256':project.active_media_sha(),
            'media_bytes_included':False,
        },
        'counts':{
            'reels':len([r for r in rows if r['kind']=='reels']),
            'stories':len([r for r in rows if r['kind']=='stories']),
        },
        'clips':rows,
        'notices':[
            'Propostas editoriais, não provas de revisão de áudio/vídeo.',
            'Zoom inteligente tem fallback 16:9 quando não há detecção segura.',
            'Fonte alternativa com SHA diferente exige conferência dos timestamps.',
            'Direitos autorais e autorização de publicação não são presumidos.',
        ],
    }


def export_project_script(project, destination_root=None) -> Path:
    """Create a content-addressed script revision under output/scripts/, never a MP4."""
    root=Path(destination_root).expanduser().resolve() if destination_root is not None else (
        application_root()/'output'/'scripts')
    title=_name(project)
    folder=root/(_slug(title)+'_'+project.package.source_sha[:12])
    document=build_project_script(project)
    # Use a stable digest of the editorial content, not timestamps, for idempotency.
    revision_content={key:value for key,value in document.items() if key!='created_at'}
    digest=fingerprint(revision_content)[:16]
    target=folder/('REVISION_'+digest+'.json')
    if target.exists():
        # Preserve a previous revision only if its exact content remains valid.
        existing=__import__('json').loads(target.read_text(encoding='utf-8'))
        if fingerprint({k:v for k,v in existing.items() if k!='created_at'}) != fingerprint(revision_content):
            raise ValueError('Conflito no histórico de roteiros; não sobrescrever o arquivo existente')
        return target
    atomic_write(target, document)
    return target
