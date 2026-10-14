from __future__ import annotations
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import json, html

def _font(size,bold=False):
    candidates=['C:/Windows/Fonts/seguisb.ttf','C:/Windows/Fonts/arialbd.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf']
    for p in candidates:
        try: return ImageFont.truetype(p,size=size)
        except: pass
    return ImageFont.load_default()

def build_board(decisions, cur_root:Path):
    cards=[]
    for d in decisions:
        imgp=cur_root/'clips'/d['clip_id']/'thumbnails'/'thumbnail_best.jpg'
        cards.append((d,imgp))
    W=1800; cw=860; ch=360; rows=(len(cards)+1)//2; H=max(500,100+rows*(ch+30))
    im=Image.new('RGB',(W,H),(18,18,22)); dr=ImageDraw.Draw(im); titlef=_font(48,True); body=_font(28,True); small=_font(23)
    dr.text((55,28),'L.D.PORTO · CURATION BOARD',font=titlef,fill=(255,85,105))
    for i,(d,p) in enumerate(cards):
        col=i%2; row=i//2; x=40+col*(cw+40); y=100+row*(ch+30)
        dr.rounded_rectangle((x,y,x+cw,y+ch),radius=24,fill=(30,30,36),outline=(70,70,80),width=2)
        if p.exists():
            ph=300; pw=300; pic=Image.open(p).convert('RGB'); pic.thumbnail((pw,ph)); im.paste(pic,(x+20,y+30))
        tx=x+345
        dr.text((tx,y+28),f"#{d['rank']}  {d['clip_id']}  • {d['duration']:.1f}s • score {d['score']}",font=small,fill=(210,210,215))
        text=d.get('title_text','')
        # basic wrap
        words=text.split(); lines=[]; cur=[]
        for w in words:
            if len(' '.join(cur+[w]))>34 and cur: lines.append(' '.join(cur));cur=[w]
            else:cur.append(w)
        if cur:lines.append(' '.join(cur))
        for j,l in enumerate(lines[:3]): dr.text((tx,y+72+j*38),l,font=body,fill=(255,255,255))
        dr.text((tx,y+200),f"{d['source_start']:.2f}s → {d['source_end']:.2f}s",font=small,fill=(160,220,255))
        if d.get('needs_review'): dr.text((tx,y+245),'⚠ NEEDS REVIEW',font=body,fill=(255,200,80))
    out=cur_root/'CURATION_BOARD.png'; im.save(out,quality=95)
    h=['<html><meta charset="utf-8"><body style="background:#111;color:#eee;font-family:Arial"><h1>L.D.PORTO · CURATION BOARD</h1>']
    for d,p in cards:
        rel=p.relative_to(cur_root) if p.exists() else None
        h.append(f"<div style='margin:20px;padding:20px;background:#222'><h2>#{d['rank']} {html.escape(d['title_text'])}</h2><p>{d['source_start']:.2f}s → {d['source_end']:.2f}s • {d['duration']:.1f}s • score {d['score']}</p>"+(f"<img src='{rel.as_posix()}' width='360'>" if rel else '')+"</div>")
    h.append('</body></html>'); (cur_root/'CURATION_BOARD.html').write_text(''.join(h),encoding='utf-8')
    return out

def write_handoff(bundle,decisions,cur_root:Path):
    clips=[]
    for d in decisions:
        segs=[s for s in bundle.segments if s.get('end',0)>=d['source_start']-20 and s.get('start',1e9)<=d['source_end']+20]
        x=dict(d); x['transcript_with_context']=[{'start':s.get('start'),'end':s.get('end'),'text':s.get('text')} for s in segs]
        clips.append(x)
    data={'video':{'id':bundle.video_id,'source':bundle.source,'duration':bundle.analysis.get('metadata',{}).get('duration')},'approved_clips':clips}
    (cur_root/'CHATGPT_HANDOFF.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# L.D.PORTO — CHATGPT HANDOFF','']
    for d in clips:
        lines += [f"## #{d['rank']} {d['clip_id']} — {d['title_text']}",f"- {d['source_start']:.2f}s → {d['source_end']:.2f}s ({d['duration']:.1f}s)",f"- Score: {d['score']}",f"- Motivo: {d['reason']}",'','### Contexto/transcrição']
        lines += [f"- [{s['start']:.2f}-{s['end']:.2f}] {s['text']}" for s in d['transcript_with_context']]
        lines.append('')
    (cur_root/'CHATGPT_HANDOFF.md').write_text('\n'.join(lines),encoding='utf-8')
