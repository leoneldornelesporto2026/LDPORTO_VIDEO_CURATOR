"""Editable 9:16 covers composed exclusively from the actual source video."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re

from PIL import Image, ImageDraw, ImageOps

from .thumbnails import extract_frame, select_candidates
from .title_card import _load_font


THUMBNAIL_PRESETS = {
    "IMPACTO": {"background": "#101823", "accent": "#C5FF35", "text_color": "#FFFFFF", "title_y": .15, "frame_y": .38, "frame_height": .36, "font_size": 102},
    "DOCUMENTAL": {"background": "#EDEAE4", "accent": "#14546B", "text_color": "#132632", "title_y": .62, "frame_y": .22, "frame_height": .35, "font_size": 78},
    "MINIMALISTA": {"background": "#161A1D", "accent": "#F5CB62", "text_color": "#FFFFFF", "title_y": .66, "frame_y": .21, "frame_height": .38, "font_size": 72},
    "MISTERIO": {"background": "#172034", "accent": "#FFD335", "text_color": "#FFFFFF", "title_y": .15, "frame_y": .38, "frame_height": .36, "font_size": 88},
}


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024*1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _finite(value, field):
    try:
        value = float(value)
    except (TypeError,ValueError) as exc:
        raise ValueError(f"{field}: timestamp obrigatório") from exc
    if not math.isfinite(value):
        raise ValueError(f"{field}: timestamp finito obrigatório")
    return value


def _get(evidence, field):
    return (evidence.get(field) if isinstance(evidence,dict) else getattr(evidence,field,None)) or []


def _literal_excerpt(episode, evidence):
    value = episode.get("original_excerpt_support") or episode.get("literal_excerpt") or episode.get("transcript_excerpt")
    if isinstance(value, str) and value.strip():
        return value
    if isinstance(value,list):
        texts = [item if isinstance(item,str) else item.get("text", "") for item in value if isinstance(item,(str,dict))]
        if any(texts):
            return " ".join(texts)
    texts = []
    for segment in _get(evidence,"segments"):
        try:
            overlaps = float(segment["end"])>episode["source_start"] and float(segment["start"])<episode["source_end"]
        except (KeyError,ValueError,TypeError):
            continue
        if overlaps:
            texts.append(str(segment.get("text") or ""))
    return " ".join(texts)


def _title_records(episode,titles,evidence):
    literal = _literal_excerpt(episode,evidence)
    options = titles or episode.get("cover_title_options") or episode.get("title_options") or episode.get("titles") or []
    if isinstance(options,str):
        options = [options]
    records = []
    for option in options:
        text = str(option.get("text") or option.get("title") or "") if isinstance(option,dict) else str(option)
        text = " ".join(text.split())
        if not text:
            continue
        if len(text)>240:
            raise ValueError("Título de capa excede 240 caracteres")
        quoted = text.casefold() in " ".join(literal.split()).casefold() if literal else False
        refs = option.get("evidence_refs") or option.get("segment_ids") or [] if isinstance(option,dict) else []
        records.append({"text": text, "status": "FACT_CHECK_REQUIRED", "support": "literal_excerpt" if quoted else "editorial_proposal",
                        "evidence_refs": refs, "literal_excerpt_match": quoted, "human_approved": False})
    if not records:
        text = " ".join(literal.split()[:5])
        if not text:
            # Part numbering is project metadata, not an invented scene or claim.
            text = f"Parte {int(episode.get('order') or 1):02d}"
        records.append({"text": text, "status": "FACT_CHECK_REQUIRED", "support": "literal_excerpt" if literal else "episode_number",
                        "evidence_refs": episode.get("segment_ids") or [], "literal_excerpt_match": bool(literal), "human_approved": False})
    return records


def _wrap(draw,text,font,width):
    lines = [""]
    for word in text.split():
        proposed = (lines[-1]+" "+word).strip()
        if draw.textbbox((0,0),proposed,font=font)[2]>width and lines[-1]:
            lines.append(word)
        else:
            lines[-1]=proposed
    return lines


def _draw_fitted_text(draw,text,box,color,base_size,font_path=None):
    left,top,right,bottom = box
    width,height = right-left,bottom-top
    for size in range(int(base_size),23,-2):
        font = _load_font(size,font_path)
        lines = _wrap(draw,text,font,width)
        boxes = [draw.textbbox((0,0),line,font=font) for line in lines]
        spacing = max(8,size//7)
        total_height = sum(b[3]-b[1] for b in boxes)+spacing*(len(lines)-1)
        if len(lines)<=4 and total_height<=height and all(b[2]-b[0]<=width for b in boxes):
            break
    else:
        raise ValueError("Título não cabe na zona segura; use uma frase menor")
    y=top
    actual=[]
    for line,bounds in zip(lines,boxes):
        line_height=bounds[3]-bounds[1]
        draw.text((left-bounds[0],y-bounds[1]),line,font=font,fill=color)
        actual.append([left,y,left+bounds[2]-bounds[0],y+line_height])
        y+=line_height+spacing
    return {"font_size": size,"lines": lines,"text_boxes": actual}


def generate_thumbnail_choices(source_path,episode,output_dir,titles=None,evidence=None,overrides=None,source_sha256=None):
    """Generate 3 or 5 real 1080x1920 candidates and a portable editable manifest.

    Overrides accept ``frame_times``, ``layouts``, ``font_path``, ``brand``,
    ``show_part`` and per-layout color/text geometry. All frame images retain the
    full source composition; titles and brand occupy separate safe areas.
    """
    source_path=Path(source_path)
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    st,en=_finite(episode.get("source_start"),"source_start"),_finite(episode.get("source_end"),"source_end")
    if st<0 or en<=st:
        raise ValueError("Intervalo de episódio inválido")
    overrides=dict(overrides or {})
    allowed={"frame_times","layouts","font_path","brand","show_part","layout_overrides","frame_count"}
    if set(overrides)-allowed:
        raise ValueError("Controles de capa desconhecidos: "+", ".join(sorted(set(overrides)-allowed)))
    count=overrides.get("frame_count", 3)
    if type(count) is not int or count not in (3, 5):
        raise ValueError("frame_count deve ser 3 ou 5")
    defaults=["IMPACTO","DOCUMENTAL","MINIMALISTA","MISTERIO","IMPACTO"]
    layouts=overrides.get("layouts") or defaults[:count]
    if len(layouts)!=count or any(layout not in THUMBNAIL_PRESETS for layout in layouts):
        raise ValueError("Quantidade ou layouts de capa inválidos")
    explicit_times=overrides.get("frame_times")
    if explicit_times is not None:
        if len(explicit_times)!=count:
            raise ValueError("Escolha exatamente frame_count timestamps de origem")
        times=[_finite(t,"frame_times") for t in explicit_times]
    else:
        # Reuse the legacy real-frame quality ranking when evidence is available.
        class Samples:
            frame_samples=_get(evidence,"frame_samples")
        ranked=select_candidates(Samples(),episode,n=count)
        times=[time for time in ranked if st<=time<en][:count]
        if len(times)<count:
            for i in range(count):
                candidate=st+(en-st)*(i+1)/(count+1)
                if all(abs(candidate - prev)>0.02 for prev in times):
                    times.append(candidate)
                if len(times)==count:
                    break
        if len(times)<count:
            raise ValueError("Intervalo sem frames distintos suficientes")
    if any(not st<=time<en for time in times):
        raise ValueError("Frame deve pertencer ao intervalo real do episódio")
    actual_source_hash=_sha256(source_path)
    if source_sha256 and actual_source_hash!=source_sha256:
        raise ValueError("SHA-256 da mídia diverge da fonte informada")
    titles=_title_records(episode,titles,evidence)
    brand=str(overrides.get("brand") or "L.D.PORTO")
    if len(brand)>40 or any(c in brand for c in "\r\n"):
        raise ValueError("Marca de capa inválida")
    width,height=1080,1920
    output_dir=Path(output_dir)
    output_dir.mkdir(parents=True,exist_ok=True)
    frames=output_dir/"frames"
    frames.mkdir(exist_ok=True)
    manifest={"schema":"LDP_THUMBNAIL_CHOICES_V5.1","episode_id":episode.get("episode_id"),"source_sha256":actual_source_hash,
              "source_start":st,"source_end":en,"state":"thumbnail_candidate","human_approved":False,
              "visual_origin":"actual_source_frames","composition":"full_source_preserve","choices":[]}
    for index,(layout,time) in enumerate(zip(layouts,times),1):
        title=titles[(index-1)%len(titles)]
        style=dict(THUMBNAIL_PRESETS[layout])
        style.update((overrides.get("layout_overrides") or {}).get(layout,{}))
        if set(style)!=set(THUMBNAIL_PRESETS[layout]):
            raise ValueError("Controle de layout desconhecido")
        for field in ("background","accent","text_color"):
            if not re.fullmatch(r"#[0-9a-fA-F]{6}",str(style[field])):
                raise ValueError("Cor de capa inválida")
        for field in ("title_y","frame_y","frame_height"):
            style[field]=_finite(style[field],field)
        if not .12<=style["title_y"]<=.7 or not .12<=style["frame_y"]<.75 or not .1<=style["frame_height"]<=.55 or style["frame_y"]+style["frame_height"]>.82:
            raise ValueError("Layout fora da zona segura")
        style["font_size"]=_finite(style["font_size"],"font_size")
        if not 24<=style["font_size"]<=160:
            raise ValueError("Tamanho de fonte inválido")
        frame_path=frames/f"frame_{index:02d}.png"
        extract_frame(source_path,time,frame_path)
        with Image.open(frame_path) as opened:
            frame=opened.convert("RGB")
        original_dimensions=list(frame.size)
        canvas=Image.new("RGB",(width,height),style["background"])
        draw=ImageDraw.Draw(canvas)
        safe_left,safe_right=int(width*.08),int(width*.84)
        frame_box=(safe_left,int(height*style["frame_y"]),safe_right,int(height*(style["frame_y"]+style["frame_height"])))
        preserved=ImageOps.contain(frame,(frame_box[2]-frame_box[0],frame_box[3]-frame_box[1]),Image.Resampling.LANCZOS)
        frame_x=frame_box[0]+(frame_box[2]-frame_box[0]-preserved.width)//2
        frame_y=frame_box[1]+(frame_box[3]-frame_box[1]-preserved.height)//2
        canvas.paste(preserved,(frame_x,frame_y))
        draw.rectangle((safe_left,int(height*.125),safe_left+110,int(height*.13)),fill=style["accent"])
        title_top=int(height*style["title_y"])
        # Reserve a text region that cannot cover any source pixels.
        title_bottom=min(int(height*.77),frame_box[1]-24) if title_top<frame_box[1] else int(height*.77)
        if title_top<frame_box[3] and title_bottom>frame_box[1]:
            raise ValueError("Texto da capa sobrepõe a imagem de origem")
        font_path=overrides.get("font_path")
        title_metrics=_draw_fitted_text(draw,title["text"],(safe_left,title_top,safe_right,title_bottom),style["text_color"],style["font_size"],font_path)
        small_font=_load_font(32,font_path)
        draw.text((safe_left,int(height*.79)),brand,font=small_font,fill=style["accent"])
        show_part=overrides.get("show_part",True)
        if not isinstance(show_part,bool):
            raise ValueError("show_part: booleano obrigatório")
        part=f"PARTE {int(episode.get('order') or 1):02d}" if show_part else ""
        if part:
            draw.text((safe_left,int(height*.135)),part,font=small_font,fill=style["accent"])
        path=output_dir/f"CAPA_{index:02d}_{layout}.png"
        canvas.save(path,format="PNG",optimize=True)
        record={"choice_id":f"CAPA_{index:02d}","layout":layout,"file":path.name,"sha256":_sha256(path),
                "dimensions":[width,height],"frame_file":frame_path.relative_to(output_dir).as_posix(),"frame_sha256":_sha256(frame_path),
                "source_timestamp":time,"source_timestamp_kind":"requested_source_seek","extraction_seek_seconds":round(time,3),
                "decoded_frame_timestamp":"not_measured","original_dimensions":original_dimensions,"frame_composition":"full_source_preserve",
                "frame_display_box":[frame_x,frame_y,frame_x+preserved.width,frame_y+preserved.height],
                "cover_title":title,"publication_title":None,"internal_series_title":episode.get("series_id"),
                "brand":brand,"part_label":part,"state":"thumbnail_candidate","editable":True,
                "style":style,"title_metrics":title_metrics,"safe_zone":{"left":.08,"right":.16,"top":.12,"bottom":.18}}
        editable=output_dir/f"CAPA_{index:02d}_{layout}.json"
        editable.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding="utf-8")
        record["editable_file"]=editable.name
        manifest["choices"].append(record)
    manifest_path=output_dir/"THUMBNAIL_CHOICES.json"
    manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    return {**manifest,"manifest":str(manifest_path)}
