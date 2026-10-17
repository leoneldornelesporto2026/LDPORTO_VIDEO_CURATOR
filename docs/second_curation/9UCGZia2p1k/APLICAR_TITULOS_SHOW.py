"""Apply unique titles using the Curator's edit API; never edit approved projects."""
import argparse
from pathlib import Path
import hashlib
import json
import shutil
import sys
import datetime


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--curator',type=Path,required=True)
    p.add_argument('--plano',type=Path,required=True,help='Path to V5 series_index.json')
    p.add_argument('--titulos',type=Path,required=True)
    p.add_argument('--aplicar',action='store_true',help='Without flag, dry run only')
    args=p.parse_args()
    root=args.curator.resolve()
    index=args.plano.resolve(strict=True)
    expected_base=(root/'output'/'projects'/'9UCGZia2p1k').resolve()
    if index.name!='series_index.json' or not index.parent.is_relative_to(expected_base) or not index.parent.name.startswith('stories_'):
        raise ValueError('Plano selecionado fora do novo projeto Stories do show')
    if args.plano.is_symlink():
        raise ValueError('Symlink não permitido')
    sys.path.insert(0,str(root))
    from ldporto_curator.series_workflow import SeriesProject
    from ldporto_curator.config import load_config
    cfg=load_config(root/'config.yaml')
    proj=SeriesProject(index.parent,cfg)
    data=json.loads(args.titulos.read_text('utf-8-sig'))
    if proj.evidence.get('source',{}).get('sha256')!=data['source_sha256']:
        raise ValueError('Identidade da mídia diverge')
    episodes=proj.episodes()
    if len(episodes)!=data['expected_episode_count']:
        raise ValueError('Projeto contém episódios diferentes; nenhuma mudança')
    # Do not edit a project with previews, approvals, renders, or unfinished attempts.
    if any((ep.get('preview') or ep.get('final') or ep.get('human_approval') or
            ep.get('status') in {'APPROVED','FINAL_APPROVED','PREVIEW_APPROVED','REJECTED'} or
            ep.get('state') in {'APPROVED','FINAL_APPROVED','PREVIEW_APPROVED','REJECTED'}) for ep in episodes):
        raise ValueError('Projeto possui prévia/aprovação/resultado. Crie um novo projeto para títulos.')
    if any((index.parent/ep.get('series_id','') ).is_symlink() for ep in episodes):
        raise ValueError('Diretório inesperado')
    entries={(x['series_id'],x['order']):x for x in data['titles']}
    planned=[]
    for ep in episodes:
        key=(ep['series_id'],ep['order'])
        new=entries.get(key)
        if not new or (ep.get('story_original_candidate_id')!=new['story_original_candidate_id']
           or abs(ep['source_start']-new['expected_start'])>.005 or abs(ep['source_end']-new['expected_end'])>.005):
            raise ValueError('Título não corresponde ao episódio ' +str(key))
        planned.append((key,new))
    if len(planned)!=len(entries):
        raise ValueError('Títulos duplicados ou excedentes')
    print('STATUS:', 'PRONTO_PARA_APLICAR' if args.aplicar else 'SOMENTE_SIMULACAO')
    for k,v in planned:
        print('%s %s -> %s'%(k[0],k[1],v['title']))
    if not args.aplicar:
        print('Nenhum arquivo modificado. Execute com --aplicar depois de revisar a lista.')
        return
    before=index.read_bytes(); before_hash=hashlib.sha256(before).hexdigest()
    backup=Path.home()/'Videos'/'LDPORTO_CURATOR_BACKUPS'/'TITULOS_SHOW_9UCGZia2p1k'
    backup.mkdir(parents=True,exist_ok=True)
    dest=backup/(datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'_'+before_hash[:12]+'.json')
    with dest.open('xb') as f:f.write(before)
    if hashlib.sha256(index.read_bytes()).hexdigest()!=before_hash:
        raise RuntimeError('Projeto modificado durante preparação; nada editado')
    # Edits through Curator preserve an editing-history trail, making the result
    # a new, unapproved revision. No manual JSON editing of signatures/hashes.
    for key, title in planned:
        ep=next(x for x in proj.episodes() if (x['series_id'],x['order'])==key)
        proj.edit(ep['episode_id'],title_text=title['title'],thumbnail_title=title['thumbnail_title'],
                  subtitle_preset='LDP_REELS_KARAOKE',camera_mode='AUTO_CONSERVADOR')
    print('TITULOS_APLICADOS:',len(planned))
    print('BACKUP:',dest)
    print('STATUS: revisão humana obrigatória, sem aprovação automática.')

if __name__=='__main__':
    main()
