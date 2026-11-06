"""CLI/GUI for L.D.PORTO Video Curator Studio."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from .core import Project
from .workspace import import_existing_project,project_output_root


def main(argv=None):
    p=argparse.ArgumentParser(description='LDPORTO Video Curator Studio — importação R57 / Reels + Stories')
    sub=p.add_subparsers(dest='cmd')
    a=sub.add_parser('gui',help='Abrir interface gráfica')
    a.add_argument('--example',type=Path)
    a=sub.add_parser('import',help='Validar e importar ZIP em pasta isolada')
    a.add_argument('--zip',required=True,type=Path);a.add_argument('--workdir',required=True,type=Path)
    for name in ('associate','list','status','preview','approve','final','assets','batch-preview','batch-finals','manifest'):
        a=sub.add_parser(name)
        a.add_argument('--workdir',required=True,type=Path)
        if name in ('preview','approve','final'):
            a.add_argument('--id',required=True)
        if name=='associate':a.add_argument('--media',required=True,type=Path)
        if name in ('list','assets','batch-preview'):
            a.add_argument('--kind',choices=('all','reels','stories'),default='all' if name!='batch-preview' else 'reels')
        if name=='batch-preview':a.add_argument('--limit',type=int,default=0)
        if name=='approve':
            a.add_argument('--watched',action='store_true')
            a.add_argument('--audio-ok',action='store_true')
            a.add_argument('--camera-ok',action='store_true')
    a=sub.add_parser('review-download',help='Vincular cópia baixada apenas para prévias revisáveis')
    a.add_argument('--workdir',required=True,type=Path)
    a.add_argument('--confirm-preview-review',action='store_true')
    a=sub.add_parser('adopt-project',help='Copiar projeto antigo para output/projects sem apagar origem')
    a.add_argument('--source',required=True,type=Path)
    a.add_argument('--destination-root',type=Path,default=None)
    a=sub.add_parser('download',help='Baixar URL autorizada do YouTube e validar SHA256 do original')
    a.add_argument('--workdir',required=True,type=Path)
    a.add_argument('--url',required=True,help='URL HTTPS de um único vídeo do YouTube')
    a=sub.add_parser('covers-premium',help='Gerar capas com card viral a partir do MP4')
    a.add_argument('--workdir',required=True,type=Path)
    a.add_argument('--kind',choices=('all','reels','stories'),default='all')
    a=sub.add_parser('export-script',help='Exportar apenas roteiro/câmera/legendas para output/scripts (sem mídia)')
    a.add_argument('--workdir',required=True,type=Path)
    a=sub.add_parser('r6-review',help='Inspecionar candidatos de um ZIP R6 recebido; sem gerar projeto')
    a.add_argument('--inbox',required=True,type=Path)
    a.add_argument('--details',action='store_true',help='Incluir trechos de transcrição na saída')
    a.add_argument('--summary',action='store_true',help='Mostrar somente contagens, alertas e 10 primeiros candidatos')
    a=sub.add_parser('r6-draft',help='Exportar roteiro de candidatos escolhidos manualmente, sem mídia')
    a.add_argument('--inbox',required=True,type=Path)
    a.add_argument('--ids',nargs='+',required=True,help='IDs canônicos do Analyzer escolhidos para Reels')
    a.add_argument('--mode',choices=('preserve','solo_fit','smart_zoom','center_crop'),default='preserve')
    a.add_argument('--confirm-review-draft',action='store_true',
                   help='Confirmar que é somente roteiro pendente, não um ZIP R57 renderizável')
    a=sub.add_parser('r6-smoke',help='Teste técnico automático do R6: escolher IDs, gerar JSON isolado e pré-validar sem mídia')
    a.add_argument('--inbox',required=True,type=Path)
    a.add_argument('--count',type=int,default=2,help='1 a 5 candidatos distintos, apenas para teste')
    a=sub.add_parser('r6-preflight',help='Conferir roteiro R6 escolhido contra o ZIP e SHA da fonte; sem render')
    a.add_argument('--inbox',required=True,type=Path)
    a.add_argument('--draft',required=True,type=Path)
    a.add_argument('--media',type=Path,default=None,
                   help='MP4 opcional para comparação exata do SHA256; não altera/baixa mídia')
    a=sub.add_parser('catalog',help='Listar shows e curadorias realmente presentes em input/ e output/')
    a.add_argument('--input',type=Path)
    a.add_argument('--projects',type=Path)
    a=sub.add_parser('smart-preset',help='Aplicar novo enquadramento de revisão, sem mexer no ZIP')
    a.add_argument('--workdir',required=True,type=Path)
    a.add_argument('--kind',choices=('reels','stories'),default='reels')
    a.add_argument('--mode',choices=('solo_fit','smart_zoom','preserve'),default='smart_zoom')
    a.add_argument('--confirm',action='store_true',help='Confirmar invalidação de prévias/aprovações anteriores')
    args=p.parse_args(argv)
    if args.cmd is None or args.cmd=='gui':
        from .gui import launch
        launch(getattr(args,'example',None))
        return 0
    if args.cmd=='r6-smoke':
        from .r6_smoke import run_r6_smoke
        result=run_r6_smoke(args.inbox,args.count)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0
    if args.cmd=='r6-preflight':
        from .r6_workflow import preflight_editorial_draft
        result=preflight_editorial_draft(args.draft,args.inbox,args.media)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0
    if args.cmd in ('r6-review','r6-draft'):
        from .r6_review import read_analyzer_review, export_editorial_draft
        review=read_analyzer_review(args.inbox)
        if args.cmd=='r6-review':
            if args.summary:
                from .r6_workflow import summarize_review
                rows=review['candidates'][:10]
                print(json.dumps({
                    'source':review['source'],
                    'summary':summarize_review(review),
                    'first_ten_candidates':[{
                        'id':r['candidate_id'],'rank':r['rank'],'title':r['title_suggestion'],
                        'start':r['start'],'end':r['end'],
                        'blocker_count':len(r['blockers']),
                    } for r in rows],
                    'no_automatic_selection':True,
                },ensure_ascii=False,indent=2))
                return 0
            out=dict(review)
            out.pop('inbox_folder',None)
            if not args.details:
                out['candidates']=[{key:row[key] for key in (
                    'candidate_id','rank','start','end','duration_seconds',
                    'title_suggestion','candidate_state','blockers')}
                    for row in review['candidates']]
            print(json.dumps(out,ensure_ascii=False,indent=2))
            return 0
        if not args.confirm_review_draft:
            raise ValueError('Use --confirm-review-draft para exportar seleção apenas como roteiro pendente')
        ids=args.ids
        overrides={cid:{'layout':args.mode} for cid in ids}
        path=export_editorial_draft(review,ids,overrides)
        print(json.dumps({
            'status':'SECOND_CURATION_DRAFT_REVIEW_REQUIRED',
            'selected_reels':len(ids),
            'source_story_candidates':review['story_candidate_count'],
            'render_ready':False,'curator_import_status':'CURATOR_IMPORT_PENDING',
            'output':str(path)},ensure_ascii=False,indent=2))
        return 0
    if args.cmd=='catalog':
        from .catalog import discover_catalog
        rows=discover_catalog(args.input,args.projects)
        print(json.dumps({'items':rows,'count':len(rows)},ensure_ascii=False,indent=2))
        return 0
    if args.cmd=='adopt-project':
        destination=import_existing_project(args.source,args.destination_root)
        print(json.dumps({'status':'COPIED_TO_PROJECT_OUTPUT','project':str(destination),
                          'source_preserved':str(args.source)},ensure_ascii=False,indent=2))
        return 0
    if args.cmd=='import':
        project=Project.create(args.zip,args.workdir)
        print(json.dumps({'project':str(project.dir),'package_sha256':project.package.digest,
            'source_sha256':project.package.source_sha,'reels':len(project.package.items('reels')),
            'stories':len(project.package.items('stories'))},indent=2))
        return 0
    project=Project(args.workdir)
    if args.cmd=='review-download':
        print(json.dumps(project.review_download_for_previews(
            confirm_timeline=args.confirm_preview_review),ensure_ascii=False,indent=2))
        return 0
    if args.cmd=='download':
        from .youtube_download import download_from_youtube
        record=download_from_youtube(project,args.url,
            progress=lambda e: print(f"{e['phase']}: {e.get('detail','')}",flush=True) if e.get('phase')!='baixando' else None)
        print(json.dumps(record,ensure_ascii=False,indent=2))
        return 0 if record['linked'] else 3
    if args.cmd=='export-script':
        from .editorial_script import export_project_script
        path=export_project_script(project)
        print(json.dumps({'status':'SCRIPT_EXPORTED','path':str(path),
                          'contains_video':False},ensure_ascii=False,indent=2))
        return 0
    if args.cmd=='covers-premium':
        from .rendering import generate_premium_covers
        folder,count=generate_premium_covers(project,args.kind)
        print(json.dumps({'covers':count,'folder':str(folder)},ensure_ascii=False,indent=2))
        return 0
    if args.cmd=='smart-preset':
        if not args.confirm:
            raise ValueError('Informe --confirm; mudar layouts invalida aprovações anteriores')
        rows=project.package.items(args.kind)
        for clip in rows:
            project.update(clip.id,layout=args.mode)
        print(json.dumps({'status':'REVIEW_REQUIRED','mode':args.mode,
                          'updated_clips':len(rows)},ensure_ascii=False,indent=2))
        return 0
    if args.cmd=='associate':
        print(json.dumps(project.set_media(args.media),indent=2))
    elif args.cmd=='list':
        for clip in project.package.items(args.kind):
            print(f'{clip.id:10} {clip.start:8.2f}-{clip.end:8.2f}s '
                  f'{project.status(clip.id):26} {project.settings(clip.id)["title"]}')
    elif args.cmd=='status':
        print(json.dumps({'path':str(project.dir),'source':project.package.source_sha,
                          'media':project.state.get('media_path'),
                          'statuses':{c.id:project.status(c.id) for c in project.package.items()}},
                         ensure_ascii=False,indent=2))
    elif args.cmd in ('preview','final'):
        from .rendering import render_item
        path,report=render_item(project,args.id,preview=args.cmd=='preview')
        print(path)
        print(json.dumps(report,ensure_ascii=False,indent=2))
    elif args.cmd=='approve':
        result=project.approve(args.id,human_reviewed=args.watched,
                               verified_audio=args.audio_ok,verified_camera=args.camera_ok)
        print(json.dumps(result,indent=2))
    elif args.cmd=='assets':
        from .rendering import extract_editorial_assets
        folder,count=extract_editorial_assets(project,args.kind)
        print(f'{count} peças exportadas em {folder}')
    elif args.cmd=='batch-preview':
        from .rendering import render_item
        clips=project.package.items(args.kind)
        if args.limit>0:clips=clips[:args.limit]
        for i,clip in enumerate(clips,1):
            if project.preview_record(clip.id):
                print(f'[{i}/{len(clips)}] prévia validada existente: {clip.id}')
                continue
            path,_=render_item(project,clip.id,preview=True)
            print(f'[{i}/{len(clips)}] {path}')
    elif args.cmd=='batch-finals':
        from .rendering import render_item
        for c in project.package.items():
            if project.approval_matches(c.id) and not project.final_record(c.id):
                path,_=render_item(project,c.id,preview=False);print(path)
        print('Manifesto:',project.export_manifest()['generated_at'])
    elif args.cmd=='manifest':
        print(json.dumps(project.export_manifest(),ensure_ascii=False,indent=2))
    return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except (RuntimeError,ValueError,FileNotFoundError) as e:
        print('ERRO:',e,file=sys.stderr)
        raise SystemExit(2)
