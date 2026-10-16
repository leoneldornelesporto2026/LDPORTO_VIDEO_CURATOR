"""Explicit local watermark/music effects for the additive V5 renderer.

The source voice is always retained. Music needs a user-supplied local file and
an explicit rights confirmation; no separation, generation or downloads occur.
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
import re

from PIL import Image, ImageDraw

from .title_card import _load_font


_AUDIO_KEYS = {"mode", "music_path", "rights_confirmed", "music_sha256", "volume", "ducking"}
_WATERMARK_KEYS = {"text", "color", "opacity", "font_size_final", "position", "enabled"}


def _number(value, field, minimum, maximum):
    if isinstance(value, bool):
        raise ValueError(f"{field}: número obrigatório")
    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field}: número obrigatório") from exc
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"{field} fora de {minimum}–{maximum}")
    return value


def _hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024*1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _audio(episode):
    config = episode.get("audio")
    if config is None:
        config = {"mode": "original"}
    if not isinstance(config, dict):
        raise ValueError("audio deve ser objeto com mode original ou normalize")
    unknown = set(config)-_AUDIO_KEYS
    if unknown:
        raise ValueError("Controles de áudio não implementados: " + ", ".join(sorted(unknown)))
    mode = config.get("mode", "original")
    if mode not in {"original", "normalize"}:
        raise ValueError("Áudio disponível: original ou normalize")
    result = dict(config, mode=mode)
    music = config.get("music_path")
    if not music:
        if set(config)-{"mode"}:
            raise ValueError("Direitos/volume/ducking/hash exigem arquivo de música explícito")
        return result
    if config.get("rights_confirmed") is not True:
        raise ValueError("Trilha exige confirmação explícita de direitos (rights_confirmed=true)")
    music = Path(music)
    if not music.is_file() or music.suffix.lower() not in {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".mp4"}:
        raise ValueError("Trilha deve ser arquivo de áudio local disponível")
    result["music_path"] = music.resolve()
    result["volume"] = _number(config.get("volume", .12), "audio.volume", 0, 1)
    result["ducking"] = config.get("ducking", True)
    if not isinstance(result["ducking"], bool):
        raise ValueError("audio.ducking deve ser booleano")
    if config.get("music_sha256") and not re.fullmatch(r"[0-9a-fA-F]{64}", str(config["music_sha256"])):
        raise ValueError("SHA-256 de música inválido")
    return result


def _watermark(episode):
    config = episode.get("watermark")
    if config is None or config is False or config == "":
        return None
    if isinstance(config, str):
        config = {"text": config}
    if not isinstance(config, dict):
        raise ValueError("watermark exige texto explícito ou objeto")
    if set(config)-_WATERMARK_KEYS:
        raise ValueError("Controles de marca não implementados: " + ", ".join(sorted(set(config)-_WATERMARK_KEYS)))
    enabled = config.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError("watermark.enabled deve ser booleano")
    if not enabled:
        return None
    text = config.get("text")
    if not isinstance(text, str) or not text.strip() or len(text)>80 or any(c in text for c in "\r\n"):
        raise ValueError("Texto de marca deve ter 1–80 caracteres numa linha")
    color = config.get("color", "#FFFFFF")
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", str(color)):
        raise ValueError("Cor de marca inválida; use #RRGGBB")
    position = config.get("position", "bottom_left")
    if position not in {"top_left", "top_right", "bottom_left", "bottom_right"}:
        raise ValueError("Posição de marca inválida")
    return {"text":text,"color":color,"opacity":_number(config.get("opacity", .75),"watermark.opacity",0,1),
            "font_size_final":_number(config.get("font_size_final",32),"watermark.font_size_final",20,60),"position":position}


def effect_input_fingerprints(episode):
    """Validate effects and return hashes of all externally supplied effect inputs.

    Call before signing/reusing a preview as well as before final encoding. Paths
    in the returned metadata are filenames only, suitable for portable manifests.
    """
    audio, watermark = _audio(episode), _watermark(episode)
    result = {"audio_mode":audio["mode"],"watermark":watermark}
    if audio.get("music_path"):
        path=audio["music_path"]
        actual=_hash(path)
        if audio.get("music_sha256") and actual != audio["music_sha256"].lower():
            raise ValueError("SHA-256 da música mudou ou diverge do informado")
        result["music"]={"filename":path.name,"sha256":actual,"size_bytes":path.stat().st_size,
                         "rights_confirmed":True,"volume":audio["volume"],"ducking":audio["ducking"]}
    return result


def _watermark_png(config, width, height, directory):
    canvas=Image.new("RGBA",(width,height),(0,0,0,0))
    draw=ImageDraw.Draw(canvas)
    max_width=width*(1-.08-.16)
    size=max(10,int(config["font_size_final"]*width/1080))
    while size>=8:
        font=_load_font(size)
        bounds=draw.textbbox((0,0),config["text"],font=font)
        tw,th=bounds[2]-bounds[0],bounds[3]-bounds[1]
        if tw<=max_width:
            break
        size-=1
    else:
        raise ValueError("Marca longa demais para a zona segura")
    x=int(width*.08) if config["position"].endswith("left") else int(width*.84)-tw
    y=int(height*.12) if config["position"].startswith("top") else int(height*.82)-th
    rgb=tuple(int(config["color"][offset:offset+2],16) for offset in (1,3,5))
    alpha=int(round(config["opacity"]*255))
    draw.text((x-bounds[0],y-bounds[1]),config["text"],font=font,fill=(*rgb,alpha),
              stroke_width=max(1,width//540),stroke_fill=(0,0,0,alpha))
    path=Path(directory)/"WATERMARK.png"
    path.parent.mkdir(parents=True,exist_ok=True)
    canvas.save(path,format="PNG",optimize=True)
    return path


def extend_render_command(cmd, episode, width, height, duration, directory):
    """Extend a copy of V4 ``_base_cmd`` with explicit effects and audio policy.

    Video/audio map labels and input indices are derived from the existing
    command, including the optional opening-title image. Original speech is
    never removed. Music loops only for the clip length, mixes at bounded volume,
    and optionally ducks beneath source audio using sidechain compression.
    """
    if not isinstance(width,int) or not isinstance(height,int) or width<=0 or height<=0:
        raise ValueError("Resolução de efeitos inválida")
    duration=_number(duration,"duration",.001,24*60*60)
    audio,watermark=_audio(episode),_watermark(episode)
    effect_input_fingerprints(episode)  # Verify the supplied bytes before any asset write.
    command=list(cmd)
    if "-filter_complex" not in command or "-t" not in command:
        raise ValueError("Comando de render precisa de filter_complex e duração")
    input_count=command.count("-i")
    if not input_count:
        raise ValueError("Fonte de render ausente")
    added_inputs=[]
    watermark_index=music_index=None
    if watermark:
        watermark_index=input_count
        added_inputs += ["-loop","1","-framerate","30","-i",str(_watermark_png(watermark,width,height,directory))]
        input_count+=1
    if audio.get("music_path"):
        music_index=input_count
        added_inputs += ["-stream_loop","-1","-i",str(audio["music_path"])]
    at=command.index("-t")
    if at+1>=len(command):
        raise ValueError("Duração de render ausente")
    command[at+1]=f"{duration:.6f}"
    command[at:at]=added_inputs
    maps=[i+1 for i,value in enumerate(command[:-1]) if value=="-map"]
    video_map=next((i for i in maps if command[i].startswith("[")),None)
    audio_map=next((i for i in maps if command[i] in {"0:a?","0:a","0:a:0?","0:a:0"}),None)
    if video_map is None or audio_map is None:
        raise ValueError("Mapeamento de vídeo/áudio de origem inesperado")
    filter_at=command.index("-filter_complex")+1
    filters=command[filter_at]
    if watermark:
        label=command[video_map]
        filters+=f";[{watermark_index}:v]format=rgba[ldp_watermark];{label}[ldp_watermark]overlay=0:0:eof_action=repeat:shortest=1[ldp_effect_video]"
        command[video_map]="[ldp_effect_video]"
    loudnorm=None
    if "-af" in command:
        at=command.index("-af")
        loudnorm=command[at+1]
        del command[at:at+2]
    if music_index is None:
        if audio["mode"]=="normalize":
            command[-1:-1]=["-af",loudnorm or "loudnorm=I=-14:TP=-1.5:LRA=11"]
    else:
        voice_filter="asetpts=PTS-STARTPTS"
        if audio["mode"]=="normalize":
            voice_filter+=","+(loudnorm or "loudnorm=I=-14:TP=-1.5:LRA=11")
        if audio["ducking"]:
            filters+=f";[0:a]{voice_filter},asplit=2[ldp_voice][ldp_sidechain];[{music_index}:a]asetpts=PTS-STARTPTS,volume={audio['volume']:.6f}[ldp_music]"
            filters+=";[ldp_music][ldp_sidechain]sidechaincompress=threshold=0.025:ratio=8:attack=20:release=350[ldp_ducked]"
            filters+=";[ldp_voice][ldp_ducked]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,alimiter=limit=0.95[ldp_effect_audio]"
        else:
            filters+=f";[0:a]{voice_filter}[ldp_voice];[{music_index}:a]asetpts=PTS-STARTPTS,volume={audio['volume']:.6f}[ldp_music]"
            filters+=";[ldp_voice][ldp_music]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,alimiter=limit=0.95[ldp_effect_audio]"
        command[audio_map]="[ldp_effect_audio]"
    command[filter_at]=filters
    return command
