from __future__ import annotations
from pathlib import Path


def ass_time(sec):
    sec=max(0,float(sec)); h=int(sec//3600); sec-=h*3600; m=int(sec//60); sec-=m*60
    return f"{h}:{m:02d}:{sec:05.2f}"


def srt_time(sec):
    ms=int(round(max(0,float(sec))*1000)); h=ms//3600000; ms%=3600000; m=ms//60000; ms%=60000; s=ms//1000; ms%=1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def esc_ass(s):
    return str(s).replace('\\','\\\\').replace('{','\\{').replace('}','\\}').replace('\n','\\N')


def _ass_wrapped_text(text):
    return esc_ass(text).replace('\\\\N', '\\N')


def wrap_caption(text, max_chars=28):
    words=str(text).strip().split(); lines=[]; cur=[]
    for w in words:
        if cur and len(' '.join(cur+[w]))>max_chars:
            lines.append(' '.join(cur)); cur=[w]
        else:
            cur.append(w)
    if cur:
        lines.append(' '.join(cur))
    if len(lines)>2:
        # Balance two lines instead of leaving a tiny orphan line.
        best=None
        for i in range(1,len(words)):
            a=' '.join(words[:i]); b=' '.join(words[i:])
            score=max(len(a),len(b))+abs(len(a)-len(b))*0.25
            if best is None or score<best[0]: best=(score,a,b)
        lines=[best[1],best[2]] if best else lines[:2]
    return '\\N'.join(lines[:2])


def _karaoke(words, clip_start):
    out=[]
    for w in words or []:
        raw=w.get('word') or w.get('raw') or ''
        dur=max(0.04,float(w.get('end',0))-float(w.get('start',0)))
        cs=max(1,int(round(dur*100)))
        out.append(f"{{\\k{cs}}}{esc_ass(raw.strip())}")
    return ' '.join(out)


def write_subtitles(bundle, clip, out_dir: Path, cfg, preview=False):
    """Write ONLY spoken captions.

    The opening title is intentionally not drawn by ASS anymore. It is rendered as
    a real RGBA PNG card by title_card.py and composited by FFmpeg. This avoids
    libass BorderStyle differences that previously produced a dark/transparent box.
    """
    out_dir.mkdir(parents=True,exist_ok=True)
    st,en=clip['source_start'],clip['source_end']
    caps=[c for c in bundle.captions if c.get('end',0)>st and c.get('start',1e9)<en]
    W,H=(540,960) if preview else (1080,1920)
    subcfg=cfg.get('subtitles',{})
    fs=int(subcfg.get('font_size_preview' if preview else 'font_size_final',36 if preview else 72))
    margin=int((clip.get('subtitle_plan', {}).get('margin_v_final') or subcfg.get('margin_v_final',320))*(0.5 if preview else 1))
    outline=max(2,int(subcfg.get('outline_final',6)*(0.5 if preview else 1)))
    shadow=max(1,int(subcfg.get('shadow_final',2)*(0.5 if preview else 1)))
    header=f"""[Script Info]\nScriptType: v4.00+\nPlayResX: {W}\nPlayResY: {H}\nScaledBorderAndShadow: yes\nWrapStyle: 2\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Sub,{subcfg.get('font','Segoe UI')},{fs},&H00FFFFFF,&H0000D7FF,&H00101010,&H60000000,-1,0,0,0,100,100,0,0,1,{outline},{shadow},2,70,70,{margin},1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"""
    lines=[header]
    srt=[]; idx=1
    for c in caps:
        a=max(st,float(c.get('start',st)))-st; b=min(en,float(c.get('end',en)))-st
        if b<=a:
            continue
        txt=c.get('display_text') or c.get('text') or ''
        words=c.get('words') or []
        ass_txt=_karaoke(words,st) if words else _ass_wrapped_text(wrap_caption(txt))
        lines.append(f"Dialogue: 0,{ass_time(a)},{ass_time(b)},Sub,,0,0,0,,{ass_txt}\n")
        srt.append(f"{idx}\n{srt_time(a)} --> {srt_time(b)}\n{txt.strip()}\n\n"); idx+=1
    ass=out_dir/('subtitles_preview.ass' if preview else 'subtitles.ass'); ass.write_text(''.join(lines),encoding='utf-8-sig')
    srtp=out_dir/'subtitles.srt'; srtp.write_text(''.join(srt),encoding='utf-8')
    return ass
