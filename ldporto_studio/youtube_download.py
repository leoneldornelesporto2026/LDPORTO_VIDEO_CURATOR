"""Explicit, isolated YouTube downloads; never weaken Analyzer SHA256 binding.

Downloads happen only after the user requests one. A yt-dlp output is attached to
its R57 project only when the exact SHA256 of the analyzed source matches.
"""
from __future__ import annotations

import re
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from .core import VIDEO_EXT, atomic_write, now, sha256_file

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


def download_from_youtube(project, url: str, *, progress=None, cancel=None) -> dict:
    """Download to a new project-local attempt and check source identity.

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
    try:
        import yt_dlp
    except ImportError as error:
        raise RuntimeError('yt-dlp não instalado. Execute INSTALAR_WINDOWS.bat novamente.') from error
    from .rendering import binaries, probe_media
    binaries()  # FFmpeg/FFprobe must exist before any download/merge.
    attempt = project.dir / 'downloads' / 'attempts' / uuid4().hex
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
                        'Arquivo baixado, mas a origem NÃO corresponde exatamente ao SHA256 da análise. '
                        'O render permanece bloqueado. Obtenha a mesma fonte do Analyzer ou refaça a análise.'),
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
