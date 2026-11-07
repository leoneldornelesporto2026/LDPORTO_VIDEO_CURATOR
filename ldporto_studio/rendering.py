"""Safe FFmpeg renderer with source-preserving composition and bounded output.

Never assumes speaker tracking or verified subtitles from a partial Analyzer ZIP.
All paths passed to subprocess as argument arrays, not shell strings.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
from uuid import uuid4

from .core import sha256_file, sha256_bytes, atomic_write


def binaries():
    ffmpeg=shutil.which('ffmpeg')
    ffprobe=shutil.which('ffprobe')
    if not ffmpeg or not ffprobe:
        raise RuntimeError('FFmpeg e FFprobe não encontrados no PATH. Instale FFmpeg antes de renderizar.')
    return ffmpeg,ffprobe


def render_code_signature():
    # Template and camera changes invalidate old preview approvals.
    from . import smart_camera, visual_style, r6_camera_evidence
    hashes=(sha256_file(Path(__file__)),sha256_file(Path(smart_camera.__file__)),
            sha256_file(Path(visual_style.__file__)),
            sha256_file(Path(r6_camera_evidence.__file__)))
    return sha256_bytes(''.join(hashes).encode('ascii'))


def probe_media(path):
    _, probe=binaries()
    cmd=[probe,'-v','error','-show_format','-show_streams','-of','json',str(path)]
    p=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=150)
    if p.returncode!=0:
        raise ValueError('FFprobe falhou: '+(p.stderr or '')[-1000:])
    data=json.loads(p.stdout)
    streams=data.get('streams',[])
    videos=[x for x in streams if x.get('codec_type')=='video']
    audios=[x for x in streams if x.get('codec_type')=='audio']
    duration=float(data.get('format',{}).get('duration') or (videos[0].get('duration') if videos else 0) or 0)
    return {'has_video':bool(videos),'has_audio':bool(audios),
            'duration':duration,'width':int(videos[0].get('width',0)) if videos else 0,
            'height':int(videos[0].get('height',0)) if videos else 0,
            'video_codec':videos[0].get('codec_name') if videos else None,
            'audio_codec':audios[0].get('codec_name') if audios else None,
            'fps':videos[0].get('avg_frame_rate') if videos else None}


def _font(size):
    from PIL import ImageFont
    paths=[
        Path('C:/Windows/Fonts/arialbd.ttf'),Path('C:/Windows/Fonts/seguisb.ttf'),
        Path('C:/Windows/Fonts/impact.ttf'),
        Path('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'),
        Path('/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf')]
    for candidate in paths:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate),size)
    return ImageFont.load_default()


def _lines(draw,text,font,max_width,max_lines=3):
    words=str(text).upper().split()
    rows=[]
    current=''
    for word in words:
        candidate=(current+' '+word).strip()
        if current and draw.textbbox((0,0),candidate,font=font)[2]>max_width:
            rows.append(current)
            current=word
        else: current=candidate
    if current:rows.append(current)
    if len(rows)>max_lines:
        rows=rows[:max_lines]
        rows[-1]=rows[-1].rstrip(' .')+'…'
    return rows


def title_overlay(out:Path,title:str,width:int,height:int,kind:str,footer=None):
    """Use the approved white/yellow live card, tailored to the selected show."""
    from .visual_style import save_title_overlay
    return save_title_overlay(out,title,width,height,kind,footer=footer)


def create_cover_from_frame(project,cid,destination:Path):
    """Render premium cover from the verified video, without altering the R57 ZIP."""
    from PIL import Image
    from .visual_style import premium_cover
    ffmpeg,_=binaries()
    c=project.package.clips[cid]
    s=project.settings(cid)
    source=project.verified_media()
    t=(float(s['source_start'])+float(s['source_end']))/2
    destination=Path(destination)
    destination.parent.mkdir(parents=True,exist_ok=True)
    if destination.exists():
        raise FileExistsError('A capa existente não será sobrescrita: '+str(destination))
    tmp=destination.with_name('captured_'+uuid4().hex+'.png')
    try:
        result=subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-nostdin',
          '-ss',f'{t:.3f}','-i',str(source),'-frames:v','1','-y',str(tmp)],
          capture_output=True,text=True,timeout=180)
        if result.returncode or not tmp.is_file():
            raise RuntimeError('Não foi possível extrair quadro do vídeo: '+result.stderr[-600:])
        from .visual_style import footer_for_project
        with Image.open(tmp) as raw:
            cover=premium_cover(raw,s['title'],c.kind,
                                footer=footer_for_project(project,c.kind))
        cover.save(destination,'PNG')
        return destination
    finally:
        tmp.unlink(missing_ok=True)


def generate_premium_covers(project,kind='all',progress=None,cancel=None):
    """Batch-export actual frame-based covers for selected Reels/Stories.

    File destinations are versioned by title+media hash; never overwrite old edits.
    """
    clips=project.package.items(kind)
    root=project.dir/'exports'/'covers_premium'
    rows=[]
    for i,c in enumerate(clips):
        if cancel is not None and cancel.is_set():
            raise RuntimeError('Geração de capas cancelada; arquivos anteriores preservados')
        s=project.settings(c.id)
        key=sha256_bytes((c.id+s['title']+project.active_media_sha()+
             str(s['source_start'])+str(s['source_end'])).encode('utf-8'))[:12]
        dest=root/c.kind/c.id/key/'CAPA_PREMIUM.png'
        if not dest.exists():
            create_cover_from_frame(project,c.id,dest)
        rows.append({'id':c.id,'kind':c.kind,'title':s['title'],
                     'relative_path':dest.relative_to(project.dir).as_posix(),
                     'sha256':sha256_file(dest)})
        if progress:progress((i+1)/max(1,len(clips)),c.id)
    atomic_write(root/'COVERS_MANIFEST.json',{
        'status':'PREVIEW_ASSETS_REQUIRE_EDITORIAL_REVIEW',
        'media_sha256':project.active_media_sha(),
        'source_analyzer_sha256':project.package.source_sha,
        'template':'LDPORTO_WHITE_LIVE_V1','items':rows})
    return root,len(rows)


def extract_editorial_assets(project,kind='all',destination=None):
    """Export all real R57 covers, captions and publication draft without modifying ZIP."""
    target=Path(destination).expanduser().resolve() if destination else project.dir/'exports'/'editorial_assets'
    target.mkdir(parents=True,exist_ok=True)
    rows=[]
    for clip in project.package.items(kind):
        folder=target/clip.kind/clip.id
        folder.mkdir(parents=True,exist_ok=True)
        for key,name in ((clip.thumbnail,'CAPA.png'),(clip.caption_srt,'LEGENDA_RASCUNHO.srt'),
                         (clip.caption_ass,'KARAOKE_RASCUNHO.ass')):
            out=folder/name
            if out.exists() and sha256_file(out)!=sha256_bytes(project.package.data(key)):
                raise ValueError('Asset existente divergente, não sobrescrito: '+str(out))
            if not out.exists(): out.write_bytes(project.package.data(key))
        publi=clip.thumbnail.rsplit('/',1)[0]+'/PUBLICACAO_RASCUNHO.json'
        if publi in project.package.available:
            p=folder/'PUBLICACAO_RASCUNHO.json'
            if not p.exists():p.write_bytes(project.package.data(publi))
        rows.append({'id':clip.id,'title':project.settings(clip.id)['title'],
                     'cover':str((folder/'CAPA.png').relative_to(target)).replace('\\','/'),
                     'caption_status':'RASCUNHO_NAO_VERIFICADO','video_rendered':bool(project.final_record(clip.id))})
    atomic_write(target/'INDEX.json',{'package_sha256':project.package.digest,'source_sha256':project.package.source_sha,
                'export_type':'EDITORIAL_ASSETS_NOT_PUBLICATION','items':rows})
    return target,len(rows)


def _draft_caption_watermark(path, width, height):
    """Non-removable in-render review notice, never a publication asset."""
    from PIL import Image, ImageDraw
    canvas=Image.new("RGBA",(width,height),(0,0,0,0))
    draw=ImageDraw.Draw(canvas)
    font=_font(max(17,round(width*.033)))
    text="ASR RASCUNHO - CONFERIR AUDIO"
    bbox=draw.textbbox((0,0),text,font=font)
    content_width=bbox[2]-bbox[0]
    x=max(8,(width-content_width)//2)
    h=max(32,round(height*.052))
    draw.rounded_rectangle((max(0,x-10),6,min(width,x+content_width+10),h),
                           radius=7,fill=(0,0,0,207))
    draw.text((x,9),text,font=font,fill=(255,218,70,255))
    canvas.save(path)


def render_item(project,cid,*,preview:bool,progress=None,cancel=None,
                analyzer_inbox=None,draft_captions:bool=False,
                require_reframe:bool=False):
    """Preview/final or isolated ASR review preview (never approvable)."""
    if cid not in project.package.clips: raise ValueError('Corte inexistente')
    if draft_captions and not preview:
        raise ValueError('Legendas não revisadas são permitidas somente na prévia técnica')
    if not preview and not project.approval_matches(cid):
        raise ValueError('Final bloqueado: assista e aprove a prévia da revisão atual')
    source=project.verified_media()
    ffmpeg,_=binaries()
    clip=project.package.clips[cid]
    s=project.settings(cid)
    if s['subtitles'] and not s['captions_verified']:
        raise ValueError('Legendas sem conferência de áudio')
    if s['subtitles'] and (abs(float(s['source_start'])-clip.start)>0.002 or abs(float(s['source_end'])-clip.end)>0.002):
        raise ValueError('Intervalo editado: reveja realinhamento das legendas antes de ativá-las')
    start,end=float(s['source_start']),float(s['source_end'])
    duration=end-start
    if not (math.isfinite(duration) and duration>0.1):raise ValueError('Corte de duração inválida')
    width,height=(540,960) if preview else (1080,1920)
    run_id=datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')+'_'+uuid4().hex[:8]
    category=('caption_draft_previews' if draft_captions else
              ('previews' if preview else 'finals'))
    root=project.dir/'outputs'/category/cid/run_id
    root.mkdir(parents=True,exist_ok=False)
    movie=root/('PREVIEW_ASR_DRAFT_540x960.mp4' if draft_captions else
                ('PREVIEW_540x960.mp4' if preview else 'FINAL_1080x1920.mp4'))
    pending=root/'ENCODING.part.mp4'
    # Never overwrite the R57 package thumbnail.
    (root/'CAPA_PROPOSTA.png').write_bytes(project.package.data(clip.thumbnail))
    from .smart_camera import analyze_camera, crop_x_expression
    camera={'requested':s['layout'],'decision':'preserve' if s['layout']=='preserve' else 'crop',
            'reason':'Modo manual de enquadramento','camera_points':[]}
    if s['layout'] in ('solo_fit','smart_zoom'):
        if preview:
            camera=analyze_camera(source,start,end,s['layout'])
            if analyzer_inbox is not None:
                from .r6_camera_evidence import read_safe_r6_camera
                media=probe_media(source)
                evidence=read_safe_r6_camera(
                    analyzer_inbox,project.package.source_sha,start,end,
                    media['width'],media['height'])
                camera['r6_evidence']={k:v for k,v in evidence.items()
                                       if k!='trusted_regions'}
                trusted=evidence['trusted_regions']
                if trusted:
                    # R6 recommendations are evaluated per scene, not used
                    # as a whole-video identity claim.
                    camera.update(decision='dynamic',camera_regions=trusted,
                                  camera_points=[],source='VERIFIED_ANALYZER_R6_SOLO',
                                  reason='Geometria de pessoa isolada confirmada pelo Analyzer')
        else:
            verified_preview=project.preview_record(cid)
            if not verified_preview:
                raise ValueError('Plano inteligente exige prévia aprovada')
            camera=verified_preview['report'].get('camera_plan') or {}
            if camera.get('requested')!=s['layout'] or camera.get('decision') not in ('preserve','crop','dynamic'):
                raise ValueError('Plano de câmera ausente/divergente na prévia aprovada')
    if camera.get('decision')=='crop':
        portrait_coverage=1.
    elif camera.get('decision')=='dynamic':
        portrait_coverage=sum(
            max(0.,float(x['end'])-float(x['start']))
            for x in camera.get('camera_regions',[]))/duration
    else:
        portrait_coverage=0.
    camera['portrait_coverage_percent']=round(min(100.,portrait_coverage*100),1)
    if s['layout'] in ('solo_fit','smart_zoom'):
        atomic_write(root/'CAMERA_PLAN.json',camera)
    if require_reframe and portrait_coverage<.35:
        raise ValueError(
            f'Reenquadramento insuficiente: {portrait_coverage:.1%} em 9:16; '
            'mínimo editorial 35%. Revise CAMERA_PLAN.json e evidências do Analyzer.')
    caption_report=None
    if draft_captions:
        from .caption_second_pass import inspect_caption_second_pass
        caption_report=inspect_caption_second_pass(project,cid)
        if (caption_report['cue_count']<=0 or
                caption_report['ass_dialogue_count']<=0):
            raise ValueError('Sem legendas reais do Analyzer para este corte; não inventar texto')
    use_title=bool(s['title_overlay'])
    # Premium cover uses a real frame of the source, not a fabricated thumbnail.
    cover_error=None
    try:
        create_cover_from_frame(project,cid,root/'CAPA_PREMIUM.png')
    except (OSError,RuntimeError,ValueError) as error:
        cover_error=str(error)

    cmd=[ffmpeg,'-hide_banner','-nostdin','-loglevel','error','-ss',f'{start:.3f}',
         '-i',str(source)]
    if use_title:
        from .visual_style import footer_for_project
        title_overlay(root/'TITLE_OVERLAY.png',s['title'],width,height,clip.kind,
                      footer=footer_for_project(project,clip.kind))
        cmd+=['-loop','1','-framerate','30','-i',str(root/'TITLE_OVERLAY.png')]
    caption_enabled=bool(s['subtitles'] or draft_captions)
    if caption_enabled:
        (root/'captions.ass').write_bytes(project.caption_payload(cid))
    if draft_captions:
        _draft_caption_watermark(root/'ASR_REVIEW_BANNER.png',width,height)
        cmd+=['-loop','1','-framerate','30','-i',str(root/'ASR_REVIEW_BANNER.png')]
    filters=[f'[0:v]fps=30,trim=duration={duration:.3f},setpts=PTS-STARTPTS']
    dynamic=camera.get('decision')=='dynamic'
    if dynamic:
        regions=camera.get('camera_regions')
        if (not isinstance(regions,list) or not 1<=len(regions)<=24):
            raise ValueError('Plano smart zoom dinâmico inválido')
        last_end=0.
        for region in regions:
            if not isinstance(region,dict):
                raise ValueError('Região de câmera inválida')
            a,b,x=(float(region[k]) for k in ('start','end','x'))
            if (not all(math.isfinite(v) for v in (a,b,x))
                    or not 0<=a<b<=duration+.002 or not 0<=x<=1
                    or a<last_end):
                raise ValueError('Região de câmera fora do corte ou sobreposta')
            last_end=b
    if s['layout']=='preserve' or camera['decision'] in ('preserve','dynamic'):
        filters[0] += ',split=3[bg][fg][solo_src]' if dynamic else ',split=2[bg][fg]'
        filters.append(f'[bg]scale={width}:{height}:force_original_aspect_ratio=increase:force_divisible_by=2,'
                       f'crop={width}:{height},boxblur=luma_radius=20:luma_power=1[back]')
        filters.append(f'[fg]scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2,'
                       'setsar=1[front]')
        filters.append('[back][front]overlay=(W-w)/2:(H-h)/2:shortest=1,format=yuv420p[preserved]' if dynamic
                       else '[back][front]overlay=(W-w)/2:(H-h)/2:shortest=1,format=yuv420p[base]')
        if dynamic:
            # Leave the complete 16:9 scene visible by default. Overlay
            # portrait crop ONLY during stable, separately detected solo shots.
            # The static crop center changes at scene boundaries, not at 30fps.
            x_expr='0.5'
            for region in reversed(regions):
                points=region.get('camera_points')
                if points:
                    if (not isinstance(points,list) or len(points)>24 or
                            any(not isinstance(p,dict) or
                                not all(k in p and isinstance(p[k],(int,float))
                                        and math.isfinite(p[k]) for k in ('t','x'))
                                or not region['start']-0.002<=p['t']<=region['end']+0.002
                                or not 0<=p['x']<=1 for p in points)):
                        raise ValueError('Keyframes do Analyzer inválidos para o corte')
                    x_value=crop_x_expression(points)
                else:
                    x_value=f"{region['x']:.6f}"
                x_expr=(f"if(between(t,{region['start']:.3f},{region['end']:.3f}),"
                        f"{x_value},{x_expr})")
            intervals='+'.join(
                f"between(t,{row['start']:.3f},{row['end']:.3f})" for row in regions)
            filters.append(
                f"[solo_src]scale={width}:{height}:force_original_aspect_ratio=increase:"
                f"force_divisible_by=2,crop={width}:{height}:'(iw-ow)*({x_expr})':"
                "(ih-oh)/2,setsar=1[portrait]")
            filters.append(
                f"[preserved][portrait]overlay=0:0:shortest=1:"
                f"enable='{intervals}',format=yuv420p[base]")
    else:
        if s['layout'] in ('solo_fit','smart_zoom'):
            x=crop_x_expression(camera['camera_points'])
            x=f"'(iw-ow)*({x})'"
        else:
            x=f'(iw-ow)*{s["center_x"]:.4f}'
        filters[0]+=(f',scale={width}:{height}:force_original_aspect_ratio=increase:force_divisible_by=2,'
                      f'crop={width}:{height}:{x}:(ih-oh)/2,setsar=1,format=yuv420p[base]')
    current='base'
    if use_title:
        filters.append(f'[{current}][1:v]overlay=0:0:shortest=1:format=auto:enable=\'lt(t,3.2)\'[titled]')
        current='titled'
    if caption_enabled:
        # Relative path: Windows drive letters must not enter the FFmpeg filter.
        filters.append(f'[{current}]ass=captions.ass,format=yuv420p[captions]')
        current='captions'
    if draft_captions:
        banner_idx=2 if use_title else 1
        filters.append(f'[{current}][{banner_idx}:v]overlay=0:0:shortest=1:format=auto[review]')
        current='review'
    cmd+=['-t',f'{duration:.3f}','-filter_complex',';'.join(filters),
          '-map',f'[{current}]','-map','0:a:0',
          '-c:v','libx264','-preset','veryfast' if preview else 'medium',
          '-crf','23' if preview else '19',
          '-pix_fmt','yuv420p','-r','30','-c:a','aac','-b:a','192k',
          '-ar','48000']
    if clip.kind=='reels':
        tail=max(0,duration-.14)
        cmd+=['-af',f'afade=t=in:st=0:d=0.10,afade=t=out:st={tail:.3f}:d=0.14,loudnorm=I=-16:TP=-1.5:LRA=11']
    else:
        # Keep original Story dynamics consistent across contiguous chapters.
        cmd+=['-af','aresample=async=1:first_pts=0']
    cmd+=['-movflags','+faststart','-progress','pipe:1','-nostats','-y',str(pending)]
    log=root/'ffmpeg.log'
    initial_binding=project.render_binding(cid,preview)
    initial_stat=source.stat()
    try:
        with log.open('w',encoding='utf-8') as err:
            proc=subprocess.Popen(cmd,cwd=root,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                stderr=err,text=True,encoding='utf-8',errors='replace',bufsize=1)
            try:
                for line in proc.stdout:
                    if cancel and cancel.is_set():
                        proc.terminate();raise RuntimeError('Render cancelado pelo usuário; tentativa preservada')
                    if progress and line.startswith('out_time_ms='):
                        try: progress(min(.98,max(0,int(line.split('=',1)[1])/1e6/duration)),cid)
                        except (ValueError,ZeroDivisionError):pass
                code=proc.wait(timeout=40)
            finally:
                if proc.stdout:proc.stdout.close()
                if proc.poll() is None:proc.kill();proc.wait()
        if code:
            raise RuntimeError('FFmpeg retornou erro '+str(code)+': '+log.read_text(encoding='utf-8',errors='replace')[-1600:])
        technical=probe_media(pending)
        if not technical['has_video'] or not technical['has_audio'] or technical['width']!=width or technical['height']!=height:
            raise RuntimeError('FFprobe: vídeo/áudio ou resolução incorretos no arquivo gerado')
        tolerance=max(.5,1.5/30)
        if abs(technical['duration']-duration)>tolerance:
            raise RuntimeError(f'FFprobe: duração {technical["duration"]:.3f}s diverge dos {duration:.3f}s planejados')
        if project.render_binding(cid,preview)!=initial_binding:
            raise RuntimeError('Configuração mudou durante o render; saída não publicada')
        if source.stat().st_size!=initial_stat.st_size or source.stat().st_mtime_ns!=initial_stat.st_mtime_ns:
            raise RuntimeError('Arquivo de mídia mudou durante o render; saída não publicada')
        os.replace(pending,movie)
        report={'source_sha256':project.package.source_sha,
                'render_media_sha256':project.active_media_sha(),
                'media_mode':project.state.get('media_mode','EXACT_ANALYZER_SOURCE'),
                'time_alignment':'NOT_AUTOMATICALLY_VERIFIED' if project.active_media_sha()!=project.package.source_sha else 'EXACT_SOURCE_BYTES',
                'package_sha256':project.package.digest,
                'clip':cid,'preview':preview,'mode':s['layout'],
                'camera_plan':camera,'cover_error':cover_error,
                'captions_included':caption_enabled,
                'asr_draft_review_only':draft_captions,
                'caption_review_report':{
                    'cue_count':caption_report['cue_count'],
                    'flags':caption_report['flags'],
                    'srt_sha256':caption_report['srt_sha256'],
                    'ass_sha256':caption_report['ass_sha256']
                } if caption_report else None,
                'camera_verified_by_human':s['camera_reviewed'],
                'captions_verified_by_human':s['captions_verified'],
                'media':technical,'source_start':start,'source_end':end,
                'sha256':sha256_file(movie),'rights_verified':s['rights_verified'],
                'publication_ready':False}
        atomic_write(root/'RENDER_REPORT.json',report)
        if not draft_captions:
            project.record_render(cid,movie,preview=preview,report=report)
            if not preview:project.export_manifest()
        if progress:progress(1.,cid)
        return movie,report
    except Exception:
        # Never claim partial files as successful; keep log and attempt for diagnosis.
        raise
