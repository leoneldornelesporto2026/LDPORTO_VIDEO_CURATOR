from __future__ import annotations
from pathlib import Path
import json, subprocess
from .utils import run
from .subtitles import write_subtitles
from .title_card import create_title_card



def _ffmpeg_progress_fraction(value, duration):
    try:
        us = float(value)
        dur = max(0.001, float(duration))
        return max(0.0, min(1.0, (us / 1_000_000.0) / dur))
    except Exception:
        return None

def _run_ffmpeg_with_progress(cmd, duration, progress=None):
    progress = progress or (lambda fraction, detail='': None)
    pcmd = list(cmd)
    if pcmd and Path(pcmd[0]).name.lower().startswith('ffmpeg'):
        pcmd = [pcmd[0], '-hide_banner', '-loglevel', 'error', '-progress', 'pipe:1', '-nostats'] + pcmd[1:]
    proc = subprocess.Popen(pcmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
    last_fraction = 0.0
    if proc.stdout is not None:
        for raw in proc.stdout:
            line = raw.strip()
            if not line or '=' not in line:
                continue
            key, value = line.split('=', 1)
            if key in {'out_time_us','out_time_ms'}:
                frac = _ffmpeg_progress_fraction(value, duration)
                if frac is not None and frac >= last_fraction:
                    last_fraction = frac
                    progress(frac, f'{frac*100:.1f}% do encode')
            elif key == 'progress' and value == 'end':
                progress(1.0, 'encode concluído')
    rc = proc.wait()
    stderr = proc.stderr.read() if proc.stderr is not None else ''
    return rc, stderr

def ffmpeg_has_nvenc():
    try:
        p = run(['ffmpeg', '-hide_banner', '-encoders'], check=False)
        return 'h264_nvenc' in (p.stdout + p.stderr)
    except Exception:
        return False


def _ass_filter_path(path: Path):
    s = str(path.resolve()).replace('\\', '/')
    return s.replace(':', '\\:').replace("'", "\\'")


def _video_dims(path: Path):
    p = run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height', '-of', 'json', str(path)], check=True)
    d = json.loads(p.stdout)
    st = (d.get('streams') or [{}])[0]
    w, h = int(st.get('width') or 0), int(st.get('height') or 0)
    if not w or not h:
        raise RuntimeError('Não foi possível obter dimensões do vídeo.')
    return w, h


def _crop_for(iw, ih, target_aspect, center):
    src_aspect = iw / ih
    if src_aspect > target_aspect:
        ch = ih
        cw = max(2, int(round(ih * target_aspect)))
        x = int(round(iw * center - cw / 2))
        x = max(0, min(iw - cw, x))
        y = 0
    else:
        cw = iw
        ch = max(2, int(round(iw / target_aspect)))
        x = 0
        y = max(0, (ih - ch) // 2)
    return cw, ch, x, y



def _crop_dims_for_zoom(iw, ih, target_aspect, zoom):
    zoom=max(1.0,float(zoom or 1.0))
    src_aspect=iw/ih
    if src_aspect>target_aspect:
        base_h=ih; base_w=ih*target_aspect
    else:
        base_w=iw; base_h=iw/target_aspect
    cw=max(2,int(round(base_w/zoom))); ch=max(2,int(round(base_h/zoom)))
    # H.264/yuv420 likes even dimensions.
    cw=max(2,cw-(cw%2)); ch=max(2,ch-(ch%2))
    return min(iw,cw),min(ih,ch)


def _motion_crop_filter(base, seg, iw, ih, rw, rh, idx):
    zoom=float(seg.get('zoom') or 1.0)
    cw,ch=_crop_dims_for_zoom(iw,ih,rw/rh,zoom)
    cx0=float(seg.get('center_x_start',seg.get('center_x',0.5)))
    cx1=float(seg.get('center_x_end',seg.get('center_x',cx0)))
    cy0=float(seg.get('center_y_start',0.42)); cy1=float(seg.get('center_y_end',cy0))
    dur=max(0.001,float(seg.get('end',0))-float(seg.get('start',0)))
    # Place the head a little above vertical center, like a human camera operator.
    target_y=float(seg.get('subject_screen_y',0.38))
    # crop x/y are evaluated per frame. `t` is local because the source was trimmed
    # and reset to PTS=0 above, producing a smooth linear camera move.
    fraction = f'min(t\\,{dur:.6f})/{dur:.6f}'
    if seg.get('motion_easing') == 'smoothstep':
        fraction = f'pow(({fraction})\\,2)*(3-2*({fraction}))'
    xexpr=(f"max(0,min(iw-ow,(({cx0:.6f}+({cx1-cx0:.6f})*({fraction}))*iw)-ow/2))")
    yexpr=(f"max(0,min(ih-oh,(({cy0:.6f}+({cy1-cy0:.6f})*({fraction}))*ih)-oh*{target_y:.4f}))")
    return f"[{base}]crop={cw}:{ch}:x='{xexpr}':y='{yexpr}',scale={rw}:{rh},setsar=1[v{idx}]"


def _graphics_split_parts(base, seg, iw, ih, rw, rh, index):
    regions = [r for r in seg.get('graphics_regions', []) if r.get('persistent') and .4 < r.get('y_start', 0) < r.get('y_end', 0) <= 1]
    if not regions:
        return None
    top, bottom = min(r['y_start'] for r in regions), max(r['y_end'] for r in regions)
    panel_source_h = max(2, int(ih * min(top, seg.get('panel_source_height', top))) // 2 * 2)
    strip_y, strip_h = int(ih * top) // 2 * 2, max(2, int(ih * (bottom - top)) // 2 * 2)
    strip_h = min(strip_h, ih - strip_y)
    reserved = max(2, int(rh * .12) // 2 * 2)
    half = (rh - reserved) // 4 * 2
    other = rh - reserved - half
    centers = seg['split_centers_x'][:2]
    parts = [f'[{base}]split=3[{base}a][{base}b][{base}gc]']
    for name, center, height in zip(('a', 'b'), centers, (half, other)):
        cw, ch, x, y = _crop_for(iw, panel_source_h, rw / height, center)
        parts.append(f'[{base}{name}]crop={iw}:{panel_source_h}:0:0,crop={cw}:{ch}:{x}:{y},scale={rw}:{height},setsar=1[{base}{name}panel]')
    parts.append(f'[{base}gc]crop={iw}:{strip_h}:0:{strip_y},scale={rw}:{reserved}:force_original_aspect_ratio=decrease,'
                 f'pad={rw}:{reserved}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1[{base}strip]')
    parts.append(f'[{base}apanel][{base}bpanel][{base}strip]vstack=inputs=3[v{index}]')
    return parts


def _graphics_crop_parts(base, seg, iw, ih, rw, rh, index):
    regions = [r for r in seg.get('graphics_regions', []) if r.get('persistent') and .4 < r.get('y_start', 0) < r.get('y_end', 0) <= 1]
    if not regions:
        return None
    top, bottom = min(r['y_start'] for r in regions), max(r['y_end'] for r in regions)
    source_height = max(2, int(ih * top) // 2 * 2)
    strip_y = source_height
    strip_h = min(ih - strip_y, max(2, int(ih * (bottom - top)) // 2 * 2))
    reserved = max(2, int(rh * .12) // 2 * 2)
    subject_height = rh - reserved
    subject = dict(seg)
    subject['center_y_start'] = float(seg.get('center_y_start', .5)) * ih / source_height
    subject['center_y_end'] = float(seg.get('center_y_end', .5)) * ih / source_height
    subject['subject_screen_y'] = .5
    parts = [f'[{base}]split=2[{base}subject][{base}gc]',
             f'[{base}subject]crop={iw}:{source_height}:0:0[{base}clean]']
    subject_filter = _motion_crop_filter(base+'clean', subject, iw, source_height, rw, subject_height, index)
    parts.append(subject_filter.replace(f'[v{index}]', f'[{base}panel]'))
    parts.append(f'[{base}gc]crop={iw}:{strip_h}:0:{strip_y},scale={rw}:{reserved}:force_original_aspect_ratio=decrease,'
                 f'pad={rw}:{reserved}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1[{base}strip]')
    parts.append(f'[{base}panel][{base}strip]vstack=inputs=2[v{index}]')
    return parts

def _adaptive_camera_parts(cam, iw, ih, rw, rh, duration):
    segs = [dict(s) for s in (cam.get('segments') or []) if float(s.get('end', 0)) > float(s.get('start', 0))]
    if not segs:
        segs = [{'start': 0.0, 'end': duration, 'mode': 'full_frame_blur'}]
    segs = sorted(segs, key=lambda s: float(s.get('start', 0)))
    segs[0]['start'] = 0.0
    for i in range(1, len(segs)):
        segs[i]['start'] = segs[i - 1]['end']
    segs[-1]['end'] = duration

    parts = []
    if len(segs) > 1:
        labels = ''.join(f'[src{i}]' for i in range(len(segs)))
        parts.append(f'[0:v]split={len(segs)}{labels}')
        src_labels = [f'[src{i}]' for i in range(len(segs))]
    else:
        src_labels = ['[0:v]']

    out_labels = []
    for i, (seg, src) in enumerate(zip(segs, src_labels)):
        a = max(0.0, float(seg.get('start', 0)))
        b = min(duration, float(seg.get('end', duration)))
        if b <= a:
            continue
        base = f'seg{i}'
        parts.append(f'{src}trim=start={a:.4f}:end={b:.4f},setpts=PTS-STARTPTS[{base}]')
        mode = seg.get('mode') or 'full_frame_blur'

        if mode == 'crop':
            graphics_parts = _graphics_crop_parts(base, seg, iw, ih, rw, rh, i) if seg.get('graphics_policy') == 'single_copy_source_strip' else None
            if graphics_parts:
                parts.extend(graphics_parts)
                out_labels.append(f'[v{i}]')
                continue
            if seg.get('motion_follow'):
                parts.append(_motion_crop_filter(base, seg, iw, ih, rw, rh, i))
            else:
                center = float(seg.get('center_x', 0.5))
                zoom = float(seg.get('zoom') or 1.0)
                if zoom > 1.0001:
                    cw, ch = _crop_dims_for_zoom(iw, ih, rw / rh, zoom)
                    x = int(round(iw * center - cw / 2)); x = max(0, min(iw - cw, x))
                    y = max(0, (ih - ch) // 2)
                else:
                    cw, ch, x, y = _crop_for(iw, ih, rw / rh, center)
                parts.append(f'[{base}]crop={cw}:{ch}:{x}:{y},scale={rw}:{rh},setsar=1[v{i}]')

        elif mode == 'split_screen' and len(seg.get('split_centers_x') or []) >= 2:
            graphics_parts = _graphics_split_parts(base, seg, iw, ih, rw, rh, i) if seg.get('graphics_policy') == 'single_copy_source_strip' else None
            if graphics_parts:
                parts.extend(graphics_parts)
                out_labels.append(f'[v{i}]')
                continue
            half = max(2, rh // 2)
            aspect = rw / half
            c1, c2 = [float(x) for x in seg['split_centers_x'][:2]]
            cw1, ch1, x1, y1 = _crop_for(iw, ih, aspect, c1)
            cw2, ch2, x2, y2 = _crop_for(iw, ih, aspect, c2)
            parts.append(f'[{base}]split=2[{base}a][{base}b]')
            parts.append(f'[{base}a]crop={cw1}:{ch1}:{x1}:{y1},scale={rw}:{half},setsar=1[{base}top]')
            parts.append(f'[{base}b]crop={cw2}:{ch2}:{x2}:{y2},scale={rw}:{rh-half},setsar=1[{base}bot]')
            parts.append(f'[{base}top][{base}bot]vstack=inputs=2[v{i}]')

        else:
            # Complete source composition on top of a blurred 9:16 fill.
            parts.append(f'[{base}]split=2[{base}bg][{base}fg]')
            lower = [r['y_start'] for r in seg.get('graphics_regions', []) if r.get('persistent') and r.get('y_start', 0) > .4]
            bg_crop = f'crop={iw}:{int(ih * min(lower)) // 2 * 2}:0:0,' if lower else ''
            parts.append(
                f'[{base}bg]{bg_crop}scale={rw}:{rh}:force_original_aspect_ratio=increase,'
                f'crop={rw}:{rh},boxblur=18:1,setsar=1[{base}bg2]'
            )
            parts.append(
                f'[{base}fg]scale={rw}:{rh}:force_original_aspect_ratio=decrease,'
                f'setsar=1[{base}fg2]'
            )
            parts.append(f'[{base}bg2][{base}fg2]overlay=(W-w)/2:(H-h)/2[v{i}]')
        out_labels.append(f'[v{i}]')

    if not out_labels:
        raise RuntimeError('Plano de câmera adaptativo sem segmentos renderizáveis.')
    if len(out_labels) == 1:
        return parts, out_labels[0]
    parts.append(''.join(out_labels) + f'concat=n={len(out_labels)}:v=1:a=0[vcam]')
    return parts, '[vcam]'


def _static_camera_parts(cam, iw, ih, rw, rh):
    parts = []
    mode = cam.get('mode')
    if mode == 'split_screen' and len(cam.get('split_centers_x') or []) >= 2:
        half = max(2, rh // 2)
        aspect = rw / half
        c1, c2 = [float(x) for x in cam['split_centers_x'][:2]]
        cw1, ch1, x1, y1 = _crop_for(iw, ih, aspect, c1)
        cw2, ch2, x2, y2 = _crop_for(iw, ih, aspect, c2)
        parts += [
            '[0:v]split=2[a][b]',
            f'[a]crop={cw1}:{ch1}:{x1}:{y1},scale={rw}:{half},setsar=1[top]',
            f'[b]crop={cw2}:{ch2}:{x2}:{y2},scale={rw}:{rh-half},setsar=1[bot]',
            '[top][bot]vstack=inputs=2[vcam]',
        ]
        return parts, '[vcam]'
    if mode == 'full_frame_blur':
        parts += [
            '[0:v]split=2[bg][fg]',
            f'[bg]scale={rw}:{rh}:force_original_aspect_ratio=increase,crop={rw}:{rh},boxblur=18:1,setsar=1[bg2]',
            f'[fg]scale={rw}:{rh}:force_original_aspect_ratio=decrease,setsar=1[fg2]',
            '[bg2][fg2]overlay=(W-w)/2:(H-h)/2[vcam]',
        ]
        return parts, '[vcam]'
    center = float(cam.get('normalized_center_x', 0.5))
    cw, ch, x, y = _crop_for(iw, ih, rw / rh, center)
    parts.append(f'[0:v]crop={cw}:{ch}:{x}:{y},scale={rw}:{rh},setsar=1[vcam]')
    return parts, '[vcam]'


def _finish_video_parts(parts, base_label, assp, title_index, title_duration, fade_in=0.12, fade_out=0.18):
    # Accurate input seeking can leave the first decoded frame a fraction of a
    # frame after zero. The encoder presents that frame at output time zero, so
    # libass must use the same clock rather than burning future colors early.
    # This preserves the selected source frames, camera composition and audio.
    # Use AVTB precision before rebasing. The measured ASS word offsets are
    # relative to the first encoded frame, not to the input seek timestamp.
    parts.append(f"{base_label}settb=AVTB,setpts=PTS-STARTPTS,subtitles='{assp}'[vsub]")
    if title_index is None or title_duration <= 0:
        return parts, '[vsub]'

    fo_start = max(0.0, title_duration - fade_out)
    parts.append(
        f'[{title_index}:v]format=rgba,'
        f'fade=t=in:st=0:d={fade_in:.3f}:alpha=1,'
        f'fade=t=out:st={fo_start:.3f}:d={fade_out:.3f}:alpha=1[vtitle]'
    )
    parts.append(f"[vsub][vtitle]overlay=0:0:enable='between(t,0,{title_duration:.3f})':eof_action=pass[vout]")
    return parts, '[vout]'


def _base_cmd(bundle, clip, video, out, ass, title_card, cfg, preview, encoder):
    cam = clip.get('camera_plan') or {}
    rw, rh = (
        (int(cfg['render'].get('preview_width', 540)), int(cfg['render'].get('preview_height', 960)))
        if preview else
        (int(cfg['render'].get('final_width', 1080)), int(cfg['render'].get('final_height', 1920)))
    )
    iw, ih = _video_dims(video)
    assp = _ass_filter_path(ass)
    duration = float(clip['duration'])

    cmd = ['ffmpeg', '-y', '-ss', f"{clip['source_start']:.3f}", '-i', str(video)]
    title_index = None
    if title_card is not None:
        title_index = 1
        cmd += ['-loop', '1', '-framerate', '30', '-i', str(title_card)]
    cmd += ['-t', f'{duration:.3f}']

    if cam.get('mode') == 'adaptive_timeline':
        parts, base = _adaptive_camera_parts(cam, iw, ih, rw, rh, duration)
    else:
        parts, base = _static_camera_parts(cam, iw, ih, rw, rh)

    tdur = min(float(clip.get('title_duration') or cfg.get('title', {}).get('duration', 3.2)), max(0.0, duration))
    fade_ms = float(cfg.get('title', {}).get('fade_ms', 180))
    parts, out_label = _finish_video_parts(
        parts, base, assp, title_index, tdur,
        fade_in=min(0.16, fade_ms / 1000.0),
        fade_out=min(0.24, fade_ms / 1000.0),
    )
    cmd += ['-filter_complex', ';'.join(parts), '-map', out_label, '-map', '0:a?']

    cmd += [
        '-af', f"loudnorm=I={cfg['render'].get('audio_lufs', -14)}:TP={cfg['render'].get('audio_true_peak', -1.5)}:LRA=11",
        '-c:v', encoder,
    ]
    if encoder == 'h264_nvenc':
        cmd += ['-preset', 'p6', '-cq', '21']
    else:
        cmd += ['-preset', 'medium', '-crf', '20']
    cmd += ['-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-movflags', '+faststart', '-shortest', str(out)]
    return cmd, rw, rh


def render_clip(bundle, clip, video: Path, out_dir: Path, cfg, preview=True, log=print, progress=None):
    from .storage import media_lease
    from .camera_verifier import verify_camera
    from .utils import write_json
    with media_lease(video):
        output = _render_clip(bundle, clip, video, out_dir, cfg, preview, log, progress)
        report = verify_camera(output, clip, cfg.get('micro_perception'))
        write_json(out_dir / ('PREVIEW_CAMERA_VERIFIER_V44.json' if preview else 'FINAL_CAMERA_VERIFIER_V44.json'), report)
        if any(issue['severity'] == 'error' for issue in report['issues']):
            raise RuntimeError('Verifier: frame do render não decodificável')
        return output


def _render_clip(bundle, clip, video: Path, out_dir: Path, cfg, preview=True, log=print, progress=None):
    if not video.exists():
        raise FileNotFoundError(video)
    out_dir.mkdir(parents=True, exist_ok=True)
    ass = write_subtitles(bundle, clip, out_dir, cfg, preview=preview)
    title_card = create_title_card(clip, out_dir, cfg, preview=preview)
    name = f"{clip['clip_id']}_{'PREVIEW' if preview else 'FINAL'}.mp4"
    out = out_dir / name
    encoders = ['h264_nvenc', 'libx264'] if cfg['render'].get('prefer_nvenc', True) and ffmpeg_has_nvenc() else ['libx264']
    last = None
    for encoder in encoders:
        cmd, rw, rh = _base_cmd(bundle, clip, video, out, ass, title_card, cfg, preview, encoder)
        cam = clip.get('camera_plan', {})
        detail = f"{cam.get('mode')} / {len(cam.get('segments') or [])} decisões / motion={cam.get('motion_segments',0)}" if cam.get('mode') == 'adaptive_timeline' else str(cam.get('mode'))
        log(f"Render {'preview' if preview else 'final'}: {clip['clip_id']} via {encoder} / câmera={detail} / título=card PNG branco")
        if progress:
            progress(0.01, f'iniciando {encoder}')
        rc, stderr = _run_ffmpeg_with_progress(cmd, float(clip['duration']), progress=progress)
        if rc == 0:
            if progress:
                progress(0.98, 'validando arquivo')
            validate_output(out, rw, rh)
            # Record what FFmpeg actually used, including a runtime NVENC fallback.
            from .approval import file_hash
            from .utils import write_json
            from .persisted_plan import render_settings, _fingerprint
            write_json(out_dir / (name + '.render.json'), {
                'encoder': encoder, 'preview': bool(preview), 'width': rw, 'height': rh,
                'duration': float(clip['duration']), 'source_start': float(clip['source_start']),
                'subtitle_sha256': file_hash(ass),
                'title_card_sha256': file_hash(title_card) if title_card else None,
                'media_sha256': file_hash(out),
                'render_settings_fingerprint': _fingerprint(render_settings(cfg)),
            })
            if progress:
                progress(1.0, 'MP4 validado')
            return out
        last = stderr
        if encoder == 'h264_nvenc':
            log('NVENC falhou em runtime; tentando libx264. ' + (stderr.splitlines()[-1] if stderr else ''))
            if progress:
                progress(0.0, 'NVENC falhou; fallback libx264')
    raise RuntimeError('Render falhou. FFmpeg:\n' + (last or 'sem detalhes'))


def validate_output(path: Path, w: int, h: int):
    p = run(['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_type,width,height', '-show_entries', 'format=duration', '-of', 'json', str(path)], check=True)
    d = json.loads(p.stdout)
    streams = d.get('streams') or []
    vs = [s for s in streams if s.get('codec_type') == 'video']
    aud = [s for s in streams if s.get('codec_type') == 'audio']
    if not vs:
        raise RuntimeError('Render sem stream de vídeo.')
    if int(vs[0].get('width', 0)) != w or int(vs[0].get('height', 0)) != h:
        raise RuntimeError(f"Resolução inválida: {vs[0].get('width')}x{vs[0].get('height')}")
    if not aud:
        raise RuntimeError('Render sem áudio.')
    if float((d.get('format') or {}).get('duration') or 0) <= 0.2:
        raise RuntimeError('Duração inválida.')
