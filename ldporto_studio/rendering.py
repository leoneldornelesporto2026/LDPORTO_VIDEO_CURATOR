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
    return sha256_file(Path(__file__))


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


def title_overlay(out:Path,title:str,width:int,height:int,kind:str):
    """Transparent safe-area title stripe, no copyrighted font assets bundled."""
    from PIL import Image,ImageDraw
    im=Image.new('RGBA',(width,height),(0,0,0,0))
    d=ImageDraw.Draw(im)
    z=width/1080
    x=int(width*.085)
    top=int(height*.095)
    size=max(16,int(63*z))
    max_width=int(width*.79)
    for _ in range(15):
        ft=_font(size)
        lines=_lines(d,title,ft,max_width,3)
        if all(d.textbbox((0,0),ln,font=ft)[2]<=max_width for ln in lines):break
        size=max(14,size-3)
    height_line=int(size*1.23)
    h=max(int(118*z),int(len(lines)*height_line+62*z))
    d.rounded_rectangle((x,top,width-x,top+h),radius=max(9,int(24*z)),fill=(255,255,255,233))
    d.rounded_rectangle((x,top,x+int(15*z),top+h),radius=max(5,int(7*z)),fill=(255,205,0,255))
    y=top+int(31*z)
    for line in lines:
        d.text((x+int(40*z),y),line,font=ft,fill=(16,16,20,255),stroke_width=0)
        y+=height_line
    # Small chapter label away from platform UI overlays
    if kind=='stories':
        pass
    im.save(out)


def create_cover_from_frame(project,cid,destination:Path):
    """Optional alternative cover from the *verified* source; original package cover is preserved."""
    from PIL import Image,ImageDraw,ImageOps,ImageFilter
    ffmpeg,_=binaries()
    c=project.package.clips[cid]
    s=project.settings(cid)
    source=project.verified_media()
    t=(float(s['source_start'])+float(s['source_end']))/2
    destination.parent.mkdir(parents=True,exist_ok=True)
    tmp=destination.with_name('captured_'+uuid4().hex+'.png')
    try:
        result=subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-nostdin','-ss',f'{t:.3f}','-i',str(source),
          '-frames:v','1','-y',str(tmp)],capture_output=True,text=True,timeout=180)
        if result.returncode or not tmp.is_file():
            raise RuntimeError('Não foi possível extrair quadro do vídeo: '+result.stderr[-600:])
        with Image.open(tmp) as raw: src=raw.convert('RGB')
        bg=ImageOps.fit(src,(1080,1920),centering=(float(s['center_x']),0.5)).filter(ImageFilter.GaussianBlur(38))
        fg=ImageOps.contain(src,(1080,1150),Image.Resampling.LANCZOS)
        bg.paste(fg,((1080-fg.width)//2,(1920-fg.height)//2))
        d=ImageDraw.Draw(bg,'RGBA')
        d.rectangle((0,0,1080,380),fill=(0,0,0,155))
        d.rectangle((0,1550,1080,1920),fill=(0,0,0,160))
        size=79
        for _ in range(25):
            f=_font(size)
            lines=_lines(d,s['title'],f,900,3)
            if all(d.textbbox((0,0),l,font=f)[2]<900 for l in lines):break
            size=max(34,size-3)
        y=1650
        for line in lines:
            box=d.textbbox((0,0),line,font=f)
            d.text(((1080-(box[2]-box[0]))/2,y),line,font=f,fill=(255,255,255,255),stroke_width=2,stroke_fill=(0,0,0,255))
            y+=int(size*1.18)
        d.text((74,145),'L.D.PORTO · VIDEO CURATOR',font=_font(35),fill=(255,212,30,255))
        bg.convert('RGB').save(destination,quality=94)
        return destination
    finally:
        tmp.unlink(missing_ok=True)


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


def render_item(project,cid,*,preview:bool,progress=None,cancel=None):
    """Render preview or explicitly approved final, keeping every attempt isolated."""
    if cid not in project.package.clips: raise ValueError('Corte inexistente')
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
    root=project.dir/'outputs'/('previews' if preview else 'finals')/cid/run_id
    root.mkdir(parents=True,exist_ok=False)
    movie=root/('PREVIEW_540x960.mp4' if preview else 'FINAL_1080x1920.mp4')
    pending=root/'ENCODING.part.mp4'
    # Always preserve the original working thumbnail. Never claim it was sampled at an exact PTS.
    (root/'CAPA_PROPOSTA.png').write_bytes(project.package.data(clip.thumbnail))
    use_title=bool(s['title_overlay'])
    cmd=[ffmpeg,'-hide_banner','-nostdin','-loglevel','error','-ss',f'{start:.3f}',
         '-i',str(source)]
    if use_title:
        title_overlay(root/'TITLE_OVERLAY.png',s['title'],width,height,clip.kind)
        cmd+=['-loop','1','-framerate','30','-i',str(root/'TITLE_OVERLAY.png')]
    if s['subtitles']:
        (root/'captions.ass').write_bytes(project.caption_payload(cid))
    filters=[f'[0:v]fps=30,trim=duration={duration:.3f},setpts=PTS-STARTPTS']
    if s['layout']=='preserve':
        filters[0] += ',split=2[bg][fg]'
        filters.append(f'[bg]scale={width}:{height}:force_original_aspect_ratio=increase:force_divisible_by=2,'
                       f'crop={width}:{height},boxblur=luma_radius=20:luma_power=1[back]')
        filters.append(f'[fg]scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2,'
                       'setsar=1[front]')
        filters.append('[back][front]overlay=(W-w)/2:(H-h)/2:shortest=1,format=yuv420p[base]')
    else:
        filters[0]+=(f',scale={width}:{height}:force_original_aspect_ratio=increase:force_divisible_by=2,'
                      f'crop={width}:{height}:(iw-ow)*{s["center_x"]:.4f}:(ih-oh)/2,setsar=1,format=yuv420p[base]')
    current='base'
    if use_title:
        filters.append(f'[{current}][1:v]overlay=0:0:shortest=1:format=auto:enable=\'lt(t,3.2)\'[titled]')
        current='titled'
    if s['subtitles']:
        # Relative path so Windows drive letters never enter FFmpeg filter parsing.
        filters.append(f'[{current}]ass=captions.ass,format=yuv420p[finished]')
        current='finished'
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
        report={'source_sha256':project.package.source_sha,'package_sha256':project.package.digest,
                'clip':cid,'preview':preview,'mode':s['layout'],'captions_included':s['subtitles'],
                'camera_verified_by_human':s['camera_reviewed'],
                'captions_verified_by_human':s['captions_verified'],
                'media':technical,'source_start':start,'source_end':end,
                'sha256':sha256_file(movie),'rights_verified':s['rights_verified'],
                'publication_ready':False}
        atomic_write(root/'RENDER_REPORT.json',report)
        project.record_render(cid,movie,preview=preview,report=report)
        if not preview:project.export_manifest()
        if progress:progress(1.,cid)
        return movie,report
    except Exception:
        # Never claim partial files as successful; keep log and attempt for diagnosis.
        raise
