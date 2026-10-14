from __future__ import annotations
from pathlib import Path
from .utils import youtube_id, safe_name, run, which


class SourceUnavailable(FileNotFoundError):
    pass


def _verified(path, bundle):
    from .approval import file_hash
    expected = (bundle.analysis.get('metadata') or {}).get('sha256')
    if expected and file_hash(path) != expected:
        raise ValueError('SHA256 da mídia não corresponde à análise. Selecione o original analisado.')
    return Path(path).resolve()

def resolve_source(bundle, source_input: str, cfg, log=print):
    p=Path(source_input)
    override = cfg.get('source_media', {}).get('path')
    if override and Path(override).is_file():
        return _verified(Path(override), bundle)
    if p.exists() and p.is_file(): return _verified(p, bundle)
    meta=bundle.analysis.get('metadata') or {}; src=(meta.get('source') or {})
    filename=src.get('filename') or meta.get('filename')
    search_roots=[bundle.root, bundle.root.parent, bundle.root.parent.parent]
    for base in search_roots:
        if filename:
            hits=list(base.rglob(filename)) if base.exists() else []
            for h in hits:
                if h.is_file() and h.suffix.lower() in {'.mp4','.mkv','.webm','.mov'}: return _verified(h, bundle)
    url=src.get('url') or source_input
    vid=src.get('id') or youtube_id(url) or bundle.video_id
    cache=Path(cfg['paths']['source_cache']); cache.mkdir(parents=True,exist_ok=True)
    existing=list(cache.glob(f"{vid}.*"))
    for e in existing:
        if e.suffix.lower() in {'.mp4','.mkv','.webm','.mov'}: return _verified(e, bundle)
    if not cfg.get('source_media', {}).get('allow_download', False):
        raise SourceUnavailable('Mídia fonte indisponível. Baixe novamente ou selecione o arquivo original; a análise existente será reutilizada.')
    if not which('yt-dlp'):
        raise RuntimeError('yt-dlp não encontrado. Rode INSTALAR.bat.')
    out=str(cache/f"{vid}.%(ext)s")
    log('Baixando vídeo original com yt-dlp...')
    run(['yt-dlp','-f','bv*+ba/b','--merge-output-format','mp4','-o',out,url],check=True)
    hits=list(cache.glob(f"{vid}.mp4")) or list(cache.glob(f"{vid}.*"))
    if not hits: raise RuntimeError('yt-dlp terminou mas o vídeo não foi localizado no cache.')
    return _verified(hits[0], bundle)
