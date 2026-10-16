"""Additive V5 review window: projects, paged episodes, local player and approvals."""
from __future__ import annotations
from copy import deepcopy
import json
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from .duration_presets import DURATION_PRESETS, STORY_60_PRESET
from .series_workflow import SeriesProject
from .local_player import LocalPlayer
from .timeline_editor import EpisodeTimeline,timestamp

MODES = ('SERIE_CRONOLOGICA', 'MELHORES_MOMENTOS', 'COMBINADO', 'MOMENTOS_INDEPENDENTES', 'DOSSIER_ONLY')
PRESET_LABELS = tuple(p.label for p in DURATION_PRESETS) + (STORY_60_PRESET.label,)
PRESET_KEYS = tuple(p.key for p in DURATION_PRESETS) + (STORY_60_PRESET.key,)


class SeriesReview(tk.Toplevel):
    def __init__(self, master, project_root, cfg):
        super().__init__(master)
        self.rootp, self.cfg = Path(project_root), deepcopy(cfg)
        self.project = None
        self.events, self.cancel = queue.Queue(), threading.Event()
        self.busy, self.page = False, 0
        self.title('L.D.PORTO V5.2 · Histórias e revisão visual')
        self.geometry('1240x860')
        self.minsize(1020, 720)
        self.protocol('WM_DELETE_WINDOW', self._close)
        self._build()
        self.after(100, self._poll)

    def _build(self):
        main = ttk.Frame(self, padding=10)
        main.pack(fill='both', expand=True)
        header = ttk.Frame(main)
        header.pack(fill='x')
        self.mode = tk.StringVar(value='SERIE_CRONOLOGICA')
        self.duration = tk.StringVar(value='Auto (<90s)')
        ttk.Label(header, text='Modo').pack(side='left')
        ttk.Combobox(header, values=MODES, textvariable=self.mode, state='readonly', width=25).pack(side='left', padx=6)
        ttk.Label(header, text='Duração do clipe').pack(side='left')
        ttk.Combobox(header, values=PRESET_LABELS, textvariable=self.duration, state='readonly', width=16).pack(side='left', padx=6)
        ttk.Button(header, text='Importar ZIP', command=self._import_zip).pack(side='left', padx=3)
        ttk.Button(header, text='Importar Stories 60s', command=self._import_stories).pack(side='left', padx=3)
        ttk.Button(header, text='Analysis concluído', command=self._import_directory).pack(side='left', padx=3)
        ttk.Button(header, text='Retomar projeto', command=self._resume).pack(side='left', padx=3)
        controls = ttk.Frame(main)
        controls.pack(fill='x', pady=6)
        ttk.Button(controls, text='Selecionar mídia', command=self._choose_media).pack(side='left', padx=3)
        ttk.Button(controls, text='Novo plano com preferência global', command=self._replan).pack(side='left', padx=3)
        ttk.Button(controls, text='Exportar dossiê ChatGPT', command=lambda: self._operate('export')).pack(side='left', padx=3)
        ttk.Button(controls, text='Renderizar aprovados', command=lambda: self._operate('batch')).pack(side='left', padx=3)
        ttk.Button(controls, text='Cancelar operação', command=self.cancel.set).pack(side='left', padx=3)
        ttk.Button(controls, text='Fonte canônica concluída', command=self._choose_canonical).pack(side='left', padx=3)
        self.canonical_path=None
        self.media = tk.StringVar(value=self.cfg.get('source_media', {}).get('path') or '')
        ttk.Label(main, textvariable=self.media).pack(anchor='w')
        self.status = tk.StringVar(value='Importe somente artefatos concluídos. Propostas não autorizam publicação.')
        ttk.Label(main, textvariable=self.status, wraplength=1160).pack(anchor='w', pady=4)
        self.progress = ttk.Progressbar(main, mode='determinate', maximum=100)
        self.progress.pack(fill='x')
        self.tabs = ttk.Notebook(main)
        self.tabs.pack(fill='both', expand=True, pady=6)
        map_tab, edit_container, cover_tab, export_tab, advanced_tab = [ttk.Frame(self.tabs, padding=8) for _ in range(5)]
        for frame, name in zip((map_tab, edit_container, cover_tab, export_tab, advanced_tab), ('História e timeline', 'Episódios e estilos', 'Capas', 'Dossiê e pendências','Avançado / diagnóstico')):
            self.tabs.add(frame, text=name)
        scroll=ttk.Scrollbar(edit_container,orient='vertical')
        scroll.pack(side='right',fill='y')
        edit_canvas=tk.Canvas(edit_container,highlightthickness=0,yscrollcommand=scroll.set)
        edit_canvas.pack(side='left',fill='both',expand=True)
        scroll.configure(command=edit_canvas.yview)
        edit_tab=ttk.Frame(edit_canvas)
        item=edit_canvas.create_window((0,0),window=edit_tab,anchor='nw')
        edit_tab.bind('<Configure>',lambda event:edit_canvas.configure(scrollregion=edit_canvas.bbox('all')))
        edit_canvas.bind('<Configure>',lambda event:edit_canvas.itemconfigure(item,width=event.width))
        self.timeline_editor=EpisodeTimeline(map_tab,on_seek=self._timeline_seek,on_select=self._timeline_select,on_apply=self._apply_limits)
        self.timeline_editor.pack(fill='x')
        self.timeline=self.timeline_editor.canvas
        self.map_text = tk.Text(map_tab, wrap='word', height=22)
        self.map_text.pack(fill='both', expand=True)
        columns = ('order', 'start', 'end', 'duration', 'state', 'title')
        self.table = ttk.Treeview(edit_tab, columns=columns, show='headings', height=6, selectmode='browse')
        for key, label, width in zip(columns, ('Parte', 'Início', 'Fim', 'Duração', 'Estado', 'Título literal/proposta'), (55, 70, 70, 70, 145, 440)):
            self.table.heading(key, text=label)
            self.table.column(key, width=width, stretch=(key == 'title'))
        self.table.pack(fill='x')
        self.table.bind('<<TreeviewSelect>>', self._select)
        nav = ttk.Frame(edit_tab)
        nav.pack(fill='x')
        ttk.Button(nav, text='Página anterior', command=lambda: self._page(-1)).pack(side='left')
        ttk.Button(nav, text='Próxima página', command=lambda: self._page(1)).pack(side='left')
        self.page_label = tk.StringVar()
        ttk.Label(nav, textvariable=self.page_label).pack(side='left', padx=10)
        self.undo_button=ttk.Button(nav,text='Desfazer',command=lambda:self._history('undo'))
        self.undo_button.pack(side='right',padx=3)
        self.redo_button=ttk.Button(nav,text='Refazer',command=lambda:self._history('redo'))
        self.redo_button.pack(side='right',padx=3)
        player_row = ttk.Frame(edit_tab)
        player_row.pack(fill='x')
        self.original_player = LocalPlayer(player_row, 430, 220)
        self.original_player.pack(side='left', padx=4)
        self.preview_player = LocalPlayer(player_row, 240, 220)
        self.preview_player.pack(side='left', padx=4)
        self.transcript = tk.Text(player_row, width=38, height=13, wrap='word')
        self.transcript.pack(side='left', fill='both', expand=True)
        seeking = ttk.Frame(edit_tab)
        seeking.pack(fill='x')
        self.source_seek = tk.DoubleVar(value=0)
        self.seek_scale = ttk.Scale(seeking, variable=self.source_seek, from_=0, to=1)
        self.seek_scale.pack(side='left', fill='x', expand=True)
        self.seek_scale.bind('<ButtonRelease-1>', self._seek)
        ttk.Button(seeking, text='Pausar', command=lambda:(self.original_player.pause(),self.preview_player.pause())).pack(side='left')
        self.waveform = tk.Canvas(edit_tab, height=38, bg='#202028', highlightthickness=0)
        self.waveform.pack(fill='x')
        actions = ttk.Frame(edit_tab)
        actions.pack(fill='x', pady=4)
        for label, action in [('▶ Original', self._play_original), ('▶ Preview', self._play_preview),
            ('Parar', self._stop), ('Gerar preview + 3 capas', lambda: self._operate('preview')),
            ('Dividir semanticamente', self._split), ('Aprovar preview assistido', self._approve), ('Rejeitar', self._reject)]:
            ttk.Button(actions, text=label, command=action).pack(side='left', padx=2)
        history_row=ttk.Frame(edit_tab);history_row.pack(fill='x',pady=3)
        ttk.Button(history_row,text='Episódio anterior',command=lambda:self._step_episode(-1)).pack(side='left',padx=2)
        ttk.Button(history_row,text='Próximo episódio',command=lambda:self._step_episode(1)).pack(side='left',padx=2)
        ttk.Button(history_row,text='Mesclar com próximo',command=self._merge_next).pack(side='left',padx=2)
        ttk.Button(history_row,text='Ver timeline / arrastar limites',command=lambda:self.tabs.select(0)).pack(side='left',padx=2)
        editor = ttk.Frame(edit_tab)
        editor.pack(fill='x')
        self.fields = {}
        defaults = [('source_start','Início','0'),('source_end','Fim','0'),('title_text','Título',''),
                    ('thumbnail_title','Texto capa',''),('order','Parte','1')]
        for i, (key, label, value) in enumerate(defaults):
            var = tk.StringVar(value=value)
            self.fields[key] = var
            ttk.Label(editor, text=label).grid(row=0, column=i*2, sticky='w')
            ttk.Entry(editor, textvariable=var, width=23 if 'title' in key else 8).grid(row=0, column=i*2+1, padx=3)
        style = ttk.Frame(edit_tab)
        style.pack(fill='x', pady=6)
        self.episode_duration = tk.StringVar(value=PRESET_LABELS[0])
        self.subtitle_preset = tk.StringVar(value='LDP_REELS_KARAOKE')
        self.camera_mode = tk.StringVar(value='SOURCE_PRESERVE')
        for label, var, values in [('Faixa individual',self.episode_duration,PRESET_LABELS),
            ('Legenda',self.subtitle_preset,('LDP_REELS_KARAOKE','LDP_KARAOKE_VERDE','LDP_IMPACTO_AMARELO','LDP_CLEAN','LDP_DOCUMENTARIO','LDP_PALAVRA_CHAVE','SEM_LEGENDA')),
            ('Câmera',self.camera_mode,('SOURCE_PRESERVE','AUTO_CONSERVADOR','FOCO_PESSOA','DOIS_PARTICIPANTES','MANUAL_KEYFRAMES'))]:
            ttk.Label(style, text=label).pack(side='left')
            ttk.Combobox(style, textvariable=var, values=values, state='readonly', width=21).pack(side='left', padx=3)
        form_buttons=ttk.Frame(edit_tab);form_buttons.pack(fill='x',pady=6)
        ttk.Button(form_buttons,text='Aplicar ajustes do episódio',command=self._save).pack(side='left',padx=3)
        ttk.Button(form_buttons,text='Salvar modelo de legenda',command=self._save_style).pack(side='left',padx=3)
        ttk.Button(form_buttons,text='Carregar modelo',command=self._load_style).pack(side='left',padx=3)
        customize = ttk.Frame(advanced_tab)
        customize.pack(fill='x')
        self.subtitle_custom = tk.StringVar(value='{}')
        ttk.Label(customize, text='Legenda personalizada (JSON):').pack(side='left')
        ttk.Entry(customize, textvariable=self.subtitle_custom).pack(side='left', fill='x', expand=True, padx=3)
        ttk.Button(customize, text='Salvar ajuste', command=self._save).pack(side='left', padx=3)
        ttk.Button(customize, text='Salvar modelo', command=self._save_style).pack(side='left', padx=3)
        ttk.Button(customize, text='Carregar modelo', command=self._load_style).pack(side='left', padx=3)
        audio_row = ttk.Frame(advanced_tab)
        audio_row.pack(fill='x', pady=3)
        self.audio_custom, self.watermark_custom = tk.StringVar(value='{"mode":"original"}'),tk.StringVar(value='null')
        ttk.Label(audio_row,text='Áudio (JSON):').pack(side='left')
        ttk.Entry(audio_row,textvariable=self.audio_custom,width=38).pack(side='left',fill='x',expand=True)
        ttk.Label(audio_row,text='Marca (JSON):').pack(side='left')
        ttk.Entry(audio_row,textvariable=self.watermark_custom,width=32).pack(side='left',fill='x',expand=True)
        ttk.Button(audio_row,text='Trilha própria',command=self._choose_music).pack(side='left')
        manual_row=ttk.Frame(advanced_tab)
        manual_row.pack(fill='x',pady=3)
        self.camera_keyframes=tk.StringVar(value='[]')
        self.thumbnail_custom=tk.StringVar(value='{}')
        ttk.Label(manual_row,text='Keyframes câmera (JSON):').pack(side='left')
        ttk.Entry(manual_row,textvariable=self.camera_keyframes,width=28).pack(side='left',fill='x',expand=True)
        ttk.Label(manual_row,text='Capa/frame/layout (JSON):').pack(side='left')
        ttk.Entry(manual_row,textvariable=self.thumbnail_custom,width=28).pack(side='left',fill='x',expand=True)
        self.diagnostic=tk.Text(advanced_tab,wrap='word')
        self.diagnostic.pack(fill='both',expand=True,pady=8)
        self.cover_frames=[]
        self.cover_selection=tk.StringVar(value='CAPA_01')
        for index in range(5):
            column=ttk.Frame(cover_tab)
            column.pack(side='left',padx=5,fill='y')
            label=ttk.Label(column,text=f'Capa {index+1}: gere a prévia para ver.')
            label.pack(pady=10)
            ttk.Radiobutton(column,text=f'Escolher capa {index+1}',variable=self.cover_selection,value=f'CAPA_{index+1:02d}').pack()
            self.cover_frames.append(label)
        self.cover_photos=[]
        ttk.Button(cover_tab,text='Salvar escolha e gerar nova revisão',command=self._choose_cover).pack(side='bottom',pady=10)
        self.export_text = tk.Text(export_tab, wrap='word')
        self.export_text.pack(fill='both', expand=True)

    def _task(self, function):
        if self.busy:
            return
        self.busy = True
        self.cancel.clear()
        self.status.set('Processando dados existentes…')
        def worker():
            try:
                result = function()
                self.events.put(('result', result))
            except Exception as exc:
                self.events.put(('error', str(exc)))
            finally:
                self.events.put(('done', None))
        threading.Thread(target=worker, daemon=True).start()

    def _poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == 'result':
                    if isinstance(value, SeriesProject):
                        self.project = value
                        self.page = 0
                        self.mode.set(value.plan.get('mode','SERIE_CRONOLOGICA'))
                        key=value.plan.get('duration_preset',PRESET_KEYS[0])
                        self.duration.set(PRESET_LABELS[PRESET_KEYS.index(key)])
                    self._refresh()
                    self.status.set(str(value.directory if isinstance(value, SeriesProject) else value))
                elif kind == 'error':
                    self.status.set(value)
                    messagebox.showerror('Revisão V5', value, parent=self)
                elif kind == 'progress':
                    self.progress['value'] = value[0]*100
                    self.status.set(value[1])
                elif kind == 'waveform':
                    key, peaks=value
                    if self._selected()==key:
                        self.waveform.delete('all')
                        w=max(800,self.waveform.winfo_width())
                        for i,peak in enumerate(peaks):
                            x=w*i/max(1,len(peaks))
                            self.waveform.create_line(x,19-peak*17,x,19+peak*17,fill='#69cccc')
                elif kind == 'done':
                    self.busy = False
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _import(self, path):
        if not path:
            return
        mode, duration = self.mode.get(), PRESET_KEYS[PRESET_LABELS.index(self.duration.get())]
        canonical=getattr(self,'canonical_path',None)
        def create():
            from .evidence_source import load_evidence
            evidence = load_evidence(path,canonical_dir=canonical)
            return SeriesProject.create(evidence, self.cfg['paths']['output_root'], self.cfg,
                duration, mode, cancel=self.cancel, progress=lambda f,d='': self.events.put(('progress',(f,d))))
        self._task(create)

    def _import_zip(self):
        self._import(filedialog.askopenfilename(parent=self, title='Pacote Analyzer concluído', filetypes=[('ZIP','*.zip')]))

    def _import_stories(self):
        """Load a reviewed story proposal into a *separate* unapproved V5 project."""
        if self.busy:
            return
        if not self.project:
            messagebox.showinfo('Stories 60s',
                'Primeiro use Importar ZIP para carregar o pacote original do Analyzer na V5.2.', parent=self)
            return
        path = filedialog.askopenfilename(parent=self,
            title='Selecione STORIES_SEQUENCIAIS_REVISAR.json',
            filetypes=[('Stories da segunda curadoria', '*.json')])
        if not path:
            return
        current = self.project
        def create():
            doc = json.loads(Path(path).read_text(encoding='utf-8-sig'))
            return SeriesProject.create_stories(current.evidence, doc,
                self.cfg['paths']['output_root'], self.cfg, cancel=self.cancel,
                progress=lambda f,d='': self.events.put(('progress',(f,d))))
        self._task(create)

    def _import_directory(self):
        self._import(filedialog.askdirectory(parent=self, title='Diretório de artefatos concluídos'))

    def _resume(self):
        if self.busy:
            return
        path = filedialog.askopenfilename(parent=self, title='series_index.json', filetypes=[('Plano V5','series_index.json')])
        if path:
            self.project = SeriesProject(Path(path).parent, self.cfg, cancel=self.cancel,
                progress=lambda f,d='': self.events.put(('progress',(f,d))))
            self.mode.set(self.project.plan.get('mode','SERIE_CRONOLOGICA'))
            key=self.project.plan.get('duration_preset',PRESET_KEYS[0])
            self.duration.set(PRESET_LABELS[PRESET_KEYS.index(key)])
            self._refresh()

    def _replan(self):
        if not self.project or self.busy:
            return
        duration = PRESET_KEYS[PRESET_LABELS.index(self.duration.get())]
        mode, evidence = self.mode.get(), self.project.evidence
        self._task(lambda: SeriesProject.create(evidence, self.cfg['paths']['output_root'], self.cfg, duration, mode,
            cancel=self.cancel, progress=lambda f,d='': self.events.put(('progress',(f,d)))))

    def _refresh(self):
        if not self.project:
            return
        selected = self._selected()
        self.table.delete(*self.table.get_children())
        episodes = self.project.episodes()
        for episode in episodes[self.page*100:(self.page+1)*100]:
            titles = episode.get('title_options') or []
            title = episode.get('title_text') or (titles[0] if titles else '')
            if isinstance(title, dict):
                title = title.get('text', '')
            self.table.insert('', 'end', iid=episode['episode_id'], values=(episode['order'],
                f"{episode['source_start']:.3f}", f"{episode['source_end']:.3f}", f"{episode['duration']:.3f}",
                episode.get('state') or episode.get('status'), title))
        self.page_label.set(f'Página {self.page+1} · {len(episodes)} propostas · série e extras separados no índice')
        if selected and self.table.exists(selected):
            self.table.selection_set(selected)
        elif self.table.get_children():
            self.table.selection_set(self.table.get_children()[0])
        self.map_text.delete('1.0', 'end')
        story=self.project.plan.get('story_map') or {}
        self.map_text.insert('end',f"Ordem: como a narrativa foi contada na fonte. Cronologia histórica não inferida.\n"
            f"Série: {len(self.project.plan.get('episodes',[]))} partes · extras: {len(self.project.plan.get('extras',[]))}\n"
            f"Fala disponível coberta: {story.get('coverage_pct_speech',0):.1f}% · fonte coberta: {story.get('coverage_pct_source',0):.1f}%\n"
            'Cobertura da fala disponível não comprova transcrição integral da obra.\n\nEVIDÊNCIAS\n')
        for name,row in self.project.evidence.get('availability',{}).items():
            self.map_text.insert('end',f"{name}: {row.get('status','unknown')} · {row.get('count',0)} registros\n")
        self.map_text.insert('end','\nLACUNAS E EXCLUSÕES\n')
        for gap in story.get('gaps',[])[:100]:
            self.map_text.insert('end',f"{timestamp(gap['start'])} → {timestamp(gap['end'])}: {gap.get('reason','sem evidência')}\n")
        if not story.get('gaps'):self.map_text.insert('end','Nenhuma lacuna medida entre os intervalos selecionados disponíveis.\n')
        self.timeline_editor.set_project(self.project.plan,self.project.evidence)
        self.diagnostic.delete('1.0','end')
        self.diagnostic.insert('end',json.dumps({'coverage':story,'availability':self.project.evidence.get('availability'),
            'provenance':self.project.evidence.get('provenance')},ensure_ascii=False,indent=2))
        self.undo_button.configure(state='normal' if getattr(self.project,'can_undo',False) else 'disabled')
        self.redo_button.configure(state='normal' if getattr(self.project,'can_redo',False) else 'disabled')
        self.export_text.delete('1.0','end')
        self.export_text.insert('end', f'Projeto: {self.project.directory}\n\nAprovação de preview não autoriza publicação.\n'
            'Revisar fala, continuidade, mapas/textos, enquadramento, áudio e títulos antes do final.\n'
            'Karaokê só usa timestamps existentes; lacunas permanecem explícitas no pacote.\n'
            'A alteração global cria outra revisão do plano, preservando a anterior.\n\n'
            f"Cobertura de fala disponível: {story.get('coverage_pct_speech',0):.1f}%\nLacunas: {len(story.get('gaps',[]))}\n"
            'Abra o ZIP exportado e leia INDEX.md. MP4 fonte permanece externo por padrão, com hash.\n')

    def _page(self, direction):
        if self.project:
            self.page = min(max(0,self.page+direction),max(0,(len(self.project.episodes())-1)//100))
            self._refresh()

    def _selected(self):
        return next(iter(self.table.selection()), None)

    def _select(self, _event=None):
        key = self._selected()
        if not key or not self.project:
            return
        episode = self.project.episode(key)
        self.timeline_editor.select_episode(episode)
        for field,var in self.fields.items():
            value = episode.get(field, '')
            if field == 'title_text' and not value:
                value = (episode.get('title_options') or [''])[0]
                if isinstance(value, dict):
                    value = value.get('text','')
            var.set(str(value))
        preset = episode.get('duration_preset', self.project.plan.get('duration_preset',PRESET_KEYS[0]))
        self.episode_duration.set(PRESET_LABELS[PRESET_KEYS.index(preset)] if preset in PRESET_KEYS else PRESET_LABELS[0])
        self.camera_mode.set(episode.get('camera_mode','SOURCE_PRESERVE'))
        self.subtitle_preset.set(episode.get('subtitle_preset','LDP_KARAOKE_VERDE'))
        self.subtitle_custom.set(json.dumps(episode.get('subtitle_overrides',{}),ensure_ascii=False))
        self.audio_custom.set(json.dumps(episode.get('audio',{'mode':'original'}),ensure_ascii=False))
        self.watermark_custom.set(json.dumps(episode.get('watermark'),ensure_ascii=False))
        self.camera_keyframes.set(json.dumps(episode.get('camera_keyframes',[]),ensure_ascii=False))
        self.thumbnail_custom.set(json.dumps(episode.get('thumbnail_overrides',{}),ensure_ascii=False))
        st,en=episode['source_start'],episode['source_end']
        self.transcript.delete('1.0','end')
        self.transcript.insert('end',f"Faixa: {episode.get('requested_duration')}\nProposta: {episode['duration']:.3f}s\n"
            f"Prévia: {episode.get('preview_duration') or 'não gerada'} · final: {episode.get('rendered_duration') or 'não gerado'}\n"
            f"{episode.get('duration_deviation_reason') or 'Faixa atendida.'}\n\n")
        if episode.get('preview'):
            self.transcript.insert('end','Precisão da legenda: '+str(episode['preview'].get('subtitle_alignment','unknown'))+
                (' · revisão de legibilidade pendente' if episode['preview'].get('subtitle_needs_review') else '')+'\n\n')
        for segment in self.project.evidence.get('segments',[]):
            if segment['end'] > st-15 and segment['start'] < en+15:
                self.transcript.insert('end',f"[{segment['start']:.3f}–{segment['end']:.3f}] {segment.get('text','')}\n")
        for scene in self.project.evidence.get('scenes',[]):
            if scene.get('end',0)>st and scene.get('start',float('inf'))<en:
                description=scene.get('observed_description') or scene.get('visual_description') or scene.get('description')
                self.transcript.insert('end',f"\nCena {scene.get('scene_id','?')}: {description or 'Imagem não descrita/observação não confirmada.'}\n")
        if self.media.get():
            self.original_player.show(self.media.get(),st,en)
            self.seek_scale.configure(from_=st,to=en)
            self.source_seek.set(st)
            self._waveform(key,self.media.get(),st,en)
        path = episode.get('preview',{}).get('project_path')
        if path:
            self.preview_player.show(self.project.directory/path)
        self.cover_selection.set(episode.get('thumbnail_selection') or 'CAPA_01')
        self.cover_photos=[]
        for label,choice in zip(self.cover_frames,episode.get('preview',{}).get('thumbnail_choices',{}).get('choices',[])):
            from PIL import Image,ImageTk
            folder=self.project.directory/episode['preview']['review_folder']/'thumbnails'
            try:
                with Image.open(folder/choice['file']) as image:
                    photo=ImageTk.PhotoImage(image.resize((145,258)))
                self.cover_photos.append(photo)
                label.configure(image=photo,text=choice['layout'],compound='bottom')
            except (OSError,KeyError):
                label.configure(image='',text='Capa indisponível')

    def _choose_media(self):
        path = filedialog.askopenfilename(parent=self,filetypes=[('Vídeo','*.mp4 *.mkv *.webm *.mov')])
        if path:
            self.media.set(path)
            self._select()

    def _choose_canonical(self):
        if not self.busy:
            self.canonical_path=filedialog.askdirectory(parent=self,title='Analysis canônico concluído com SHA256 correspondente') or None
            self.status.set('Fonte canônica para próxima importação: '+str(self.canonical_path or 'não selecionada'))

    def _save(self):
        key=self._selected()
        if not key or self.busy:
            return
        episode=self.project.episode(key)
        if (episode.get('state') or episode.get('status')) in {'PREVIEW_APPROVED','FINAL_RENDERED','PUBLISH_READY'} or episode.get('human_approval'):
            if not messagebox.askyesno('Invalidar aprovação', 'Este ajuste invalida a aprovação deste episódio e preserva os arquivos anteriores. Continuar?',parent=self):
                return
        try:
            changes={k:v.get() for k,v in self.fields.items()}
            changes.update(source_start=float(changes['source_start']),source_end=float(changes['source_end']),order=int(changes['order']),
                duration_preset=PRESET_KEYS[PRESET_LABELS.index(self.episode_duration.get())],camera_mode=self.camera_mode.get(),
                subtitle_preset=self.subtitle_preset.get(),subtitle_overrides=json.loads(self.subtitle_custom.get()),
                confirm_invalidation=True)
            if hasattr(self,'audio_custom'):
                changes['audio']=json.loads(self.audio_custom.get())
                changes['watermark']=json.loads(self.watermark_custom.get())
            if hasattr(self,'camera_keyframes'):
                changes['camera_keyframes']=json.loads(self.camera_keyframes.get())
                changes['thumbnail_overrides']=json.loads(self.thumbnail_custom.get())
            from .media_effects import effect_input_fingerprints
            effect_input_fingerprints(changes)
        except (ValueError,TypeError) as exc:
            messagebox.showerror('Ajuste inválido',str(exc),parent=self)
            return
        project = self.project
        self._task(lambda: (project.edit(key,**changes), 'Ajuste salvo; gere e revise outra prévia.')[1])

    def _save_style(self):
        path=filedialog.asksaveasfilename(parent=self,defaultextension='.json',initialdir=self.rootp/'.cache',title='Salvar modelo de legenda')
        if path:
            try:
                overrides=json.loads(self.subtitle_custom.get())
                if not isinstance(overrides,dict):
                    raise ValueError('Modelo de legenda exige objeto JSON')
                from .subtitle_presets import resolve_subtitle_preset
                resolve_subtitle_preset(self.subtitle_preset.get(),overrides)
                Path(path).write_text(json.dumps({'preset':self.subtitle_preset.get(),'overrides':overrides},ensure_ascii=False,indent=2),encoding='utf-8')
            except (ValueError,TypeError,OSError) as exc:
                messagebox.showerror('Modelo inválido',str(exc),parent=self)

    def _load_style(self):
        path=filedialog.askopenfilename(parent=self,filetypes=[('Modelo','*.json')])
        if path:
            try:
                data=json.loads(Path(path).read_text(encoding='utf-8-sig'))
                if not isinstance(data,dict) or not isinstance(data.get('overrides',{}),dict):
                    raise ValueError('Modelo/overrides exigem objeto JSON')
                from .subtitle_presets import resolve_subtitle_preset
                resolve_subtitle_preset(data['preset'],data.get('overrides',{}))
                self.subtitle_preset.set(data['preset'])
                self.subtitle_custom.set(json.dumps(data.get('overrides',{}),ensure_ascii=False))
            except (ValueError,KeyError,TypeError,OSError) as exc:
                messagebox.showerror('Modelo inválido',str(exc),parent=self)

    def _operate(self, kind):
        if not self.project:
            return
        key, media=self._selected(),self.media.get()
        if kind=='preview' and not key:
            return
        project=self.project
        functions={'export':project.export,'preview':lambda:project.render(key,media),'batch':lambda:project.render_approved(media)}
        self._task(functions[kind])

    def _approve(self):
        key=self._selected()
        if key and not self.busy and messagebox.askyesno('Aprovação humana','Você assistiu ao preview e conferiu fala, áudio, continuidade, legendas, câmera e capa?',parent=self):
            episode=self.project.episode(key)
            deviation=episode.get('duration_within_target') is False
            if deviation and not messagebox.askyesno('Duração fora da faixa','Aceitar explicitamente a duração proposta fora da faixa escolhida?',parent=self):
                return
            project=self.project
            self._task(lambda:(project.approve(key,human_reviewed=True,duration_deviation_accepted=deviation),'Preview aprovado; publicação pendente.')[1])

    def _reject(self):
        key=self._selected()
        if key and not self.busy:
            project=self.project
            self._task(lambda:(project.reject(key),'Proposta rejeitada.')[1])

    def _split(self):
        key=self._selected()
        if not key or self.busy:
            return
        if not messagebox.askyesno('Divisão semântica','Dividir apenas em limites comprovados de frases/Q&A? A numeração muda e invalida prévias afetadas; arquivos anteriores serão preservados.',parent=self):
            return
        project=self.project
        preset=PRESET_KEYS[PRESET_LABELS.index(self.episode_duration.get())]
        self._task(lambda:(project.split(key,preset,confirm_invalidation=True),'Divisão salva; revise a continuidade e as prévias.')[1])

    def _history(self,action):
        if not self.project or self.busy:
            return
        project=self.project
        if not getattr(project,'can_'+action,False):
            return
        self._task(lambda:(getattr(project,action)(), 'Histórico aplicado. As partes afetadas exigem outra prévia/aprovação.')[1])

    def _timeline_select(self,key):
        if not self.project or self.busy:
            return
        episodes=self.project.episodes()
        index=next((i for i,e in enumerate(episodes) if e['episode_id']==key),None)
        if index is not None:
            page=index//100
            if page!=self.page:self.page=page;self._refresh()
            self.table.selection_set(key)
            self.table.see(key)
            self._select()

    def _timeline_seek(self,seconds):
        self.source_seek.set(seconds)
        if self.media.get():
            self.original_player.show(self.media.get(),seconds)
        key=self._selected()
        if key:
            episode=self.project.episode(key)
            preview=episode.get('preview',{}).get('project_path')
            if preview and episode['source_start']<=seconds<episode['source_end']:
                self.preview_player.show(self.project.directory/preview,seconds-episode['source_start'])
        self.status.set('Fonte em '+timestamp(seconds)+' · seeking do backend; PTS observado no player quando disponível')

    def _apply_limits(self,start,end):
        key=self._selected()
        if not key or self.busy:
            return
        episode=self.project.episode(key)
        if episode.get('human_approval') and not messagebox.askyesno('Invalidar prévia','Aplicar os limites invalida a aprovação desta parte. Continuar?',parent=self):
            return
        project=self.project
        self._task(lambda:(project.edit(key,source_start=start,source_end=end,confirm_invalidation=True),
            'Limites aplicados; revise frases/Q&A e gere outra prévia.')[1])

    def _step_episode(self,direction):
        if not self.project:return
        episodes=self.project.episodes();key=self._selected()
        index=next((i for i,e in enumerate(episodes) if e['episode_id']==key),0)
        index=max(0,min(len(episodes)-1,index+direction))
        if episodes:self._timeline_select(episodes[index]['episode_id'])

    def _merge_next(self):
        key=self._selected()
        if not key or self.busy:return
        episodes=self.project.plan.get('episodes',[])
        index=next((i for i,e in enumerate(episodes) if e['episode_id']==key),None)
        if index is None or index+1>=len(episodes):return
        if not messagebox.askyesno('Mesclar partes','Mesclar com a parte seguinte somente se não houver lacuna excluída? A numeração muda e prévias afetadas serão invalidadas.',parent=self):return
        project=self.project;ids=[key,episodes[index+1]['episode_id']]
        self._task(lambda:(project.merge(ids,confirm_invalidation=True),'Partes mescladas; continuidade e faixa exigem revisão.')[1])

    def _play_original(self):
        key=self._selected()
        if key and self.media.get():
            self.preview_player.stop()
            episode=self.project.episode(key)
            self.original_player.show(self.media.get(),episode['source_start'],episode['source_end'],True)

    def _play_preview(self):
        key=self._selected()
        if key:
            path=self.project.episode(key).get('preview',{}).get('project_path')
            if path:
                self.original_player.stop()
                self.preview_player.show(self.project.directory/path,play=True)

    def _seek(self,_event=None):
        key=self._selected()
        if key and self.media.get():
            episode=self.project.episode(key)
            position=float(self.source_seek.get())
            self.original_player.show(self.media.get(),position,episode['source_end'])
            preview=episode.get('preview',{}).get('project_path')
            if preview:
                self.preview_player.show(self.project.directory/preview,max(0,position-episode['source_start']))

    def _waveform(self,key,media,start,end):
        if getattr(self,'waveform_busy',False):
            return
        self.waveform_busy=True
        def worker():
            try:
                import numpy as np
                import subprocess
                result=subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-ss',str(start),'-i',media,
                    '-t',str(end-start),'-vn','-ac','1','-ar','1000','-f','f32le','pipe:1'],capture_output=True,timeout=45,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                if result.returncode:
                    return
                values=np.frombuffer(result.stdout,dtype='<f4')
                peaks=[min(1,float(np.abs(chunk).max())) for chunk in np.array_split(values, min(400,len(values))) if len(chunk)]
                self.events.put(('waveform',(key,peaks)))
            except Exception:
                pass
            finally:
                self.waveform_busy=False
        threading.Thread(target=worker,daemon=True).start()

    def _choose_music(self):
        path=filedialog.askopenfilename(parent=self,title='Trilha própria autorizada',filetypes=[('Áudio','*.wav *.mp3 *.flac *.m4a')])
        if path and messagebox.askyesno('Direitos da trilha','Você confirma que possui autorização para usar este arquivo como trilha?',parent=self):
            self.audio_custom.set(json.dumps({'mode':'original','music_path':path,'rights_confirmed':True,'volume':.12,'ducking':True},ensure_ascii=False))

    def _choose_cover(self):
        key=self._selected()
        if not key or self.busy:
            return
        if self.project.episode(key).get('human_approval') and not messagebox.askyesno('Invalidar aprovação','A nova capa requer outra revisão do preview. Continuar?',parent=self):
            return
        project=self.project
        selection=self.cover_selection.get()
        self._task(lambda:(project.edit(key,thumbnail_selection=selection,confirm_invalidation=True),'Capa escolhida; gere e revise nova prévia.')[1])

    def _stop(self):
        self.original_player.stop()
        self.preview_player.stop()

    def _close(self):
        self.cancel.set()
        self._stop()
        self.destroy()
