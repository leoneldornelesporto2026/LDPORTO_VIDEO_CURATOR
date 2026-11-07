"""Second-curation caption QA: compare actual SRT and ASS texts and timing.

This is STRUCTURAL review only. It cannot listen to speech or prove ASR
accuracy. The real audio must be checked by an editor before enabling captions.
Never grants review/approval flags or changes the original R6/R57 packages.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import unicodedata

from .core import fingerprint, json_bytes, sha256_bytes, sha256_file
from .r6_caption_drafts import parse_original_srt

MAX_REPORT_BYTES = 4 * 1024 * 1024
MAX_CUES = 2000


def _plain(text):
    text = re.sub(r"\{[^}]*\}", "", text)
    text = text.replace(r"\N", " ").replace(r"\n", " ").replace(r"\h", " ")
    text = unicodedata.normalize("NFKC", text).casefold()
    return " ".join(re.findall(r"\w+", text, flags=re.UNICODE))


def _ass_time_ms(raw):
    match=re.fullmatch(r"(\\d+):(\\d{2}):(\\d{2})\\.(\\d{2})",raw.strip())
    if not match:
        raise ValueError("Timestamp ASS malformado: "+raw)
    hh,mm,ss,cs=(int(value) for value in match.groups())
    if mm>=60 or ss>=60:
        raise ValueError("Timestamp ASS fora do formato")
    return ((hh*60+mm)*60+ss)*1000+cs*10


def _ass_dialogue(ass):
    try:
        text=ass.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("ASS de origem não está em UTF-8") from exc
    events=[]
    for row in text.splitlines():
        if row.startswith("Dialogue:"):
            parts=row.split(":",1)[1].split(",",9)
            if len(parts)!=10:
                raise ValueError("Diálogo ASS malformado")
            a,b=_ass_time_ms(parts[1]),_ass_time_ms(parts[2])
            if a>=b:
                raise ValueError("Intervalo ASS invertido/zerado")
            events.append({"start_ms":a,"end_ms":b,"text":parts[9]})
    return events


def inspect_caption_second_pass(project, cid):
    """Inspect real R57 source captions, no writes and no fabricated approval."""
    if cid not in project.package.clips:
        raise ValueError("Corte não existe no projeto")
    clip=project.package.clips[cid]
    settings=project.settings(cid)
    srt=project.package.data(clip.caption_srt)
    ass=project.caption_payload(cid)
    clip_duration_ms=round(
        (float(settings["source_end"])-float(settings["source_start"]))*1000)
    if clip_duration_ms <= 0:
        raise ValueError("Intervalo de corte inválido")
    cues=parse_original_srt(srt,clip_duration_ms)
    if len(cues)>MAX_CUES:
        raise ValueError("Legenda ultrapassa 2000 linhas")
    dialogues=_ass_dialogue(ass)
    flags=[]
    if not cues:
        flags.append("SEM_FALAS_NO_SRT")
    if len(dialogues)!=len(cues):
        flags.append("SRT_ASS_QUANTIDADE_DIFERENTE")
    entries=[]
    previous_end=0
    for i,(start,end,text) in enumerate(cues):
        issues=[]
        duration=max(.001,(end-start)/1000)
        cps=len(text.replace("\n"," ")) / duration
        if start<previous_end:
            issues.append("SOBREPOSICAO_TEMPORAL")
        previous_end=max(previous_end,end)
        if duration<.55:
            issues.append("FALA_MUITO_CURTA_PARA_REVISAR")
        if cps>24:
            issues.append("LEITURA_RAPIDA_REVISAR")
        if len(text.strip())>120:
            issues.append("FALA_LONGA_REVISAR")
        if i<len(dialogues):
            if _plain(dialogues[i]["text"])!=_plain(text):
                issues.append("TEXTO_SRT_ASS_DIFERENTE")
            # ASS stores centisecond timestamps; allow the quantization
            # error, never a significant timeline shift.
            if (abs(dialogues[i]["start_ms"]-start)>35 or
                    abs(dialogues[i]["end_ms"]-end)>35):
                issues.append("TEMPOS_SRT_ASS_DIFERENTES")
        if not text.strip():
            issues.append("TEXTO_VAZIO")
        flags += issues
        entries.append({"index":i+1,"start_ms":start,"end_ms":end,
                        "text_original_asr":text,"characters_per_second":round(cps,1),
                        "flags":issues,"human_audio_verified":False})
    result={
        "schema_version":"ldporto-caption-second-curation-1.0",
        "status":"SECOND_CURATOR_AUDIO_AND_TEXT_REVIEW_REQUIRED",
        "source_sha256":project.package.source_sha,
        "r57_package_sha256":project.package.digest,
        "clip_id":cid,"clip_kind":clip.kind,
        "source_start_seconds":settings["source_start"],
        "source_end_seconds":settings["source_end"],
        "srt_sha256":sha256_bytes(srt),
        "ass_sha256":sha256_bytes(ass),
        "r57_caption_override_present":bool(project._item(cid).get("caption_override")),
        "cue_count":len(cues),"ass_dialogue_count":len(dialogues),
        "flags":sorted(set(flags)),"cues":entries,
        "structural_text_consistency":not any(x in flags for x in
            ("SEM_FALAS_NO_SRT","SRT_ASS_QUANTIDADE_DIFERENTE",
             "TEXTO_SRT_ASS_DIFERENTE","TEMPOS_SRT_ASS_DIFERENTES")),
        "original_analyzer_asr_may_contain_errors":True,
        "second_listening_pass_completed":False,
        "captions_verified":False,"human_approved":False,
        "publication_ready":False,"media_modified":False,
    }
    if len(json_bytes(result))>MAX_REPORT_BYTES:
        raise ValueError("Relatório de legenda excede 4 MiB")
    return result


def save_caption_second_pass_report(project, cid):
    result=inspect_caption_second_pass(project,cid)
    folder=project.dir/"exports"/"caption_second_pass"/cid
    name="SECOND_PASS_"+fingerprint(result)[:20]+".json"
    target=folder/name
    if target.exists():
        if target.is_symlink() or json.loads(target.read_text(encoding="utf-8"))!=result:
            raise ValueError("Relatório anterior de legenda mudou; sem sobrescrever")
        return target
    folder.mkdir(parents=True,exist_ok=True)
    target.write_bytes(json_bytes(result))
    if sha256_file(target)!=sha256_bytes(json_bytes(result)):
        raise ValueError("Relatório salvo com bytes divergentes")
    return target
