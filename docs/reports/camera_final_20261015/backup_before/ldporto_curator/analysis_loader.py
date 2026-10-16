from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from .utils import load_json, youtube_id

@dataclass
class AnalysisBundle:
    root: Path
    video_id: str
    analysis: dict
    insights: dict
    editorial: list
    review: dict
    segments: list
    words: list
    captions: list
    timeline: list
    scenes: list
    people_observations: list
    frame_samples: list
    silences: list
    speakers: list
    speaker_person_mapping: list
    questions_answers: list
    second_package: dict = field(default_factory=dict)
    second_decisions: dict = field(default_factory=dict)
    director: list = field(default_factory=list)

    @property
    def source(self):
        return ((self.analysis.get("metadata") or {}).get("source") or {})

def _candidate_dirs(analysis_root: Path):
    if not analysis_root.exists(): return []
    return [p.parent for p in analysis_root.rglob("analysis.json")]

def find_analysis(analysis_root: str|Path, source_or_id: str):
    root=Path(analysis_root)
    target=youtube_id(source_or_id)
    found=[]
    for d in _candidate_dirs(root):
        a=load_json(d/'analysis.json',{}) or {}
        src=((a.get('metadata') or {}).get('source') or {})
        sid=src.get('id') or youtube_id(src.get('url'))
        if target and sid==target:
            found.append((d.stat().st_mtime,d))
        elif not target and source_or_id and (src.get('url')==source_or_id):
            found.append((d.stat().st_mtime,d))
    if not found:
        raise FileNotFoundError("Este vídeo ainda não possui análise. Execute primeiro o L.D.PORTO VIDEO ANALYZER.")
    return sorted(found, reverse=True)[0][1]

def load_bundle(path: str|Path):
    d=Path(path)
    a=load_json(d/'analysis.json',{}) or {}
    insights=load_json(d/'llm_insights.json',{}) or {}
    va=load_json(d/'video_analysis.json',{}) or {}
    src=((a.get('metadata') or {}).get('source') or {})
    vid=src.get('id') or youtube_id(src.get('url')) or d.name
    decision_ref = load_json(d / 'second_curation_decision_ref.json', {}) or {}
    return AnalysisBundle(
      root=d, video_id=vid, analysis=a, insights=insights,
      editorial=load_json(d/'editorial_moments.json',[]) or [],
      review=load_json(d/'ollama_editorial_review.json',{}) or {},
      segments=(a.get('transcript_segments') or load_json(d/'transcript_segments.json',[]) or insights.get('segments') or []),
      words=load_json(d/'words.json',[]) or [],
      captions=load_json(d/'caption_segments.json',[]) or (a.get('transcript_segments') if a.get('second_curation_import') else []) or [],
      timeline=load_json(d/'timeline.json',[]) or [],
      scenes=load_json(d/'scenes.json',[]) or [],
      people_observations=load_json(d/'people_observations.json',[]) or [],
      frame_samples=((va.get('frame_samples') or [])),
      silences=(a.get('silences') or insights.get('silences') or []),
      speakers=load_json(d/'speakers.json',[]) or [],
      speaker_person_mapping=load_json(d/'speaker_person_mapping.json',[]) or [],
      questions_answers=load_json(d/'questions_answers.json',[]) or [],
      second_package=load_json(d/'editorial/candidate_catalog.json',{}) or load_json(d/'second_curation_package.json',{}) or {},
      second_decisions=load_json(decision_ref['path'], {}) if decision_ref.get('path') else load_json(d/'SECOND_CURATION_DECISIONS.json',{}) or {},
      director=load_json(d/'camera_director_timeline.json',[]) or [],
    )
