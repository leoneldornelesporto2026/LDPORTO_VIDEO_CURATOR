from __future__ import annotations
from pathlib import Path
from .analysis_loader import find_analysis, load_bundle
from .curator import curate
from .camera import build_camera_plan
from .source_video import resolve_source
from .thumbnails import create_assets
from .render import render_clip
from .review import build_board, write_handoff
from .utils import write_json

class Pipeline:
    def __init__(self, cfg, project_root: Path, log=print, progress=None):
        self.cfg = cfg
        self.root = project_root
        self.log = log
        self.progress = progress or (lambda event: None)

    def _emit(self, plan, step, label, fraction=0.0, detail='', status='running', operation_label='Processando...'):
        total = max(1, len(plan))
        frac = None if fraction is None else max(0.0, min(1.0, float(fraction)))
        overall = ((step - 1) + (frac or 0.0)) / total
        if status in {'done','completed'} and step >= total:
            overall = 1.0
        self.progress({
            'stage': f'{step}:{label}', 'label': label, 'step': step, 'total_steps': total,
            'stage_fraction': frac, 'overall_fraction': max(0.0, min(1.0, overall)),
            'detail': detail, 'status': status, 'plan': plan, 'operation_label': operation_label
        })

    def _prepare_curation(self, source_input, plan, step_map, operation_label):
        s = step_map
        self._emit(plan, s['analysis'], 'Localizando análise', 0.05, source_input, operation_label=operation_label)
        from .second_curation_import import registered_input
        imported = registered_input(self.root, source_input)
        ar = Path(imported['analysis_dir']) if imported else find_analysis(self.cfg['paths']['analysis_root'], source_input)
        self.log(f'Análise encontrada: {ar}')
        self._emit(plan, s['analysis'], 'Localizando análise', 1.0, str(ar), operation_label=operation_label)

        self._emit(plan, s['load'], 'Carregando inteligência do Analyzer', 0.08, 'transcript, cenas, pessoas e câmera', operation_label=operation_label)
        b = load_bundle(ar)
        if imported and imported.get('decision_path'):
            from .utils import load_json
            b.second_decisions = load_json(imported['decision_path'], {})
        self._emit(plan, s['load'], 'Carregando inteligência do Analyzer', 1.0, f'vídeo={b.video_id}', operation_label=operation_label)

        self._emit(plan, s['curate'], 'Aplicando segunda curadoria', 0.05, 'ranking, overrides e contexto', operation_label=operation_label)
        dec = curate(b, self.cfg, self.root, log=self.log)
        self.progress({'event':'eta_context', 'metadata':b.analysis.get('metadata',{}), 'clips':dec, 'operation':operation_label})
        self.progress({'event': 'curation_source', 'curation_source': dec[0]['curation_source'] if dec else 'FIRST_PASS'})
        self._emit(plan, s['curate'], 'Aplicando segunda curadoria', 1.0, f'{len(dec)} cortes selecionados; revisão de preview pendente', operation_label=operation_label)

        out = Path(self.cfg['paths']['output_root'])/'curation'/b.video_id
        out.mkdir(parents=True, exist_ok=True)
        self._emit(plan, s['plans'], 'Montando câmera e planos editoriais', 0.0, f'{len(dec)} cortes', operation_label=operation_label)
        total_dec = max(1, len(dec))
        for i, d in enumerate(dec, 1):
            d['camera_plan'] = build_camera_plan(b, d, self.cfg)
            d['subtitle_plan'] = {'format':'ASS','max_lines':2,'word_highlight':True}
            d['thumbnail_plan'] = {'opening_frame':True,'best':True,'clean':True}
            self._emit(plan, s['plans'], 'Montando câmera e planos editoriais', i/total_dec, f'corte {i}/{len(dec)}', operation_label=operation_label)

        from .approval import plan_signature
        write_json(out/'EDIT_DECISIONS.json', {'video_id':b.video_id,'source':b.source,'approved_clips':dec,
                                              'plan_signature': plan_signature(dec, self.cfg)})
        write_handoff(b, dec, out)
        report = ['# L.D.PORTO — CURATION REPORT','',f'Vídeo: {b.source.get("title") or b.video_id}',f'Cortes selecionados: {len(dec)}; aprovação humana de preview é uma etapa separada.','']
        for d in dec:
            cam = d['camera_plan']
            report += [
                f"## #{d['rank']} {d['clip_id']} — {d['title_text']}",
                f"- {d['source_start']:.2f}s → {d['source_end']:.2f}s ({d['duration']:.1f}s)",
                f"- Score: {d['score']}", f"- Motivo: {d['reason']}",
                f"- Câmera: {cam.get('mode')} / fonte={cam.get('visual_source','timeline')} / decisões={len(cam.get('segments') or [])}",
                f"- Evidência de falante: {cam.get('speaker_evidence_segments',0)} trechos; duas faces incertas: {cam.get('uncertain_two_face_segments',0)}", ''
            ]
        (out/'CURATION_REPORT.md').write_text('\n'.join(report), encoding='utf-8')
        self.log(f'Curadoria: {len(dec)} cortes selecionados para revisão.')
        return b, dec, out

    def curate_only(self, source_input):
        plan = ['Localizar análise','Carregar dados','Curadoria','Câmera/planos','Salvar handoff']
        op = 'Curando vídeo...'
        b, dec, out = self._prepare_curation(source_input, plan, {'analysis':1,'load':2,'curate':3,'plans':4}, op)
        self._emit(plan, 5, 'Salvando handoff e relatório', 1.0, f'{len(dec)} cortes', status='done', operation_label=op)
        return b, dec, out

    def test_one(self, source_input, rank=1):
        plan = ['Localizar análise','Carregar dados','Curadoria','Câmera/planos','Localizar vídeo','Gerar miniaturas','Preparar render','Renderizar preview','Validar e montar board','Concluir teste']
        op = 'Gerando preview do corte...'
        b, dec, out = self._prepare_curation(source_input, plan, {'analysis':1,'load':2,'curate':3,'plans':4}, op)
        if not dec:
            raise RuntimeError('Nenhum corte selecionado. O fluxo V5 permite propostas e dossiê com shortlist vazia.')
        clip = next((x for x in dec if x['rank']==rank), dec[0])

        self._emit(plan, 5, 'Localizando vídeo fonte', 0.1, 'procurando mídia original/cache', operation_label=op)
        video = resolve_source(b, source_input, self.cfg, self.log)
        self._emit(plan, 5, 'Localizando vídeo fonte', 1.0, video.name, operation_label=op)

        cd = out/'clips'/clip['clip_id']
        cd.mkdir(parents=True, exist_ok=True)
        from .final_camera import refine_clip
        self._emit(plan, 6, 'Refinando câmera do corte', 0.0, 'evidência local e regiões de GC', operation_label=op)
        refine_clip(b, clip, video, cd, self.cfg,
                    progress=lambda f,d='': self._emit(plan, 6, 'Refinando câmera do corte', .7*f, d, operation_label=op))
        from .approval import plan_signature
        signature = plan_signature(dec, self.cfg, clip['clip_id'])
        write_json(out/'EDIT_DECISIONS.json', {'video_id':b.video_id, 'source':b.source, 'approved_clips':dec,
                                              'plan_signature':signature, 'reviewed_clip_id':clip['clip_id']})
        self._emit(plan, 6, 'Gerando miniaturas', .7, f"rank {clip['rank']}", operation_label=op)
        clip['thumbnail_plan'].update(create_assets(
            b, clip, video, cd, self.cfg,
            progress=lambda f,d='': self._emit(plan, 6, 'Gerando miniaturas', .7+.3*f, d, operation_label=op)
        ))
        write_json(cd/'clip.json', clip)
        self._emit(plan, 6, 'Gerando miniaturas', 1.0, 'assets prontos', operation_label=op)

        rend = Path(self.cfg['paths']['output_root'])/'renders'/b.video_id/clip['clip_id']
        rend.mkdir(parents=True, exist_ok=True)
        self._emit(plan, 7, 'Preparando render', 1.0, 'legendas, título e câmera preparados', operation_label=op)
        self._emit(plan, 8, 'Renderizando preview', 0.0, f"{clip['duration']:.1f}s de vídeo", operation_label=op)
        mp4 = render_clip(
            b, clip, video, rend, self.cfg, preview=True, log=self.log,
            progress=lambda f,d='': self._emit(plan, 8, 'Renderizando preview', f, d, operation_label=op)
        )
        from .approval import record_preview, plan_signature
        record_preview(out, mp4, signature, clip['clip_id'])

        self._emit(plan, 9, 'Validando e montando board', 0.2, 'checando MP4 e painel', operation_label=op)
        build_board(dec, out)
        self._emit(plan, 9, 'Validando e montando board', 1.0, 'board atualizado', operation_label=op)
        self.log(f'TESTE DE 1 CORTE PRONTO: {mp4}')
        self._emit(plan, 10, 'Concluir teste', 1.0, str(mp4), status='done', operation_label=op)
        return mp4, out

    def approve_test(self, source_input):
        plan = ['Localizar análise','Registrar aprovação']
        op = 'Registrando aprovação...'
        self._emit(plan, 1, 'Localizando análise', 0.1, operation_label=op)
        from .second_curation_import import registered_input
        imported = registered_input(self.root, source_input)
        ar = Path(imported['analysis_dir']) if imported else find_analysis(self.cfg['paths']['analysis_root'], source_input)
        b = load_bundle(ar)
        self._emit(plan, 1, 'Localizando análise', 1.0, b.video_id, operation_label=op)
        out = Path(self.cfg['paths']['output_root'])/'curation'/b.video_id
        out.mkdir(parents=True, exist_ok=True)
        from .approval import approve_preview
        from .utils import load_json
        current = load_json(out / 'EDIT_DECISIONS.json', {}) or {}
        if current.get('plan_signature'):
            approve_preview(out, current['plan_signature'])
        else:
            raise RuntimeError('Gere um preview antes de registrar a aprovação')
        self._emit(plan, 2, 'Registrar aprovação', 1.0, 'lote liberado', status='done', operation_label=op)
        return out

    def render_all(self, source_input, preview=False):
        bootstrap = ['Localizar análise','Carregar dados','Curadoria','Câmera/planos']
        op = 'Renderizando lote final...'
        b, dec, out = self._prepare_curation(source_input, bootstrap, {'analysis':1,'load':2,'curate':3,'plans':4}, op)
        if self.cfg.get('safety',{}).get('require_first_test_approval_before_batch',True) and not (out/'FIRST_TEST_APPROVED.flag').exists():
            raise RuntimeError('Primeiro teste ainda não foi aprovado. Use TESTAR 1 CORTE, revise o MP4 e clique APROVAR TESTE antes do lote.')
        plan = ['Localizar análise','Carregar dados','Curadoria','Câmera/planos','Localizar vídeo']
        for i in range(1, len(dec)+1):
            plan += [f'Assets corte {i}/{len(dec)}', f'Render corte {i}/{len(dec)}']
        plan += ['Board/handoff','Concluir lote']

        self._emit(plan, 5, 'Localizando vídeo fonte', 0.1, operation_label=op)
        video = resolve_source(b, source_input, self.cfg, self.log)
        self._emit(plan, 5, 'Localizando vídeo fonte', 1.0, video.name, operation_label=op)

        from .final_camera import refine_clip
        from .approval import plan_signature
        reviewed_id = None
        if self.cfg.get('safety',{}).get('require_first_test_approval_before_batch',True):
            from .approval import approval_matches, plan_signature
            from .utils import load_json
            approval = load_json(out/'FIRST_TEST_APPROVED_V44.json', {}) or {}
            reviewed_id = approval.get('reviewed_clip_id')
            reviewed = next((d for d in dec if d['clip_id'] == reviewed_id), None)
            if reviewed is None:
                raise RuntimeError('Gere e aprove um preview V4.4 do plano atual antes do lote.')
            refine_clip(b, reviewed, video, out/'clips'/reviewed_id, self.cfg)
            if not approval_matches(out, plan_signature(dec, self.cfg, reviewed_id)):
                raise RuntimeError('A aprovação não corresponde ao plano atual. Gere e aprove um novo preview.')

        results = []
        step = 6
        for idx, clip in enumerate(dec, 1):
            cd = out/'clips'/clip['clip_id']
            cd.mkdir(parents=True, exist_ok=True)
            asset_label = f'Assets corte {idx}/{len(dec)}'
            self._emit(plan, step, asset_label, 0.0, clip['title_text'][:70], operation_label=op)
            if clip['clip_id'] != reviewed_id:
                refine_clip(b, clip, video, cd, self.cfg,
                            progress=lambda f,d='',st=step,lab=asset_label: self._emit(plan, st, lab, .7*f, d, operation_label=op))
            clip['thumbnail_plan'].update(create_assets(
                b, clip, video, cd, self.cfg,
                progress=lambda f,d='',st=step,lab=asset_label: self._emit(plan, st, lab, .7+.3*f, d, operation_label=op)
            ))
            write_json(cd/'clip.json', clip)
            self._emit(plan, step, asset_label, 1.0, 'assets prontos', operation_label=op)
            step += 1

            rd = Path(self.cfg['paths']['output_root'])/'renders'/b.video_id/clip['clip_id']
            rd.mkdir(parents=True, exist_ok=True)
            render_label = f'Render corte {idx}/{len(dec)}'
            self._emit(plan, step, render_label, 0.0, f"{clip['duration']:.1f}s", operation_label=op)
            results.append(render_clip(
                b, clip, video, rd, self.cfg, preview=preview, log=self.log,
                progress=lambda f,d='',st=step,lab=render_label: self._emit(plan, st, lab, f, d, operation_label=op)
            ))
            self._emit(plan, step, render_label, 1.0, 'MP4 validado', operation_label=op)
            step += 1

        self._emit(plan, step, 'Board/handoff', 0.2, 'atualizando painel final', operation_label=op)
        build_board(dec, out)
        write_handoff(b, dec, out)
        write_json(out/'EDIT_DECISIONS.json', {'video_id':b.video_id,'source':b.source,'approved_clips':dec,
                                              'plan_signature':plan_signature(dec, self.cfg, reviewed_id)})
        self._emit(plan, step, 'Board/handoff', 1.0, 'handoff pronto', operation_label=op)
        step += 1
        self._emit(plan, step, 'Concluir lote', 1.0, f'{len(results)} vídeos renderizados', status='done', operation_label=op)
        return results, out
