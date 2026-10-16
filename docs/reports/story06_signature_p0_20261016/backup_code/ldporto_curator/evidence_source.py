"""Read-only, bounded evidence adapter for the additive V5 workflow.

An artifact being settled is different from every measurement being complete.
Partial Analyzer packages never become a full transcript by inference.
"""
from __future__ import annotations

from copy import deepcopy
import base64
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re

from . import __version__
from .analysis_loader import AnalysisBundle
from .second_curation_import import read_package
from .second_curation_decisions import compile_decisions

SCHEMA_VERSION = "5.1.0"
MAX_FILES = 5000
MAX_BYTES = 256 * 1024 ** 2
_COMPLETE = {"complete", "completed", "done", "finished", "ready", "success", "succeeded"}
_ACTIVE = {"running", "processing", "in_progress", "pending", "started"}
_ACTIVE_NAMES = {"analysis_running.flag", "processing.flag", "in_progress.flag", ".running", ".lock", "analysis.lock", "processing.lock"}
_SKIP_DIRS = {"checkpoints", ".package", "models", "weights", "__pycache__"}

# Ordered aliases cover canonical Analyzer files and compact package layouts.
_FILES = {
    "segments": ("transcript/full_segments.jsonl", "transcript/full_transcript.json", "transcript/transcript_segments.jsonl", "transcript/segments.jsonl", "transcript_segments.json", "transcript/segments.json", "transcript/relevant_segments.jsonl"),
    "words": ("transcript/full_words.jsonl", "transcript/words.jsonl", "words.json", "transcript/words.json", "transcript/relevant_words.jsonl"),
    "scenes": ("scenes.json", "visual/scenes.json", "timeline/scenes.json", "visual/shot_boundaries.json", "shot_boundaries.json"),
    "timeline": ("timeline.json", "timeline/timeline.json", "timeline/av_timeline.json", "audiovisual/timeline.json"),
    "chapters": ("chapters.json", "editorial/chapters.json", "story/chapters.json"),
    "qa": ("questions_answers.json", "editorial/questions_answers.json", "story/questions_answers.json", "qa.json"),
    "candidates": ("editorial/candidate_catalog.json", "second_curation_package.json"),
    "shortlist": ("editorial/default_shortlist.json", "default_shortlist.json"),
    "review_queue": ("editorial/review_queue.json", "review_queue.json", "editorial/ranking.json", "ranking.json"),
    "story_arcs": ("story_arcs.json", "editorial/story_arcs.json", "story/story_arcs.json"),
    "program_sections": ("program_sections.json", "editorial/program_sections.json", "story/program_sections.json"),
    "speakers": ("speakers.json", "transcript/speakers.json", "audio/speakers.json"),
    "participants": ("participants.json", "editorial/participants.json", "people/participants.json"),
    "speaker_person_mapping": ("speaker_person_mapping.json", "visual/speaker_person_mapping.json", "audiovisual/speaker_person_mapping.json"),
    "people_observations": ("people_observations.json", "visual/people_observations.json"),
    "frame_samples": ("frame_samples.json", "visual/frame_samples.json", "video_analysis.json"),
    "camera_timeline": ("camera_director_timeline.json", "camera/camera_director_timeline.json", "camera/timeline.json"),
    "ocr": ("ocr.json", "visual/ocr.json", "ocr_observations.json", "visual/ocr_observations.json"),
    "graphics": ("broadcast_graphics.json", "visual/broadcast_graphics.json", "graphics.json", "visual/graphics.json"),
    "visual_refs": ("visual_refs.json", "visual/visual_refs.json", "visual/contact_sheets.json", "contact_sheets.json"),
    "silences": ("silences.json", "audio/silences.json"),
    "excluded_intervals": ("excluded_intervals.json", "editorial/excluded_intervals.json"),
    "quality": ("quality.json", "qa/quality.json", "quality_report.json"),
    "blockers": ("blockers.json", "qa/blockers.json"),
    "decisions": ("SECOND_CURATION_DECISIONS.json",),
}
_ROW_KEYS = {"segments": ("segments", "transcript_segments"), "words": ("words",), "candidates": ("candidates",),
             "shortlist": ("candidate_ids", "shortlist"), "qa": ("questions_answers", "qa", "pairs"),
             "frame_samples": ("frame_samples",), "review_queue": ("review_queue", "ranking", "candidates", "candidate_ids")}


