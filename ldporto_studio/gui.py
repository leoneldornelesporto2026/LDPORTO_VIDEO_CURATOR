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
from .rendering import render_item,extract_editorial_assets,create_cover_from_frame,binaries


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
        self.default_workspace=Path.home()/'Videos'/'LDPORTO_CURATOR_STUDIO_PROJECTS'
        self.q=queue.Queue()
        self.busy=False
        self.cancel=threading.Event()
        self.preview_photo=None
        self.selected=None
        self._build()
        self.after(90,self._poll)
        if self.example and self.example.is_file():
            self.after(250,self.load_example)

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
        ttk.Label(top,text='R57 • 12 REELS + 60 STORIES • REVISÃO SEGURA',foreground='#a9b6ca').pack(side='right')
        toolbar=ttk.Frame(container)
        toolbar.pack(fill='x',pady=(12,10))
        for label,fn in [
          ('CARREGAR CURADORIA ZIP',self.import_zip),('ABRIR PROJETO',self.open_project),
          ('EXEMPLO R57',self.load_example),('VINCULAR MP4 ORIGINAL',self.select_media),
          ('EXPORTAR CAPAS + PLANOS',self.export_assets)]:
            ttk.Button(toolbar,text=label,command=fn).pack(side='left',padx=(0,7))
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
        ttk.Label(cf,text='Enquadramento (crop só após inspeção)').pack(anchor='w',pady=(8,2))
        self.layout=tk.StringVar(value='preserve')
        self.layout_select=ttk.Combobox(cf,textvariable=self.layout,values=('preserve','center_crop'),state='readonly')
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
        tools=ttk.Frame(right);tools.pack(fill='x',pady=4)
        for label,fn in [('Prévia de todos os Reels',lambda:self.batch('reels')),
                         ('Prévia de todos os Stories',lambda:self.batch('stories')),
                         ('Finais aprovados',self.batch_final),
                         ('Gerar capa do MP4',self.make_cover)]:
            ttk.Button(tools,text=label,command=fn).pack(side='left',padx=(0,4))
        ttk.Button(right,text='CANCELAR PROCESSAMENTO ATUAL',command=self.cancel_active).pack(anchor='w',pady=(4,0))
        ttk.Label(container,text='EXECUÇÃO • original preservado • revisão humana antes dos finais • sem publicação automática',
                  foreground='#94a8bd').pack(anchor='w',pady=(10,4))
        self.progress=ttk.Progressbar(container,mode='determinate',maximum=100);self.progress.pack(fill='x')
        self.log=tk.Text(container,height=5,bg='#090d13',fg='#cee3f4',insertbackground='white',font=('Consolas',9),wrap='word')
        self.log.pack(fill='x',pady=(5,0))
        self.log_message('Programa independente. O conteúdo R57 é uma proposta editorial, não vídeos aprovados.')

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
                    self.progress['value']=int(payload*100)
                elif action=='log':
                    self.log_message(payload)
                elif action=='done':
                    self.busy=False
                    self.progress['value']=100
                    self.log_message('Concluído: '+str(payload))
                    self.refresh_table()
                    if self.selected:self.show_details(self.selected)
                elif action=='error':
                    self.busy=False
                    self.log_message('ERRO: '+payload)
                    messagebox.showerror('Operação não concluída',payload)
        except queue.Empty: pass
        self.after(120,self._poll)

    def _project_location(self,archive):
        from .core import sha256_file
        digest=sha256_file(archive)
        return self.default_workspace/(Path(archive).stem[:45]+'_'+digest[:10])

    def _load_archive(self,archive):
        loc=self._project_location(archive)
        def run():
            self.project=Project.create(archive,loc)
            self.q.put(('log','Projeto importado com integridade: '+str(loc)))
            return f'{len(self.project.package.clips)} cortes carregados'
        self._task('Importando arquivo e validando todos os SHA256...',run)

    def import_zip(self):
        if self.busy:return
        path=filedialog.askopenfilename(title='Escolha curadoria R57',filetypes=[('Curadoria ZIP','*.zip')])
        if path:self._load_archive(path)

    def load_example(self):
        if self.busy:return
        if self.example and self.example.is_file():self._load_archive(self.example)
        else: messagebox.showinfo('Exemplo não encontrado','Coloque CURADORIA_R57.zip na pasta example ou importe um ZIP na interface.')

    def open_project(self):
        if self.busy:return
        folder=filedialog.askdirectory(title='Selecione a pasta com project.json',initialdir=str(self.default_workspace))
        if folder:
            try:self.project=Project(folder);self.refresh_table();self.log_message('Projeto aberto: '+folder)
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
        self.source_status.set('Curadoria: '+str(len(self.project.package.clips))+' cortes | MP4: '+
            (self.project.state['media_path'] or 'AUSENTE — informe original para habilitar o render'))
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

    def open_srt(self):
        if not self.project or not self.selected:return
        c=self.project.package.clips[self.selected]
        out=self.project.dir/'exports'/'review'/c.id
        out.mkdir(parents=True,exist_ok=True)
        p=out/'LEGENDA_RASCUNHO.srt'
        p.write_bytes(self.project.package.data(c.caption_srt))
        open_file(p)
        self.log_message('SRT aberta para revisão; marcar "conferi" só após escutar o trecho original.')

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
             'Original SHA256 obrigatório. Legendas ASR não conferidas permanecem desligadas.\n'
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

    def make_cover(self):
        if self.busy:return
        if not self.project or not self.selected:return
        try:self._save()
        except Exception as e:return messagebox.showerror('Revise a edição',str(e))
        cid=self.selected
        dest=self.project.dir/'exports'/'covers_from_verified_media'/cid/(cid+'_CAPA_ORIGINAL.png')
        self._task('Criando capa alternativa a partir do MP4 original...',
                   lambda:create_cover_from_frame(self.project,cid,dest))


def launch(example=None):
    CuratorApp(example).mainloop()
