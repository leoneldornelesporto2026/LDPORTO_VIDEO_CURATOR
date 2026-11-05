"""L.D.PORTO editorial cover/title system. No external font asset bundled.

Clean white, golden-outline viral card: brand + LIVE badge, large black hook,
short golden underline and a small genre footer. Works in 540x960 / 1080x1920.
"""
from __future__ import annotations

from pathlib import Path


def _font(px: int):
    from PIL import ImageFont
    for name in (
        'C:/Windows/Fonts/arialbd.ttf',
        'C:/Windows/Fonts/seguisb.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        '/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf',
    ):
        if Path(name).is_file():
            return ImageFont.truetype(name, max(12, int(px)))
    return ImageFont.load_default()


def _wrap(draw, text: str, font, available: int, limit: int = 3):
    words = str(text).upper().split()
    lines=[]
    current=''
    for word in words:
        candidate = f'{current} {word}'.strip()
        if current and draw.textbbox((0,0),candidate,font=font)[2] > available:
            lines.append(current)
            current=word
        else:
            current=candidate
    if current:lines.append(current)
    if len(lines)>limit:
        lines=lines[:limit]
        last=lines[-1]
        while last and draw.textbbox((0,0),last+'…',font=font)[2] > available:
            last=last[:-1]
        lines[-1]=last.rstrip()+'…'
    return lines


def editorial_card(title: str, width: int, height: int, *, footer: str = 'ROCK NACIONAL · CBJR'):
    """Return transparent RGBA overlay containing the requested viral title card."""
    from PIL import Image, ImageDraw
    image=Image.new('RGBA',(width,height),(0,0,0,0))
    d=ImageDraw.Draw(image)
    s=width/1080
    left=round(width*.045)
    right=width-left
    top=round(height*.060)
    card_h=round(388*s)
    bottom=top+card_h
    radius=max(14,round(33*s))
    d.rounded_rectangle((left+4*s,top+9*s,right+4*s,bottom+9*s),radius=radius,fill=(0,0,0,92))
    d.rounded_rectangle((left,top,right,bottom),radius=radius,fill=(253,253,251,250),outline=(237,189,24,255),width=max(2,round(5*s)))
    d.rounded_rectangle((left+7*s,top+15*s,left+19*s,bottom-15*s),radius=max(4,round(7*s)),fill=(242,197,41,255))
    label_font=_font(28*s)
    d.text((left+51*s,top+32*s),'L.D.PORTO.OFICIAL',font=label_font,fill=(64,67,69,255))
    # Small red emblem + live badge; avoid depending on Unicode emoji font coverage.
    bx=right-219*s
    by=top+27*s
    d.rounded_rectangle((bx,by,bx+173*s,by+44*s),radius=max(8,round(22*s)),fill=(255,255,255,255),outline=(224,224,224,255),width=max(1,round(s)))
    dot=9*s
    d.ellipse((bx+21*s,by+20*s-dot,bx+21*s+2*dot,by+20*s+dot),fill=(207,32,55,255))
    d.text((bx+55*s,by+6*s),'AO VIVO',font=_font(24*s),fill=(72,74,77,255))
    max_w=round((right-left)-120*s)
    size=72*s
    for _ in range(36):
        main_font=_font(size)
        lines=_wrap(d,title,main_font,max_w,3)
        ascent = d.textbbox((0,0),'AXÉ',font=main_font)
        step = max(15,round((ascent[3]-ascent[1])*1.17))
        if len(lines)*step <= round(192*s) and all(d.textbbox((0,0),line,font=main_font)[2]<=max_w for line in lines):
            break
        size=max(19*s,size-2*s)
    heading_block_h=len(lines)*step
    text_top=top+round(100*s)+max(0,round(82*s-heading_block_h/2))
    for i,line in enumerate(lines):
        box=d.textbbox((0,0),line,font=main_font)
        px=(width-(box[2]-box[0]))/2
        d.text((px,text_top+i*step),line,font=main_font,fill=(16,17,19,255))
    underline_y=bottom-round(86*s)
    d.rounded_rectangle((width*.38,underline_y,width*.62,underline_y+max(3,round(9*s))),radius=max(1,round(4*s)),fill=(237,191,37,255))
    footer_font=_font(24*s)
    fb=d.textbbox((0,0),footer,font=footer_font)
    d.text(((width-(fb[2]-fb[0]))/2,bottom-round(60*s)),footer,font=footer_font,fill=(84,84,82,255))
    return image


def save_title_overlay(path: Path, title: str, width: int, height: int, kind: str):
    footer = 'ROCK NACIONAL · CBJR' if kind=='reels' else 'SHOW AO VIVO · CBJR'
    overlay=editorial_card(title,width,height,footer=footer)
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    overlay.save(path)
    return path


def premium_cover(frame, title: str, kind: str):
    """Preserve complete horizontal shot over a softly blurred vertical canvas."""
    from PIL import Image, ImageOps, ImageFilter
    src=frame.convert('RGB')
    w,h=1080,1920
    bg=ImageOps.fit(src,(w,h),centering=(.5,.5)).filter(ImageFilter.GaussianBlur(44))
    full=ImageOps.contain(src,(w,1180),Image.Resampling.LANCZOS)
    zone_y=round(h*.58)
    bg.paste(full,((w-full.width)//2,zone_y-full.height//2))
    bg=bg.convert('RGBA')
    footer = 'ROCK NACIONAL · CBJR' if kind=='reels' else 'SHOW AO VIVO · CBJR'
    bg.alpha_composite(editorial_card(title,w,h,footer=footer))
    return bg.convert('RGB')
