"""Archive integrity, immutable edit plans and review-bound render records.

Pure-Python core. The input editorial ZIP is READ ONLY. Projects are stored in a
separate workspace, with atomic state writes and no automatic publication.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import uuid
import zipfile

VIDEO_EXT = {'.mp4', '.mkv', '.webm', '.mov', '.m4v'}
SAFE_MEDIA = re.compile(r'^(REEL|STORY)_\d{2,3}$')
ALLOWED_SUFFIXES = {'.png','.jpg','.jpeg','.json','.csv','.txt','.md','.ass','.srt','.py','.html'}
MAX_ARCHIVE_BYTES = 600 * 1024 * 1024
MAX_MEMBER_BYTES = 70 * 1024 * 1024
MAX_ENTRIES = 1500


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(2 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False,
                      separators=(',', ':')).encode('utf-8')


def fingerprint(value) -> str:
    return sha256_bytes(json_bytes(value))


def atomic_write(path: Path, document) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temp.write_text(json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False) + '\n', encoding='utf-8')
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def read_json(path: Path, default=None):
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding='utf-8-sig'))


def _assert_valid_path(name: str):
    parts = PurePosixPath(name)
    if not name or '\\' in name or ':' in name or name.startswith('/') or '..' in parts.parts or parts.is_absolute():
        raise ValueError('Caminho inseguro no ZIP: ' + name)
    if name.endswith('/'):
        return
    if any(x in {'.',''} for x in parts.parts) or Path(name).suffix.lower() not in ALLOWED_SUFFIXES:
        raise ValueError('Tipo/caminho não permitido no pacote: ' + name)


@dataclass(frozen=True)
class Clip:
    id: str
    kind: str
    start: float
    end: float
    title: str
    thumbnail: str
    caption_ass: str
    caption_srt: str

    @property
    def duration(self):
        return self.end - self.start


class CuradoriaPackage:
    """Strict, source-bound loader of the R57 editorial execution contract."""
    def __init__(self, archive_path: str | Path):
        self.path = Path(archive_path).expanduser().resolve()
        if not self.path.is_file() or self.path.suffix.lower() != '.zip':
            raise ValueError('Selecione um pacote de curadoria .zip existente')
        self.digest = sha256_file(self.path)
        with zipfile.ZipFile(self.path) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ENTRIES or sum(x.file_size for x in infos) > MAX_ARCHIVE_BYTES:
                raise ValueError('Pacote excede os limites de segurança')
            files = {}
            seen = set()
            for info in infos:
                name = info.filename
                _assert_valid_path(name)
                if info.is_dir():
                    continue
                if info.file_size > MAX_MEMBER_BYTES or stat.S_ISLNK(info.external_attr >> 16):
                    raise ValueError('Entrada não permitida no ZIP: ' + name)
                if name.casefold() in seen:
                    raise ValueError('Caminho duplicado no ZIP: ' + name)
                seen.add(name.casefold())
                files[name] = info
            required = {'EXECUTION_PLAN.json','MANIFEST_SHA256.json','REELS_EDIT_PLAN.json',
                        'STORIES_SEQUENCIAIS_REVISAR.json','QUALITY_GATES.json'}
            if not required <= files.keys():
                raise ValueError('Pacote não é um contrato de execução R57 completo: ' + str(required - files.keys()))
            manifest = json.loads(archive.read('MANIFEST_SHA256.json'))
            declared = manifest.get('files')
            if not isinstance(declared,list) or len(declared)!=len(set(x.get('path') for x in declared)):
                raise ValueError('Manifesto inválido ou duplicado')
            if set(files) != {x['path'] for x in declared} | {'MANIFEST_SHA256.json'}:
                raise ValueError('Manifesto não corresponde aos arquivos do ZIP')
            for entry in declared:
                name=entry['path']
                info=files[name]
                if entry.get('bytes')!=info.file_size or sha256_bytes(archive.read(name))!=entry.get('sha256'):
                    raise ValueError('SHA256 divergente no pacote: '+name)
            self.plan = json.loads(archive.read('EXECUTION_PLAN.json'))
            self.reels_plan = json.loads(archive.read('REELS_EDIT_PLAN.json'))
            self.stories_plan = json.loads(archive.read('STORIES_SEQUENCIAIS_REVISAR.json'))
            self.quality_gates = json.loads(archive.read('QUALITY_GATES.json'))
            self.manifest = manifest
            self.available = frozenset(files)
        self.source_sha = self.plan['source_sha256']
        if not re.fullmatch(r'[a-f0-9]{64}', self.source_sha):
            raise ValueError('SHA256 da fonte inválido')
        if (self.reels_plan.get('source_sha256')!=self.source_sha
                or self.stories_plan.get('source_sha256')!=self.source_sha
                or self.quality_gates.get('original_source_sha256')!=self.source_sha):
            raise ValueError('SHA256 de fonte diverge entre os planos')
        self.source_duration=float(self.plan['source_duration_seconds'])
        if not math.isfinite(self.source_duration) or self.source_duration<=0:
            raise ValueError('Duração da fonte inválida')
        self.clips = {}
        for kind in ('reels','stories'):
            rows = self.plan.get(kind)
            if not isinstance(rows,list) or not rows:
                raise ValueError(f'Lista {kind} ausente')
            for row in rows:
                cid=row['id']
                if not SAFE_MEDIA.fullmatch(cid) or cid in self.clips or (cid.startswith('REEL_')) != (kind=='reels'):
                    raise ValueError('ID de corte inválido ou duplicado: '+cid)
                start,end=float(row['source_start']),float(row['source_end'])
                if not all(map(math.isfinite,(start,end))) or not 0<=start<end<=self.source_duration+0.001:
                    raise ValueError('Janela fora da fonte: '+cid)
                if abs(end-start-float(row['duration_seconds']))>0.012:
                    raise ValueError('Duração do corte inconsistente: '+cid)
                for key in ('thumbnail','caption_ass','caption_srt'):
                    if row[key] not in self.available:
                        raise ValueError('Asset de corte ausente: '+cid+' -> '+row[key])
                    if not row[key].startswith(('REELS/' if kind=='reels' else 'STORIES/')+cid+'/'):
                        raise ValueError('Asset fora da pasta do corte: '+cid)
                self.clips[cid] = Clip(cid,kind,start,end,str(row['title']),
                    row['thumbnail'],row['caption_ass'],row['caption_srt'])
        if set(x['id'] for x in self.reels_plan['clips']) != {x for x in self.clips if x.startswith('REEL_')}:
            raise ValueError('Plano editorial Reels não corresponde ao plano de execução')
        stories=sorted((c for c in self.clips.values() if c.kind=='stories'),key=lambda c:c.start)
        if abs(stories[0].start)>0.003 or abs(stories[-1].end-self.source_duration)>0.003:
            raise ValueError('Stories não cobrem a fonte inteira')
        if any(abs(a.end-b.start)>0.003 for a,b in zip(stories,stories[1:])):
            raise ValueError('Stories apresentam gaps/overlaps')
        if any(c.duration>60.001 for c in stories):
            raise ValueError('Story maior que 60 segundos')

    def data(self, name: str) -> bytes:
        if name not in self.available:
            raise ValueError('Arquivo não declarado no manifesto: ' + name)
        with zipfile.ZipFile(self.path) as archive:
            return archive.read(name)

    def json(self, name: str):
        return json.loads(self.data(name))

    def items(self, kind='all'):
        rows=list(self.clips.values())
        if kind in ('reels','stories'):
            rows=[c for c in rows if c.kind==kind]
        return sorted(rows,key=lambda c:(0 if c.kind=='reels' else 1,int(c.id.split('_')[1])))

    def caption_status(self, cid: str):
        c=self.clips[cid]
        sub=c.thumbnail.rsplit('/',1)[0] + '/LEGENDA_REVISAO.json'
        return self.json(sub)


class Project:
    """Persisted project. Every edited setting changes the approval fingerprint."""
    def __init__(self, workdir: str | Path):
        self.dir=Path(workdir).expanduser().resolve()
        self.state_path=self.dir/'project.json'
        self.state=read_json(self.state_path)
        if not self.state or self.state.get('schema_version')!='1.0':
            raise FileNotFoundError('Projeto Curator Studio inexistente: '+str(self.dir))
        archive=self.dir/'input'/'curadoria.zip'
        if sha256_file(archive)!=self.state['package_sha256']:
            raise ValueError('Pacote original alterado depois da importação')
        self.package=CuradoriaPackage(archive)
        self._media_cache=None
        if self.package.source_sha!=self.state['source_sha256']:
            raise ValueError('Fonte do projeto mudou')

    @classmethod
    def create(cls, archive_path: str | Path, workdir: str | Path):
        destination=Path(workdir).expanduser().resolve()
        if (destination/'project.json').exists():
            return cls(destination)
        package=CuradoriaPackage(archive_path)
        if any(destination.iterdir()) if destination.exists() else False:
            raise FileExistsError('Pasta de projeto contém arquivos. Escolha uma pasta vazia: '+str(destination))
        (destination/'input').mkdir(parents=True,exist_ok=True)
        shutil.copy2(package.path,destination/'input'/'curadoria.zip')
        state={'schema_version':'1.0','created_at':now(),'package_sha256':package.digest,
            'source_sha256':package.source_sha,'source_duration_seconds':package.source_duration,
            'media_path':None,'media_stat':None,'items':{},'history':[],
            'publication_ready':False,'project_status':'REVIEW_REQUIRED'}
        atomic_write(destination/'project.json',state)
        return cls(destination)

    def save(self):
        atomic_write(self.state_path,self.state)

    def _item(self,cid):
        if cid not in self.package.clips: raise ValueError('Corte não existe: '+cid)
        return self.state['items'].setdefault(cid,{'settings':{},'previews':[], 'approval':None,'finals':[]})

    def settings(self,cid):
        clip=self.package.clips[cid]
        override=self._item(cid)['settings']
        return {
            'title':override.get('title',clip.title),
            'source_start':override.get('source_start',clip.start),
            'source_end':override.get('source_end',clip.end),
            'layout':override.get('layout','preserve'),
            'center_x':override.get('center_x',0.5),
            'subtitles':override.get('subtitles',False),
            'captions_verified':override.get('captions_verified',False),
            'camera_reviewed':override.get('camera_reviewed',False),
            'audio_reviewed':override.get('audio_reviewed',False),
            'rights_verified':override.get('rights_verified',False),
            'title_overlay':override.get('title_overlay',True),
        }

    def update(self,cid,**edits):
        settings=self.settings(cid)
        if set(edits)-set(settings):
            raise ValueError('Configuração desconhecida: '+str(set(edits)-set(settings)))
        settings.update(edits)
        clip=self.package.clips[cid]
        a,b=float(settings['source_start']),float(settings['source_end'])
        if not (math.isfinite(a) and math.isfinite(b) and 0<=a<b<=self.package.source_duration+0.001):
            raise ValueError('Entrada/saída fora da duração do vídeo')
        if clip.kind=='stories' and (abs(a-clip.start)>0.001 or abs(b-clip.end)>0.001):
            raise ValueError('Stories preservam intervalo original contínuo. Edite apenas os Reels.')
        if settings['layout'] not in {'preserve','center_crop','solo_fit','smart_zoom'}:
            raise ValueError('Layout desconhecido')
        x=float(settings['center_x'])
        if not 0<=x<=1: raise ValueError('Centro da câmera deve ser entre 0 e 1')
        settings['center_x']=x
        settings['title']=str(settings['title']).strip()[:130]
        if not settings['title']:
            raise ValueError('Título vazio')
        for key in ('subtitles','captions_verified','camera_reviewed','audio_reviewed','rights_verified','title_overlay'):
            if not isinstance(settings[key],bool): raise ValueError('Campo booleano inválido: '+key)
        if settings['subtitles'] and not settings['captions_verified']:
            raise ValueError('Legendas ASR não revisadas: confirme transcrição e áudio antes de habilitar')
        old = self.settings(cid)
        if settings != old:
            render_keys = ('title','source_start','source_end','layout','center_x','subtitles','title_overlay')
            affects_render = any(settings[k] != old[k] for k in render_keys)
            self._item(cid)['settings']=settings
            if affects_render:
                self._item(cid)['approval']=None
            self.state['history'].append({'at':now(),'item':cid,
                'event':'RENDER_CHANGED_APPROVAL_INVALIDATED' if affects_render else 'REVIEW_FLAGS_UPDATED'})
            self.save()
        return settings

    def set_media(self,path):
        value=Path(path).expanduser().resolve()
        if not value.is_file() or value.suffix.lower() not in VIDEO_EXT:
            raise ValueError('Selecione o MP4/MKV/WebM/MOV original existente')
        digest=sha256_file(value)
        if digest!=self.package.source_sha:
            raise ValueError('SHA256 da mídia NÃO corresponde ao Analyzer. Fonte esperada: '+self.package.source_sha+'; recebida: '+digest)
        from .rendering import probe_media
        info=probe_media(value)
        if not info['has_audio'] or not info['has_video']:
            raise ValueError('Mídia original precisa de áudio e vídeo')
        if abs(info['duration']-self.package.source_duration)>3:
            raise ValueError(f'Duração diverge da análise: {info["duration"]:.3f}s ≠ {self.package.source_duration:.3f}s')
        previous=self.state.get('media_path')
        if (previous and Path(previous).resolve()!=value) or self.active_media_sha()!=digest:
            for item in self.state['items'].values():
                item['approval']=None
        st=value.stat()
        self.state.update(media_path=str(value),media_sha256=digest,
            media_mode='EXACT_ANALYZER_SOURCE',source_association=None,
            media_stat={'size':st.st_size,'mtime_ns':st.st_mtime_ns})
        self._media_cache=(str(value),st.st_size,st.st_mtime_ns,digest)
        self.save()
        return info

    def active_media_sha(self):
        """SHA256 of bytes actually rendered, not necessarily Analyzer's input bytes."""
        return self.state.get('media_sha256') or self.package.source_sha

    def review_download_for_previews(self, *, confirm_timeline=False):
        """Allow a downloaded recode only for preview review, with distinct provenance.

        An identical YouTube ID and duration DO NOT prove matching edit timestamps.
        Clips require human audio/context and camera review before rendering finals.
        """
        if not confirm_timeline:
            raise ValueError('Revisão explícita da origem necessária: confira áudio e sincronização nas prévias')
        record=next((r for r in reversed(self.state.get('download_history',[]))
            if r.get('status')=='SOURCE_REVIEW_REQUIRED' and r.get('path')),None)
        if record is None:
            raise ValueError('Nenhum download divergente registrado neste projeto')
        path=Path(record['path']).resolve()
        from .youtube_download import managed_download_path
        if (not managed_download_path(self,path,record.get('video_id'))
            or not path.is_file() or path.is_symlink()):
            raise ValueError('Vídeo fora de input/videos ou dos locais antigos permitidos')
        receipt=read_json(path.parent/'download_report.json',{}) or {}
        if receipt!=record or receipt.get('expected_sha256')!=self.package.source_sha:
            raise ValueError('Relatório do download ausente, alterado ou de outra análise')
        from .youtube_download import source_video_id,parse_youtube_url
        video_id,canonical=parse_youtube_url(record.get('url',''))
        expected=source_video_id(self.package)
        if not expected or video_id!=expected or record.get('video_id')!=expected or record.get('url')!=canonical:
            raise ValueError('ID ou endereço do vídeo não corresponde à curadoria R57')
        digest=sha256_file(path)
        if digest!=record.get('sha256') or digest==self.package.source_sha:
            raise ValueError('SHA256 do download não confere com seu relatório ou já é fonte original')
        from .rendering import probe_media
        info=probe_media(path)
        if not info['has_video'] or not info['has_audio']:
            raise ValueError('Download sem áudio ou vídeo válido')
        if not math.isfinite(info['duration']) or abs(info['duration']-self.package.source_duration)>3:
            raise ValueError(
                f'Duração incompatível: download {info["duration"]:.3f}s, '
                f'curadoria {self.package.source_duration:.3f}s. '
                'Não reutilize timestamps: refaça a análise da mídia baixada.')
        if any(float(self.settings(c.id)['source_end'])>info['duration']+0.01
               for c in self.package.items()):
            raise ValueError('Existe corte além da duração do download; reanálise obrigatória')
        if (self.active_media_sha()!=digest or self.state.get('media_mode')!='ALTERNATE_REVIEW_SOURCE'):
            for item in self.state['items'].values():
                item['approval']=None
        st=path.stat()
        association={
            'status':'HUMAN_ACCEPTED_FOR_PREVIEWS_ONLY','confirmed_at':now(),
            'analyzer_source_sha256':self.package.source_sha,
            'actual_media_sha256':digest,'youtube_video_id':video_id,
            'download_report':str(path.parent/'download_report.json'),
            'warning':'Same YouTube ID and similar duration DO NOT prove matching timestamps',
        }
        self.state.update(media_path=str(path),media_sha256=digest,
            media_mode='ALTERNATE_REVIEW_SOURCE',source_association=association,
            media_stat={'size':st.st_size,'mtime_ns':st.st_mtime_ns})
        self._media_cache=None
        self.state['history'].append({'at':now(),'event':'ALTERNATE_SOURCE_ENABLED_FOR_PREVIEWS',
            'media_sha256':digest,'analyzer_sha256':self.package.source_sha})
        self.save()
        return {'status':'ALTERNATE_REVIEW_SOURCE','path':str(path),'actual_sha256':digest,
                'analyzer_sha256':self.package.source_sha,'duration_seconds':info['duration'],
                'warning':'Confira áudio, contexto e sincronização de CADA prévia antes de aprovar finais.'}

    def verified_media(self):
        path=self.state.get('media_path')
        if not path: raise ValueError('Mídia original não selecionada. Associe o arquivo e confira SHA256.')
        p=Path(path)
        if not p.is_file(): raise FileNotFoundError('Mídia original foi movida: '+path)
        st=p.stat()
        identity=(str(p),st.st_size,st.st_mtime_ns)
        digest=self.active_media_sha()
        mode=self.state.get('media_mode','EXACT_ANALYZER_SOURCE')
        if mode=='ALTERNATE_REVIEW_SOURCE':
            from .youtube_download import managed_download_path
            assoc=self.state.get('source_association') or {}
            report=read_json(p.parent/'download_report.json',{}) or {}
            video_id=assoc.get('youtube_video_id') or report.get('video_id')
            if (digest==self.package.source_sha
                or assoc.get('status')!='HUMAN_ACCEPTED_FOR_PREVIEWS_ONLY'
                or assoc.get('actual_media_sha256')!=digest
                or assoc.get('analyzer_source_sha256')!=self.package.source_sha
                or report.get('sha256')!=digest
                or report.get('status')!='SOURCE_REVIEW_REQUIRED'
                or report.get('expected_sha256')!=self.package.source_sha
                or (assoc.get('youtube_video_id') and report.get('video_id')!=assoc.get('youtube_video_id'))
                or not managed_download_path(self,p,video_id)):
                raise ValueError('Vínculo de revisão da mídia alternativa inválido')
        elif mode!='EXACT_ANALYZER_SOURCE' or digest!=self.package.source_sha:
            raise ValueError('A origem declarada diverge do Analyzer')
        if (mode=='EXACT_ANALYZER_SOURCE' and self._media_cache
            and self._media_cache[:3]==identity and self._media_cache[3]==digest):
            return p
        if sha256_file(p)!=digest:
            raise ValueError('Arquivo de mídia mudou: SHA256 da mídia vinculada diverge')
        self._media_cache=(*identity,digest)
        return p

    def caption_payload(self,cid):
        clip=self.package.clips[cid]
        alt=self._item(cid).get('caption_override')
        if alt:
            path=self.dir/alt['relative_path']
            if not path.is_file() or sha256_file(path)!=alt['sha256']:
                raise ValueError('Legenda revisada alterada ou ausente: não renderizar')
            return path.read_bytes()
        return self.package.data(clip.caption_ass)

    def import_caption(self,cid,path):
        if cid not in self.package.clips:
            raise ValueError('Corte não reconhecido')
        p=Path(path).expanduser().resolve()
        if p.suffix.lower()!='.ass' or not p.is_file() or p.stat().st_size>2*1024*1024:
            raise ValueError('Importe ASS revisada válida de até 2 MiB')
        content=p.read_bytes()
        try: text=content.decode('utf-8-sig')
        except UnicodeDecodeError as error:
            raise ValueError('Legenda revisada precisa estar em UTF-8') from error
        if '[Script Info]' not in text or '[Events]' not in text or 'Dialogue:' not in text:
            raise ValueError('ASS não contém seções e eventos necessários')
        digest=sha256_bytes(content)
        dest=self.dir/'reviews'/'captions'/cid/(digest+'.ass')
        dest.parent.mkdir(parents=True,exist_ok=True)
        if not dest.is_file():dest.write_bytes(content)
        item=self._item(cid)
        item['caption_override']={'relative_path':dest.relative_to(self.dir).as_posix(),'sha256':digest}
        current=self.settings(cid)
        current['captions_verified']=False
        current['subtitles']=False
        item['settings']=current
        item['approval']=None
        self.state['history'].append({'at':now(),'item':cid,'event':'REVISED_CAPTION_IMPORTED_APPROVAL_INVALIDATED'})
        self.save()
        return dest

    def render_binding(self,cid,preview: bool):
        c=self.package.clips[cid]
        settings=self.settings(cid)
        subtitle_sha=sha256_bytes(self.caption_payload(cid)) if settings['subtitles'] else None
        from .rendering import render_code_signature
        pixel_settings={k:settings[k] for k in
            ('title','source_start','source_end','layout','center_x','subtitles','title_overlay')}
        return fingerprint({'schema':'studio-v1','clip':cid,'source':self.package.source_sha,
             'render_media_sha256':self.active_media_sha(),
             'media_mode':self.state.get('media_mode','EXACT_ANALYZER_SOURCE'),
             'package':self.package.digest,'settings':pixel_settings,'preview':preview,
             'subtitle_sha':subtitle_sha,'code':render_code_signature()})

    def preview_record(self,cid):
        records=self._item(cid)['previews']
        binding=self.render_binding(cid,True)
        for item in reversed(records):
            p=self.dir/item['relative_path']
            if item.get('binding')==binding and p.is_file() and sha256_file(p)==item.get('sha256'):
                return item
        return None

    def approval_matches(self,cid):
        item=self._item(cid)
        approval=item['approval']
        preview=self.preview_record(cid)
        settings=self.settings(cid)
        return bool(approval and preview and settings['audio_reviewed'] and settings['camera_reviewed']
                    and approval.get('preview_sha256')==preview['sha256']
                    and approval.get('binding')==preview['binding']
                    and approval.get('media_sha256')==self.active_media_sha())

    def approve(self,cid,*,human_reviewed,verified_audio,verified_camera):
        preview=self.preview_record(cid)
        if preview is None: raise ValueError('Não existe prévia íntegra da revisão atual')
        if not all([human_reviewed,verified_audio,verified_camera]):
            raise ValueError('Assista e confirme áudio/contexto e enquadramento antes de aprovar')
        settings=self.settings(cid)
        if settings['subtitles'] and not settings['captions_verified']:
            raise ValueError('Legendas não aprovadas')
        # Explicit confirmation applies to CLI callers as well as the GUI.
        self.update(cid,audio_reviewed=True,camera_reviewed=True)
        settings=self.settings(cid)
        approval={'at':now(),'preview_sha256':preview['sha256'],'binding':preview['binding'],
                  'media_sha256':self.active_media_sha(),
                  'media_mode':self.state.get('media_mode','EXACT_ANALYZER_SOURCE'),
                  'human_reviewed':True,
                  'audio_reviewed':True,'camera_reviewed':True,
                  'rights_verified':settings['rights_verified']}
        self._item(cid)['approval']=approval
        self.state['history'].append({'at':now(),'item':cid,'event':'PREVIEW_APPROVED'})
        self.save()
        return approval

    def record_render(self,cid,path:Path,*,preview,report):
        relative=path.relative_to(self.dir).as_posix()
        record={'at':now(),'relative_path':relative,'sha256':sha256_file(path),
                'binding':self.render_binding(cid,preview),'preview':preview,'report':report}
        key='previews' if preview else 'finals'
        self._item(cid)[key].append(record)
        if preview:self._item(cid)['approval']=None
        self.state['history'].append({'at':now(),'item':cid,'event':('PREVIEW' if preview else 'FINAL')+'_RENDERED'})
        self.save()
        return record

    def final_record(self,cid):
        binding=self.render_binding(cid,False)
        for item in reversed(self._item(cid)['finals']):
            if item['binding']!=binding: continue
            f=self.dir/item['relative_path']
            if f.is_file() and sha256_file(f)==item['sha256']:
                return item
        return None

    def status(self,cid):
        if self.final_record(cid): return 'FINAL_READY_REVIEW_RIGHTS'
        if self.approval_matches(cid): return 'PREVIEW_APPROVED'
        if self.preview_record(cid): return 'PREVIEW_READY_REVIEW'
        return 'PENDING_PREVIEW'

    def export_manifest(self):
        rows=[]
        for c in self.package.items():
            settings=self.settings(c.id)
            final=self.final_record(c.id)
            status=self.status(c.id)
            rows.append({'id':c.id,'kind':c.kind,'title':settings['title'],
                         'source_start':settings['source_start'],'source_end':settings['source_end'],
                         'status':status,'final':final,'rights_verified':settings['rights_verified'],
                         'publication_ready':bool(final and self.approval_matches(c.id) and settings['rights_verified'])})
        result={'generated_at':now(),'program':'LDPORTO_CURATOR_STUDIO_1.0',
                'source_sha256':self.package.source_sha,'package_sha256':self.package.digest,
                 'render_media_sha256':self.active_media_sha(),
                 'media_mode':self.state.get('media_mode','EXACT_ANALYZER_SOURCE'),
                'warning':'Exportação local não implica autorização de publicação',
                'items':rows}
        atomic_write(self.dir/'EXPORT_MANIFEST.json',result)
        return result
