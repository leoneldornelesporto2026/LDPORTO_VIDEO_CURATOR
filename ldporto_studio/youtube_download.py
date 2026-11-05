"""Explicit, isolated YouTube downloads; never weaken Analyzer SHA256 binding.

Downloads happen only after the user requests one. A yt-dlp output is attached to
its R57 project only when the exact SHA256 of the analyzed source matches.
"""
from __future__ import annotations

import os
import re
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from .core import VIDEO_EXT, atomic_write, now, sha256_file, read_json

_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_ALLOWED_HOSTS = frozenset({
    'youtube.com', 'www.youtube.com', 'm.youtube.com',
    'music.youtube.com', 'youtu.be', 'www.youtu.be',
})
_R57_SOURCE_SHA = 'f8b424b9fc26c79141fb2288fee3354d5f02c1c773523f87f95b1191252283ea'
_R57_VIDEO_ID = 'aUgESZsOGmY'


def parse_youtube_url(url: str) -> tuple[str, str]:
    """Accept only a single public YouTube video, never playlists or redirects."""
    if not isinstance(url, str) or len(url) > 2048:
        raise ValueError('URL do YouTube inválida')
    raw = url.strip()
    try:
        parts = urlsplit(raw)
        host = (parts.hostname or '').lower()
        if (parts.scheme != 'https' or host not in _ALLOWED_HOSTS
                or parts.username or parts.password or parts.port not in (None, 443)):
            raise ValueError('Informe uma URL HTTPS de vídeo do YouTube')
        if host.endswith('youtu.be'):
            segments = parts.path.strip('/').split('/')
            if len(segments) != 1:
                raise ValueError('Link curto precisa apontar para apenas um vídeo')
            video_id = segments[0]
        elif parts.path == '/watch':
            query = parse_qs(parts.query)
            if 'list' in query or 'index' in query or len(query.get('v', [])) != 1:
                raise ValueError('Informe um único vídeo, não uma playlist')
            video_id = query['v'][0]
        elif re.fullmatch(r'/(shorts|live|embed)/[A-Za-z0-9_-]{11}/?', parts.path):
            video_id = parts.path.strip('/').split('/')[1]
        else:
            raise ValueError('Use um link watch, shorts, live ou youtu.be')
        if not _VIDEO_ID.fullmatch(video_id):
            raise ValueError('ID do vídeo YouTube inválido')
        return video_id, f'https://www.youtube.com/watch?v={video_id}'
    except (ValueError, TypeError) as error:
        raise ValueError(str(error)) from error


def source_video_id(package) -> str | None:
    """Bind source ID only when proven by the package contract or known R57 source."""
    declared = package.plan.get('source_video_id') or package.plan.get('video_id')
    if isinstance(declared, str) and _VIDEO_ID.fullmatch(declared):
        return declared
    if package.source_sha == _R57_SOURCE_SHA:
        return _R57_VIDEO_ID
    return None


def suggested_youtube_url(package) -> str:
    video_id = source_video_id(package)
    return f'https://www.youtube.com/watch?v={video_id}' if video_id else ''


def videos_download_root() -> Path:
    """Use the Windows Videos known folder, not the Git repository output/.

    Files are not copied/moved automatically; earlier project-local attempts remain
    supported and retain their original integrity receipts.
    """
    base=Path.home() / 'Videos'
    if os.name == 'nt':
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                  r'Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders') as key:
                configured,_=winreg.QueryValueEx(key,'My Video')
                if isinstance(configured,str) and configured:
                    expanded=os.path.expandvars(configured)
                    if not re.search(r'%[A-Za-z_][A-Za-z_0-9]*%',expanded):
                        base=Path(expanded).expanduser()
        except (OSError,ImportError):
            pass
    return base.resolve() / 'LDPORTO_VIDEO_CURATOR'


def download_input_root() -> Path:
    """New downloads live with the Curator under input/videos/, never in Git."""
    from .workspace import application_root
    return (application_root() / 'input' / 'videos').resolve()


def managed_download_path(project, path, video_id: str) -> bool:
    """Accept current input/videos and verified legacy paths, never arbitrary files."""
    p=Path(path).resolve()
    if (not video_id or not _VIDEO_ID.fullmatch(video_id)
        or p.suffix.lower() not in VIDEO_EXT):
        return False
    old_root=(project.dir/'downloads'/'attempts').resolve()
    legacy_windows_root=(videos_download_root()/video_id/project.package.digest[:12]).resolve()
    current_root=(download_input_root()/video_id/project.package.digest[:12]).resolve()
    return any(p.is_relative_to(root) for root in (old_root,legacy_windows_root,current_root))


def existing_youtube_download(project, url: str) -> dict | None:
    """Reuse only the latest recorded, unchanged download of the SAME video.

    No new network call, no duplicate project state and no weakening source checks.
    A stale, missing or modified file cannot be reused.
    """
    video_id, canonical = parse_youtube_url(url)
    rows = project.state.get('download_history', [])
    for record in reversed(rows):
        if not isinstance(record, dict) or record.get('video_id') != video_id:
            continue
        if record.get('url') != canonical:
            continue
        if record.get('expected_sha256') != project.package.source_sha:
            continue
        if record.get('status') not in ('SOURCE_REVIEW_REQUIRED', 'VERIFIED_AND_LINKED'):
            continue
        raw_path = record.get('path')
        if not raw_path or not isinstance(raw_path, str):
            continue
        source = Path(raw_path).expanduser().resolve()
        if (not managed_download_path(project,source,video_id)
            or not source.is_file() or source.is_symlink()):
            continue
        receipt = read_json(source.parent / 'download_report.json', {}) or {}
        if receipt != record:
            continue
        if abs(float(record.get('duration_seconds', -1)) -
               project.package.source_duration) > 3:
            continue
        if sha256_file(source) != record.get('sha256'):
            continue
        return {**record, 'reused_existing': True}
    return None


