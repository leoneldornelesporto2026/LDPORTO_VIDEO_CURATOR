"""Immutable editor snapshots; the authoritative command cursor lives in the plan.

Snapshots never grant review approval. Restoring an editor revision gives each
affected episode a fresh render generation, preserving old files as evidence.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from uuid import uuid4


HISTORY_KEY = "editing_history"
_RUNTIME = {
    "state", "status", "preview", "final", "approval", "human_approval",
    "approval_history", "artifact_history", "revision_nonce", "invalidation_reason",
    "approval_invalidated", "preview_duration", "rendered_duration", "duration_rendered",
    "duration_verified_by_ffprobe", "encoding_tolerance_seconds", "render_validation",
}


def history_for(plan):
    history = deepcopy(plan.get(HISTORY_KEY) or {
        "feature_version": "5.2.0", "entries": [], "cursor": 0, "abandoned_branches": [],
    })
    if (not isinstance(history.get("entries"), list)
            or isinstance(history.get("cursor"), bool)
            or not isinstance(history.get("cursor"), int)
            or not 0 <= history["cursor"] <= len(history["entries"])):
        raise ValueError("Histórico de edição inválido; preserve o projeto para inspeção")
    return history


def snapshot_payload(plan):
    return {key: deepcopy(value) for key, value in plan.items() if key != HISTORY_KEY}


def write_snapshot(directory, plan):
    payload = snapshot_payload(plan)
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(data).hexdigest()
    relative = Path("editing_history") / "snapshots" / (digest + ".json")
    path = Path(directory) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("Snapshot histórico alterado; original preservado para inspeção")
    else:
        pending = path.with_suffix(".pending.json")
        pending.write_bytes(data)
        pending.replace(path)
    return {"project_path": relative.as_posix(), "sha256": digest}


def read_snapshot(directory, reference):
    root = Path(directory).resolve()
    path = (root / reference["project_path"]).resolve()
    snapshot_root = root / "editing_history" / "snapshots"
    if not path.is_relative_to(snapshot_root) or not path.is_file() or path.is_symlink():
        raise ValueError("Snapshot histórico ausente ou fora do projeto")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != reference["sha256"]:
        raise ValueError("SHA256 do snapshot histórico divergente")
    return json.loads(data)


def episodes_by_id(plan):
    return {episode["episode_id"]: episode for key in ("episodes", "extras")
            for episode in plan.get(key, [])}


def affected_ids(before, after, explicit=()):
    previous, following = episodes_by_id(before), episodes_by_id(after)
    result = set(previous) ^ set(following)
    for identifier in previous.keys() & following.keys():
        left = {key: value for key, value in previous[identifier].items() if key not in _RUNTIME}
        right = {key: value for key, value in following[identifier].items() if key not in _RUNTIME}
        if left != right:
            result.add(identifier)
    return sorted(result | set(explicit))


def invalidate_episode(episode, originals=(), *, reason):
    """Retain stale evidence references, remove active gates, rotate signed nonce."""
    old = [deepcopy(episode), *map(deepcopy, originals)]
    artifacts, approvals = [], []
    for source in old:
        artifacts.extend(deepcopy(source.get("artifact_history") or []))
        approvals.extend(deepcopy(source.get("approval_history") or []))
        for kind in ("preview", "final"):
            if source.get(kind):
                artifacts.append({"kind": kind, "artifact": deepcopy(source[kind]),
                                  "status": "stale", "reason": reason})
        approval = source.get("human_approval") or source.get("approval")
        if approval:
            approvals.append({"approval": deepcopy(approval), "status": "stale", "reason": reason})

    def unique(rows):
        seen, result = set(), []
        for row in rows:
            token = json.dumps(row, sort_keys=True, ensure_ascii=False, allow_nan=False)
            if token not in seen:
                result.append(row)
                seen.add(token)
        return result

    episode["artifact_history"], episode["approval_history"] = unique(artifacts), unique(approvals)
    for key in ("preview", "final", "approval", "render_validation", "plan_hash"):
        episode.pop(key, None)
    rejected = episode.get("status") == "REJECTED" or episode.get("state") == "REJECTED"
    episode["status"] = episode["state"] = "REJECTED" if rejected else "REVIEW_REQUIRED"
    episode["human_approval"] = None
    episode["approval_invalidated"], episode["needs_review"] = True, True
    episode["invalidation_reason"] = reason
    episode["preview_duration"] = episode["rendered_duration"] = None
    episode["duration_verified_by_ffprobe"] = False
    episode.pop("encoding_tolerance_seconds", None)
    # episode_signature binds all unknown editorial fields automatically. Never
    # reuse a directory containing an approval from an earlier generation.
    episode["revision_nonce"] = uuid4().hex


def invalidate_plan(after, before, identifiers, *, reason):
    old = episodes_by_id(before)
    for identifier, episode in episodes_by_id(after).items():
        if identifier in identifiers:
            origins = []
            for origin in (identifier, episode.get("revision_of"), *episode.get("merged_episode_ids", [])):
                if origin in old:
                    origins.append(old[origin])
            # Undo may replace edited-window IDs or join split parts. Retain
            # artifacts from the removed affected proposals in the restored
            # episode's stale history, as well as in immutable disk revisions.
            if reason in {"editor_undo", "editor_redo"}:
                for origin in identifiers:
                    if origin in old and origin not in episodes_by_id(after):
                        origins.append(old[origin])
            invalidate_episode(episode, origins, reason=reason)
    after["status"], after["human_approval"] = "REVIEW_REQUIRED", None


def append_command(directory, before, after, *, action, identifiers, details=None):
    history = history_for(before)
    if history["cursor"] < len(history["entries"]):
        history.setdefault("abandoned_branches", []).append({
            "fork_cursor": history["cursor"],
            "entries": history["entries"][history["cursor"]:],
        })
        history["entries"] = history["entries"][:history["cursor"]]
    entry = {"command_id": uuid4().hex, "action": action, "affected_episode_ids": list(identifiers),
             "before": write_snapshot(directory, before), "after": write_snapshot(directory, after),
             "details": deepcopy(details or {})}
    history["entries"].append(entry)
    history["cursor"] = len(history["entries"])
    after[HISTORY_KEY] = history
    return entry


def restore_command(directory, current, *, redo=False):
    history = history_for(current)
    cursor = history["cursor"]
    if (redo and cursor >= len(history["entries"])) or (not redo and cursor <= 0):
        raise ValueError("Nenhuma ação para refazer" if redo else "Nenhuma ação para desfazer")
    entry = history["entries"][cursor if redo else cursor - 1]
    target = read_snapshot(directory, entry["after" if redo else "before"])
    if target.get("source_sha256") != current.get("source_sha256"):
        raise ValueError("Snapshot e projeto pertencem a fontes diferentes")
    affected = entry["affected_episode_ids"]
    current_by_id = episodes_by_id(current)
    # Approvals/previews acquired after this command remain active on episodes
    # that this undo/redo does not change.
    for key in ("episodes", "extras"):
        target[key] = [deepcopy(current_by_id[episode["episode_id"]])
                       if episode["episode_id"] not in affected and episode["episode_id"] in current_by_id
                       else episode for episode in target.get(key, [])]
    action = "redo" if redo else "undo"
    invalidate_plan(target, current, affected, reason="editor_" + action)
    history["cursor"] = cursor + (1 if redo else -1)
    target[HISTORY_KEY] = history
    target["audit_trail"] = deepcopy(current.get("audit_trail") or [])
    target["audit_trail"].append({"action": action, "command_id": entry["command_id"],
                                  "affected_episode_ids": affected, "approval_restored": False})
    return target
