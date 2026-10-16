"""Cria uma NOVA revisão V5.2 de Stories com câmera baseada na fonte real.

Nunca substitui o projeto anterior. --verificar é somente leitura.
--criar executa somente micropercepção facial LOCAL do MP4 original, sem Qwen.
--renderizar só prévias da revisão criada (aprovação humana permanece pendente).
"""
from __future__ import annotations
import argparse
from copy import deepcopy
from pathlib import Path
from uuid import uuid4
import hashlib
import json
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def digest(p):
    h = hashlib.sha256()
    with Path(p).open('rb') as f:
        for block in iter(lambda:f.read(4*1024*1024),b''):
            h.update(block)
    return h.hexdigest()


def prepare(parent, source, manifest):
    from ldporto_curator.series_workflow import _verified_supplemental_words
    if not source.is_file() or source.is_symlink():
        raise ValueError('MP4 original ausente ou link; abortado')
    sha = digest(source)
    if sha != parent.evidence['source']['sha256'] or sha != parent.plan['source_sha256']:
        raise ValueError('SHA256 original diverge do projeto; abortado')
    for name in ('series_index.json','evidence.json','source_manifest.json'):
        if (parent.directory/name).is_symlink() or not (parent.directory/name).is_file():
            raise ValueError('Arquivo de evidência ausente ou link: '+name)
    ep = parent.episodes()
    if len(ep) != 16 or len({e['episode_id'] for e in ep}) != 16:
        raise ValueError('16 episódios originais distintos são exigidos')
    if any(not 0 < (e['source_end']-e['source_start']) <= 60.000001 for e in ep):
        raise ValueError('Duração de Story fora dos 60 segundos')
    evidence = deepcopy(parent.evidence)
    old_ids = {w.get('word_id') for w in evidence.get('words') or []}
    source_s06 = [s for s in evidence.get('segments') or [] if s.get('segment_id') == 'SEG_00163']
    has_s06_words = any(w.get('segment_id')=='SEG_00163' for w in evidence.get('words') or [])
    added=[]
    if source_s06 and not has_s06_words:
        if not manifest or not manifest.is_file():
            raise ValueError('Story 6 precisa do manifesto original WORD_EVIDENCE_SEG00163.json')
        added, audit = _verified_supplemental_words(manifest, evidence)
        if len(added) != 12 or {w.get('segment_id') for w in added} != {'SEG_00163'}:
            raise ValueError('Evidências suplementares insuficientes ou não exclusivas do SEG_00163')
        if old_ids.intersection(w['word_id'] for w in added):
            raise ValueError('Palavras suplementares duplicadas')
        evidence['words'].extend(deepcopy(added))
        evidence['words'].sort(key=lambda w:(w['start'],w['end'],w.get('word_id','')))
        evidence.setdefault('provenance', {})['supplemental_word_evidence'] = audit
    return evidence, sha, added