def download_from_youtube(project, url: str, *, progress=None, cancel=None) -> dict:
    """Download into Curator input/videos/ and check source identity.

    A SHA mismatch is a completed DOWNLOAD, not a verified media association.
    The file remains isolated for manual analysis, with a machine-readable report.
    """
    video_id, canonical = parse_youtube_url(url)
    expected = source_video_id(project.package)
    if expected and video_id != expected:
        raise ValueError('O link não pertence ao vídeo do pacote. Esperado: ' + expected)
    if cancel is None:
        cancel = threading.Event()
    if cancel.is_set():
        raise RuntimeError('Download cancelado antes de iniciar')
    existing = existing_youtube_download(project, canonical)
    if existing:
        if progress:
            progress({'phase':'arquivo local reutilizado', 'fraction':1.0,
                      'detail':'Download existente validado pelo SHA256'})
        return existing
    try:
        import yt_dlp
    except ImportError as error:
        raise RuntimeError('yt-dlp não instalado. Execute INSTALAR_WINDOWS.bat novamente.') from error
    from .rendering import binaries, probe_media
    binaries()  # FFmpeg/FFprobe must exist before any download/merge.
    attempt = download_input_root() / video_id / project.package.digest[:12] / uuid4().hex
    attempt.mkdir(parents=True, exist_ok=False)

    def report_progress(phase, percentage=None, detail=''):
        if progress:
            progress({'phase': phase, 'fraction': percentage, 'detail': detail})

    def ensure_active():
        if cancel.is_set():
            raise RuntimeError('Download cancelado; arquivos parciais foram preservados em ' + str(attempt))

    def hook(info):
        ensure_active()
        if info.get('status') == 'downloading':
            transferred = info.get('downloaded_bytes') or 0
            total = info.get('total_bytes') or info.get('total_bytes_estimate') or 0
            fraction = .80 * min(1, transferred / total) if total > 0 else None
            report_progress('baixando', fraction, f'{transferred // 1048576} MiB')
        elif info.get('status') == 'finished':
            report_progress('mesclando áudio/vídeo', .82)

    def postprocess_hook(info):
        ensure_active()
        if info.get('status') == 'finished':
            report_progress('validando', .90)

    opts = {
        'ignoreconfig': True,
        'noplaylist': True,
        'skip_download': False,
        'quiet': True,
        'no_warnings': True,
        'format': ('bv[height<=1080][ext=mp4]+ba[ext=m4a]/'
                   'b[height<=1080][ext=mp4]/'
                   'bv[height<=1080]+ba/b[height<=1080]'),
        'merge_output_format': 'mp4',
        'outtmpl': {'default': str(attempt / 'source.%(ext)s')},
        'overwrites': False,
        'continuedl': True,
        'progress_hooks': [hook],
        'postprocessor_hooks': [postprocess_hook],
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(canonical, download=True)
        ensure_active()
        if not isinstance(info, dict) or info.get('id') != video_id:
            raise ValueError('O YouTube retornou identidade diferente do vídeo solicitado')
        media = [p for p in attempt.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXT]
        if len(media) != 1 or not media[0].stat().st_size:
            raise RuntimeError('yt-dlp não produziu um único vídeo com áudio e imagem. Pasta: ' + str(attempt))
        output = media[0]
        digest = sha256_file(output)
        report_progress('checando integridade', .94)
        details = probe_media(output)
        if not (details.get('has_audio') and details.get('has_video')):
            raise ValueError('Download não contém áudio e vídeo válidos')
        same_duration = abs(details['duration'] - project.package.source_duration) <= 3
        matched = digest == project.package.source_sha and same_duration
        if matched:
            project.set_media(output)
        record = {
            'created_at': now(), 'video_id': video_id, 'url': canonical,
            'path': str(output), 'sha256': digest,
            'expected_sha256': project.package.source_sha,
            'duration_seconds': details['duration'],
            'expected_duration_seconds': project.package.source_duration,
            'duration_compatible': same_duration,
            'status': 'VERIFIED_AND_LINKED' if matched else 'SOURCE_REVIEW_REQUIRED',
            'linked': matched,
            'message': ('MP4 original verificado e vinculado ao projeto.' if matched else
                        'Download concluído e íntegro. O SHA256 é diferente da fonte do Analyzer, '
                        'como pode ocorrer em outra codificação do mesmo vídeo. '
                        'Se ID e duração forem compatíveis, você pode revisar essa mídia nas prévias. '
                        'Isso NÃO comprova a sincronização dos cortes.'),
        }
        atomic_write(attempt / 'download_report.json', record)
        project.state.setdefault('download_history', []).append(record)
        project.state['youtube_url'] = canonical
        project.state['history'].append({'at': now(), 'event': 'YOUTUBE_DOWNLOAD_' + record['status']})
        project.save()
        report_progress('concluído', 1)
        return record
    except Exception as error:
        atomic_write(attempt / 'download_error.json', {
            'created_at': now(), 'video_id': video_id,
            'status': 'FAILED_OR_CANCELLED', 'message': str(error),
        })
        raise