def _json(payload, name):
    try:
        value = json.loads(payload.decode("utf-8-sig"), parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Número não finito: " + value)))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("JSON inválido: " + name) from error
    return value


def _document(files, name):
    if name.endswith(".jsonl"):
        return [_json(line, name) for line in files[name].splitlines() if line.strip()]
    return _json(files[name], name)


def _relative_ref(value):
    if not isinstance(value, str) or not value or "\\" in value or ":" in value or "\x00" in value:
        raise ValueError("Referência externa ou caminho inválido")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"..", "."} for part in value.split("/")):
        raise ValueError("Referência externa ou caminho inválido")
    return path.as_posix()


def _directory_files(root):
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Diretório de evidências inválido")
    files, paths, total = {}, {}, 0
    # Only the explicitly supplied directory is inspected; never search Analyzer roots.
    for path in root.rglob("*"):
        rel = path.relative_to(root)
        if any(part.casefold() in _SKIP_DIRS for part in rel.parts):
            continue
        if path.is_symlink():
            raise ValueError("Symlink não permitido nas evidências")
        if path.name.casefold() in _ACTIVE_NAMES or path.name.casefold().endswith(".lock"):
            raise ValueError("Análise ativa: sentinela de processamento presente")
        if not path.is_file() or path.suffix.casefold() not in {".json", ".jsonl", ".flag", ".jpg", ".jpeg", ".png", ".webp", ".md", ".txt", ".srt"}:
            continue
        size = path.stat().st_size
        total += size
        if len(paths) >= MAX_FILES or total > MAX_BYTES:
            raise ValueError("Evidências acima do limite de tamanho")
        paths[rel.as_posix()] = (path, size)

    def read(name):
        path, size = paths[name]
        payload = path.read_bytes()
        if len(payload) != size or path.stat().st_size != size:
            raise ValueError("Artefato mudou durante a leitura")
        files[name] = payload

    for name in ("analysis.json", "completion.json", "SECOND_CURATION_MANIFEST.json"):
        if name in paths:
            read(name)
    analysis = _document(files, "analysis.json") if "analysis.json" in files else {}
    completion = _document(files, "completion.json") if "completion.json" in files else {}
    status = str(analysis.get("analysis_status", analysis.get("status", ""))).casefold()
    metadata = analysis.get("metadata") or {}
    if status in _ACTIVE or metadata.get("processing") is True or analysis.get("processing") is True:
        raise ValueError("Análise ainda em processamento")
    stages = analysis.get("stage_status") or {}
    if isinstance(stages, dict) and any(str(row.get("status", "")).casefold() in _ACTIVE for row in stages.values() if isinstance(row, dict)):
        raise ValueError("Análise possui etapa ativa")
    settled = (status in _COMPLETE or any(name in paths for name in ("ANALYSIS_COMPLETE.flag", "COMPLETED.flag"))
               or completion.get("artifact_complete") is True and str(completion.get("status", "")).casefold() in _COMPLETE)
    manifest = _document(files, "SECOND_CURATION_MANIFEST.json") if "SECOND_CURATION_MANIFEST.json" in files else {}
    if manifest:
        listed = manifest.get("files") or []
        refs = [row.get("path") for row in listed]
        if len(refs) != len(set(refs)):
            raise ValueError("Manifest possui caminhos duplicados")
        if not {"source/metadata.json", "editorial/candidate_catalog.json", "transcript/relevant_segments.jsonl"} <= set(refs):
            raise ValueError("Manifest sem arquivos essenciais de um pacote concluído")
        for row in listed:
            name = _relative_ref(row["path"])
            if name in paths and name not in files:
                read(name)
            if name not in files or len(files[name]) != row["bytes"] or hashlib.sha256(files[name]).hexdigest() != row["sha256"]:
                raise ValueError("Checksum inválido: " + name)
        settled = True  # A verified imported archive is a settled artifact, even when partial.
    if not settled:
        raise ValueError("Diretório sem comprovação explícita de conclusão; use um pacote ou snapshot concluído")
    for name in paths:
        if name not in files:
            read(name)
    return files, analysis, manifest


