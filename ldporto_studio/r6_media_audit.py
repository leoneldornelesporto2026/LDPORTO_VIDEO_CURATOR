"""Discover and hash-check existing R6 media; read-only and no network activity.

Deliberately limits search to known managed download locations. A matching
YouTube ID, name, resolution or duration NEVER establishes time alignment.
Only the exact SHA256 of the Analyzer source is an exact-byte match.
"""
from __future__ import annotations

import os
from pathlib import Path

from .core import VIDEO_EXT, sha256_file
from .r6_review import read_analyzer_review
from .workspace import application_root, project_output_root
from .youtube_download import videos_download_root

ALLOWED_MEDIA = frozenset(VIDEO_EXT)
MAX_HASH_FILES = 12
MAX_SCAN_ENTRIES = 2000
MAX_SCAN_DIRS = 400
MAX_FILE_BYTES = 40 * 1024 * 1024 * 1024

def _safe_media(path):
    try:
        return (not path.is_symlink() and path.is_file()
                and path.suffix.lower() in ALLOWED_MEDIA
                and 0 < path.stat().st_size <= MAX_FILE_BYTES)
    except (OSError,ValueError):
        return False

def _scan_root(root, *, depth_limit=4, budget=None):
    """Yield bounded direct and nested media candidates without following links."""
    if budget is None:
        budget={'dirs':0,'entries':0,'truncated':False}
    root=Path(root).expanduser()
    if not root.is_dir() or root.is_symlink():
        return
    for where, dirs, files in os.walk(root,followlinks=False):
        directory=Path(where)
        depth=len(directory.relative_to(root).parts)
        budget['dirs']+=1
        if budget['dirs']>MAX_SCAN_DIRS:
            budget['truncated']=True
            return
        dirs[:]=sorted(d for d in dirs
                       if depth<depth_limit and not (directory/d).is_symlink())
        for name in sorted(files):
            budget['entries']+=1
            if budget['entries']>MAX_SCAN_ENTRIES:
                budget['truncated']=True
                return
            candidate=directory/name
            if _safe_media(candidate):
                yield candidate

def _managed_roots(video_id, app_root=None, projects_root=None, videos_root=None):
    """Only roots established by the Curator; never search the entire home drive."""
    app=Path(app_root).expanduser().resolve() if app_root is not None else application_root()
    projects=(Path(projects_root).expanduser().resolve() if projects_root is not None
              else project_output_root())
    windows=(Path(videos_root).expanduser().resolve() if videos_root is not None
             else videos_download_root())
    roots=[
        ('CURATOR_INPUT_VIDEOS', app/'input'/'videos'/video_id, 4),
        ('LEGACY_WINDOWS_VIDEOS',windows/video_id,4),
    ]
    if projects.is_dir() and not projects.is_symlink():
        # Projects have their own private downloads; restrict to that known layout.
        for project in sorted(projects.iterdir())[:100]:
            if project.is_dir() and not project.is_symlink():
                roots.append(('LEGACY_PROJECT_DOWNLOADS',
                              project/'downloads'/'attempts',3))
    return roots

def audit_r6_media(inbox_directory, *, explicit_media=None, max_files=MAX_HASH_FILES,
                   app_root=None, projects_root=None, videos_root=None):
    """Scan known local folders, hash bounded candidates, return safe comparison.

    No download, no copies or associations. A different SHA256 is NOT a match
    even if the filename, YouTube video ID or duration looks correct.
    """
    if type(max_files) is not int or not 1 <= max_files <= MAX_HASH_FILES:
        raise ValueError('max_files deve ser inteiro entre 1 e 12')
    review=read_analyzer_review(inbox_directory)
    source=review['source']
    url=source.get('url') or ''
    from .youtube_download import parse_youtube_url
    try:
        video_id,_=parse_youtube_url(url)
    except ValueError:
        video_id=None
    candidates=[]
    seen=set()
    budget={'dirs':0,'entries':0,'truncated':False}
    if explicit_media is not None:
        p=Path(explicit_media).expanduser().resolve()
        if not _safe_media(p):
            raise ValueError('MP4/MKV/etc. informado não existe, é link simbólico ou é inválido')
        candidates.append(('EXPLICIT_MEDIA',p))
        seen.add(p)
    if video_id is not None:
        roots=_managed_roots(video_id,app_root,projects_root,videos_root)
        for label,root,depth in roots:
            if budget['truncated']:
                break
            for file in _scan_root(root,depth_limit=depth,budget=budget):
                canonical=file.resolve()
                if canonical not in seen:
                    seen.add(canonical)
                    candidates.append((label,canonical))
                if len(candidates)>=max_files:
                    budget['truncated']=True
                    break
            if len(candidates)>=max_files:
                break
    else:
        budget['truncated']=True  # Can't infer a safe target folder; explicit path still works.
    rows=[]
    for label,path in candidates[:max_files]:
        digest=sha256_file(path)
        exact=digest==source['source_sha256']
        rows.append({
            'location_type':label,
            'path':str(path),
            'size_bytes':path.stat().st_size,
            'sha256':digest,
            'source_status':'EXACT_ANALYZER_SOURCE' if exact else 'DIFFERENT_SHA256_REVIEW_REQUIRED',
            'matches_analyzer':exact,
            'can_reuse_timestamps_without_reanalysis':exact,
        })
    matches=[row for row in rows if row['matches_analyzer']]
    mismatches=[row for row in rows if not row['matches_analyzer']]
    status=('EXACT_SOURCE_FOUND' if matches else
            'ALTERNATE_MEDIA_ONLY_REVIEW_REQUIRED' if mismatches else
            'NO_MANAGED_MEDIA_FOUND')
    return {
        'schema_version':'ldporto-r6-media-audit-1.0',
        'status':status,
        'video_title':source['title'],
        'youtube_video_id':video_id,
        'source_sha256':source['source_sha256'],
        'searched_known_directories_only':True,
        'searched_directory_count':budget['dirs'],
        'scanned_entry_count':budget['entries'],
        'hashed_media_count':len(rows),
        'exact_matches_count':len(matches),
        'different_sha_count':len(mismatches),
        'scan_truncated':budget['truncated'],
        'media':rows,
        'render_ready':False,
        'media_associated':False,
        'human_approved':False,
        'download_executed':False,
        'files_modified':False,
        'next_step':('Review exact-source path and validate a technical preview in an isolated workspace'
                     if matches else
                     'Locate original Analyzer media or explicitly verify an alternate MP4; no timestamps assumed'),
    }
