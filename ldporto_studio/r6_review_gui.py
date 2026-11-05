"""Tkinter selection window for Analyzer R6 proposals.

Only reads validated Analyzer data; never opens R57 projects, renders video
or changes approvals. Saving produces a media-free review script.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox
from .r6_review import export_editorial_draft, LAYOUTS


class AnalyzerR6ReviewDialog(tk.Toplevel):
    def __init__(self, parent, review, on_export=None):
        super().__init__(parent)
        self.review=review
        self.on_export=on_export
        self.overrides={}
        self.current=None
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
                            'Prévia, áudio, câmera, legenda e direitos exigem revisão.').pack(anchor='w',pady=(0,9))
        host=ttk.PanedWindow(outer,orient='horizontal')
        host.pack(fill='both',expand=True)
        left=ttk.Frame(host,padding=(0,6,8,6))
        right=ttk.Frame(host,padding=(8,6,0,6))
        host.add(left,weight=3);host.add(right,weight=2)
        self.tree=ttk.Treeview(left,columns=('rank','start','duration','state'),show='tree headings',
                               selectmode='extended')
        self.tree.heading('#0',text='Candidato / título do Analyzer')
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
        for row in review['candidates']:
            self.tree.insert('', 'end',iid=row['candidate_id'],
                             text=row['title_suggestion'][:52],
                             values=(row['rank'],row['start'],
                                     row['duration_seconds'],row['candidate_state'][:22]))
        self.tree.bind('<<TreeviewSelect>>',self._on_select)
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
        footer=ttk.Frame(outer)
        footer.pack(fill='x',pady=(10,0))
        self.selection_status=tk.StringVar(value='Nenhum selecionado.')
        ttk.Label(footer,textvariable=self.selection_status).pack(side='left',fill='x',expand=True)
        ttk.Button(footer,text='EXPORTAR SELECIONADOS — SOMENTE ROTEIRO JSON',
                   command=self._export).pack(side='right')
        ttk.Button(footer,text='FECHAR',command=self.destroy).pack(side='right',padx=(0,8))

    def _on_select(self,event=None):
        selected=self.tree.selection()
        self.selection_status.set(
            f'{len(selected)} candidato(s) selecionado(s). '
            'Use Ctrl/Shift para múltiplos; o botão de edição individual exige um.')
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
        self.tree.item(cid,text=title[:52])
        self.selection_status.set(f'{cid}: título e câmera registrados para exportação.')

    def _export(self):
        chosen=set(self.tree.selection())
        if not chosen:
            messagebox.showwarning('Selecione os cortes','Escolha explicitamente um ou mais candidatos.',parent=self)
            return
        # Order follows the producer's first-pass catalog, not the order Tk emits IDs.
        ids=[row['candidate_id'] for row in self.review['candidates']
             if row['candidate_id'] in chosen]
        if not messagebox.askyesno('Exportar roteiro de revisão',
             f'Exportar {len(ids)} candidatos selecionados como roteiro JSON sem mídia?\n'
             'Nenhum corte será aprovado, renderizado ou publicado. '
             'Edições do formulário ainda não salvas não serão incluídas.',
             parent=self):
            return
        try:
            path=export_editorial_draft(self.review,ids,overrides=self.overrides)
        except (ValueError,OSError,TypeError) as exc:
            messagebox.showerror('Não foi possível exportar',str(exc),parent=self)
            return
        self.selection_status.set('ROTEIRO SALVO: '+str(path))
        if self.on_export:
            self.on_export(path)
        messagebox.showinfo('Roteiro de revisão exportado',
             f'Salvo em:\n{path}\n\n'
             'JSON somente com decisões editoriais; fonte e projetos R57 intactos.',parent=self)
