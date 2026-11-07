"""Yellow, mobile-safe ASS subtitles without changing Analyzer/Curator originals.

The original SRT/ASS is immutable. Only the rendered copy gets presentation
changes; dialogue text and timestamps stay byte-for-byte equivalent.
"""
from __future__ import annotations

import re

STYLE_VALUES={
    "Fontname":"Arial",
    "Fontsize":"68",
    "PrimaryColour":"&H0000FFFF",  # ASS AA BB GG RR: bright opaque yellow
    "SecondaryColour":"&H0000FFFF",
    "OutlineColour":"&H00000000",
    "BackColour":"&H90000000",
    "Bold":"-1",
    "Italic":"0",
    "BorderStyle":"1",
    "Outline":"5",
    "Shadow":"2",
    "Alignment":"2",
    "MarginL":"94",
    "MarginR":"94",
    "MarginV":"244",   # PlayResY=1920 -> 122px above preview 960 bottom
}
# FFmpeg's libass applies Style on Dialogue, but inline ASS color overrides
# win over the Style. Remove only inline color overrides from preview copy.
_COLOUR_TAG=re.compile(r"\\(?:[1-4]?c|alpha|[1-4]a)&H[0-9a-fA-F]{1,8}&",re.I)


def make_yellow_ass(original: bytes) -> bytes:
    if not isinstance(original,bytes) or len(original)>4*1024*1024:
        raise ValueError("ASS inválida ou acima do limite de 4 MiB")
    try:
        document=original.decode("utf-8-sig")
    except UnicodeError as exc:
        raise ValueError("ASS de legendas deve ser UTF-8") from exc
    if "[V4+ Styles]" not in document or "[Events]" not in document:
        raise ValueError("ASS sem seções de estilos e eventos")
    output=[]
    section=""
    fields=[]
    modified=0
    for line in document.splitlines(keepends=True):
        ending="\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
        body=line[:-len(ending)] if ending else line
        stripped=body.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section=stripped
        if section=="[V4+ Styles]":
            if stripped.startswith("Format:"):
                fields=[s.strip() for s in stripped.split(":",1)[1].split(",")]
            elif stripped.startswith("Style:"):
                if not fields:
                    raise ValueError("ASS sem cabeçalho de formato de estilo")
                values=body.split(":",1)[1].lstrip().split(",")
                if len(values)!=len(fields):
                    raise ValueError("Style ASS não coincide com Format")
                for name,value in STYLE_VALUES.items():
                    if name not in fields:
                        raise ValueError("ASS sem campo de estilo: "+name)
                    values[fields.index(name)]=value
                body="Style: "+",".join(values)
                modified+=1
        elif section=="[Events]" and stripped.startswith("Dialogue:"):
            # Only inside ASS override blocks: text, timing and other tags
            # (\k for karaoke, \pos etc.) are otherwise preserved.
            def _strip_color(match):
                return "{"+_COLOUR_TAG.sub("",match.group(1))+"}"
            body=re.sub(r"\{([^{}]*)\}",_strip_color,body)
        output.append(body+ending)
    if modified==0:
        raise ValueError("ASS não possui estilo para legendas visíveis")
    return "".join(output).encode("utf-8")