def make_camera_reviews(parent, source, manifest, *, create=False, fps=5):
    from ldporto_curator.series_workflow import SeriesProject, _canonical_hash
    from ldporto_curator.micro_perception import inspect_clip
    from ldporto_curator.camera_refinement import refine_camera_plan
    from ldporto_curator.smart_composition import improve_camera_plan
    from ldporto_curator.subtitle_presets import write_episode_subtitles
    from ldporto_curator.utils import write_json
    evidence, sha, added = prepare(parent, source, manifest)
    checked = {'status':'SOURCE_AND_STORIES_VERIFIED','episodes':len(parent.episodes()),
               'source_sha256':sha,'added_words':len(added),'prior_approvals_imported':False,
               'existing_mp4_modified':False,'new_analysis_full_video':False}
    if not create:
        return checked
    destination = parent.directory.parent/('camera_stories_' + uuid4().hex[:16])
    if destination.exists():
        raise ValueError('Destino já existe')
    from ldporto_curator.editing_history import invalidate_episode
    from ldporto_curator.camera_geometry import base_size
    # The camera is newly proposed from LOCAL vision; no historical title,
    # transcript, publication approval or Reel is rewritten.
    draft = deepcopy(parent.plan)
    draft['parent_plan_id'] = parent.plan['plan_id']
    draft['plan_id'] = str(parent.plan['plan_id'])+'_CAMERA_REVIEW_'+uuid4().hex[:12]
    draft['human_approval'] = None
    draft['status'] = 'REVIEW_REQUIRED'
    draft['camera_recovery'] = {'schema':'LDP_STORY_CAMERA_LOCAL_REVIEW_V1',
        'parent_project':str(parent.directory),'parent_evidence_sha256':digest(parent.directory/'evidence.json'),
        'parent_source_manifest_sha256':digest(parent.directory/'source_manifest.json'),
        'source_sha256':sha,'approved':False,'qwen_used':False,'new_analyzer_run':False}
    camcfg = deepcopy(parent.cfg.get('camera_v44', {}))
    camcfg.setdefault('director_style', {})['min_hold_seconds'] = 2.0
    metadata = evidence.get('metadata') or evidence['source']
    total_crop = 0
    import shutil
    from tempfile import TemporaryDirectory
    with TemporaryDirectory(prefix='ldporto_camera_review_') as scratch:
        scratch = Path(scratch)
        for index, row in enumerate([*draft.get('episodes',[]), *draft.get('extras',[])], 1):
            e = row
            interval={'source_start': e['source_start'], 'source_end': e['source_end']}
            print(f'VISUAL {index}/16 {e["episode_id"]}',flush=True)
            micro = inspect_clip(source, interval, scratch/e['episode_id'],
                {'sample_fps':fps,'max_clip_seconds':60.1,
                 'face_model':str(ROOT.parent/'LDPORTO_VIDEO_ANALYZER'/'models'/'face_detection_yunet_2023mar.onnx')})
            # SOURCE_PRESERVE in the inherited proposals is not taken as
            # evidence that the whole shot needs blur; measured geometry wins
            # only where every safety check permits a crop.
            plan = refine_camera_plan(micro, metadata,e['source_start'],e['source_end'],camcfg,None)
            plan = improve_camera_plan(plan,micro,metadata,e['source_start'],e['source_end'],camcfg)
            crop = sum(r.get('mode')=='crop' for r in plan.get('segments',[]))
            total_crop += crop
            print(f'CAMERA: crop={crop}, blur={sum(r.get("mode")=="full_frame_blur" for r in plan.get("segments",[]))}',flush=True)
            invalidate_episode(e,reason='new_camera_visual_review')
            for key in ('preview','final','approval','human_approval','caption_revision','caption_timeline','plan_hash'):
                e.pop(key,None)
            e['camera_plan']=plan
            e['subtitle_preset']='LDP_REELS_KARAOKE'
            e['subtitle_overrides']={}
            e['state']='REVIEW_REQUIRED'
            e['status']='REVIEW_REQUIRED'
            # Validate both physical sizes, including the recovered Story 6.
            with TemporaryDirectory(prefix='ldporto_caption_check_') as capdir:
                result = write_episode_subtitles(evidence,e,Path(capdir),preset='LDP_REELS_KARAOKE',width=540,height=960)
                if result['sync'].get('renderable') is not True:
                    raise ValueError('Legenda não cabe no episódio '+e['episode_id'])
                fin = write_episode_subtitles(evidence,e,Path(capdir)/'final',preset='LDP_REELS_KARAOKE',width=1080,height=1920,
                    canonical_timeline=result['sync'])
                if fin['sync'].get('renderable') is not True:
                    raise ValueError('Legenda final não cabe no episódio '+e['episode_id'])
            (scratch / 'evidence').mkdir(exist_ok=True)
            write_json(scratch / 'evidence' / (e['episode_id']+'_micro.json'),micro)
        if not total_crop:
            raise ValueError('ZERO_EFFECTIVE_VERTICAL_CROPS: detector sem evidência suficiente; nenhum projeto criado')
        # Verify the source project did not change while sampling.
        if sha != digest(source) or draft['camera_recovery']['parent_evidence_sha256'] != digest(parent.directory/'evidence.json') or draft['camera_recovery']['parent_source_manifest_sha256'] != digest(parent.directory/'source_manifest.json'):
            raise ValueError('Fontes mudaram durante o refinamento; nenhum projeto criado')
        derived = SeriesProject(destination,parent.cfg)
        derived.evidence, derived.plan = evidence, draft
        destination.mkdir(parents=True,exist_ok=False)
        derived.save()
        shutil.copytree(scratch/'evidence',destination/'camera_evidence')
        write_json(destination/'CAMERA_AUDIT.json',{'schema':'LDP_CAMERA_REVIEW_V1',
            'parent_project':str(parent.directory),'source_sha256':sha,'crop_segments':total_crop,
            'approved':False,'all_16_captions_checked':True,'added_words':len(added)})
    return {**checked,'status':'NEW_UNAPPROVED_STORY_CAMERA_REVIEW','destination':str(destination),
            'crop_segments':total_crop,'all_16_captions_checked':True}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--projeto-stories',type=Path,required=True)
    parser.add_argument('--midia',type=Path,required=True)
    parser.add_argument('--manifesto-palavras',type=Path)
    parser.add_argument('--criar',action='store_true')
    parser.add_argument('--renderizar',action='store_true')
    parser.add_argument('--nova-revisao',type=Path)
    args=parser.parse_args(argv)
    from ldporto_curator.series_workflow import SeriesProject
    if args.renderizar:
        if args.criar or not args.nova_revisao:
            parser.error('--renderizar exige --nova-revisao e não aceita --criar junto')
        p = SeriesProject(args.nova_revisao)
        audit=json.loads((p.directory/'CAMERA_AUDIT.json').read_text(encoding='utf-8'))
        if audit.get('approved') is not False or audit['source_sha256'] != digest(args.midia):
            raise ValueError('Revisão de câmera sem vínculo de mídia válido')
        for i,e in enumerate(p.episodes(),1):
            print('PREVIEW',i,len(p.episodes()),e['episode_id'],flush=True)
            print(p.render(e['episode_id'], args.midia, preview=True),flush=True)
        print('STATUS: 16 prévias para revisão humana; NENHUMA aprovação automática')
    else:
        parent=SeriesProject(args.projeto_stories)
        result=make_camera_reviews(parent,args.midia,args.manifesto_palavras,create=args.criar)
        print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0

if __name__=='__main__':
    raise SystemExit(main())
