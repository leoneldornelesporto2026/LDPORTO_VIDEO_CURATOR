"""Windows-oriented Tk GUI. Every slow operation executes in a worker thread."""
from __future__ import annotations

from io import BytesIO
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from .core import Project
from .rendering import render_item,extract_editorial_assets,create_cover_from_frame,generate_premium_covers,binaries
from .youtube_download import download_from_youtube, suggested_youtube_url, parse_youtube_url
from .workspace import project_output_root, import_existing_project
from .catalog import discover_catalog, reviewable_catalog, catalog_label, input_root
from .editorial_script import export_project_script
from .r6_review import read_analyzer_review


def open_file(path):
    p=Path(path)
    if sys.platform=='win32':
        os.startfile(str(p))
    elif sys.platform=='darwin':
        subprocess.Popen(['open',str(p)])
    else:
        subprocess.Popen(['xdg-open',str(p)])


class CuratorApp(tk.Tk):
    def __init__(self,example=None):
        super().__init__()
        self.title('L.D.PORTO • VIDEO CURATOR STUDIO 1.0 | Reels + Stories')
        self.geometry('1330x875')
        self.minsize(1120,700)
        self.configure(bg='#14171d')
        self.project=None
        self.example=Path(example).resolve() if example else None
        self.default_workspace=project_output_root()
        self.q=queue.Queue()
        self.busy=False
        self.cancel=threading.Event()
        self.preview_photo=None
        self.selected=None
        self.review_after_download=False
        self.catalog_entries=[]
        self.catalog_by_label={}
        self.catalog_show_all=tk.BooleanVar(value=False)
        self._build()
        self.after(90,self._poll)
        # The user chooses a show; never automatically overwrite the active
        # selection by silently opening the bundled Charlie Brown Jr. example.
        self.after(350,self.scan_catalog)

    def _build(self):
        style=ttk.Style(self)
        style.theme_use('clam')
        style.configure('TFrame',background='#14171d')
        style.configure('TLabel',background='#14171d',foreground='#e9eef6',font=('Segoe UI',10))
        style.configure('TButton',padding=(12,7),font=('Segoe UI',9,'bold'))
        style.configure('TCheckbutton',background='#14171d',foreground='#e9eef6')
        style.configure('Treeview',background='#20252f',foreground='#e8edf6',fieldbackground='#20252f',rowheight=29,font=('Segoe UI',9))
        style.configure('Treeview.Heading',background='#292f3c',foreground='white',font=('Segoe UI',9,'bold'))
        style.map('Treeview',background=[('selected','#a43b32')])
        style.configure('TCombobox',fieldbackground='#eaf0f7')
        container=ttk.Frame(self,padding=14)
        container.pack(fill='both',expand=True)
        top=ttk.Frame(container)
        top.pack(fill='x')
        ttk.Label(top,text='L.D.PORTO  /  VIDEO CURATOR STUDIO',font=('Segoe UI',20,'bold'),foreground='#f7d454').pack(side='left')
        ttk.Label(top,text='BIBLIOTECA DE SHOWS • CORTES REVISÁVEIS',foreground='#a9b6ca').pack(side='right')

        library=ttk.LabelFrame(container,text='VÍDEOS JÁ PROCESSADOS — input/ + output/projects/')
        library.pack(fill='x',pady=(10,1))
        library_row=ttk.Frame(library)
        library_row.pack(fill='x',padx=8,pady=(5,3))
        self.catalog_selection=tk.StringVar(value='')
        self.catalog_dropdown=ttk.Combobox(library_row,textvariable=self.catalog_selection,
                                           state='readonly',width=84)
        self.catalog_dropdown.pack(side='left',fill='x',expand=True,padx=(0,8))
        self.catalog_dropdown.bind('<<ComboboxSelected>>',self.on_catalog_selected)
        ttk.Button(library_row,text='ATUALIZAR INPUT',command=self.scan_catalog).pack(side='left',padx=(0,6))
        ttk.Checkbutton(library_row,text='Mostrar todos (inclui testes)',
                        variable=self.catalog_show_all,
                        command=self.scan_catalog).pack(side='left',padx=(0,6))
        ttk.Button(library_row,text='ABRIR / SELECIONAR CORTES',
                   command=self.open_catalog_selection).pack(side='left')
        self.catalog_description=tk.StringVar(
            value='Procurando shows analisados em input/ e projetos com cortes em output/projects/...')
        ttk.Label(library,textvariable=self.catalog_description,foreground='#fbd68d',
                  wraplength=1220).pack(anchor='w',padx=9,pady=(2,6))
        toolbar=ttk.Frame(container)
        toolbar.pack(fill='x',pady=(12,10))
        for label,fn in [
          ('CARREGAR CURADORIA ZIP',self.import_zip),('ABRIR PROJETO',self.open_project),
          ('EXEMPLO R57',self.load_example),('VINCULAR MP4 ORIGINAL',self.select_media),
          ('EXPORTAR CAPAS + PLANOS',self.export_assets),
          ('IMPORTAR PROJETO ANTIGO',self.import_old_project)]:
            ttk.Button(toolbar,text=label,command=fn).pack(side='left',padx=(0,7))
        download_row=ttk.Frame(container)
        download_row.pack(fill='x',pady=(0,9))
        ttk.Label(download_row,text='URL do YouTube:').pack(side='left',padx=(0,8))
        self.youtube_url=tk.StringVar(value='')
        ttk.Entry(download_row,textvariable=self.youtube_url,width=62).pack(side='left',fill='x',expand=True,padx=(0,8))
        ttk.Button(download_row,text='BAIXAR VÍDEO DO YOUTUBE',command=self.download_youtube).pack(side='left')
        review_row=ttk.Frame(container)
        review_row.pack(fill='x',pady=(0,8))
        ttk.Button(review_row,text='USAR DOWNLOAD NAS PRÉVIAS (REVISÃO)',
                   command=self.review_download).pack(side='left')
        ttk.Label(review_row,text='Revisão individual do áudio/câmera obrigatória.',
                  foreground='#fbd68d').pack(side='left',padx=10)
        self.source_status=tk.StringVar(value='Selecione uma curadoria ZIP; o MP4 é verificado pelo SHA256 do Analyzer.')
        ttk.Label(container,textvariable=self.source_status,foreground='#fbd68d',wraplength=1240).pack(fill='x',pady=(0,9))
        split=ttk.PanedWindow(container,orient='horizontal');split.pack(fill='both',expand=True)
        left=ttk.Frame(split,padding=4)
        right_host=ttk.Frame(split,padding=4)
        split.add(left,weight=5);split.add(right_host,weight=4)
        right_scroll=tk.Canvas(right_host,bg='#14171d',highlightthickness=0,borderwidth=0)
        right_bar=ttk.Scrollbar(right_host,orient='vertical',command=right_scroll.yview)
        right_scroll.configure(yscrollcommand=right_bar.set)
        right_bar.pack(side='right',fill='y')
        right_scroll.pack(side='left',fill='both',expand=True)
        right=ttk.Frame(right_scroll,padding=4)
        right_win=right_scroll.create_window((0,0),window=right,anchor='nw')
        right.bind('<Configure>',lambda event:right_scroll.configure(scrollregion=right_scroll.bbox('all')))
        right_scroll.bind('<Configure>',lambda event:right_scroll.itemconfigure(right_win,width=event.width))
        ttk.Label(left,text='Cortes da curadoria',font=('Segoe UI',13,'bold')).pack(anchor='w',pady=(0,5))
        filt=ttk.Frame(left);filt.pack(fill='x')
        self.kind_filter=tk.StringVar(value='Todos')
        for label,value in [('Todos','Todos'),('Reels','reels'),('Stories','stories')]:
            ttk.Radiobutton(filt,text=label,value=value,variable=self.kind_filter,
                command=self.refresh_table).pack(side='left',padx=(0,8))
        tree_box=ttk.Frame(left);tree_box.pack(fill='both',expand=True,pady=(7,0))
        self.tree=ttk.Treeview(tree_box,columns=('tipo','inicio','duracao','status'),show='tree headings',selectmode='browse')
        self.tree.heading('#0',text='Título do vídeo');self.tree.column('#0',width=300,minwidth=205)
        for key,title,width in [('tipo','Tipo',55),('inicio','Início',75),('duracao','Duração',73),('status','Situação',150)]:
            self.tree.heading(key,text=title);self.tree.column(key,width=width,minwidth=50,anchor='center')
        self.tree.pack(side='left',fill='both',expand=True)
        sc=ttk.Scrollbar(tree_box,command=self.tree.yview);sc.pack(side='right',fill='y')
        self.tree.configure(yscrollcommand=sc.set)
        self.tree.bind('<<TreeviewSelect>>',self.on_select)
        ttk.Label(right,text='Edição & aprovação',font=('Segoe UI',13,'bold')).pack(anchor='w',pady=(0,5))
        controls=ttk.Frame(right);controls.pack(fill='x')
        self.cover_label=ttk.Label(controls,text='CAPA 9:16\nSelecione um corte',anchor='center',justify='center')
        self.cover_label.grid(row=0,column=0,rowspan=10,padx=(0,12),sticky='n')
        cf=ttk.Frame(controls);cf.grid(row=0,column=1,sticky='nsew')
        controls.columnconfigure(1,weight=1)
        def field(label,value):
            ttk.Label(cf,text=label).pack(anchor='w',pady=(7,2))
            v=tk.StringVar(value=value)
            ttk.Entry(cf,textvariable=v).pack(fill='x')
            return v
        self.edit_title=field('Título / gancho','')
        timebox=ttk.Frame(cf);timebox.pack(fill='x')
        a=ttk.Frame(timebox);a.pack(side='left',fill='x',expand=True,padx=(0,6))
        b=ttk.Frame(timebox);b.pack(side='left',fill='x',expand=True)
        ttk.Label(a,text='Entrada (segundos)').pack(anchor='w',pady=(8,2))
        self.edit_start=tk.StringVar();ttk.Entry(a,textvariable=self.edit_start,width=10).pack(fill='x')
        ttk.Label(b,text='Saída (segundos)').pack(anchor='w',pady=(8,2))
        self.edit_end=tk.StringVar();ttk.Entry(b,textvariable=self.edit_end,width=10).pack(fill='x')
        ttk.Label(cf,text='Enquadramento (automático com fallback 16:9)').pack(anchor='w',pady=(8,2))
        self.layout=tk.StringVar(value='preserve')
        self.layout_select=ttk.Combobox(cf,textvariable=self.layout,values=('preserve','center_crop','solo_fit','smart_zoom'),state='readonly')
        self.layout_select.pack(fill='x')
        ttk.Label(cf,text='Centro crop: 0 esquerda — 1 direita').pack(anchor='w',pady=(8,1))
        self.center_var=tk.DoubleVar(value=.5)
        ttk.Scale(cf,variable=self.center_var,from_=0.,to=1.,orient='horizontal').pack(fill='x')
        self.title_overlay=tk.BooleanVar(value=True)
        ttk.Checkbutton(cf,text='Título premium na abertura (3,2s)',variable=self.title_overlay).pack(anchor='w',pady=2)
        self.captions_verified=tk.BooleanVar(value=False)
        self.subtitles=tk.BooleanVar(value=False)
        ttk.Checkbutton(cf,text='Conferi transcrição e áudio desta legenda',variable=self.captions_verified).pack(anchor='w',pady=2)
        ttk.Checkbutton(cf,text='Incluir karaokê ASS no vídeo',variable=self.subtitles).pack(anchor='w',pady=2)
        ttk.Button(cf,text='VER SRT PARA REVISÃO',command=self.open_srt).pack(fill='x',pady=(7,0))
        ttk.Button(cf,text='2ª CHECAGEM DE LEGENDAS (SRT/ASS)',
                   command=self.second_caption_check).pack(fill='x',pady=(5,0))
        ttk.Button(cf,text='IMPORTAR ASS CORRIGIDA',command=self.import_ass).pack(fill='x',pady=(6,0))
        ttk.Button(cf,text='SALVAR EDIÇÃO',command=self.save_edit).pack(fill='x',pady=(6,0))
        sep=ttk.Separator(right);sep.pack(fill='x',pady=12)
        state=ttk.Frame(right);state.pack(fill='x')
        self.status_label=tk.StringVar(value='PENDENTE: importar pacote e selecionar mídia')
        ttk.Label(state,textvariable=self.status_label,font=('Segoe UI',10,'bold'),foreground='#ffe077',wraplength=420).pack(anchor='w',pady=3)
        self.audio_checked=tk.BooleanVar(value=False)
        self.camera_checked=tk.BooleanVar(value=False)
        self.rights_checked=tk.BooleanVar(value=False)
        ttk.Checkbutton(state,text='Assisti à prévia e revisei áudio / contexto',variable=self.audio_checked).pack(anchor='w')
        ttk.Checkbutton(state,text='Revisei o enquadramento da prévia',variable=self.camera_checked).pack(anchor='w')
        ttk.Checkbutton(state,text='Tenho as autorizações necessárias de uso',variable=self.rights_checked).pack(anchor='w')
        actions=ttk.Frame(right);actions.pack(fill='x',pady=(12,4))
        for label,fn in [('GERAR PRÉVIA',self.preview_selected),('ABRIR PRÉVIA',self.open_preview),
                         ('APROVAR PRÉVIA',self.approve_selected),('RENDER FINAL',self.final_selected)]:
            ttk.Button(actions,text=label,command=fn).pack(side='left',padx=(0,5))
        review_tools=ttk.Frame(right);review_tools.pack(fill='x',pady=(3,6))
        ttk.Button(review_tools,text='PRÉVIA INTELIGENTE + LEGENDAS',
                   command=self.smart_caption_preview).pack(side='left',padx=(0,6))
        ttk.Button(review_tools,text='ABRIR REVISÃO COM LEGENDAS',
                   command=self.open_smart_caption_preview).pack(side='left')
        tools=ttk.Frame(right);tools.pack(fill='x',pady=4)
        for label,fn in [('Prévia de todos os Reels',lambda:self.batch('reels')),
                         ('Prévia de todos os Stories',lambda:self.batch('stories')),
                         ('Finais aprovados',self.batch_final),
                         ('Gerar capa do MP4',self.make_cover)]:
            ttk.Button(tools,text=label,command=fn).pack(side='left',padx=(0,4))
        ttk.Button(right,text='APLICAR SMART ZOOM AOS REELS',command=self.apply_smart_preset).pack(fill='x',pady=(6,2))
        ttk.Button(right,text='GERAR CAPAS PREMIUM DO SHOW',command=self.batch_premium_covers).pack(fill='x',pady=2)
        ttk.Button(right,text='EXPORTAR ROTEIRO PARA GIT (SEM VÍDEO)',
                   command=self.export_script).pack(fill='x',pady=2)
        ttk.Button(right,text='CANCELAR PROCESSAMENTO ATUAL',command=self.cancel_active).pack(anchor='w',pady=(4,0))
        ttk.Label(container,text='EXECUÇÃO • original preservado • revisão humana antes dos finais • sem publicação automática',
                  foreground='#94a8bd').pack(anchor='w',pady=(10,4))
        self.progress=ttk.Progressbar(container,mode='determinate',maximum=100);self.progress.pack(fill='x')
        self.log=tk.Text(container,height=5,bg='#090d13',fg='#cee3f4',insertbackground='white',font=('Consolas',9),wrap='word')
        self.log.pack(fill='x',pady=(5,0))
        self.log_message('Biblioteca de shows disponível. Selecione um projeto ou pacote processado; nada é aprovado automaticamente.')

    def log_message(self,message):
        self.log.insert('end',message+'\n');self.log.see('end')

    def _task(self,label,fn):
        if self.busy:return
        self.busy=True
        self.cancel.clear()
        self.progress['value']=0
        self.log_message(label)
        def work():
            try:
                result=fn()
                self.q.put(('done',result))
            except Exception as e:
                self.q.put(('error',str(e)))
        threading.Thread(target=work,daemon=True).start()

    def cancel_active(self):
        if self.busy:
            self.cancel.set()
            self.log_message('Cancelamento solicitado; tentativas incompletas serão preservadas.')

    def _poll(self):
        try:
            while True:
                action,payload=self.q.get_nowait()
                if action=='progress':
                    if payload is not None:self.progress['value']=int(payload*100)
                elif action=='youtube_url':
                    self.youtube_url.set(payload)
                elif action=='catalog_entries':
                    previous=self.catalog_by_label.get(self.catalog_selection.get())
                    previous_id=previous['id'] if previous else None
                    self.catalog_entries=payload
                    labels=[]
                    by_label={}
                    for entry in payload:
                        base=catalog_label(entry)
                        label=base
                        if label in by_label:
                            label=base+' | ID '+entry['id'][:7]
                        labels.append(label)
                        by_label[label]=entry
                    self.catalog_by_label=by_label
                    self.catalog_dropdown['values']=labels
                    chosen=next((label for label,entry in by_label.items()
                                 if entry['id']==previous_id),None)
                    self.catalog_selection.set(chosen or (labels[0] if labels else ''))
                    self.on_catalog_selected()
                    self.log_message(f'Biblioteca atualizada: {len(payload)} item(ns) real(is) encontrados.')
                elif action=='r6_review':
                    from .r6_review_gui import AnalyzerR6ReviewDialog
                    AnalyzerR6ReviewDialog(
                        self,payload,
                        on_export=lambda path:self.log_message('Roteiro R6 exportado: '+str(path)))
                elif action=='open_project':
                    self.project=Project(payload)
                    self.youtube_url.set(self.project.state.get('youtube_url') or suggested_youtube_url(self.project.package))
                    self.refresh_table()
                    self.log_message('Projeto adotado na pasta output: '+str(payload))
                elif action=='log':
                    self.log_message(payload)
                elif action=='download_report':
                    reuse=bool(payload.get('reused_existing'))
                    self.log_message(('Vídeo já estava salvo; download repetido evitado. ' if reuse
                                      else 'Vídeo baixado e verificado. ') +
                                     'Arquivo: '+payload['path'])
                    if payload['linked']:
                        self.log_message('Fonte exata do Analyzer vinculada. Gere uma prévia.')
                    elif payload.get('duration_compatible'):
                        self.review_after_download=messagebox.askyesno(
                            'Vídeo pronto para prévias — revisão necessária',
                            ('O MP4 já estava no projeto.' if reuse else 'O MP4 foi baixado com sucesso.')+
                            '\n\nÉ o mesmo ID do YouTube, e a duração é compatível com a R57. '
                            'O SHA256 mudou, possivelmente por outra codificação.\n\n'
                            'Isso NÃO garante que o áudio, as cenas e os timestamps coincidam. '
                            'Você precisará assistir e conferir CADA prévia antes do final.\n\n'
                            'Vincular este arquivo para GERAR PRÉVIAS agora?'
                        )
                        if not self.review_after_download:
                            self.log_message('Download preservado; revisão de fonte não autorizada.')
                    else:
                        messagebox.showwarning('Duração incompatível com a R57',
                            'Vídeo salvo, mas duração incompatível com a análise. '
                            'Os intervalos dos cortes não podem ser reaproveitados com segurança. '
                            'É necessário refazer a análise desse MP4.')
                elif action=='done':
                    self.busy=False
                    self.progress['value']=100
                    self.log_message('Concluído: '+str(payload))
                    self.refresh_table()
                    if self.selected:self.show_details(self.selected)
                    if self.review_after_download:
                        self.review_after_download=False
                        self._task('Vinculando MP4 existente para prévias de revisão...',
                            lambda:self.project.review_download_for_previews(confirm_timeline=True))
                elif action=='error':
                    self.busy=False
                    self.log_message('ERRO: '+payload)
                    messagebox.showerror('Operação não concluída',payload)
        except queue.Empty: pass
        self.after(120,self._poll)

    def scan_catalog(self):
        if self.busy:
            self.after(650,self.scan_catalog)
            return
        include_all=self.catalog_show_all.get()
        def run():
            all_entries=discover_catalog()
            entries=all_entries if include_all else reviewable_catalog(all_entries)
            self.q.put(('catalog_entries',entries))
            hidden=len(all_entries)-len(entries)
            return (
                f'{len(entries)} itens exibidos de {len(all_entries)} encontrados; '
                f'{hidden} registros de diagnóstico/sem candidatos ocultos na visualização. '
                'Nenhum arquivo foi modificado.'
            )
        self._task('Verificando pastas input/ e output/projects/ (somente leitura)...',run)

    def on_catalog_selected(self,event=None):
        entry=self.catalog_by_label.get(self.catalog_selection.get())
        if entry is None:
            self.catalog_description.set(
                'Nenhum pacote analisado encontrado. Copie o ZIP do Analyzer para input/analyzer/<video_id>/<run_id>/ '
                'ou selecione EXEMPLO R57. Vídeos sem análise não aparecem como curadorias.')
            return
        detail=(f'{entry["status"]}  |  {entry["reels"]} Reels / {entry["stories"]} Stories'
                if entry['kind'] in ('project','curator_zip')
                else f'{entry["status"]}  |  {entry["candidates"]} candidatos para segunda curadoria')
        if entry['kind'] in ('invalid_zip','invalid_project'):
            detail=entry['status']+' — não processar até corrigir a origem'
        self.catalog_description.set(detail+'  |  '+entry['path'])

    def open_catalog_selection(self):
        if self.busy:return
        entry=self.catalog_by_label.get(self.catalog_selection.get())
        if entry is None:
            return messagebox.showwarning('Nenhum vídeo processado',
                'Coloque um ZIP validado do Analyzer em input/ ou use EXEMPLO R57.')
        kind=entry['kind']
        path=Path(entry['path'])
        if kind=='project':
            self._task('Abrindo show e seus Reels/Stories já processados...',
                       lambda: self.q.put(('open_project',path)) or 'Projeto selecionado')
        elif kind=='curator_zip':
            self._load_archive(path)
        elif kind=='analyzer_zip':
            def work():
                review=read_analyzer_review(path.parent)
                self.q.put(('r6_review',review))
                return (f"Análise R6 verificada: {review['candidate_count']} candidatos reais, "
                        f"{review['story_candidate_count']} Stories; "
                        "selecione os trechos na janela de segunda curadoria.")
            self._task('Validando ZIP R6, manifesto e abrindo candidatos sem renderizar...',work)
        else:
            messagebox.showerror('Pacote não importável',
                                 entry['status']+'\n\nArquivo: '+str(path))

    def _project_location(self,archive):
        from .core import sha256_file
        digest=sha256_file(archive)
        return self.default_workspace/(Path(archive).stem[:45]+'_'+digest[:10])

    def _load_archive(self,archive):
        loc=self._project_location(archive)
        def run():
            self.project=Project.create(archive,loc)
            self.q.put(('youtube_url',self.project.state.get('youtube_url') or suggested_youtube_url(self.project.package)))
            self.q.put(('log','Projeto importado com integridade: '+str(loc)))
            return f'{len(self.project.package.clips)} cortes carregados'
        self._task('Importando arquivo e validando todos os SHA256...',run)

    def import_zip(self):
        if self.busy:return
        path=filedialog.askopenfilename(title='Escolha ZIP editorial compatível (R57)',filetypes=[('Curadoria ZIP','*.zip')])
        if path:self._load_archive(path)

    def load_example(self):
        if self.busy:return
        if self.example and self.example.is_file():self._load_archive(self.example)
        else: messagebox.showinfo('Exemplo não encontrado','Coloque CURADORIA_R57.zip na pasta example ou importe um ZIP na interface.')

    def import_old_project(self):
        if self.busy:return
        folder=filedialog.askdirectory(
            title='Selecione o projeto antigo (pasta que contém project.json)',
            initialdir=str(Path.home()/'Videos'))
        if not folder:return
        if not messagebox.askyesno('Copiar projeto para output',
             'O projeto antigo será COPIADO para output/projects dentro deste código. '
             'Downloads, MP4s, capas e aprovações serão preservados. '
             'Nada será removido da pasta original. Continuar?'):
            return
        def run():
            target=import_existing_project(folder,self.default_workspace)
            self.q.put(('open_project',target))
            return 'Migração por cópia concluída: '+str(target)
        self._task('Copiando projeto para output (sem apagar a origem)...',run)

    def open_project(self):
        if self.busy:return
        folder=filedialog.askdirectory(title='Selecione a pasta com project.json',initialdir=str(self.default_workspace))
        if folder:
            try:
                self.project=Project(folder)
                self.youtube_url.set(self.project.state.get('youtube_url') or suggested_youtube_url(self.project.package))
                self.refresh_table()
                self.log_message('Projeto aberto: '+folder)
            except Exception as e:messagebox.showerror('Não foi possível abrir projeto',str(e))

    def refresh_table(self):
        if not self.project:return
        selected=self.selected
        self.tree.delete(*self.tree.get_children())
        kind=self.kind_filter.get()
        for c in self.project.package.items(kind):
            title=self.project.settings(c.id)['title']
            self.tree.insert('', 'end',iid=c.id,text=title[:54],values=(
                'REEL' if c.kind=='reels' else 'STORY',
                f'{c.start/60:.1f}m',f'{c.duration:.1f}s',self.project.status(c.id).replace('_',' ')))
        if selected in self.tree.get_children():self.tree.selection_set(selected)
        elif self.tree.get_children():
            self.tree.selection_set(self.tree.get_children()[0]);self.selected=self.tree.get_children()[0]
        mode=self.project.state.get('media_mode','')
        descriptor=' [FONTE ALTERNATIVA: SINCRONIA A REVISAR]' if mode=='ALTERNATE_REVIEW_SOURCE' else ''
        latest=next((r for r in reversed(self.project.state.get('download_history',[]))
            if isinstance(r,dict) and r.get('status')=='SOURCE_REVIEW_REQUIRED'),None)
        pending='DOWNLOAD SALVO — clique BAIXAR para reaproveitar e liberar prévias de revisão' if latest else 'AUSENTE — baixe o vídeo do YouTube'
        self.source_status.set('Curadoria: '+str(len(self.project.package.clips))+' cortes | MP4: '+
            (self.project.state['media_path'] or pending)+descriptor)
        if self.selected:self.show_details(self.selected)

    def on_select(self,event=None):
        selected=self.tree.selection()
        if selected:self.selected=selected[0];self.show_details(self.selected)

    def show_details(self,cid):
        if not self.project:return
        c=self.project.package.clips[cid]
        s=self.project.settings(cid)
        self.edit_title.set(s['title']);self.edit_start.set(f'{s["source_start"]:.3f}');self.edit_end.set(f'{s["source_end"]:.3f}')
        self.layout.set(s['layout']);self.center_var.set(float(s['center_x']))
        self.subtitles.set(s['subtitles']);self.captions_verified.set(s['captions_verified'])
        self.title_overlay.set(s['title_overlay']);self.audio_checked.set(s['audio_reviewed'])
        self.camera_checked.set(s['camera_reviewed']);self.rights_checked.set(s['rights_verified'])
        self.status_label.set(cid+' · '+self.project.status(cid)+' | LEGENDAS: '+
             ('CONFERIDAS' if s['captions_verified'] else 'RASCUNHO ATÉ REVISÃO'))
        self.cover_label.config(image='',text='Carregando capa...')
        try:
            from PIL import Image,ImageTk
            record=self.project.preview_record(cid)
            upgraded=(self.project.dir/record['relative_path']).parent/'CAPA_PREMIUM.png' if record else None
            if upgraded and upgraded.is_file():
                with Image.open(upgraded) as current:
                    image=current.convert('RGB')
                    image.thumbnail((205,365))
                    self.preview_photo=ImageTk.PhotoImage(image)
            else:
                with Image.open(BytesIO(self.project.package.data(c.thumbnail))) as original:
                    image=original.convert('RGB')
                    image.thumbnail((205,365))
                    self.preview_photo=ImageTk.PhotoImage(image)
            self.cover_label.configure(image=self.preview_photo,text='')
        except Exception:
            self.cover_label.configure(text='CAPA PNG disponível\nno pacote de curadoria',image='')

    def _save(self):
        if not self.project or not self.selected:raise ValueError('Selecione um corte')
        return self.project.update(self.selected,title=self.edit_title.get(),
            source_start=float(self.edit_start.get()),source_end=float(self.edit_end.get()),
            layout=self.layout.get(),center_x=float(self.center_var.get()),
            title_overlay=self.title_overlay.get(),subtitles=self.subtitles.get(),
            captions_verified=self.captions_verified.get(),audio_reviewed=self.audio_checked.get(),
            camera_reviewed=self.camera_checked.get(),rights_verified=self.rights_checked.get())

    def save_edit(self):
        if self.busy:return
        try:self._save();self.refresh_table();self.log_message(self.selected+': alterações salvas sem sobrescrever a análise')
        except Exception as e:messagebox.showerror('Dados inválidos',str(e))

    def select_media(self):
        if not self.project:return messagebox.showwarning('Importe primeiro','Importe a curadoria ZIP antes de selecionar o MP4.')
        if self.busy:return
        path=filedialog.askopenfilename(title='MP4 original do Analyzer',filetypes=[('Mídia original','*.mp4 *.mkv *.webm *.mov *.m4v')])
        if path:self._task('Conferindo SHA256 do original e inspecionando streams...',lambda:self.project.set_media(path))

    def download_youtube(self):
        if self.busy:return
        if not self.project:
            return messagebox.showwarning('Importe primeiro','Carregue a curadoria ZIP antes do download.')
        url=self.youtube_url.get().strip()
        try:
            parse_youtube_url(url)
        except ValueError as error:
            return messagebox.showerror('Link inválido',str(error))
        if not messagebox.askyesno('Usar vídeo do YouTube',
             'O Studio vai REAPROVEITAR um MP4 já salvo e íntegro, se existir. '
             'Novos downloads ficam em input/videos/ do Curator, ignorados pelo Git.\n\n'
             'Baixe apenas conteúdo para o qual tenha autorização de uso.\n\n'
             'Se a codificação divergir da análise, você poderá confirmar o uso '
             'para PRÉVIAS (não finais aprovados). Continuar?'):
            return
        self.review_after_download=False
        def work():
            result=download_from_youtube(self.project,url,cancel=self.cancel,
                progress=lambda event:self.q.put(('progress',event.get('fraction'))))
            self.q.put(('download_report',result))
            return result['status']+' — '+result['path']
        self._task('Procurando MP4 já salvo; baixando somente se necessário...',work)

    def review_download(self):
        if self.busy:return
        if not self.project:
            return messagebox.showwarning('Importe primeiro','Carregue a curadoria R57.')
        records=[r for r in self.project.state.get('download_history',[])
                 if r.get('status')=='SOURCE_REVIEW_REQUIRED']
        if not records:
            return messagebox.showwarning('Sem download','Baixe o vídeo primeiro.')
        record=records[-1]
        try:
            delta=float(record['duration_seconds'])-self.project.package.source_duration
        except (KeyError,TypeError,ValueError):
            return messagebox.showerror('Dados incompletos','Download sem duração verificável.')
        if abs(delta)>3:
            return messagebox.showerror('Duração incompatível',
                f'O vídeo tem {record["duration_seconds"]:.2f}s e a curadoria espera '
                f'{self.project.package.source_duration:.2f}s (diferença {delta:.2f}s). '
                'Os timestamps podem estar deslocados. Refaça a análise desse MP4.')
        if not messagebox.askyesno('Revisão de mídia baixada',
            'O vídeo tem a mesma identificação e duração aproximada, mas SHA256 DIFERENTE.\n\n'
            'Isso NÃO comprova que os momentos estejam sincronizados com a curadoria.\n'
            'O vídeo será liberado apenas para PRÉVIAS. É obrigatório assistir e conferir '
            'áudio, contexto e câmera em CADA corte, antes de aprovar finais.\n\n'
            'Não altera o ZIP original nem os hashes da análise. Continuar?'):
            return
        self._task('Conferindo e vinculando fonte alternativa apenas para PRÉVIAS...',
                   lambda:self.project.review_download_for_previews(confirm_timeline=True))

    def open_srt(self):
        if not self.project or not self.selected:return
        c=self.project.package.clips[self.selected]
        out=self.project.dir/'exports'/'review'/c.id
        out.mkdir(parents=True,exist_ok=True)
        p=out/'LEGENDA_RASCUNHO.srt'
        original=self.project.package.data(c.caption_srt)
        if not p.exists():
            p.write_bytes(original)
        # Never clobber a local correction made after opening the draft.
        open_file(p)
        self.log_message('SRT aberta sem sobrescrever edições existentes; '
                         'confira palavras e tempos ouvindo o vídeo. '
                         'A ASS corrigida deve ser importada separadamente.')

    def second_caption_check(self):
        if self.busy or not self.project or not self.selected:return
        try:
            from .caption_second_pass import save_caption_second_pass_report
            result=save_caption_second_pass_report(self.project,self.selected)
            report=json.loads(result.read_text(encoding='utf-8'))
        except (ValueError,OSError,TypeError,KeyError) as exc:
            return messagebox.showerror('Segunda checagem bloqueada',str(exc))
        self.log_message('2ª checagem estrutural — ouvir o trecho antes de '
                         'marcar texto e áudio conferidos: '+str(result))
        messagebox.showinfo(
            '2ª checagem da legenda (NÃO é aprovação)',
            f"Linhas SRT: {report['cue_count']}\n"
            f"Diálogos ASS: {report['ass_dialogue_count']}\n"
            f"Alertas: {', '.join(report['flags']) or 'sem alertas estruturais'}\n\n"
            'O sistema ainda NÃO verificou o áudio falado.\n'
            'Ouça e corrija texto/tempos antes de ativar as legendas.\n\n'
            f'Relatório: {result}')
        open_file(result)

    def import_ass(self):
        if self.busy or not self.project or not self.selected:return
        path=filedialog.askopenfilename(title='Importe a legenda ASS corrigida e validada',
                                       filetypes=[('Legenda ASS','*.ass')])
        if not path:return
        try:
            dest=self.project.import_caption(self.selected,path)
            self.show_details(self.selected)
            self.refresh_table()
            self.log_message('ASS corrigida importada: '+str(dest)+'; reveja áudio antes de ativá-la.')
        except Exception as error:
            messagebox.showerror('Legenda não importada',str(error))

    def export_assets(self):
        if not self.project:return messagebox.showwarning('Importe primeiro','Importe a curadoria ZIP.')
        self._task('Exportando todas as 72 capas, legendas e descrições originais...',
                   lambda:extract_editorial_assets(self.project))

    def _render(self,preview):
        if self.busy:return
        if not self.project or not self.selected:return
        try:self._save()
        except Exception as e:return messagebox.showerror('Revise os campos',str(e))
        cid=self.selected
        self._task(('Prévia' if preview else 'Final')+' de '+cid,
          lambda:render_item(self.project,cid,preview=preview,
              progress=lambda value,item:self.q.put(('progress',value)),cancel=self.cancel))

    def _find_analyzer_inbox_for_project(self):
        """Find only source-SHA matching Analyzer receipts, never guess from title."""
        source=self.project.package.source_sha
        root=input_root()/'analyzer'
        if not root.is_dir():
            return None
        video_id=self.project.package.plan.get('source_video_id')
        safe_id=(isinstance(video_id,str) and 1<=len(video_id)<=32
                 and all(char.isalnum() or char in '_-' for char in video_id))
        bases=[root/video_id] if safe_id else []
        if not any(p.is_dir() for p in bases):
            bases=[p for p in root.iterdir() if p.is_dir() and not p.is_symlink()]
        matching=[]
        for base in bases:
            if not base.is_dir() or base.is_symlink():continue
            for item in base.iterdir():
                if not item.is_dir() or item.is_symlink():continue
                receipt=item/'ANALYZER_TO_CURATOR_HANDOFF.json'
                if not receipt.is_file() or receipt.stat().st_size>128*1024:
                    continue
                try:
                    data=json.loads(receipt.read_text(encoding='utf-8'))
                except (ValueError,OSError,UnicodeError):
                    continue
                if data.get('source_sha256')==source:
                    matching.append(item)
        return max(matching,key=lambda p:p.stat().st_mtime_ns) if matching else None

    def smart_caption_preview(self):
        if self.busy or not self.project or not self.selected:return
        if not messagebox.askyesno(
                'Prévia 9:16 com legendas ASR em revisão',
                'Reenquadrar por pessoa/cena e mostrar a transcrição recebida'
                ' na prévia, com aviso ASR NÃO CONFERIDO?\n\n'
                'Esta é uma prévia editorial isolada. Não aprova nem publica. '
                'O enquadramento deve atingir ao menos 35% do Reel.'):
            return
        cid=self.selected
        try:
            inbox=self._find_analyzer_inbox_for_project()
            self.project.update(cid,layout='smart_zoom')
            self.layout.set('smart_zoom')
        except (OSError,ValueError,KeyError) as error:
            return messagebox.showerror('Preparação bloqueada',str(error))
        if inbox is None:
            self.log_message('Analyzer correspondente não encontrado; tentativa com '
                             'OpenCV local, sem fingir evidência R6.')
        def work():
            movie,report=render_item(
                self.project,cid,preview=True,analyzer_inbox=inbox,
                draft_captions=True,require_reframe=True,cancel=self.cancel,
                progress=lambda value,item:self.q.put(('progress',value)))
            return ('MP4 revisável: '+str(movie)+
                    ' | retrato real '+str(report['camera_plan']['portrait_coverage_percent'])+'%')
        self._task('Gerando revisão isolada com câmera inteligente + ASR...',work)

    def open_smart_caption_preview(self):
        if not self.project or not self.selected:return
        root=self.project.dir/'outputs'/'caption_draft_previews'/self.selected
        paths=list(root.glob('*/PREVIEW_ASR_DRAFT_540x960.mp4')) if root.is_dir() else []
        if not paths:
            return messagebox.showwarning(
                'Sem prévia com ASR','Gere uma PRÉVIA INTELIGENTE + LEGENDAS primeiro.')
        latest=max(paths,key=lambda p:p.stat().st_mtime_ns)
        open_file(latest)

    def preview_selected(self):self._render(True)
    def final_selected(self):self._render(False)

    def open_preview(self):
        if not self.project or not self.selected:return
        record=self.project.preview_record(self.selected)
        if not record:return messagebox.showwarning('Sem prévia','Gere uma prévia antes de abrir.')
        open_file(self.project.dir/record['relative_path'])

    def approve_selected(self):
        if self.busy:return
        if not self.project or not self.selected:return
        try:
            self._save()
            self.project.approve(self.selected,human_reviewed=True,
                                 verified_audio=self.audio_checked.get(),verified_camera=self.camera_checked.get())
            self.refresh_table()
            self.log_message(self.selected+': prévia aprovada. Render final permitido apenas para esta revisão.')
        except Exception as e:messagebox.showerror('Aprovação bloqueada',str(e))

    def batch(self,kind):
        if self.busy:return
        if not self.project:return messagebox.showwarning('Importe primeiro','Importe a curadoria ZIP.')
        if not messagebox.askyesno('Gerar prévias','Renderizar prévias de todos os '+kind+'?\n'
             'Fonte exata ou vídeo alternativo revisado para prévias. ' 
             'Legendas ASR não conferidas permanecem desligadas.\n'
             'O processamento pode ser demorado. Não haverá publicação automática.'):
            return
        rows=self.project.package.items(kind)
        def run():
            for i,c in enumerate(rows):
                if self.cancel.is_set():raise RuntimeError('Lote cancelado pelo usuário')
                if self.project.preview_record(c.id):
                    self.q.put(('log','Prévia já validada: '+c.id));continue
                self.q.put(('log','Render: '+c.id+' ('+str(i+1)+'/'+str(len(rows))+')'))
                render_item(self.project,c.id,preview=True,cancel=self.cancel,progress=lambda f,item:self.q.put(('progress',(i+f)/len(rows))))
            return f'{kind}: {len(rows)} itens avaliados (prévia/reutilização), sem aprovação automática'
        self._task('Processamento de lote com histórico por corte...',run)

    def batch_final(self):
        if self.busy:return
        if not self.project:return
        rows=[x for x in self.project.package.items() if self.project.approval_matches(x.id)]
        if not rows:
            return messagebox.showwarning('Nenhum aprovado','Aprove as prévias individualmente antes de gerar finais.')
        if not messagebox.askyesno('Renderizar finais','Gerar '+str(len(rows))+' finais aprovados?\n'
              'Nenhum vídeo será publicado automaticamente.'):
            return
        def run():
            for i,c in enumerate(rows):
                if self.cancel.is_set():raise RuntimeError('Lote cancelado pelo usuário')
                if self.project.final_record(c.id):continue
                self.q.put(('log','Final '+c.id+' ('+str(i+1)+'/'+str(len(rows))+')'))
                render_item(self.project,c.id,preview=False,cancel=self.cancel,progress=lambda f,item:self.q.put(('progress',(i+f)/len(rows))))
            return self.project.export_manifest()['generated_at']+' • manifest salvo'
        self._task('Render final dos cortes aprovados...',run)

    def apply_smart_preset(self):
        if self.busy or not self.project:return
        if not messagebox.askyesno('Aplicar enquadramento automático',
             'Alterar os Reels deste show para smart_zoom? O detector inspeciona quadros reais; '
             'combina evidências de câmera, rosto e movimento localizado, '
             'preservando cenas amplas quando necessário. '
             'Aprovações/prévias anteriores ficam desatualizadas para esses Reels. '
             'Stories não serão alterados. Continuar?'):
            return
        def work():
            rows=self.project.package.items('reels')
            for c in rows:
                self.project.update(c.id,layout='smart_zoom')
            return f'{len(rows)} Reels configurados para smart_zoom. Gere e revise as prévias.'
        self._task('Aplicando padrão smart_zoom apenas nos Reels...',work)

    def export_script(self):
        if self.busy or not self.project:
            return messagebox.showwarning('Selecione um show','Abra um projeto com cortes.')
        try:
            if self.selected:self._save()
        except Exception as error:
            return messagebox.showerror('Revise o roteiro',str(error))
        self._task('Exportando roteiro editorial (somente texto, sem vídeo)...',
                   lambda:export_project_script(self.project))

    def batch_premium_covers(self):
        if self.busy or not self.project:return
        if not messagebox.askyesno('Gerar capas premium',
             'Extrair quadros do MP4 associado e gerar capas brancas/amarelas '
             'para os cortes existentes deste projeto? Os PNGs ficam SOMENTE em output/, '
             'sem substituir as capas R57. Pode demorar. Continuar?'):
            return
        def work():
            folder,count=generate_premium_covers(self.project,'all',cancel=self.cancel,
                progress=lambda p,c:self.q.put(('progress',p)))
            return f'{count} capas premium geradas/reutilizadas em {folder}'
        self._task('Gerando capas premium a partir do MP4 verificado...',work)

    def make_cover(self):
        if self.busy:return
        if not self.project or not self.selected:return
        try:self._save()
        except Exception as e:return messagebox.showerror('Revise a edição',str(e))
        cid=self.selected
        from .core import sha256_bytes
        c=self.project.package.clips[cid]
        s=self.project.settings(cid)
        key=sha256_bytes((cid+s['title']+self.project.active_media_sha()).encode('utf-8'))[:12]
        dest=self.project.dir/'exports'/'covers_premium'/c.kind/cid/key/'CAPA_PREMIUM.png'
        if dest.exists():
            self.log_message('Capa premium existente: '+str(dest))
            return open_file(dest)
        self._task('Criando capa premium a partir do MP4...',
                   lambda:create_cover_from_frame(self.project,cid,dest))


def launch(example=None):
    CuratorApp(example).mainloop()
