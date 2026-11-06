"""Tkinter selection window for Analyzer R6 proposals.

Only reads validated Analyzer data; never opens R57 projects, renders video
or changes approvals. Saving produces a media-free review script.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox
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
        ttk.Label(story_actions,
                  text='Somente divisões técnicas da duração; confirme conteúdo e cortes depois.').pack(side='left')
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
                'Criar uma proposta de janelas contínuas, cada uma com no máximo 60 segundos?\\n'
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
            f'Proposta registrada em:\\n{path}\\n\\n'
            'Divisões ainda precisam de revisão editorial; nenhum Story foi aprovado.',
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
