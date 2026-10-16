"""Measured V5 opening titles; preserve the existing V4.4 card renderer."""
from pathlib import Path
from PIL import Image, ImageDraw
from .title_card import _load_font
from .utils import write_json


def create_episode_title_card(episode, directory, cfg, preview=True):
    if not episode.get('title_enabled', True):
        return None
    text = str(episode.get('title_text') or '').strip()
    if not text:
        return None
    if len(text)>240:
        raise ValueError('Título de abertura longo; escolha um trecho mais curto para manter legibilidade')
    width,height=(540,960) if preview else (1080,1920)
    scale=width/1080
    pad=max(12,int(28*scale))
    left,right=int(width*.08),int(width*.84)
    top=int(height*.13)
    max_height=int(height*.23)
    settings=cfg.get('title',{})
    initial=int(float(settings.get('font_size_final',64))*scale)
    minimum=int(40*scale)
    canvas=Image.new('RGBA',(width,height),(0,0,0,0))
    draw=ImageDraw.Draw(canvas)
    for size in range(max(initial,minimum),minimum-1,-1):
        font=_load_font(size,settings.get('font_path'))
        lines=['']
        for word in text.split():
            proposed=(lines[-1]+' '+word).strip()
            box=draw.textbbox((0,0),proposed,font=font)
            if box[2]-box[0]>right-left-2*pad and lines[-1]:
                lines.append(word)
            else:
                lines[-1]=proposed
        boxes=[draw.textbbox((0,0),line,font=font) for line in lines]
        spacing=max(4,int(8*scale))
        total=sum(b[3]-b[1] for b in boxes)+spacing*(len(lines)-1)+2*pad
        if len(lines)<=4 and total<=max_height and all(b[2]-b[0]<=right-left-2*pad for b in boxes):
            break
    else:
        raise ValueError('Título não cabe legivelmente na zona segura; reduza o texto e gere outra prévia')
    bottom=top+total
    draw.rounded_rectangle((left,top,right,bottom),radius=max(8,int(24*scale)),fill='white')
    y=top+pad
    text_boxes=[]
    for line,box in zip(lines,boxes):
        tw,th=box[2]-box[0],box[3]-box[1]
        x=(left+right-tw)/2
        draw.text((x-box[0],y-box[1]),line,font=font,fill='#101010')
        text_boxes.append([x,y,x+tw,y+th])
        y+=th+spacing
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    path=directory/('title_card_preview.png' if preview else 'title_card.png')
    canvas.save(path,optimize=True)
    write_json(directory/'TITLE_LAYOUT.json',{'literal_title':text,'lines':lines,'font_size':size,
        'width':width,'height':height,'card_bounds':[left,top,right,bottom],
        'text_bounds':text_boxes,'safe_width':[left,right],'status':'measured_layout_human_review_pending'})
    return path
