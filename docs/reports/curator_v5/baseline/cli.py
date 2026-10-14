from pathlib import Path
import argparse
from ldporto_curator.config import load_config
from ldporto_curator.pipeline import Pipeline
ROOT=Path(__file__).resolve().parent
p=argparse.ArgumentParser(); p.add_argument('source'); p.add_argument('--config',default=str(ROOT/'config.yaml'))
g=p.add_mutually_exclusive_group(required=True); g.add_argument('--curate',action='store_true'); g.add_argument('--test-one',type=int,metavar='RANK'); g.add_argument('--approve-test',action='store_true'); g.add_argument('--render-all',action='store_true'); g.add_argument('--import-second-curation',action='store_true')
p.add_argument('--source-file', help='Arquivo original para rehydration, validado por SHA256')
p.add_argument('--download-source', action='store_true', help='Baixar mídia novamente sem reexecutar a análise')
a=p.parse_args(); cfg=load_config(a.config)
cfg['source_media']={'path':a.source_file,'allow_download':a.download_source}
pipe=Pipeline(cfg,ROOT,print)
if a.import_second_curation:
    import json
    from ldporto_curator.second_curation_import import import_second_curation
    print(json.dumps(import_second_curation(a.source, ROOT, cfg['paths']['analysis_root']), ensure_ascii=False, indent=2))
elif a.curate: pipe.curate_only(a.source)
elif a.test_one: pipe.test_one(a.source,a.test_one)
elif a.approve_test: pipe.approve_test(a.source)
elif a.render_all: pipe.render_all(a.source,preview=False)
