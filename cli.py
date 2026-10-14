from pathlib import Path
import argparse
from ldporto_curator.config import load_config
from ldporto_curator.pipeline import Pipeline
ROOT=Path(__file__).resolve().parent
p=argparse.ArgumentParser(); p.add_argument('source'); p.add_argument('--config',default=str(ROOT/'config.yaml'))
g=p.add_mutually_exclusive_group(required=True); g.add_argument('--curate',action='store_true'); g.add_argument('--test-one',type=int,metavar='RANK'); g.add_argument('--approve-test',action='store_true'); g.add_argument('--render-all',action='store_true'); g.add_argument('--import-second-curation',action='store_true')
g.add_argument('--plan-series', action='store_true', help='Criar propostas V5 sem shortlist/aprovação automática')
g.add_argument('--dossier-only', action='store_true', help='Exportar evidências disponíveis sem render')
g.add_argument('--preview-episode', metavar='EPISODE_ID')
g.add_argument('--approve-episode', metavar='EPISODE_ID')
g.add_argument('--render-approved-series', action='store_true')
g.add_argument('--export-series', action='store_true')
p.add_argument('--mode', default='SERIE_CRONOLOGICA', choices=['SERIE_CRONOLOGICA','MELHORES_MOMENTOS','MOMENTOS_INDEPENDENTES','COMBINADO','DOSSIER_ONLY'])
p.add_argument('--duration-preset', default='auto_under_90', choices=['auto_under_90','under_30','from_30_to_59','from_60_to_89','from_90_to_180','from_180_to_300','from_300_to_600','from_600_to_900'])
p.add_argument('--canonical-analysis', help='Snapshot concluído opcional, com hash da fonte correspondente')
p.add_argument('--human-reviewed', action='store_true', help='Registrar ação humana após assistir à prévia')
p.add_argument('--accept-duration-deviation', action='store_true', help='Aceitar explicitamente proposta fora da faixa')
p.add_argument('--source-file', help='Arquivo original para rehydration, validado por SHA256')
p.add_argument('--download-source', action='store_true', help='Baixar mídia novamente sem reexecutar a análise')
a=p.parse_args(); cfg=load_config(a.config)
cfg['source_media']={'path':a.source_file,'allow_download':a.download_source}
pipe=Pipeline(cfg,ROOT,print)
if a.plan_series or a.dossier_only:
    from ldporto_curator.evidence_source import load_evidence
    from ldporto_curator.series_workflow import SeriesProject
    evidence = load_evidence(a.source, canonical_dir=a.canonical_analysis)
    project = SeriesProject.create(evidence, cfg['paths']['output_root'], cfg, a.duration_preset,
        'DOSSIER_ONLY' if a.dossier_only else a.mode)
    print('Projeto V5:', project.directory)
    print('Propostas para revisão:', len(project.episodes()))
    print('Dossiê:', project.export())
elif a.preview_episode or a.approve_episode or a.render_approved_series or a.export_series:
    from ldporto_curator.series_workflow import SeriesProject
    project = SeriesProject(a.source, cfg)
    if not project.plan:
        p.error('source deve ser a pasta do projeto V5 que contém series_index.json')
    if a.preview_episode or a.render_approved_series:
        if not a.source_file:
            p.error('--source-file deve apontar para a mídia original')
        print(project.render(a.preview_episode, a.source_file) if a.preview_episode else project.render_approved(a.source_file))
    elif a.approve_episode:
        project.approve(a.approve_episode, human_reviewed=a.human_reviewed,
            duration_deviation_accepted=a.accept_duration_deviation)
        print('Preview aprovado por ação humana. Publicação continua pendente.')
    else:
        print(project.export())
elif a.import_second_curation:
    import json
    from ldporto_curator.second_curation_import import import_second_curation
    print(json.dumps(import_second_curation(a.source, ROOT, cfg['paths']['analysis_root']), ensure_ascii=False, indent=2))
elif a.curate: pipe.curate_only(a.source)
elif a.test_one: pipe.test_one(a.source,a.test_one)
elif a.approve_test: pipe.approve_test(a.source)
elif a.render_all: pipe.render_all(a.source,preview=False)
