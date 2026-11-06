"""Technical R6 video-preview smoke from the exact Analyzer original.

Not the R57 converter or an editorial render. This trims at most 8 seconds
from ONE real Analyzer candidate into a watermarked (by container file names
and sidecar, not image overlay) review-only MP4, preserving the entire 16:9
source within the vertical frame. No smart crop, captions, publication,
approvals, or project modifications. Requires explicit opt-in.
"""
from __future__ import annotations

from hashlib import sha256
import json
import math
import os
from pathlib import Path
import subprocess
from uuid import uuid4

from .core import atomic_write, sha256_file
from .r6_review import read_analyzer_review
from .r6_smoke import pick_smoke_candidates
from .rendering import binaries, probe_media
from .workspace import application_root

MAX_PREVIEW_SECONDS = 8
TARGET_WIDTH, TARGET_HEIGHT = 360, 640


def render_r6_technical_preview(inbox, media, *, confirm=False,
                                output_root=None, seconds=6) -> dict:
    if confirm is not True:
        raise ValueError('Use --confirm-preview-test para autorizar uma prévia técnica isolada')
    if isinstance(seconds, bool) or not isinstance(seconds,(int,float)) or not math.isfinite(seconds):
        raise ValueError('Duração inválida')
    if not 1 <= seconds <= MAX_PREVIEW_SECONDS:
        raise ValueError('A prévia técnica deve ter entre 1 e 8 segundos')
    review=read_analyzer_review(inbox)  # ZIP + original handoff SHA checked
    item_id=pick_smoke_candidates(review,1)[0]
    candidate=next(row for row in review['candidates'] if row['candidate_id']==item_id)
    raw=Path(media).expanduser()
    if raw.is_symlink():
        raise ValueError('Não é permitida mídia por link simbólico')
    source=raw.resolve(strict=True)
    if source.suffix.lower() not in ('.mp4','.mkv','.mov','.webm','.m4v'):
        raise ValueError('Formato audiovisual não permitido')
    if not source.is_file() or not source.stat().st_size:
        raise ValueError('Fonte original ausente ou vazia')
    digest=sha256_file(source)
    original=review['source']['source_sha256']
    if digest!=original:
        raise ValueError('BLOQUEADO: MP4 diferente da fonte do Analyzer (SHA256)')
    info=probe_media(source)
    if not(info['has_video'] and info['has_audio']):
        raise ValueError('Fonte deve conter vídeo e áudio')
    if info['duration']+0.3<float(candidate['end']):
        raise ValueError('Duração física da mídia não cobre o trecho do Analyzer')
    # This is a small sample taken from the first selected source interval, not a
    # false full clip or a false R57 "ready" package.
    start=float(candidate['start'])
    clip_duration=round(min(float(seconds),float(candidate['end'])-start),3)
    if clip_duration<1:
        raise ValueError('Candidato pequeno demais para prévia técnica')
    ffmpeg,_=binaries()
    root=(Path(output_root).expanduser().resolve() if output_root is not None
          else application_root()/'output'/'r6_preview_smoke')
    folder=root/original[:12]/review['source']['zip_sha256'][:12]
    folder.mkdir(parents=True,exist_ok=True)
    file=folder/('TECHNICAL_PREVIEW_'+item_id+'.mp4')
    report=folder/('TECHNICAL_PREVIEW_'+item_id+'.json')
    # Idempotence: a repeated run must not silently overwrite a media result.
    if file.exists() or report.exists():
        if not (file.is_file() and report.is_file()):
            raise ValueError('Prévia/recibo parcial já existe; original preservado')
        existing=json.loads(report.read_text(encoding='utf-8'))
        if (existing.get('source_sha256')!=original
            or existing.get('source_zip_sha256')!=review['source']['zip_sha256']
            or existing.get('source_candidate_id')!=item_id
            or existing.get('sample_seconds')!=clip_duration
            or existing.get('preview_sha256')!=sha256_file(file)):
            raise ValueError('Prévia existente divergiu; arquivo preservado')
        return {**existing,'reused_existing':True,'file_path':str(file),'report_path':str(report)}
    tmp=folder/('.partial_'+uuid4().hex+'.mp4')
    # Default safe composition: full frame preserved with pad; do not claim
    # focus tracking or crop. -ss is input seek for fast short technical test.
    filters=(f'scale={TARGET_WIDTH}:{TARGET_HEIGHT}:force_original_aspect_ratio=decrease,'
             f'pad={TARGET_WIDTH}:{TARGET_HEIGHT}:(ow-iw)/2:(oh-ih)/2:black,setsar=1')
    args=[ffmpeg,'-hide_banner','-nostdin','-loglevel','error',
          '-ss',str(start),'-i',str(source),'-t',str(clip_duration),
          '-map','0:v:0','-map','0:a:0',
          '-vf',filters,'-c:v','libx264','-preset','veryfast','-crf','27',
          '-pix_fmt','yuv420p','-c:a','aac','-b:a','96k',
          '-movflags','+faststart','-n',str(tmp)]
    try:
        process=subprocess.run(args,capture_output=True,text=True,encoding='utf-8',
                               errors='replace',timeout=240)
        if process.returncode!=0 or not tmp.is_file() or not tmp.stat().st_size:
            raise RuntimeError('FFmpeg falhou no teste: '+(process.stderr or '')[-1200:])
        product=probe_media(tmp)
        if (product['width']!=TARGET_WIDTH or product['height']!=TARGET_HEIGHT
            or not product['has_audio'] or not product['has_video']
            or not 0.5 <= product['duration'] <= clip_duration+1):
            raise ValueError('Prévia técnica sem áudio/vídeo ou dimensões esperadas')
        if file.exists() or report.exists():
            raise ValueError('Prévia já existe; operação não substituiu arquivos')
        tmp.rename(file)
        receipt={
            'schema_version':'ldporto-r6-technical-preview-1.0',
            'status':'TECHNICAL_PREVIEW_REVIEW_REQUIRED',
            'source_candidate_id':item_id,
            'source_sha256':original,
            'source_zip_sha256':review['source']['zip_sha256'],
            'source_start':start,
            'sample_seconds':clip_duration,
            'preview_sha256':sha256_file(file),
            'file_bytes':file.stat().st_size,
            'output_width':product['width'],
            'output_height':product['height'],
            'output_duration':product['duration'],
            'has_audio':product['has_audio'],
            'composition':'preserve_full_source_with_vertical_padding',
            'caption_verified':False,
            'camera_tracking_verified':False,
            'editorial_selection_confirmed':False,
            'render_ready':False,
            'human_approved':False,
            'publication_ready':False,
            'is_complete_reel':False,
            'reused_existing':False,
            'file_path':str(file),
            'report_path':str(report),
        }
        atomic_write(report,receipt)
        return receipt
    finally:
        if tmp.exists():tmp.unlink()
