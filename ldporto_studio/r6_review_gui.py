"""Tkinter selection window for Analyzer R6 proposals.

Only reads validated Analyzer data; never opens R57 projects, renders video
or changes approvals. Saving produces a media-free review script.
"""
from __future__ import annotations

import json
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from .r6_review import export_editorial_draft, LAYOUTS
from .r6_workflow import FILTERS, select_visible_candidates, summarize_review


class AnalyzerR6ReviewDialog(tk.Toplevel):
    def __init__(self, parent, review, on_export=None):
        super().__init__(parent)
        self.review=review
        self.on_export=on_export
        self.overrides={}
        self.current=None
        self.chosen_ids=set()
        self.last_exported_path=None
        self.last_story_proposal_path=None
        self.rows={row['candidate_id']:row for row in review['candidates']}
        self.summary=summarize_review(review)
        source=review['source']
        self.title('Segunda curadoria R6 — '+source['title'])
        self.geometry('1150x760')
        self.minsize(900,580)
        self.transient(parent)
        outer=ttk.Frame(self,padding=12)
        outer.pack(fill='both',expand=True)
        ttk.Label(outer,text=source['title'],font=('Segoe UI',15,'bold')).pack(anchor='w')
        ttk.Label(outer,text=(
            f"Análise {source['analysis_state']}  |  "
            f"{review['candidate_count']} candidatos de Reels  |  "
            f"{review['story_candidate_count']} candidatos de Stories  |  "
            "NENHUM aprovado. Selecione os trechos para criar roteiro de revisão."
        ),wraplength=1050).pack(anchor='w',pady=(3,9))
        ttk.Label(outer,text='R6 é evidência; o roteiro gerado ainda não é um ZIP R57 executável. '
                            'Prévia, áudio, câmera, legenda e direitos exigem revisão.').pack(anchor='w',pady=(0,6))
        ttk.Label(outer,text=(
            f"{self.summary['unique_intervals']} intervalos distintos; "
            f"{self.summary['same_interval_alternates']} alternativas com mesmo intervalo; "
            f"{self.summary['titles_to_review']} títulos pendentes; "
            f"{self.summary['publication_eligible_false']} sem elegibilidade de publicação."
        ),wraplength=1050).pack(anchor='w',pady=(0,7))
        filter_row=ttk.Frame(outer)
        filter_row.pack(fill='x',pady=(0,8))
        ttk.Label(filter_row,text='Buscar trecho / fala / ID:').pack(side='left',padx=(0,6))
        self.search=tk.StringVar()
        ttk.Entry(filter_row,textvariable=self.search,width=30).pack(side='left',padx=(0,10))
        ttk.Label(filter_row,text='Filtro:').pack(side='left')
        self.filter_mode=tk.StringVar(value=FILTERS['all'])
        self.filter_box=ttk.Combobox(
            filter_row,textvariable=self.filter_mode,state='readonly',width=33,
            values=list(FILTERS.values()))
        self.filter_box.pack(side='left',padx=(6,10))
        self.filter_box.bind('<<ComboboxSelected>>',lambda event:self._populate())
        self.collapse_duplicates=tk.BooleanVar(value=False)
        ttk.Checkbutton(filter_row,text='Ocultar intervalos repetidos (só na tela)',
                        variable=self.collapse_duplicates,
                        command=self._populate).pack(side='left')
        self.search.trace_add('write',lambda *args:self._populate())
        host=ttk.PanedWindow(outer,orient='horizontal')
        host.pack(fill='both',expand=True)
        left=ttk.Frame(host,padding=(0,6,8,6))
        right=ttk.Frame(host,padding=(8,6,0,6))
        host.add(left,weight=3);host.add(right,weight=2)
        self.tree=ttk.Treeview(left,columns=('rank','start','duration','state'),show='tree headings',
                               selectmode='extended')
        self.tree.heading('#0',text='✓ marcado / candidato / título')
        self.tree.column('#0',width=325,minwidth=230)
        for key,title,width in (
            ('rank','Rank',48),('start','Início (s)',75),
            ('duration','Duração',73),('state','Estado',145)):
            self.tree.heading(key,text=title)
            self.tree.column(key,width=width,anchor='center')
        scroll=ttk.Scrollbar(left,command=self.tree.yview)
        scroll.pack(side='right',fill='y')
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(fill='both',expand=True)
        self.tree.tag_configure('chosen',background='#254436',foreground='#f0fff7')
        self._populate()
        self.tree.bind('<<TreeviewSelect>>',self._on_select)
        batch_row=ttk.Frame(left)
        batch_row.pack(fill='x',pady=(7,2))
        ttk.Button(batch_row,text='MARCAR SELECIONADOS',
                   command=self._mark_selected).pack(side='left',padx=(0,5))
        ttk.Button(batch_row,text='DESMARCAR SELECIONADOS',
                   command=self._unmark_selected).pack(side='left',padx=(0,5))
        ttk.Button(batch_row,text='LIMPAR MARCAÇÕES',
                   command=self._clear_marked).pack(side='left')
        self.details_title=tk.StringVar(value='')
        self.details_layout=tk.StringVar(value='preserve')
        ttk.Label(right,text='Detalhes do candidato selecionado',
                  font=('Segoe UI',11,'bold')).pack(anchor='w',pady=(0,6))
        ttk.Label(right,text='Título a revisar').pack(anchor='w',pady=2)
        ttk.Entry(right,textvariable=self.details_title).pack(fill='x')
        ttk.Label(right,text='Enquadramento planejado (padrão: preserve)').pack(anchor='w',pady=(9,2))
        ttk.Combobox(right,textvariable=self.details_layout,state='readonly',
                     values=('preserve','solo_fit','smart_zoom','center_crop')).pack(fill='x')
        ttk.Label(right,text='Notas editoriais').pack(anchor='w',pady=(9,2))
        self.notes=tk.Text(right,height=3,wrap='word',font=('Segoe UI',9))
        self.notes.pack(fill='x')
        ttk.Button(right,text='SALVAR TÍTULO / CÂMERA DE 1 CANDIDATO',
                   command=self._apply_one).pack(fill='x',pady=(8,8))
        ttk.Label(right,text='Transcrição e pendências — dados do Analyzer').pack(anchor='w')
        self.evidence=tk.Text(right,height=14,wrap='word',state='disabled',
                              font=('Consolas',9))
        self.evidence.pack(fill='both',expand=True,pady=(3,5))
        story_actions=ttk.Frame(outer)
        story_actions.pack(fill='x',pady=(8,0))
        ttk.Button(story_actions,text='PROPOR STORIES (SEM APROVAR)',
                   command=self._propose_story_windows).pack(side='right')
        ttk.Button(story_actions,text='CHECKLIST ASSETS R57',
                   command=self._export_asset_template).pack(side='right',padx=(0,6))
        ttk.Button(story_actions,text='GERAR ZIP R57 (SÓ PRÉVIAS)',
                   command=self._build_preview_r57).pack(side='right',padx=(0,6))
        ttk.Button(story_actions,text='EVIDÊNCIAS R6',
                   command=self._export_r6_evidence).pack(side='right',padx=(0,6))
        ttk.Button(story_actions,text='INVENTÁRIO R6 (SEM SELEÇÃO)',
                   command=self._inspect_r6_inventory).pack(side='right',padx=(0,6))
        ttk.Button(story_actions,text='RASCUNHOS DE LEGENDAS ASR',
                   command=self._export_caption_drafts).pack(side='right',padx=(0,6))
        ttk.Label(story_actions,
                  text='Materiais para revisar; sem aprovação.').pack(side='left')
        cover_actions=ttk.Frame(outer)
        cover_actions.pack(fill='x',pady=(5,0))
        ttk.Label(cover_actions,
                  text='Capas de quadros reais (requer vídeo SHA256 original)').pack(side='left')
        ttk.Button(cover_actions,text='RASCUNHOS DE CAPAS DA FONTE',
                   command=self._export_cover_drafts).pack(side='right')
        ttk.Button(cover_actions,text='PREENCHER ASSETS COM RASCUNHOS',
                   command=self._stage_existing_r6_assets).pack(side='right',padx=(0,6))
        footer=ttk.Frame(outer)
        footer.pack(fill='x',pady=(8,0))
        self.selection_status=tk.StringVar(value='Nenhum marcado para o roteiro.')
        ttk.Label(footer,textvariable=self.selection_status,wraplength=650).pack(side='left',fill='x',expand=True)
        ttk.Button(footer,text='EXPORTAR MARCADOS — ROTEIRO JSON',
                   command=self._export).pack(side='right')
        ttk.Button(footer,text='PLANO R6 → R57 (PENDÊNCIAS)',
                   command=self._prepare_r57_plan).pack(side='right',padx=(0,6))
        ttk.Button(footer,text='ABRIR PASTA DO ROTEIRO',
                   command=self._open_export_folder).pack(side='right',padx=(0,6))
        ttk.Button(footer,text='FECHAR',command=self.destroy).pack(side='right',padx=(0,8))

    def _populate(self):
        if not hasattr(self,'tree'):
            return
        active=set(self.tree.selection())
        key=next((name for name,label in FILTERS.items()
                  if label==self.filter_mode.get()),'all')
        rows=select_visible_candidates(
            self.review,key,
            self.search.get(),self.collapse_duplicates.get())
        self.tree.delete(*self.tree.get_children())
        for row in rows:
            cid=row['candidate_id']
            title=self.overrides.get(cid,{}).get('title',row['title_suggestion'])
            self.tree.insert('', 'end',iid=cid,
                             text=('✓ ' if cid in self.chosen_ids else '  ')+title[:51],
                             values=(row['rank'],row['start'],
                                     row['duration_seconds'],row['candidate_state'][:22]),
                             tags=('chosen',) if cid in self.chosen_ids else ())
        present=set(self.tree.get_children())
        if active & present:
            self.tree.selection_set(list(active & present))
        self._selection_hint(len(rows))

    def _selection_hint(self, visible=None):
        if visible is None:
            visible=len(self.tree.get_children())
        # The first table population occurs before the footer is constructed.
        if not hasattr(self,'selection_status'):
            return
        self.selection_status.set(
            f'{visible}/{self.review["candidate_count"]} visíveis · '
            f'{len(self.chosen_ids)} marcados para o roteiro. '
            'Selecione com Ctrl/Shift e clique MARCAR SELECIONADOS.')

    def _mark_selected(self):
        ids=self.tree.selection()
        if not ids:
            messagebox.showwarning('Marque os candidatos',
                'Selecione um ou mais candidatos (Ctrl/Shift) e clique MARCAR SELECIONADOS.',parent=self)
            return
        self.chosen_ids.update(ids)
        self._populate()
        self.tree.selection_set(ids)

    def _unmark_selected(self):
        self.chosen_ids.difference_update(self.tree.selection())
        self._populate()

    def _clear_marked(self):
        if not self.chosen_ids:
            return
        if messagebox.askyesno('Limpar lista',
            'Remover todas as marcações deste roteiro? Isso não altera o ZIP nem as edições salvas.',
            parent=self):
            self.chosen_ids.clear()
            self._populate()

    def _on_select(self,event=None):
        selected=self.tree.selection()
        self._selection_hint()
        if len(selected)!=1:
            self.current=None
            return
        cid=selected[0]
        row=next(x for x in self.review['candidates'] if x['candidate_id']==cid)
        override=self.overrides.get(cid,{})
        self.current=cid
        self.details_title.set(override.get('title',row['title_suggestion']))
        self.details_layout.set(override.get('layout','preserve'))
        self.notes.delete('1.0','end')
        self.notes.insert('1.0',override.get('notes',''))
        summary=(
            f"ID: {cid}\n"
            f"Tempo: {row['start']} – {row['end']} s\n"
            f"Tipo: {row['content_type']}\n"
            f"Estado: {row['candidate_state']}\n"
            f"Elegível p/ shortlist: {row['shortlist_eligible']}\n"
            f"Elegível p/ publicação: {row['publication_eligible']}\n"
            f"Legendas: {row['caption_preflight']['status']}\n"
            f"Câmera: {row['camera_feasibility'] or 'não aferida'}\n"
            f"Abertura/fecho limpos: {row['clean_opening']} / {row['clean_ending']}\n"
            f"Contexto: {row['context_requirement']}\n"
            f"Score editorial (heurístico): {row['editorial_score_final']}\n"
            f"Gancho sugerido (não verificado): {row['generated_hook_idea']}\n"
            f"Pendências: {', '.join(row['blockers']) or 'Revisão humana obrigatória'}\n\n"
            f"TRANSCRIÇÃO (não conferida):\n{row['transcript_excerpt'] or '(ausente)'}"
        )
        self.evidence.config(state='normal')
        self.evidence.delete('1.0','end')
        self.evidence.insert('1.0',summary)
        self.evidence.config(state='disabled')

    def _apply_one(self):
        if self.current is None or len(self.tree.selection())!=1:
            messagebox.showwarning('Selecione apenas um',
                                   'Selecione um candidato para editar o título e a câmera.',parent=self)
            return
        cid=self.current
        title=self.details_title.get().strip()
        notes=self.notes.get('1.0','end-1c')
        layout=self.details_layout.get()
        if not title or len(title)>130 or len(notes)>2000 or layout not in LAYOUTS:
            messagebox.showerror('Edição inválida','Título máximo 130, notas máximo 2000 e layout válido.',parent=self)
            return
        self.overrides[cid]={'title':title,'layout':layout,'notes':notes}
        self.tree.item(cid,text=('✓ ' if cid in self.chosen_ids else '  ')+title[:51])
        self.selection_status.set(f'{cid}: título e câmera registrados para exportação.')

    def _open_export_folder(self):
        if self.last_exported_path is None:
            return messagebox.showinfo('Sem roteiro exportado',
                'Primeiro MARQUE os candidatos e clique EXPORTAR MARCADOS.',parent=self)
        from .gui import open_file
        open_file(self.last_exported_path.parent)

    def _propose_story_windows(self):
        if self.last_exported_path is None:
            messagebox.showwarning(
                'Exporte a seleção R6',
                'É necessário exportar um roteiro de candidatos antes de propor Stories.',
                parent=self)
            return
        if not messagebox.askyesno(
                'Divisão técnica para Stories',
                'Criar uma proposta de janelas contínuas, cada uma com no máximo 60 segundos?\n'
                'NÃO são cenas identificadas, Stories aprovados ou conteúdo pronto.',
                parent=self):
            return
        try:
            from .r6_story_timeline import export_story_proposal
            path=export_story_proposal(self.review['inbox_folder'],self.last_exported_path)
        except (ValueError, OSError, TypeError, KeyError) as exc:
            messagebox.showerror('Não foi possível propor Stories',str(exc),parent=self)
            return
        self.last_story_proposal_path=path
        self.selection_status.set('PROPOSTA DE STORIES: '+str(path))
        messagebox.showinfo(
            'Timeline técnica proposta',
            f'Proposta registrada em:\n{path}\n\n'
            'Divisões ainda precisam de revisão editorial; nenhum Story foi aprovado.',
            parent=self)

    def _inspect_r6_inventory(self):
        try:
            from .r6_evidence_reuse import inspect_r6_inventory
            inventory=inspect_r6_inventory(self.review['inbox_folder'])
        except (ValueError, OSError, TypeError, KeyError) as exc:
            messagebox.showerror('Inventário de evidências bloqueado',str(exc),parent=self)
            return
        details=(
            f"Reels candidatos: {inventory['candidate_count']}\n"
            f"Contact sheets disponíveis: {inventory['available_contact_sheets']}\n"
            f"Contact sheets ausentes/indisponíveis: {inventory['unavailable_contact_sheets']}\n"
            f"Transcrições disponíveis: {inventory['available_transcript_files']}\n"
            f"Stories originais do Analyzer: {inventory['story_candidate_count']}\n\n"
            'Nenhum candidato foi selecionado e nenhum arquivo foi criado.\n'
            'Contact sheets e ASR são somente materiais de revisão.'
        )
        messagebox.showinfo('Inventário do R6 original',details,parent=self)

    def _stage_existing_r6_assets(self):
        if self.last_exported_path is None or self.last_story_proposal_path is None:
            messagebox.showwarning(
                'Roteiro e Stories obrigatórios',
                'Exporte primeiro os Reels e a proposta de Stories.',
                parent=self)
            return
        covers=filedialog.askdirectory(
            parent=self,title='Selecione a pasta COVERS_R6_DRAFT com manifesto')
        if not covers:
            return
        captions=None
        if messagebox.askyesno(
                'Legendas disponíveis?',
                'Você já gerou a pasta CAPTIONS_R6_DRAFT com SRT/ASS originais?\n'
                'SIM para vinculá-la; NÃO para deixar legendas pendentes.',
                parent=self):
            captions=filedialog.askdirectory(
                parent=self,title='Selecione a pasta CAPTIONS_R6_DRAFT')
            if not captions:
                return
        if not messagebox.askyesno(
                'Consolidar rascunhos?',
                'Copiar SOMENTE arquivos existentes, verificando SHA256?\n'
                'Arquivos ausentes permanecerão vazios.\n'
                'Nenhuma aprovação ou publicação será registrada.',
                parent=self):
            return
        self.configure(cursor='watch')
        self.update_idletasks()
        try:
            from .r6_asset_staging import (
                save_asset_staging, BINDINGS_NAME, MANIFEST_NAME)
            folder=save_asset_staging(
                self.review['inbox_folder'],self.last_exported_path,
                self.last_story_proposal_path,covers,captions_dir=captions)
            report=json.loads((folder/MANIFEST_NAME).read_text(encoding='utf-8'))
        except (ValueError, OSError, TypeError, KeyError, RuntimeError) as exc:
            messagebox.showerror('Checklist não preenchido',str(exc),parent=self)
            return
        finally:
            self.configure(cursor='')
        self.selection_status.set('ASSETS PARA REVISÃO: '+str(folder))
        messagebox.showinfo(
            'Rascunhos vinculados',
            f"Assets existentes: {report['assets_available']}/{report['assets_required']}\n"
            f"Pendências: {len(report['missing_assets'])}\n\n"
            f"Bindings: {folder/BINDINGS_NAME}\n\n"
            'Edite e revise as cópias antes do ZIP R57 de prévias.',
            parent=self)

    def _export_cover_drafts(self):
        if self.last_exported_path is None or self.last_story_proposal_path is None:
            messagebox.showwarning('Seleção e Stories necessários',
                'Exporte os Reels escolhidos e a proposta de Stories primeiro.',
                parent=self)
            return
        media=filedialog.askopenfilename(
            parent=self,
            title='Escolha o vídeo original exato usado pelo Analyzer',
            filetypes=[('Vídeos originais','*.mp4 *.mkv *.mov *.m4v *.webm')])
        if not media:
            return
        if not messagebox.askyesno(
                'Capas técnicas para revisão',
                'Confirmar extração de um quadro real por Reel e Story?\n'
                'O arquivo será recusado se SHA256 for diferente do original.\n'
                'Os PNGs serão rascunhos SEM aprovação ou publicação.',
                parent=self):
            return
        self.configure(cursor='watch')
        self.update_idletasks()
        try:
            from .r6_cover_drafts import export_cover_drafts
            folder=export_cover_drafts(
                self.review['inbox_folder'],self.last_exported_path,
                self.last_story_proposal_path,media,confirm_review_only=True)
            report=json.loads((folder/'COVER_DRAFT_MANIFEST.json').read_text(
                encoding='utf-8'))
        except (ValueError, OSError, TypeError, KeyError, RuntimeError) as exc:
            messagebox.showerror('Capas não extraídas',str(exc),parent=self)
            return
        finally:
            self.configure(cursor='')
        self.selection_status.set('CAPAS PARA REVISÃO: '+str(folder))
        messagebox.showinfo(
            'Capas extraídas do original',
            f"PNGs: {report['images_created']}\n"
            f"Vídeo: {report['source_sha256'][:16]}...\n\n"
            f'Pasta: {folder}\n\n'
            'Quadros ainda exigem curadoria, enquadramento e direitos.',
            parent=self)

    def _export_caption_drafts(self):
        if self.last_exported_path is None or self.last_story_proposal_path is None:
            messagebox.showwarning(
                'Seleção e Stories necessários',
                'Exporte primeiro os Reels escolhidos e a proposta de Stories.',
                parent=self)
            return
        if not messagebox.askyesno(
                'Gerar rascunhos de legendas?',
                'Recortar os textos ASR originais e ajustar seus tempos por corte?\n'
                'Texto e tempo NÃO foram revisados contra o áudio.\n'
                'Não haverá aprovação, render ou publicação.',
                parent=self):
            return
        self.configure(cursor='watch')
        self.update_idletasks()
        try:
            from .r6_caption_drafts import export_caption_drafts
            folder=export_caption_drafts(
                self.review['inbox_folder'],self.last_exported_path,
                self.last_story_proposal_path)
            report=json.loads((folder/'CAPTION_DRAFT_MANIFEST.json').read_text(
                encoding='utf-8'))
        except (ValueError, OSError, TypeError, KeyError) as exc:
            messagebox.showerror('Rascunhos de legendas bloqueados',str(exc),parent=self)
            return
        finally:
            self.configure(cursor='')
        self.selection_status.set('LEGENDAS RASCUNHO: '+str(folder))
        messagebox.showinfo(
            'Rascunhos criados para revisão',
            f"Com texto ASR: {report['clips_with_draft']}\n"
            f"Sem legendas de origem: {report['clips_without_cues']}\n\n"
            f"Pasta: {folder}\n\n"
            'Revise texto e tempo contra o vídeo antes de vincular ao R57.',
            parent=self)

    def _export_r6_evidence(self):
        if self.last_exported_path is None:
            messagebox.showwarning(
                'Exporte a seleção R6 primeiro',
                'Marque os Reels desejados e exporte o roteiro R6.',parent=self)
            return
        if not messagebox.askyesno(
                'Reaproveitar evidências do Analyzer?',
                'Copiar somente contact sheets JPEG e transcrições originais que '
                'já existirem no ZIP R6 validado?\n'
                'São materiais para revisão, NÃO capas finais nem legendas aprovadas.',
                parent=self):
            return
        self.configure(cursor='watch')
        self.update_idletasks()
        try:
            from .r6_evidence_reuse import export_r6_evidence
            folder=export_r6_evidence(
                self.review['inbox_folder'], self.last_exported_path)
            report=json.loads((folder/'EVIDENCE_REUSE_MANIFEST.json').read_text(encoding='utf-8'))
        except (ValueError, OSError, TypeError, KeyError) as exc:
            messagebox.showerror('Evidências não exportadas',str(exc),parent=self)
            return
        finally:
            self.configure(cursor='')
        self.selection_status.set('EVIDÊNCIAS R6: '+str(folder))
        messagebox.showinfo(
            'Evidências preservadas',
            f"Contatos visuais existentes: {report['reused_visual_count']}\n"
            f"Contatos visuais ausentes: {report['missing_visual_count']}\n"
            f"Transcrições originais: {report['existing_transcript_count']}\n\n"
            f'Pasta: {folder}\n\n'
            'Revise e prepare capas e legendas reais separadamente.',
            parent=self)

    def _export_asset_template(self):
        if self.last_exported_path is None or self.last_story_proposal_path is None:
            messagebox.showwarning('Roteiro e Stories necessários',
                'Exporte os Reels R6 e a proposta de Stories primeiro.',parent=self)
            return
        if not messagebox.askyesno('Checklist de assets reais',
                'Criar template JSON com caminhos vazios para capa, ASS e SRT?\n'
                'Não cria mídias, legendas nem ZIP R57.',parent=self):
            return
        try:
            from .r6_asset_bindings import save_asset_template
            path=save_asset_template(
                self.review['inbox_folder'], self.last_exported_path,
                self.last_story_proposal_path)
        except (ValueError, OSError, TypeError, KeyError) as exc:
            messagebox.showerror('Checklist bloqueado',str(exc),parent=self)
            return
        self.selection_status.set('CHECKLIST ASSETS: '+str(path))
        messagebox.showinfo('Template de assets salvo',
            f'Arquivo:\n{path}\n\n'
            'Preencha caminhos relativos dos arquivos reais e audite pela CLI.',
            parent=self)

    def _build_preview_r57(self):
        if self.last_exported_path is None or self.last_story_proposal_path is None:
            messagebox.showwarning(
                'Roteiro R6 e proposta de Stories obrigatórios',
                'Primeiro exporte os Reels selecionados e proponha os Stories.',
                parent=self)
            return
        bindings = filedialog.askopenfilename(
            parent=self,
            title='Selecione o JSON de assets preenchido com caminhos reais',
            filetypes=[('Arquivos JSON', '*.json')])
        if not bindings:
            return
        assets_root = filedialog.askdirectory(
            parent=self, title='Escolha a pasta que contém as capas e legendas reais')
        if not assets_root:
            return
        if not messagebox.askyesno(
                'Gerar R57 só para prévias?',
                'O Studio irá validar capas, ASS e SRT e criar um ZIP R57 '
                'importável somente para iniciar a revisão.\n'
                'As divisões de Stories NÃO foram aprovadas. '
                'Nenhum MP4 final ou publicação será executado.',
                parent=self):
            return
        self.configure(cursor='watch')
        self.update_idletasks()
        try:
            from .r6_r57_preview_package import build_preview_archive
            result = build_preview_archive(
                self.review['inbox_folder'],
                self.last_exported_path,
                self.last_story_proposal_path,
                bindings, assets_root,
                confirm_preview_only=True)
        except (ValueError, OSError, TypeError, KeyError) as exc:
            messagebox.showerror('ZIP R57 não gerado', str(exc), parent=self)
            return
        finally:
            self.configure(cursor='')
        self.selection_status.set('R57 PARA PRÉVIAS: ' + result['zip_path'])
        messagebox.showinfo(
            'Pacote R57 para revisão criado',
            f"ZIP validado: \n{result['zip_path']}\n\n"
            'Agora importe no Studio, associe a fonte original por SHA256 '
            'e revise as prévias antes de qualquer aprovação.',
            parent=self)

    def _prepare_r57_plan(self):
        if self.last_exported_path is None:
            messagebox.showwarning(
                'Exporte um roteiro primeiro',
                'Marque candidatos e exporte o roteiro R6 antes de preparar o plano R57.',
                parent=self)
            return
        if not messagebox.askyesno(
                'Plano de preparação R57',
                'Gerar checklist JSON de lacunas a partir do último roteiro exportado?\n'
                'NÃO cria ZIP R57, Stories, mídia ou aprovações.',
                parent=self):
            return
        try:
            from .r6_r57_bridge import export_r57_bridge
            path=export_r57_bridge(
                self.review['inbox_folder'],self.last_exported_path,
                story_proposal_path=self.last_story_proposal_path)
        except (ValueError, OSError, TypeError, KeyError) as exc:
            messagebox.showerror('Plano R57 bloqueado',str(exc),parent=self)
            return
        self.selection_status.set('PLANO R57 PENDENTE: '+str(path))
        messagebox.showinfo(
            'Plano de preparação exportado',
            f'Salvo em:\n{path}\n\n'
            'Importação R57 continua BLOQUEADA até Stories e assets revisados.',
            parent=self)

    def _export(self):
        chosen=set(self.chosen_ids)
        if not chosen:
            return messagebox.showwarning('Nenhum corte marcado',
                'Selecione candidatos, clique MARCAR SELECIONADOS e depois EXPORTAR MARCADOS.',
                parent=self)
        if self.current in chosen and len(self.tree.selection())==1:
            row=self.rows[self.current]
            old=self.overrides.get(self.current,{})
            if (self.details_title.get().strip()!=old.get('title',row['title_suggestion'])
                or self.details_layout.get()!=old.get('layout','preserve')
                or self.notes.get('1.0','end-1c')!=old.get('notes','')):
                return messagebox.showwarning('Edição não salva',
                    'Clique SALVAR TÍTULO / CÂMERA DE 1 CANDIDATO antes de exportar.',
                    parent=self)
        # Preserve first-pass ordering, but only for explicitly MARKED IDs.
        ids=[row['candidate_id'] for row in self.review['candidates']
             if row['candidate_id'] in chosen]
        flagged=sum(bool(self.rows[cid].get('blockers')) for cid in ids)
        repeated=len(ids)-len({(self.rows[cid]['start'],self.rows[cid]['end']) for cid in ids})
        if not messagebox.askyesno('Exportar roteiro pendente',
             f'{len(ids)} candidatos MARCADOS para roteiro de revisão.\n'
             f'{flagged} candidatos com alertas. {repeated} alternativas de mesmo intervalo.\n\n'
             'Somente JSON de edição: SEM MP4, SEM aprovação, SEM renderização.\n'
             'Os alertas e a proveniência ficarão no roteiro. Continuar?',
             parent=self):
            return
        try:
            path=export_editorial_draft(self.review,ids,overrides=self.overrides)
        except (ValueError,OSError,TypeError) as exc:
            messagebox.showerror('Não foi possível exportar',str(exc),parent=self)
            return
        if self.last_exported_path != path:
            self.last_story_proposal_path=None
        self.last_exported_path=path
        self.selection_status.set('ROTEIRO EXPORTADO: '+str(path))
        if self.on_export:
            self.on_export(path)
        messagebox.showinfo('Roteiro de revisão exportado',
             f'Salvo em:\n{path}\n\n'
             'JSON somente com decisões editoriais; fonte e projetos R57 intactos.',parent=self)