def _rows(document, component):
    if isinstance(document, list):
        return deepcopy(document)
    if isinstance(document, dict):
        for key in _ROW_KEYS.get(component, (component, "items", "rows")):
            if isinstance(document.get(key), list):
                return deepcopy(document[key])
    return []


def _validate_interval(row, duration, component):
    if not isinstance(row, dict):
        return
    if "start" not in row and "source_start" in row:
        row["start"] = row["source_start"]
    if "end" not in row and "source_end" in row:
        row["end"] = row["source_end"]
    if "start" not in row and "start_time" in row:
        row["start"] = row["start_time"]
    if "end" not in row and "end_time" in row:
        row["end"] = row["end_time"]
    if component == "qa" and "start" not in row and "question_start" in row:
        row["start"] = row["question_start"]
    if component == "qa" and "end" not in row and "answer_end" in row:
        row["end"] = row["answer_end"]
    for key in ("start", "end", "time", "timestamp", "question_start", "answer_end"):
        if key in row and row[key] is not None:
            value = row[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= duration:
                raise ValueError("Tempo inválido em " + component)
    if row.get("start") is not None and row.get("end") is not None and row["end"] < row["start"]:
        raise ValueError("Intervalo invertido em " + component)
    if component in {"segments", "candidates", "chapters", "qa", "scenes"} and row.get("start") is not None and row.get("end") is not None and row["end"] == row["start"]:
        raise ValueError("Intervalo vazio em " + component)


def _declared_status(component, documents, manifest, analysis, name, present):
    declarations = []
    for doc in (manifest, analysis, documents.get(name, {}) if name else {}):
        if isinstance(doc, dict):
            registry = doc.get("evidence_availability") or doc.get("availability") or {}
            declaration = registry.get(component) if isinstance(registry, dict) else None
            if isinstance(declaration, dict):
                declarations.append(declaration.get("status"))
            elif isinstance(declaration, str):
                declarations.append(declaration)
            if name and isinstance(doc, dict) and doc.get("status") in {"partial", "stale", "not_measured"}:
                declarations.append(doc["status"])
    for status in ("stale", "not_measured", "partial", "missing"):
        if status in declarations:
            return status
    if not present:
        stages = analysis.get("stage_status") or {}
        aliases = {"speakers": "diarization", "speaker_person_mapping": "active_speaker", "people_observations": "people_tracking", "scenes": "scenes", "words": "transcription", "ocr": "ocr"}
        stage_key = aliases.get(component, component)
        stage = next((row for key, row in stages.items() if key == stage_key or key.endswith("_" + stage_key)), {}) if isinstance(stages, dict) else {}
        if isinstance(stage, dict) and stage.get("status") in {"skipped", "disabled", "not_measured", "not_run", "unavailable"}:
            return "not_measured"
        return "missing"
    if name and "relevant_" in name:
        return "partial"
    # Partial packages are a selected view unless they explicitly carry full transcript files.
    if component in {"segments", "words"} and (str(analysis.get("analysis_status", "")).casefold() == "partial" or analysis.get("second_curation_import") is True):
        return "partial"
    return "available"


def _assemble(files, metadata, analysis, manifest, package_hash=None):
    if not isinstance(metadata, dict):
        raise ValueError("Metadados de fonte inválidos")
    source_hash, duration = metadata.get("sha256"), metadata.get("duration")
    if not isinstance(source_hash, str) or not source_hash.strip():
        raise ValueError("Fonte sem SHA-256 declarado")
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
        raise ValueError("Duração da fonte inválida")
    if manifest.get("source_hash") not in {None, source_hash}:
        raise ValueError("Hash da fonte diverge do manifesto")
    source = deepcopy(metadata)
    original_source = metadata.get("source") or {}
    if not isinstance(original_source, dict):
        raise ValueError("Metadados da origem inválidos")
    source.update({"video_id": original_source.get("id") or metadata.get("video_id") or source_hash[:12],
                   "id": original_source.get("id") or metadata.get("video_id") or source_hash[:12],
                   "title": original_source.get("title") or metadata.get("title")})
    documents = {name: _document(files, name) for name in files if name.endswith((".json", ".jsonl"))}
    insights = documents.get("llm_insights.json") or {}
    evidence = {"schema_version": SCHEMA_VERSION, "source": source, "metadata": deepcopy(metadata), "availability": {},
                "provenance": {"source_sha256": source_hash, "input_package_sha256": package_hash,
                    "analyzer_version": metadata.get("analyzer_version") or manifest.get("analyzer_version"),
                    "analyzer_fingerprint": metadata.get("analyzer_fingerprint") or manifest.get("analyzer_fingerprint"),
                    "analyzer_provenance": deepcopy(manifest.get("provenance") or metadata.get("provenance") or {}),
                    "curator_version": __version__, "evidence_adapter_version": SCHEMA_VERSION,
                    "curator_fingerprint": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    "source_hash_validation": "declared_metadata_and_manifest_consistency_not_media_rehash",
                    "analysis_status": analysis.get("analysis_status"), "build_mismatch": deepcopy(manifest.get("build_mismatch", metadata.get("build_mismatch", analysis.get("build_mismatch"))))},
                "quality": {}, "blockers": [], "documents": documents, "unresolved_references": []}
    for component, aliases in _FILES.items():
        name = next((candidate for candidate in aliases if candidate in documents), None)
        document = documents.get(name) if name else None
        embedded_source = None
        if name is None:
            keys = _ROW_KEYS.get(component, (component,))
            for doc, location in ((analysis, "analysis.json"), (insights, "llm_insights.json")):
                key = next((key for key in keys if key in doc), None)
                if key:
                    document, embedded_source = doc[key], location + "#" + key
                    break
        if document is None:
            fallback = {"quality": (documents.get("video_analysis.json") or {}, "quality", "video_analysis.json"),
                "participants": (analysis.get("summary") or {}, "main_participants", "analysis.json#summary"),
                "chapters": (insights, "chapters", "llm_insights.json")}.get(component)
            if fallback and fallback[1] in fallback[0]:
                document = fallback[0][fallback[1]]
                embedded_source = fallback[2] + "#" + fallback[1]
        present = name is not None or embedded_source is not None
        if component in {"quality", "decisions"}:
            rows = deepcopy(document or {})
        else:
            rows = _rows(document, component)
        evidence[component] = rows
        status = _declared_status(component, documents, manifest, analysis, name, present)
        if isinstance(document, dict) and document.get("source_sha256", document.get("source_hash", source_hash)) != source_hash:
            status = "stale"
        source_names = [name or embedded_source] if present else []
        physical_name = name or (embedded_source.split("#", 1)[0] if embedded_source else None)
        evidence["availability"][component] = {"status": status, "count": len(rows) if isinstance(rows, (list, dict)) else 0,
            "sources": source_names, "source_sha256": source_hash, "completeness_claim": "available_inventory_only" if status == "available" else "not_complete",
            "artifact_sha256": hashlib.sha256(files[physical_name]).hexdigest() if physical_name in files else None}
        if component in {"segments", "words", "scenes"}:
            id_key = {"segments": "segment_id", "words": "word_id", "scenes": "scene_id"}[component]
            ids = set()
            for index, row in enumerate(rows):
                if not isinstance(row, dict):
                    raise ValueError("Linha inválida em " + component)
                if not row.get(id_key):
                    row[id_key] = "DERIVED_" + id_key.upper() + "_" + hashlib.sha256(json.dumps([source_hash, component, index, row], ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:20]
                    row["id_provenance"] = "curator_derived_evidence_id"
                if not isinstance(row[id_key], str) or row[id_key] in ids:
                    raise ValueError("IDs duplicados ou inválidos em " + component)
                ids.add(row[id_key])
                if component == "segments" and not isinstance(row.get("text"), str):
                    raise ValueError("Transcrição literal inválida")
        else:
            id_keys = {"timeline": "timeline_id", "chapters": "chapter_id", "qa": "qa_id", "story_arcs": "arc_id", "program_sections": "section_id", "speakers": "speaker_id", "participants": "participant_id", "frame_samples": "frame_sample_id"}
            id_key = id_keys.get(component)
            if id_key and isinstance(rows, list):
                ids = [row[id_key] for row in rows if isinstance(row, dict) and id_key in row]
                if any(not isinstance(value, str) or not value for value in ids) or len(ids) != len(set(ids)):
                    raise ValueError("IDs duplicados ou inválidos em " + component)
        for row in rows if isinstance(rows, list) else []:
            _validate_interval(row, duration, component)
    candidates = evidence["candidates"]
    candidate_ids = [row.get("candidate_id") for row in candidates]
    if len(candidate_ids) != len(set(candidate_ids)) or any(not isinstance(cid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", cid) for cid in candidate_ids):
        raise ValueError("Candidate IDs inválidos")
    if any(cid not in candidate_ids for cid in evidence["shortlist"] if isinstance(cid, str)):
        raise ValueError("Shortlist referencia candidato inexistente")
    ids = {"segment_ids": {r["segment_id"] for r in evidence["segments"]}, "word_ids": {r["word_id"] for r in evidence["words"]}, "scene_ids": {r["scene_id"] for r in evidence["scenes"]}}
    for component in _FILES:
        for row in evidence[component] if isinstance(evidence[component], list) else []:
            if not isinstance(row, dict):
                continue
            for key, available in ids.items():
                missing = [ref for ref in row.get(key, []) if ref not in available]
                if missing:
                    if component == "candidates" and key == "segment_ids":
                        raise ValueError("Candidato referencia segmento inexistente")
                    evidence["unresolved_references"].append({"component": component, "key": key, "ids": missing})
            refs = list(row.get("visual_refs", [])) + list(row.get("file_refs", []))
            refs += [row[key] for key in ("keyframe", "frame_path", "image_path", "contact_sheet", "portrait") if isinstance(row.get(key), str)]
            if component in {"visual_refs", "frame_samples", "people_observations"} and isinstance(row.get("path"), str):
                refs.append(row["path"])
            for ref in refs:
                name = _relative_ref(ref)
                if name not in files:
                    evidence["unresolved_references"].append({"component": component, "key": "file_ref", "path": name})
    if evidence["decisions"]:
        compile_decisions(evidence["decisions"], {"candidates": candidates}, metadata, evidence["segments"])
        if package_hash and evidence["decisions"].get("input_package_sha256") not in {None, package_hash}:
            raise ValueError("Decisões pertencem a outro pacote")
    evidence["evidence_semantics"] = {"transcript": "literal_asr_not_human_audio_verified", "speaker": "acoustic_diarization_not_identity",
        "visible_person": "visual_observation_not_named_identity", "speaker_person_mapping": "only_explicit_source_mapping",
        "scene_description": "source_observation_or_labeled_model_interpretation", "camera": "suggestion_not_render_validation",
        "candidate": "proposal_not_human_approval"}
    evidence["asset_inventory"] = [{"path": name, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(), "included_in_handoff": False}
        for name, payload in files.items() if Path(name).suffix.casefold() in {".jpg", ".jpeg", ".png", ".webp"}]
    evidence["_asset_payloads"] = {name: base64.b64encode(payload).decode("ascii") for name, payload in files.items() if Path(name).suffix.casefold() in {".jpg", ".jpeg", ".png", ".webp"}}
    evidence["provenance"]["artifact_inventory"] = [{"path": name, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()} for name, payload in sorted(files.items())]
    return evidence


def load_evidence(path: str | Path, canonical_dir: str | Path | None = None) -> dict:
    """Load a verified ZIP, settled analysis directory or V4.4 decision document.

    ``canonical_dir`` is an explicit read-only input, never an auto-discovered
    Analyzer path. Its source hash must match before enriching partial evidence.
    """
    path = Path(path)
    if path.is_symlink():
        raise ValueError("Symlink não permitido")
    if path.is_file() and path.suffix.casefold() == ".zip":
        package = read_package(path)
        files, manifest, metadata = package["files"], package["manifest"], package["metadata"]
        analysis = _document(files, "analysis.json") if "analysis.json" in files else {"analysis_status": "partial"}
        evidence = _assemble(files, metadata, analysis, manifest, package["package_sha256"])
    elif path.is_dir():
        files, analysis, manifest = _directory_files(path)
        metadata = _document(files, "source/metadata.json") if "source/metadata.json" in files else analysis.get("metadata") or {}
        evidence = _assemble(files, metadata, analysis, manifest)
    elif path.is_file() and path.suffix.casefold() == ".json":
        if canonical_dir is None:
            raise ValueError("Decisões requerem canonical_dir explícito para localizar as evidências")
        if path.stat().st_size > MAX_BYTES:
            raise ValueError("Arquivo de decisões acima do limite")
        decisions = _json(path.read_bytes(), path.name)
        evidence = load_evidence(canonical_dir)
        compile_decisions(decisions, {"candidates": evidence["candidates"]}, evidence["metadata"], evidence["segments"])
        evidence["decisions"] = decisions
        evidence["availability"]["decisions"] = {"status": "available", "count": len(decisions.get("actions", [])), "sources": [path.name], "source_sha256": evidence["source"]["sha256"]}
        evidence["provenance"]["decision_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        canonical_dir = None
    else:
        raise ValueError("Selecione ZIP, diretório concluído ou decisões JSON")
    if canonical_dir is not None:
        canonical = load_evidence(canonical_dir)
        if canonical["source"]["sha256"] != evidence["source"]["sha256"]:
            raise ValueError("Hash canônico diverge do pacote")
        if canonical["source"]["duration"] != evidence["source"]["duration"]:
            raise ValueError("Duração canônica diverge do pacote")
        for component in _FILES:
            status, local_status = evidence["availability"][component]["status"], canonical["availability"][component]["status"]
            enrich_partial = status == local_status == "partial" and isinstance(canonical[component], list) and len(canonical[component]) > len(evidence[component])
            if component not in {"candidates", "shortlist", "review_queue", "decisions"} and status in {"missing", "partial", "not_measured", "stale"} and (local_status == "available" or enrich_partial):
                evidence[component] = deepcopy(canonical[component])
                evidence["availability"][component] = deepcopy(canonical["availability"][component])
                evidence["availability"][component]["sources"] = ["canonical/" + ref for ref in evidence["availability"][component]["sources"]]
        evidence["provenance"]["canonical_source_sha256"] = canonical["source"]["sha256"]
        evidence["provenance"]["canonical_analyzer_version"] = canonical["provenance"].get("analyzer_version")
        package_version = evidence["provenance"].get("analyzer_version")
        canonical_version = canonical["provenance"].get("analyzer_version")
        if package_version and canonical_version and package_version != canonical_version:
            evidence["provenance"]["canonical_build_mismatch"] = {"package_analyzer_version": package_version,
                "canonical_analyzer_version": canonical_version, "source_hash_match": True, "needs_human_review": True}
        evidence["documents"].update({"canonical/" + name: doc for name, doc in canonical["documents"].items()})
        evidence["_asset_payloads"].update({"canonical/" + name: value for name, value in canonical["_asset_payloads"].items()})
        evidence["asset_inventory"].extend({**row, "path": "canonical/" + row["path"]} for row in canonical["asset_inventory"])
    return evidence


def evidence_from_bundle(bundle: AnalysisBundle) -> dict:
    """Adapt the existing V4.4 bundle without following external decision paths.

    For completed input verification prefer ``load_evidence``. This bridge only
    describes already-loaded historical data and explicitly records that limit.
    """
    analysis = deepcopy(bundle.analysis)
    files = {"analysis.json": json.dumps(analysis, ensure_ascii=False).encode("utf-8")}
    aliases = {"segments": "transcript_segments.json", "words": "words.json", "scenes": "scenes.json", "timeline": "timeline.json",
        "speakers": "speakers.json", "speaker_person_mapping": "speaker_person_mapping.json", "people_observations": "people_observations.json",
        "questions_answers": "questions_answers.json", "frame_samples": "frame_samples.json", "director": "camera_director_timeline.json"}
    for attribute, name in aliases.items():
        rows = getattr(bundle, attribute, [])
        if rows:
            files[name] = json.dumps(rows, ensure_ascii=False).encode("utf-8")
    if bundle.second_package:
        files["editorial/candidate_catalog.json"] = json.dumps(bundle.second_package, ensure_ascii=False).encode("utf-8")
    if bundle.second_decisions:
        files["SECOND_CURATION_DECISIONS.json"] = json.dumps(bundle.second_decisions, ensure_ascii=False).encode("utf-8")
    evidence = _assemble(files, analysis.get("metadata") or {}, analysis, {}, None)
    evidence["provenance"]["input_verification"] = "already_loaded_bundle_not_reverified"
    return evidence
