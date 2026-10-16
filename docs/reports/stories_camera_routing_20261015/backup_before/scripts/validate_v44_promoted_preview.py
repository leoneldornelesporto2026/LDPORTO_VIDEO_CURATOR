"""Exercise the actual imported decision through preview, without granting approval."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ldporto_curator.config import load_config
from ldporto_curator.pipeline import Pipeline
from ldporto_curator.utils import write_json
root=Path(__file__).resolve().parents[1]
cfg=load_config(root/'config.yaml')
cfg['paths']['output_root']=str(root/'.cache/v44_validation/promoted_preview')
cfg['paths']['source_cache']=str(root.parent/'LDPORTO_VIDEO_ANALYZER/input/youtube/yZ78vCgiPZk')
cfg['render']['prefer_nvenc']=True
pipeline=Pipeline(cfg,root/'.cache/v44_validation/import_real')
mp4,folder=pipeline.test_one('yZ78vCgiPZk',1)
write_json(folder/'PROMOTED_PREVIEW_VALIDATION.json',{'execution_scope':'real_promoted_candidate_preview',
           'preview':str(mp4),'decision_source':'SECOND_CURATOR','approval_granted':False,
           'final_batch_rendered':False})
print(mp4,flush=True)
