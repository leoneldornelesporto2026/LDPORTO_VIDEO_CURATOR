"""Recupera apenas o Story S02/3 via palavras originais verificadas.

Nenhuma reanálise, ASR, Qwen, edição in-place, aprovação ou render em lote.
Por padrão verifica tudo e não cria/edita arquivo algum.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import shutil
from pathlib import Path
import sys
import tempfile
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SOURCE_SHA = "b2958122415980a8afff4f77c23ead3c31c00345e5df0ab460995eb731efb00f"
EPISODE_ID = "PROP_f5106b486d19e3c2e8be43ca"
MISSING_SEGMENT = "SEG_00163"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def check_case(project, manifest, episode_id=EPISODE_ID):
    """Valida fonte, evidência lexical e layout antes de criar revisão."""
    from ldporto_curator.series_workflow import _verified_supplemental_words
    from ldporto_curator.subtitle_presets import write_episode_subtitles

    if project.evidence.get("source", {}).get("sha256") != SOURCE_SHA:
        raise ValueError("SHA256 da fonte do projeto não é o original analisado. BLOQUEADO.")
    if project.plan.get("source_sha256") != SOURCE_SHA:
        raise ValueError("SHA256 do plano é diferente da fonte. BLOQUEADO.")
    episode = project.episode(episode_id)
    if not (0 < episode["duration"] <= 60):
        raise ValueError("Duração do Story fora dos 60s")
    segments = [s for s in project.evidence.get("segments", [])
                if s.get("segment_id") == MISSING_SEGMENT and
                s["end"] > episode["source_start"] and s["start"] < episode["source_end"]]
    if len(segments) != 1:
        raise ValueError("SEG_00163 não pertence ao Story escolhido ou está duplicado")
    source_words = project.evidence.get("words", []) or []
    already = [w for w in source_words if w.get("segment_id") == MISSING_SEGMENT]
    if already:
        from ldporto_curator.subtitle_presets import _align_words
        valid, reason = _align_words(segments[0], source_words)
        if reason or len(valid) != len(already):
            raise ValueError("Segmento já tem palavras, mas seu alinhamento é inconsistente: " + str(reason))
        supplemental, recovery = [], {"status": "already_verified_in_project", "added_word_ids": []}
    else:
        supplemental, recovery = _verified_supplemental_words(manifest, project.evidence)
        if not supplemental or {w.get("segment_id") for w in supplemental} != {MISSING_SEGMENT}:
            raise ValueError("Recuperação não devolveu somente o segmento original esperado")
    candidate = deepcopy(project.evidence)
    candidate.setdefault("words", []).extend(deepcopy(supplemental))
    candidate["words"].sort(key=lambda w: (w["start"], w["end"], w.get("word_id", "")))
    with tempfile.TemporaryDirectory(prefix="ldporto_story06_check_") as tmp:
        result = write_episode_subtitles(candidate, episode, Path(tmp),
                                         preset="LDP_REELS_KARAOKE", width=540, height=960)
        meta = result["sync"]
        if not meta.get("renderable") or meta.get("alignment") != "word":
            raise ValueError("Ainda existe bloco sem timestamp válido/área segura: " +
                             json.dumps(meta.get("diagnostics", []), ensure_ascii=False)[:1100])
        events = meta.get("events", [])
        if not events or any(e.get("method") != "word" or not e.get("ass_event_written")
                             or not e["layout"].get("fits_safe_box") or
                             len(e["layout"].get("visual_lines", [])) > 2 for e in events):
            raise ValueError("Prévia contém evento sem alinhamento ou fora da caixa")
        if meta.get("visual_behavior") != "yellow_phrase_cumulative_white_at_measured_onset":
            raise ValueError("Preset karaoke não foi aplicado")
        from ldporto_curator.subtitle_presets import write_episode_subtitles as write
        final = write(candidate, episode, Path(tmp) / "final", preset="LDP_REELS_KARAOKE",
                      width=1080, height=1920, canonical_timeline=meta)
        if not final["sync"].get("renderable") or final["sync"].get("canonical_timeline_sha256") != meta.get("canonical_timeline_sha256"):
            raise ValueError("Render final não reutiliza a mesma timeline canônica")
    return episode, recovery, {"episode_id": episode_id, "status": "SAFE_TO_DERIVE",
        "source_sha256": SOURCE_SHA, "added_words": len(supplemental),
        "caption_events": len(events), "word_ids": sum(len(e["word_ids"]) for e in events),
        "max_lines": max(len(e["layout"]["visual_lines"]) for e in events),
        "renderable_preview_540x960": True, "renderable_final_1080x1920": True,
        "human_audio_review": "REQUIRED", "approved": False, "qwen_used": False}



def derive_unpreviewed_story(parent, destination, manifest_path):
    """Create a new *unapproved* Story 6 project when no prior preview exists.

    A Story that failed while composing subtitles has no signed camera and no
    historical preview assets. Do not claim either exists; freeze a newly
    computed conservative camera in a separate, review-only copy instead.
    Verified original words are the only permitted evidence enrichment.
    """
    from ldporto_curator.series_workflow import (SeriesProject, conservative_camera,
        _verified_supplemental_words, _canonical_hash)
    from ldporto_curator.editing_history import invalidate_episode
    from ldporto_curator.utils import write_json

    destination = Path(destination).resolve()
    if destination.exists() or destination.is_relative_to(parent.directory):
        raise ValueError("Nova revisão exige pasta inédita fora do projeto original")
    before = {name: digest(parent.directory / name)
              for name in ("series_index.json", "evidence.json", "source_manifest.json")}
    if parent.episode(EPISODE_ID).get("preview") or parent.episode(EPISODE_ID).get("final"):
        raise ValueError("Já há prévia/final: esta via somente serve ao episódio sem preview; valide a revisão histórica")
    if parent.evidence.get("source", {}).get("sha256") != SOURCE_SHA or parent.plan.get("source_sha256") != SOURCE_SHA:
        raise ValueError("SHA256 da fonte e do plano não correspondem ao original")

    supplements, audit = _verified_supplemental_words(manifest_path, parent.evidence)
    if not supplements or {w.get("segment_id") for w in supplements} != {MISSING_SEGMENT}:
        raise ValueError("Sem evidências suplementares verificadas e exclusivas do SEG_00163")

    evidence = deepcopy(parent.evidence)
    evidence.setdefault("words", []).extend(deepcopy(supplements))
    evidence["words"].sort(key=lambda w: (w["start"], w["end"], w.get("word_id", "")))
    evidence.setdefault("provenance", {})["supplemental_word_evidence"] = deepcopy(audit)

    episode = deepcopy(parent.episode(EPISODE_ID))
    # No source camera is being invented: conservative_camera uses already
    # captured geometry or retains full-frame blur when focus is uncertain.
    camera = deepcopy(episode.get("camera_plan")) if episode.get("camera_plan") else None
    if camera is None:
        camera = conservative_camera(evidence, episode, parent.cfg)
        camera_provenance = "new_conservative_camera_not_historically_approved"
    else:
        if not isinstance(camera, dict) or not camera.get("segments"):
            raise ValueError("Plano de câmera existente incompleto")
        camera_provenance = "original_unapproved_camera_copied"
    if not isinstance(camera, dict) or not camera.get("segments"):
        raise ValueError("Câmera conservadora inválida")

    invalidate_episode(episode, reason="new_unapproved_story06_caption_recovery")
    for key in ("preview", "final", "approval", "human_approval", "caption_revision",
                "caption_timeline", "plan_hash"):
        episode.pop(key, None)
    episode["camera_plan"] = camera
    episode["subtitle_preset"] = "LDP_REELS_KARAOKE"
    episode["subtitle_overrides"] = {}
    episode["state"] = "REVIEW_REQUIRED"
    episode["status"] = "REVIEW_REQUIRED"
    episode["needs_review"] = True

    plan = deepcopy(parent.plan)
    plan.pop("caption_revision", None)
    plan.pop("editing_history", None)  # old snapshots remain with parent
    plan["episodes"] = [episode] if any(e["episode_id"] == EPISODE_ID for e in parent.plan.get("episodes", [])) else []
    plan["extras"] = [episode] if not plan["episodes"] else []
    plan["parent_plan_id"] = parent.plan.get("plan_id")
    plan["plan_id"] = str(parent.plan.get("plan_id", "STORIES")) + "_STORY06_REVIEW_" + uuid4().hex[:12]
    plan["status"] = "REVIEW_REQUIRED"
    plan["human_approval"] = None
    plan["story06_recovery"] = {
        "schema": "LDP_STORY06_UNPREVIEWED_RECOVERY_V1", "parent_project": str(parent.directory),
        "parent_hashes": before, "source_sha256": SOURCE_SHA,
        "camera_provenance": camera_provenance, "camera_sha256": _canonical_hash(camera),
        "evidence_enrichment": deepcopy(audit), "added_word_ids": [w["word_id"] for w in supplements],
        "human_audio_review": "REQUIRED", "human_visual_review": "REQUIRED",
        "approved": False, "qwen_executed": False,
        "historical_camera_or_preview_claimed": False,
        "render_settings": deepcopy(parent.cfg),
        "render_settings_sha256": _canonical_hash(parent.cfg),
    }
    plan.setdefault("audit_trail", []).append({"action": "new_story06_review_without_historical_preview",
        "camera_provenance": camera_provenance, "automatic_approval": False})

    # No writes to source project. All output lives in a brand-new directory.
    project = SeriesProject(destination, parent.cfg)
    project.evidence, project.plan = evidence, plan
    project.save()
    snapshot_dir = destination / "parent_snapshot"
    snapshot_dir.mkdir(parents=True, exist_ok=False)
    for name, expected in before.items():
        target = snapshot_dir / name
        shutil.copy2(parent.directory / name, target)
        if digest(target) != expected or digest(parent.directory / name) != expected:
            raise RuntimeError("A fonte foi alterada durante a revisão: " + name)
    write_json(destination / "CAMERA_REVIEW_REQUIRED.json", {
        "camera_plan": camera, "camera_provenance": camera_provenance,
        "camera_sha256": _canonical_hash(camera), "approved": False,
        "source_sha256": SOURCE_SHA,
    })
    result = project.prepare_caption_timeline(EPISODE_ID)
    sync = result["sync"]
    if (not sync.get("renderable") or sync.get("alignment") != "word"
            or sync.get("visual_behavior") != "yellow_phrase_cumulative_white_at_measured_onset"
            or any(not e.get("layout", {}).get("fits_safe_box") or
                   len(e.get("layout", {}).get("visual_lines", [])) > 2
                   for e in sync.get("events", []))):
        raise ValueError("A timeline derivada não passou nos gates; projeto provisório preservado para inspeção")
    return project, camera_provenance

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--projeto", type=Path, required=True, help="Pasta original dos Stories V5.2")
    parser.add_argument("--manifesto", type=Path, required=True, help="WORD_EVIDENCE_SEG00163.json")
    parser.add_argument("--destino", type=Path, default=None, help="Nova pasta de revisão, não existente")
    parser.add_argument("--aplicar", action="store_true", help="Criar nova revisão, sem alterar origem")
    parser.add_argument("--renderizar-preview", action="store_true", help="Renderizar somente Story 6 na nova revisão")
    parser.add_argument("--midia", type=Path, default=None, help="Original do Analyzer, SHA256 exato")
    args = parser.parse_args(argv)
    if args.renderizar_preview and not args.aplicar:
        parser.error("--renderizar-preview exige --aplicar")
    from ldporto_curator.series_workflow import SeriesProject
    parent = SeriesProject(args.projeto)
    files = [args.projeto / name for name in ("series_index.json", "evidence.json", "source_manifest.json")]
    hashes = {str(p): digest(p) for p in files}
    episode, recovery, report = check_case(parent, args.manifesto)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("EVIDÊNCIA:", recovery.get("status", "SHA256 + ASR chunk verificados"))
    if not args.aplicar:
        print("VERIFICACAO OK: nenhuma revisão criada. Use --aplicar para criar uma revisão separada.")
        return 0
    destination = args.destino or (args.projeto.parent / ("story06_caption_recovered_" + uuid4().hex[:12]))
    if destination.exists():
        raise ValueError("Pasta de revisão já existe; não sobrescrever: " + str(destination))
    if args.renderizar_preview:
        if args.midia is None or not args.midia.is_file() or digest(args.midia) != SOURCE_SHA:
            raise ValueError("MP4 original ausente/SHA256 diferente; não gerar revisão")
    historical = parent.episode(EPISODE_ID)
    if historical.get("preview"):
        recovered = parent.derive_caption_revision(destination, episode_ids={EPISODE_ID},
            word_evidence=(args.manifesto if report["added_words"] else None),
            subtitle_preset="LDP_REELS_KARAOKE")
        camera_provenance = "historical_camera_verified_and_frozen"
    else:
        # Story 6 never reached preview: don't demand nonexistent frozen assets.
        # Create a new unapproved, conservative camera in an isolated revision.
        recovered, camera_provenance = derive_unpreviewed_story(parent, destination, args.manifesto)
    meta = recovered.prepare_caption_timeline(EPISODE_ID)["sync"]
    print("CAMERA:", camera_provenance, "| revisão visual obrigatória")
    if not meta.get("renderable") or meta.get("alignment") != "word":
        raise ValueError("Revisão derivada requer inspeção. Projeto original não foi modificado.")
    if args.renderizar_preview:
        print("RENDERIZANDO somente o Story S02 Parte 3/5 na nova revisão...")
        preview = recovered.render(EPISODE_ID, args.midia, preview=True)
        print("PREVIEW:", preview)
    for file, expected in hashes.items():
        if digest(Path(file)) != expected:
            raise RuntimeError("ALERTA: arquivo da origem mudou durante a operação: " + file)
    print("NOVA_REVISAO:", destination)
    print("STATUS: precisa assistir à prévia e aprovar manualmente. Não renderize o lote automaticamente.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("BLOQUEADO:", exc, file=sys.stderr)
        sys.exit(2)
