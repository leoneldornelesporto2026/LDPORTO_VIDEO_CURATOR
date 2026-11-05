"""Read-only local show library for the existing L.D.PORTO Video Curator Studio.

Only REAL Analyzer/Curator packages under input/ and saved projects under
output/projects/ are listed. An Analyzer R6 ZIP is NOT a Studio R57 execution
plan. Never render an Analyzer ZIP as if it were an approved editorial package.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import re
from urllib.parse import parse_qs, urlsplit
from zipfile import BadZipFile, ZipFile

from .workspace import application_root, project_output_root

R57_REQUIRED = frozenset({
    'EXECUTION_PLAN.json', 'MANIFEST_SHA256.json', 'REELS_EDIT_PLAN.json',
    'STORIES_SEQUENCIAIS_REVISAR.json', 'QUALITY_GATES.json',
})
R6_REQUIRED = frozenset({'SECOND_CURATION_MANIFEST.json', 'CURATION_INDEX.json'})
_CBJR_R57_SOURCE = 'f8b424b9fc26c79141fb2288fee3354d5f02c1c773523f87f95b1191252283ea'
_CBJR_TITLE = 'Charlie Brown Jr. — Planeta Atlântida 2012'
_MAX_JSON = 2 * 1024 * 1024
_MAX_INPUT_FILES = 3000
_MAX_ZIPS = 250


def input_root() -> Path:
    return application_root() / 'input'


def _read_local_json(path: Path):
    if not path.is_file() or path.stat().st_size > _MAX_JSON:
        return {}
    with path.open('rb') as stream:
        value = json.load(stream)
    return value if isinstance(value, dict) else {}


def _zip_json(archive: ZipFile, member: str):
    try:
        info = archive.getinfo(member)
    except KeyError:
        return {}
    if info.file_size > _MAX_JSON or info.file_size < 0:
        return {}
    try:
        obj = json.loads(archive.read(info))
    except (UnicodeError, json.JSONDecodeError, RuntimeError, ValueError):
        return {}
    return obj if isinstance(obj, dict) else {}


def _fallback_title(path: Path) -> str:
    name = path.stem
    name = re.sub(r'(?i)\b(segunda|second|curation|curadoria|package|pacote|handoff|analyzer|studio|output|input|zip|r5[0-9]|r6[0-9]?)\b', ' ', name)
    name = re.sub(r'[_-]+', ' ', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name[:110] or path.stem[:110]


def _source_title(*, explicit='', source_sha='', path: Path) -> str:
    title = str(explicit or '').strip()
    if title:
        return title[:150]
    if source_sha == _CBJR_R57_SOURCE:
        return _CBJR_TITLE
    return _fallback_title(path)


def _video_id(url: str) -> str:
    try:
        p = urlsplit(url)
        if p.hostname in ('youtube.com', 'www.youtube.com', 'm.youtube.com'):
            value = parse_qs(p.query).get('v', [''])[0]
        elif p.hostname in ('youtu.be', 'www.youtu.be'):
            value = p.path.strip('/')
        else:
            return ''
        return value if re.fullmatch(r'[A-Za-z0-9_-]{11}', value) else ''
    except (TypeError, ValueError):
        return ''


def _record(kind: str, path: Path, title: str, status: str, **details) -> dict:
    resolved = path.resolve()
    return {
        'id': sha256((kind + '\0' + str(resolved)).encode('utf-8')).hexdigest()[:20],
        'kind': kind, 'path': str(resolved), 'title': title[:150],
        'status': status,
        'reels': 0, 'stories': 0, 'candidates': 0,
        'source_sha256': '', 'run_id': '', 'source_url': '',
        **details,
    }


def inspect_zip(path: Path) -> dict | None:
    """Classify one ZIP without extraction; inspect bounded metadata only.

    Full per-file SHA and R57 contracts are validated only when the user opens
    the package with CuradoriaPackage/Project.create.
    """
    try:
        with ZipFile(path) as z:
            names = set(z.namelist())
            if R57_REQUIRED <= names:
                plan = _zip_json(z, 'EXECUTION_PLAN.json')
                source_sha = str(plan.get('source_sha256') or '')
                reels = plan.get('reels')
                stories = plan.get('stories')
                if not isinstance(reels, list) or not isinstance(stories, list):
                    return _record('invalid_zip', path, _fallback_title(path),
                                   'PLANO R57 INCOMPLETO')
                title = _source_title(explicit=plan.get('source_title') or plan.get('video_title') or '',
                                      source_sha=source_sha, path=path)
                return _record('curator_zip', path, title, 'CURADORIA PRONTA PARA IMPORTAR',
                               reels=len(reels), stories=len(stories),
                               source_sha256=source_sha,
                               source_url=str(plan.get('source_url') or ''),
                               run_id=str(plan.get('run_id') or ''))
            if R6_REQUIRED <= names:
                manifest = _zip_json(z, 'SECOND_CURATION_MANIFEST.json')
                index = _zip_json(z, 'CURATION_INDEX.json')
                source = index.get('source') if isinstance(index.get('source'), dict) else {}
                source_sha = str(manifest.get('source_hash') or '')
                title = _source_title(explicit=source.get('title') or '',source_sha=source_sha,path=path)
                run_id = str(manifest.get('run_id') or index.get('run_id') or '')
                workflow = manifest.get('workflow') if isinstance(manifest.get('workflow'), dict) else {}
                review_state = str(workflow.get('review_state') or 'PARTIAL')
                candidates = index.get('candidate_count') or 0
                try: candidates = max(0,int(candidates))
                except (TypeError, ValueError): candidates = 0
                return _record('analyzer_zip', path, title,
                               'ANALYZER R6 — AGUARDANDO SEGUNDA CURADORIA',
                               candidates=candidates, source_sha256=source_sha,
                               run_id=run_id, source_url=str(source.get('url') or ''),
                               analyzer_state=review_state)
            return None
    except (OSError, BadZipFile, EOFError, ValueError, RuntimeError):
        return _record('invalid_zip', path, _fallback_title(path),
                       'ZIP ILEGÍVEL OU INCOMPLETO')


def inspect_project(path: Path) -> dict | None:
    try:
        state = _read_local_json(path / 'project.json')
        if state.get('schema_version') != '1.0':
            return None
        archive = path / 'input' / 'curadoria.zip'
        if not archive.is_file():
            return _record('invalid_project', path, path.name,
                           'PROJETO SEM ZIP ORIGINAL')
        with ZipFile(archive) as z:
            if not R57_REQUIRED <= set(z.namelist()):
                return _record('invalid_project',path,path.name,'PACOTE INCOMPATÍVEL')
            plan = _zip_json(z,'EXECUTION_PLAN.json')
        source_sha = str(state.get('source_sha256') or '')
        title = _source_title(explicit=state.get('source_title') or plan.get('source_title') or '',
                              source_sha=source_sha,path=path)
        reels = plan.get('reels',[])
        stories = plan.get('stories',[])
        media = bool(state.get('media_path') and Path(state['media_path']).is_file())
        return _record('project',path,title,
                       'PROJETO EM ANDAMENTO' if media else 'PROJETO — VÍDEO PENDENTE',
                       reels=len(reels) if isinstance(reels,list) else 0,
                       stories=len(stories) if isinstance(stories,list) else 0,
                       source_sha256=source_sha,
                       run_id=str(state.get('created_at') or ''),
                       media_linked=media,
                       edited_cuts=len(state.get('items') or {}),
                       source_url=str(state.get('youtube_url') or ''))
    except (OSError, BadZipFile, EOFError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return _record('invalid_project',path,path.name,'PROJETO NÃO PÔDE SER LIDO')


def _input_zips(root: Path):
    """Walk only input/, with depth/entry bounds and no symlink following."""
    if not root.is_dir():
        return
    visited=0
    found=0
    for base,dirs,files in os.walk(root,followlinks=False):
        current=Path(base)
        depth=len(current.relative_to(root).parts)
        dirs[:]=sorted(d for d in dirs if depth<5 and not d.startswith('.')
                       and not (depth==0 and d=='videos')
                       and not (current/d).is_symlink())
        for filename in sorted(files):
            visited+=1
            if visited>_MAX_INPUT_FILES:
                return
            if not filename.lower().endswith('.zip') or filename.startswith('.'):
                continue
            path=current/filename
            if path.is_symlink() or not path.is_file():
                continue
            found+=1
            yield path
            if found>=_MAX_ZIPS:
                return


def discover_catalog(input_directory=None, projects_directory=None) -> list[dict]:
    """Return a current, selection-ready list of real stored shows and handoffs."""
    inbox = Path(input_directory or input_root()).expanduser().resolve()
    projects = Path(projects_directory or project_output_root()).expanduser().resolve()
    inbox.mkdir(parents=True,exist_ok=True)
    items=[]
    if projects.is_dir():
        for path in sorted(projects.iterdir()):
            if path.is_dir() and not path.is_symlink() and not path.name.startswith('.'):
                row=inspect_project(path)
                if row: items.append(row)
    for zip_path in _input_zips(inbox):
        row=inspect_zip(zip_path)
        if row: items.append(row)
    order={'project':0,'curator_zip':1,'analyzer_zip':2,'invalid_project':3,'invalid_zip':4}
    items.sort(key=lambda r:(order.get(r['kind'],9),r['title'].casefold(),r['path'].casefold()))
    return items


def catalog_label(item: dict) -> str:
    kind=item['kind']
    counts=(f"{item['reels']} Reels + {item['stories']} Stories" if kind in ('project','curator_zip')
            else f"{item['candidates']} candidatos" if kind=='analyzer_zip' else '')
    run=f" | {item['run_id'][:12]}" if kind=='analyzer_zip' and item.get('run_id') else ''
    return f"{item['title']}  |  {item['status']}"+(f" | {counts}" if counts else '')+run
