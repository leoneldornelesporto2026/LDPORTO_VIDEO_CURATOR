"""Portable, checksum-verified evidence packet without implicit approvals."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import zipfile

PACKET_VERSION = "5.1.0"
_SECRET_KEYS = re.compile(r"(^|_)(token|secret|password|api_key|authorization|credential|hf_token)(_|$)", re.I)
_PRIVATE_PATH = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\[^\\]+\\|/(?:Users|home|mnt|tmp|var|opt|private|Volumes)/)[^\s\"<>]*")
_TOKEN = re.compile(r"\b(?:hf_[A-Za-z0-9]{16,}|sk-[A-Za-z0-9_-]{16,})\b")


def _sanitize(value, redactions, location="root"):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if _SECRET_KEYS.search(str(key)):
                redactions.append({"location": location + "." + str(key), "reason": "credential_field_removed"})
                continue
            if str(key).startswith("_asset_payload"):
                continue
            result[key] = _sanitize(item, redactions, location + "." + str(key))
        return result
    if isinstance(value, list):
        return [_sanitize(item, redactions, location + "[" + str(index) + "]") for index, item in enumerate(value)]
    if isinstance(value, str):
        clean = _PRIVATE_PATH.sub("[LOCAL_PATH_REDACTED]", value)
        if clean.startswith("/"):
            clean = "[LOCAL_PATH_REDACTED]"
        clean = _TOKEN.sub("[CREDENTIAL_REDACTED]", clean)
        if clean != value:
            redactions.append({"location": location, "reason": "private_path_or_credential_redacted", "original_sha256": hashlib.sha256(value.encode("utf-8")).hexdigest()})
        return clean
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Número não finito no handoff")
    return deepcopy(value)


def _json_bytes(document):
    return (json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _slug(value):
    return re.sub(r"[^A-Za-z0-9_-]+", "_", str(value)).strip("_")[:100] or "video"


def _lines(segments):
    return "\n".join(f"[{row['start']:.3f}–{row['end']:.3f}] {row.get('speaker') or 'speaker_unknown'} | {row.get('text', '')}" for row in segments) + ("\n" if segments else "")


def _overlap(rows, start, end):
    return [row for row in rows if isinstance(row, dict) and row.get("start") is not None and row.get("end") is not None and row["end"] > start and row["start"] < end]


def _scene_description(scenes):
    observed, interpreted = [], []
    for scene in scenes:
        source_description = scene.get("visual_description") or scene.get("description") or scene.get("observed_description") or scene.get("semantic_description")
        if source_description:
            explicit_observation = bool(scene.get("observed_description")) or scene.get("description_provenance") in {"human_observed", "direct_observation"}
            is_interpretation = (scene.get("inference") is True or scene.get("shot_type_inference") is True
                or str(scene.get("description_method", "")).startswith("model") or not explicit_observation)
            target = interpreted if is_interpretation else observed
            target.append({"scene_id": scene.get("scene_id"), "description": source_description, "confidence": scene.get("confidence"), "method": scene.get("description_method") or scene.get("method"),
                "verification": "source_interpretation_or_unverified_description" if is_interpretation else "explicit_source_observation"})
    return {"status": "available" if observed or interpreted else "unknown", "source_observations": observed,
        "source_model_interpretations": interpreted, "scene_boundaries": scenes,
        "note": "Shot boundaries and person track IDs do not establish objects, civil identities or events. Descriptions absent from the source remain unknown."}


def _safe_relative(value):
    value = str(value)
    if not value or "\\" in value or ":" in value or "\x00" in value or PurePosixPath(value).is_absolute() or any(part in {"..", ".", ""} for part in value.split("/")):
        raise ValueError("Caminho de mídia não portátil")
    return value


def validate_handoff(path: str | Path) -> dict:
    """Verify CRC, relative paths, exact inventory, lengths and SHA-256 hashes."""
    path = Path(path)
    with zipfile.ZipFile(path) as archive:
        rows = archive.infolist()
        if len(rows) > 10000 or sum(row.file_size for row in rows) > 2 * 1024 ** 3:
            raise ValueError("Handoff acima do limite de tamanho")
        names = [row.filename for row in rows]
        if len(names) != len(set(name.casefold() for name in names)):
            raise ValueError("Arquivos duplicados no handoff")
        for row in rows:
            _safe_relative(row.filename)
            if row.is_dir() or row.external_attr >> 16 & 0o170000 == 0o120000:
                raise ValueError("Entrada de diretório/symlink inválida")
        if archive.testzip() is not None:
            raise ValueError("CRC inválido no handoff")
        files = {name: archive.read(name) for name in names}
    manifest = json.loads(files["MANIFEST_SHA256.json"])
    entries = manifest.get("files") or []
    listed = {row["path"]: row for row in entries}
    if len(listed) != len(entries) or set(listed) != set(files) - {"MANIFEST_SHA256.json"}:
        raise ValueError("Inventário do handoff diverge do manifesto")
    for name, row in listed.items():
        if len(files[name]) != row["bytes"] or hashlib.sha256(files[name]).hexdigest() != row["sha256"]:
            raise ValueError("Checksum inválido: " + name)
    return manifest


def export_handoff(evidence: dict, plan: dict, output_dir: str | Path, media_paths=None) -> Path:
    """Write a versioned directory and its deterministic ZIP; return the ZIP.

    ``media_paths`` accepts a mapping of portable destination to explicit local
    file, or a list of local files. Only supplied media are copied. Missing media
    are described, and do not block a text-only dossier. No source is changed.
    """
    if not isinstance(evidence, dict) or not isinstance(plan, dict):
        raise ValueError("Evidências/plano inválidos")
    redactions = []
    safe_evidence = _sanitize(evidence, redactions, "evidence")
    safe_plan = _sanitize(plan, redactions, "plan")
    source = safe_evidence.get("source") or {}
    source_hash, duration = source.get("sha256"), source.get("duration")
    if not source_hash or isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
        raise ValueError("Fonte inválida para handoff")
    plan_hash = (safe_plan.get("source") or {}).get("sha256") or safe_plan.get("source_sha256")
    if plan_hash and plan_hash != source_hash:
        raise ValueError("Plano pertence a outra fonte")
    main_episodes = safe_plan.get("episodes") or []
    extras = safe_plan.get("extras") or []
    episodes = main_episodes + extras
    episode_ids = [row.get("episode_id") for row in episodes]
    if len(set(episode_ids)) != len(episode_ids) or any(not isinstance(value, str) or not value for value in episode_ids):
        raise ValueError("IDs de episódio inválidos")
    media, media_inventory = {}, []
    external_media = []
    for episode in episodes:
        for kind in ("preview", "final"):
            artifact = episode.get(kind)
            if not isinstance(artifact, dict):
                continue
            relative = artifact.get("project_path")
            if relative:
                relative = _safe_relative(relative)
                external_media.append({"episode_id": episode["episode_id"], "kind": kind, "project_path": relative,
                    "sha256": artifact.get("sha256"), "rendered_duration": artifact.get("rendered_duration"), "included": False,
                    "hash_status": "declared_render_artifact_hash", "note": "Referenced relative to the project. MP4 excluded unless explicitly supplied."})
    supplied = media_paths.items() if isinstance(media_paths, dict) else (("media/" + Path(value).name, value) for value in media_paths or [])
    for destination, origin in supplied:
        destination = _safe_relative(destination)
        if not destination.startswith("media/"):
            destination = "media/" + destination
        if destination in media:
            raise ValueError("Destino de mídia duplicado")
        path = Path(origin)
        if path.is_symlink():
            raise ValueError("Symlink de mídia não permitido")
        if path.is_file():
            payload = path.read_bytes()
            original_sha256 = hashlib.sha256(payload).hexdigest()
            if path.suffix.casefold() == '.json':
                payload = _json_bytes(_sanitize(json.loads(payload.decode('utf-8-sig')), redactions, 'media.' + destination))
            elif path.suffix.casefold() in {'.txt', '.md', '.ass', '.srt', '.vtt'}:
                payload = _sanitize(payload.decode('utf-8-sig'), redactions, 'media.' + destination).encode('utf-8')
            media[destination] = payload
            media_inventory.append({"path": destination, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(),
                "original_sha256": original_sha256, "included": True, "sanitized_copy": original_sha256 != hashlib.sha256(payload).hexdigest()})
        else:
            media_inventory.append({"path": destination, "included": False, "status": "missing"})
    # Analyzer visual samples are evidence and accompany the textual packet.
    import base64
    for relative, encoded in (evidence.get("_asset_payloads") or {}).items():
        destination = "source_visuals/" + _safe_relative(relative)
        payload = base64.b64decode(encoded, validate=True)
        inventory = next((row for row in evidence.get("asset_inventory", []) if row.get("path") == relative), None)
        if not inventory or hashlib.sha256(payload).hexdigest() != inventory.get("sha256"):
            raise ValueError("Asset visual diverge do inventário")
        media[destination] = payload
        media_inventory.append({"path": destination, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(), "included": True, "evidence_ref": relative})
        for row in safe_evidence.get("asset_inventory", []):
            if row.get("path") == relative:
                row["included_in_handoff"] = True
                row["portable_path"] = destination
    signature = hashlib.sha256(_json_bytes({"evidence": safe_evidence, "plan": safe_plan, "media": media_inventory, "external_media": external_media})).hexdigest()
    name = "CHATGPT_SECOND_CURATION_PACKET_" + _slug(source.get("video_id") or source.get("id")) + "_" + signature[:16]
    root = Path(output_dir)
    if root.is_symlink() or any(parent.is_symlink() for parent in root.parents):
        raise ValueError("Destino de handoff via symlink não permitido")
    root.mkdir(parents=True, exist_ok=True)
    folder, archive_path = root / name, root / (name + ".zip")
    if archive_path.exists():
        manifest = validate_handoff(archive_path)
        if manifest.get("packet_signature") == signature:
            return archive_path
        raise ValueError("Handoff existente não pode ser sobrescrito")
    if folder.exists():
        raise ValueError("Pasta de handoff existente sem ZIP válido; preserve-a e escolha outro diretório")
    files = {}

    def add(relative, document, json_document=True):
        relative = _safe_relative(relative)
        if relative in files or relative in media:
            raise ValueError("Arquivo de handoff duplicado")
        files[relative] = _json_bytes(document) if json_document else str(document).encode("utf-8")

    availability = safe_evidence.get("availability") or {}
    segments = sorted(safe_evidence.get("segments") or [], key=lambda row: (row["start"], row["end"], row.get("segment_id", "")))
    add("source_manifest.json", {"source": source, "provenance": safe_evidence.get("provenance"), "source_metadata": safe_evidence.get("metadata"),
        "evidence_semantics": safe_evidence.get("evidence_semantics"), "media": media_inventory + external_media,
        "source_asset_inventory": safe_evidence.get("asset_inventory", []), "redactions": redactions})
    add("evidence_availability.json", availability)
    add("story_map.json", safe_plan.get("story_map") or {})
    add("series_index.json", safe_plan)
    add("evidence/all_available_evidence.json", safe_evidence)
    add("transcript/segments.jsonl", "".join(json.dumps(row, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n" for row in segments), False)
    add("transcript/transcript_full_available.txt", _lines(segments), False)
    add("transcript/transcript_status.json", {"availability": availability.get("segments", {"status": "missing"}), "word_alignment": availability.get("words", {"status": "missing"}),
        "literal_policy": "all available source segments, no paraphrase and no reconstructed missing speech", "human_audio_verified": False,
        "redacted_literal_fields": [row for row in redactions if row["location"].startswith("evidence.segments")],
        "note": "Available is an inventory status; whole-source completeness and ASR fidelity require explicit evidence. Partial source artifacts stay partial."})
    for component in ("words", "scenes", "timeline", "chapters", "program_sections", "story_arcs", "qa", "speakers", "participants", "speaker_person_mapping", "frame_samples", "camera_timeline", "ocr", "graphics", "visual_refs", "quality", "blockers", "excluded_intervals", "silences", "candidates", "shortlist", "review_queue", "decisions"):
        add("evidence/" + component + ".json", safe_evidence.get(component, []))
    add("evidence/scene_descriptions.json", _scene_description(safe_evidence.get("scenes") or []))
    context_seconds = 20.0
    for index, episode in enumerate(episodes, 1):
        start, end = episode.get("source_start"), episode.get("source_end")
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in (start, end)) or not 0 <= start < end <= duration:
            raise ValueError("Intervalo de episódio fora da fonte")
        exact = _overlap(segments, start, end)
        before = _overlap(segments, max(0, start - context_seconds), start)
        after = _overlap(segments, end, min(duration, end + context_seconds))
        scenes = _overlap(safe_evidence.get("scenes") or [], start, end)
        words = _overlap(safe_evidence.get("words") or [], start, end)
        episode_data = {**episode, "transcript_literal_segments": exact, "word_timestamps": words,
            "context_before": before, "context_after": after, "scene_evidence": _scene_description(scenes),
            "audio_review_status": episode.get("audio_review_status", "unverified"),
            "publication_status": episode.get("publication_status", "needs_human_review"),
            "observed_vs_editorial": "transcript_literal_segments and source scene_evidence are source data; titles, hooks and summaries are editorial proposals"}
        category = "episodes" if index <= len(main_episodes) else "EXTRAS_MELHORES_MOMENTOS"
        category_index = index if category == "episodes" else index - len(main_episodes)
        relative = category + "/" + f"{category_index:03d}_" + _slug(episode["episode_id"])
        add(relative + "/episode.json", episode_data)
        add(relative + "/transcript_exact.txt", _lines(exact), False)
        add(relative + "/transcript_context.txt", "CONTEXTO ANTERIOR\n" + _lines(before) + "\nTRECHO (SEGMENTOS LITERAIS)\n" + _lines(exact) + "\nCONTEXTO POSTERIOR\n" + _lines(after), False)
        add(relative + "/source_refs.json", {"source_sha256": source_hash, "source_start": start, "source_end": end,
            "segment_ids": [row.get("segment_id") for row in exact], "word_ids": [row.get("word_id") for row in words], "scene_ids": [row.get("scene_id") for row in scenes],
            "candidate_ids": episode.get("candidate_ids", []), "literal_segment_boundary_policy": "Whole overlapping source segments are retained. No invented word-level cut at episode boundary."})
        title_options = episode.get('title_options') or []
        literal_support = ' '.join(row.get('text','') for row in exact)
        keywords = list(dict.fromkeys(word.casefold() for word in re.findall(r'[^\W\d_]{5,}', literal_support)))[:10]
        cover_options = [{'text':' '.join(str(row.get('text','')).split()[:5]),
                          'support':row.get('segment_ids',[]), 'status':'FACT_CHECK_REQUIRED'}
                         for row in title_options[:3] if isinstance(row,dict)]
        add(relative + '/social_copy_drafts.json', {
            'status':'DRAFT', 'factuality':'FACT_CHECK_REQUIRED', 'publication_approved':False,
            'publication_title_options':title_options[:3], 'cover_title_options':cover_options,
            'description_options':[{'kind':'literal_excerpt', 'text':literal_support, 'segment_ids':[row.get('segment_id') for row in exact]},
                                   {'kind':'literal_excerpt_with_context', 'text':literal_support,
                                    'context_refs':[row.get('segment_id') for row in before+after],
                                    'needs_editorial_rewrite':True}],
            'pinned_comment':{'kind':'creative_prompt', 'text':'Qual trecho você quer comentar?', 'asserts_source_facts':False},
            'keywords':keywords, 'hashtags':['#'+word for word in keywords[:5]],
            'subtitle_preset':episode.get('subtitle_preset'), 'camera_proposal':episode.get('camera_plan') or {'status':'unknown'},
            'note':'Descriptions retain source excerpts. Keywords are literal tokens, not confirmed topics or names; review ASR, context and copy before publishing.'})
        for key in ("camera_plan", "subtitle_style", "thumbnail_choices", "social_copy_drafts"):
            if key in episode:
                add(relative + "/" + key + ".json", episode[key])
        add(relative + "/story_and_scenes.md", "\n".join([f"# {episode['episode_id']}", "", f"Origem: {start:.3f}s → {end:.3f}s ({end-start:.3f}s)",
            "Estado: " + str(episode.get("status", "REVIEW_REQUIRED")), "Áudio: " + str(episode_data["audio_review_status"]), "",
            "## Evidências literais", _lines(exact), "## Cenas", json.dumps(episode_data["scene_evidence"], ensure_ascii=False, indent=2), "",
            "## Propostas editoriais", json.dumps({key: episode.get(key) for key in ("story_premise", "title_options", "hook_options", "setup", "development", "payoff", "teaser_next", "uncertainties", "risk_flags")}, ensure_ascii=False, indent=2), ""]), False)
    statuses = "\n".join(f"- {component}: {row.get('status')} ({row.get('count', 0)}) — {', '.join(row.get('sources', [])) or 'fonte ausente'}" for component, row in availability.items())
    add("INDEX.md", "\n".join(["# L.D.PORTO — Segunda curadoria / ChatGPT", "", "Este pacote contém o inventário completo das evidências disponíveis e propostas editoriais para revisão humana.",
        f"Vídeo: {source.get('video_id')}; duração da fonte: {duration:.3f}s; SHA-256: {source_hash}.",
        "", "Leia source_manifest.json, evidence_availability.json e series_index.json antes de sugerir títulos, descrições, tags ou comentários.",
        "Transcrição literal: transcript/transcript_full_available.txt e transcript/segments.jsonl. Nenhuma fala ausente foi reconstruída.",
        "Cenas sem descrição comprovada permanecem unknown. Speaker acústico, pessoa visível e identidade nominal são informações distintas.",
        "As propostas não constituem aprovação de preview, render final ou publicação. A fidelidade do ASR ainda exige conferência auditiva.",
        "Mídia incluída consta no manifesto; assets apenas referenciados têm SHA-256 e disponibilidade explícita. Caminhos locais/credenciais são removidos com registro de redacão.",
        "", "## Disponibilidade", statuses, "", f"Episódios da série: {len(main_episodes)}; melhores momentos extras: {len(extras)}. Contexto anterior/posterior: até {context_seconds:g}s, preservando segmentos inteiros.", "",
        "## Integridade", "MANIFEST_SHA256.json lista cada arquivo do ZIP, tamanho e SHA-256. O manifesto não inclui seu próprio hash.", ""]), False)
    files.update(media)
    manifest = {"schema_version": PACKET_VERSION, "packet_type": "CHATGPT_SECOND_CURATION_PACKET", "packet_signature": signature, "source_sha256": source_hash,
        "input_package_sha256": (safe_evidence.get("provenance") or {}).get("input_package_sha256"),
        "files": [{"path": relative, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()} for relative, payload in sorted(files.items())]}
    files["MANIFEST_SHA256.json"] = _json_bytes(manifest)
    folder.mkdir()
    for relative, payload in sorted(files.items()):
        target = folder / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    with zipfile.ZipFile(archive_path, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for relative, payload in sorted(files.items()):
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, payload)
    validate_handoff(archive_path)
    return archive_path
