"""Bounded real-media camera validation, writes only to its validation folder."""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ldporto_curator.micro_perception import inspect_clip
from ldporto_curator.camera_refinement import refine_camera_plan
from ldporto_curator.analysis_loader import AnalysisBundle
from ldporto_curator.render import render_clip
from ldporto_curator.utils import write_json
from ldporto_curator.approval import file_hash
import cv2
import yaml

root = Path(__file__).resolve().parents[1]
analyzer = root.parent / 'LDPORTO_VIDEO_ANALYZER'
video = analyzer / 'input/youtube/yZ78vCgiPZk/yZ78vCgiPZk.mp4'
out = root / '.cache/v44_validation/real_camera'
cfg = yaml.safe_load((root / 'config.yaml').read_text(encoding='utf-8'))
cfg['render']['prefer_nvenc'] = False
metadata = {'width': 1920, 'height': 1080, 'fps': 30, 'duration': 8245.014}
bundle = AnalysisBundle(out, 'V44_REAL_SHORT', {'metadata':metadata}, {}, [], {}, [], [], [], [], [], [], [], [], [], [], [])
rows = []
for label, start in [('interview', 3200.), ('commercial_gc', 7059.), ('story_payoff', 7800.)]:
    folder = out / label
    clip = {'clip_id':label, 'rank':1, 'source_start':start, 'source_end':start+8, 'duration':8.,
            'title_text':'Validação V4.4', 'title_style':'neutral', 'subtitle_plan':{}}
    micro = inspect_clip(video, clip, folder/'micro_cache')
    plan = refine_camera_plan(micro, metadata, start, start+8)
    clip['camera_plan'] = plan
    write_json(folder/'clip_micro_perception.json', micro)
    write_json(folder/'FINAL_CAMERA_PLAN_V44.json', plan)
    files=[]
    for preview in (True, False):
        mp4 = render_clip(bundle, clip, video, folder, cfg, preview=preview)
        capture=cv2.VideoCapture(str(mp4))
        for t in (1., 4., 6.5):
            capture.set(cv2.CAP_PROP_POS_MSEC, t*1000)
            ok, frame=capture.read()
            if not ok:
                raise RuntimeError(f'Undecodable rendered frame: {mp4} at {t}')
            if t == 4:
                cv2.imwrite(str(folder/('preview_frame.jpg' if preview else 'final_frame.jpg')), frame)
        capture.release()
        files.append({'path':str(mp4), 'sha256':file_hash(mp4), 'preview':preview})
    rows.append({'label':label, 'bounds':[start,start+8], 'micro_sample_count':micro['sample_count'],
                 'local_tracklets':micro['raw_tracklets'], 'face_observations':len(micro['observations']),
                 'micro_status':micro['status'], 'diagnostics':plan['diagnostics'], 'renders':files})
    print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
write_json(out/'REAL_CAMERA_VALIDATION.json', {'execution_scope':'real_short_clips', 'source_sha256':file_hash(video), 'clips':rows,
          'identity_accuracy':'not_measured', 'visual_review':'pending', 'no_full_benchmark_credit':True})
