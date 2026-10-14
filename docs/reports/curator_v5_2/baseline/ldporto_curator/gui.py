from __future__ import annotations
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
import threading, queue, subprocess, os, time
from .config import load_config
from .pipeline import Pipeline

def _fmt_seconds(seconds):
    if seconds is None:
        return 'calculando...'
    try:
        seconds = max(0, int(round(float(seconds))))
    except Exception:
        return 'calculando...'
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f'{h}h{m:02d}m'
    if m:
        return f'{m}m{s:02d}s'
    return f'{s}s'

class App(tk.Tk):
    def __init__(self, project_root):
        super().__init__()
        self.rootp = Path(project_root)
        self.cfg = load_config(self.rootp / 'config.yaml')
        self.q = queue.Queue()
        self.busy = False
        self.operation_started = None
        self.stage_started = None
        self.current_stage_key = None
        self.eta_smoothed = None
        self.stage_eta_smoothed = None
        self.action_buttons = []
        self.title('L.D.PORTO VIDEO CURATOR')
        self.geometry('1220x920')
        self.minsize(1050, 760)
        self.configure(bg='#151519')
        self._build()
        self.after(120, self._poll)

    def _build(self):
        sty = ttk.Style(self)
        sty.theme_use('clam')
        sty.configure('TLabel', background='#151519', foreground='white')
        sty.configure('TCheckbutton', background='#151519', foreground='white')
        sty.configure('TFrame', background='#151519')
        sty.configure('Progress.Horizontal.TProgressbar', troughcolor='#2a2a31', background='#ff5267')
        sty.configure('Stage.Horizontal.TProgressbar', troughcolor='#2a2a31', background='#8bd5ff')

        f = ttk.Frame(self, padding=22)
        f.pack(fill='both', expand=True)
        ttk.Label(f, text='L.D.PORTO · VIDEO CURATOR', font=('Segoe UI', 25, 'bold'), foreground='#ff5267').pack(anchor='w')
        ttk.Label(f, text='insights → curadoria → câmera → legendas → TESTE → aprovação → lote', font=('Segoe UI', 12)).pack(anchor='w', pady=(2, 18))

        self.src = tk.StringVar(value='https://www.youtube.com/watch?v=wA1ipztt54c')
        self.analysis_root = tk.StringVar(value=self.cfg['paths']['analysis_root'])
        self.output_root = tk.StringVar(value=self.cfg['paths']['output_root'])
        self.use_ollama = tk.BooleanVar(value=bool(self.cfg.get('ollama', {}).get('enabled', True)))
        self._pathrow(f, 'URL do YouTube já analisada (ou vídeo local)', self.src, False)
        self._pathrow(f, 'Pasta analysis do VIDEO ANALYZER', self.analysis_root, True)
        self._pathrow(f, 'Pasta de saída da Fase 2', self.output_root, True)

        opts = ttk.Frame(f)
        opts.pack(fill='x', pady=7)
        ttk.Label(opts, text='Rank para teste:').pack(side='left')
        self.rank = tk.IntVar(value=1)
        ttk.Spinbox(opts, from_=1, to=12, textvariable=self.rank, width=5).pack(side='left', padx=8)
        ttk.Checkbutton(opts, text='Usar Ollama na curadoria genérica', variable=self.use_ollama).pack(side='left', padx=18)
        ttk.Label(opts, text='Lote bloqueado até aprovação do preview.', foreground='#ffd36b').pack(side='left', padx=18)

        buttons = ttk.Frame(f)
        buttons.pack(fill='x', pady=(6, 10))
        for txt, kind in [('1) CURAR', 'curate'), ('2) TESTAR 1 CORTE', 'test'), ('3) APROVAR TESTE', 'approve'), ('4) RENDERIZAR TODOS', 'all')]:
            b = ttk.Button(buttons, text=txt, command=lambda k=kind: self.work(k))
            b.pack(side='left', padx=(0, 9))
            self.action_buttons.append(b)
        ttk.Button(buttons, text='Abrir resultados', command=self.open_results).pack(side='left', padx=8)
        import_button = ttk.Button(buttons, text='IMPORTAR SEGUNDA CURADORIA', command=lambda: self.work('import'))
        import_button.pack(side='left', padx=8)
        self.action_buttons.append(import_button)
        ttk.Button(f, text='V5.1 · Séries, estilos e dossiê ChatGPT', command=self.open_series_review).pack(anchor='w', pady=4)
        media_row = ttk.Frame(f)
        media_row.pack(fill='x', pady=4)
        ttk.Button(media_row, text='Selecionar mídia original', command=self.select_media).pack(side='left', padx=4)
        ttk.Button(media_row, text='LIMPAR ARQUIVOS PESADOS', command=self.clean_heavy).pack(side='left', padx=4)
        self.curation_source = tk.StringVar(value='Curadoria: FIRST_PASS')
        ttk.Label(f, textvariable=self.curation_source, foreground='#b8c7ff').pack(anchor='w')

        prog = ttk.Frame(f)
        prog.pack(fill='x', pady=(2, 10))
        self.progress_title = tk.StringVar(value='Pronto para executar.')
        ttk.Label(prog, textvariable=self.progress_title, font=('Segoe UI', 12, 'bold')).pack(anchor='w')

        top = ttk.Frame(prog)
        top.pack(fill='x', pady=(5, 2))
        self.overall_text = tk.StringVar(value='Progresso geral: 0.0%')
        self.step_text = tk.StringVar(value='Etapas: —')
        ttk.Label(top, textvariable=self.overall_text).pack(side='left')
        ttk.Label(top, textvariable=self.step_text, foreground='#ffd36b').pack(side='right')
        self.overall_bar = ttk.Progressbar(prog, maximum=100, mode='determinate', style='Progress.Horizontal.TProgressbar')
        self.overall_bar.pack(fill='x', pady=(0, 5))

        row = ttk.Frame(prog)
        row.pack(fill='x', pady=(0, 2))
        self.stage_text = tk.StringVar(value='Etapa atual: —')
        self.time_text = tk.StringVar(value='Decorrido: — | ETA etapa: — | ETA total: —')
        ttk.Label(row, textvariable=self.stage_text).pack(side='left')
        ttk.Label(row, textvariable=self.time_text, foreground='#b8c7ff').pack(side='right')
        self.stage_bar = ttk.Progressbar(prog, maximum=100, mode='determinate', style='Stage.Horizontal.TProgressbar')
        self.stage_bar.pack(fill='x', pady=(0, 5))

        self.pipeline_text = tk.StringVar(value='Fluxo: aguardando execução.')
        ttk.Label(prog, textvariable=self.pipeline_text, foreground='#c9c9d2', wraplength=1160, justify='left').pack(anchor='w')

        self.status = tk.StringVar(value='Pronto.')
        ttk.Label(f, textvariable=self.status, foreground='#d8d8df').pack(anchor='w', pady=(0, 2))
        self.log = tk.Text(f, bg='#202027', fg='#eee', insertbackground='white', font=('Consolas', 10), height=19, wrap='word')
        self.log.pack(fill='both', expand=True, pady=(5, 0))

    def _pathrow(self, parent, label, var, isdir):
        box = ttk.Frame(parent)
        box.pack(fill='x', pady=4)
        ttk.Label(box, text=label, width=34).pack(side='left')
        ttk.Entry(box, textvariable=var).pack(side='left', fill='x', expand=True)
        def pick():
            p = filedialog.askdirectory() if isdir else filedialog.askopenfilename(filetypes=[('Vídeos', '*.mp4 *.mkv *.mov *.webm'), ('Todos', '*.*')])
            if p:
                var.set(p)
        if isdir:
            ttk.Button(box, text='Escolher...', command=pick).pack(side='left', padx=8)

    def write(self, msg):
        self.q.put({'type': 'log', 'message': str(msg)})

    def progress(self, event):
        data = dict(event or {})
        data['type'] = 'progress'
        self.q.put(data)

    def _set_buttons(self, enabled):
        for b in self.action_buttons:
            b.configure(state='normal' if enabled else 'disabled')

    def _reset_progress(self, label):
        from .eta import CuratorEta
        self.eta_model = CuratorEta(self.rootp/'.cache/runtime_history_v44.json', self.cfg)
        now = time.monotonic()
        self.operation_started = now
        self.stage_started = now
        self.current_stage_key = None
        self.eta_smoothed = None
        self.stage_eta_smoothed = None
        self.overall_bar['value'] = 0
        self.stage_bar['value'] = 0
        self.overall_text.set('Progresso geral: 0.0%')
        self.step_text.set('Etapa 0/?')
        self.stage_text.set('Etapa atual: preparando...')
        self.time_text.set('Decorrido: 0s | ETA etapa: calculando... | ETA total: calculando...')
        self.pipeline_text.set('Fluxo: preparando plano de execução...')
        self.progress_title.set(label)

    def _handle_progress(self, e):
        if e.get('event') == 'eta_context':
            if hasattr(self, 'eta_model'):
                self.eta_model.context(e['metadata'], e['clips'], e.get('operation'))
            return
        if e.get('event') == 'curation_source':
            self.curation_source.set('Curadoria: ' + e['curation_source'])
            return
        now = time.monotonic()
        label = e.get('label') or e.get('stage') or 'Etapa'
        stage_key = e.get('stage') or label
        plan = list(e.get('plan') or [])
        idx = int(e.get('step') or 1)
        total = max(1, int(e.get('total_steps') or len(plan) or 1))
        sf = e.get('stage_fraction')
        status = e.get('status') or 'running'
        detail = e.get('detail') or ''

        if self.operation_started is None:
            self.operation_started = now
        if stage_key != self.current_stage_key:
            self.current_stage_key = stage_key
            self.stage_started = now
            self.stage_eta_smoothed = None

        if e.get('overall_fraction') is None:
            of = ((idx - 1) + (float(sf) if sf is not None else 0.0)) / total
        else:
            of = float(e.get('overall_fraction'))
        of = max(0.0, min(1.0, of))
        self.overall_bar['value'] = of * 100
        self.overall_text.set(f'Progresso geral: {of*100:5.1f}%')

        sfv = None if sf is None else max(0.0, min(1.0, float(sf)))
        self.stage_bar['value'] = 0 if sfv is None else sfv * 100
        remaining = max(0, total - idx)
        self.step_text.set(f'Etapa {idx}/{total} • faltam {remaining} após esta')
        self.stage_text.set('Etapa atual: ' + label + (f' — {detail}' if detail else ''))

        elapsed = max(0.0, now - self.operation_started)
        eta = None
        if 0.02 <= of < 0.999:
            raw = elapsed * (1 - of) / of
            self.eta_smoothed = raw if self.eta_smoothed is None else 0.22 * raw + 0.78 * self.eta_smoothed
            eta = self.eta_smoothed

        stage_eta = None
        if sfv is not None and self.stage_started is not None and 0.03 <= sfv < 0.999:
            se = max(0.0, now - self.stage_started)
            raw = se * (1 - sfv) / sfv
            self.stage_eta_smoothed = raw if self.stage_eta_smoothed is None else 0.28 * raw + 0.72 * self.stage_eta_smoothed
            stage_eta = self.stage_eta_smoothed

        estimate = self.eta_model.update(e) if hasattr(self, 'eta_model') else {}
        interval = lambda value: ('~' + _fmt_seconds(value[0]) + '–' + _fmt_seconds(value[1])) if value else 'calculando...'
        self.time_text.set(f'Decorrido: {_fmt_seconds(elapsed)} | ETA etapa: {interval(estimate.get("stage_range_seconds"))} | ETA total: {interval(estimate.get("total_range_seconds"))}')

        if plan:
            parts = []
            for n, name in enumerate(plan, 1):
                if n < idx:
                    mark = '✓'
                elif n == idx:
                    mark = '✓' if status in {'done', 'completed'} else '▶'
                else:
                    mark = '○'
                parts.append(f'{mark} {name}')
            self.pipeline_text.set('Fluxo: ' + '  •  '.join(parts))

        if status == 'failed':
            self.progress_title.set('Execução interrompida por erro')
        elif status in {'done', 'completed'} and of >= 0.999:
            self.overall_bar['value'] = 100
            self.stage_bar['value'] = 100
            self.progress_title.set('Concluído ✓')
        else:
            self.progress_title.set(e.get('operation_label') or 'Processando...')

    def _poll(self):
        try:
            while True:
                item = self.q.get_nowait()
                if isinstance(item, str):
                    item = {'type': 'log', 'message': item}
                if item.get('type') == 'progress':
                    self._handle_progress(item)
                elif item.get('type') == 'imported':
                    report = item['report']
                    self.curation_source.set('Curadoria: ' + report['curation_source'])
                    if report.get('source_url') or report.get('video_id'):
                        self.src.set(report.get('source_url') or report['video_id'])
                    self.status.set('Segunda curadoria importada. Gere e revise o preview.')
                elif item.get('type') == 'done':
                    self.busy = False
                    self._set_buttons(True)
                elif item.get('type') == 'source_unavailable':
                    self.after(200, lambda k=item['kind']: self.missing_media_dialog(k))
                else:
                    m = str(item.get('message', ''))
                    if m:
                        self.log.insert('end', m + '\n')
                        self.log.see('end')
                        self.status.set(m)
        except queue.Empty:
            pass
        self.after(120, self._poll)

    def _sync(self):
        self.cfg['paths']['analysis_root'] = self.analysis_root.get().strip()
        self.cfg['paths']['output_root'] = self.output_root.get().strip()
        self.cfg['ollama']['enabled'] = bool(self.use_ollama.get())

    def work(self, kind):
        if self.busy:
            return
        self._sync()
        import_path = None
        if kind == 'import':
            import_path = filedialog.askopenfilename(title='Importar segunda curadoria', filetypes=[('Pacote ou decisões', '*.zip *.json')])
            if not import_path:
                return
        labels = {'curate':'Curando vídeo...', 'test':'Gerando preview do corte...', 'approve':'Registrando aprovação...', 'all':'Renderizando lote final...'}
        self._reset_progress(labels.get(kind, 'Processando...'))
        self.busy = True
        self._set_buttons(False)

        def runit():
            try:
                p = Pipeline(self.cfg, self.rootp, self.write, progress=self.progress)
                src = self.src.get().strip()
                if kind == 'import':
                    from .second_curation_import import import_second_curation
                    report = import_second_curation(import_path, self.rootp, self.cfg['paths']['analysis_root'])
                    self.q.put({'type': 'imported', 'report': report})
                    self.write('Importação validada: ' + report['curation_source'])
                elif kind == 'curate':
                    p.curate_only(src)
                elif kind == 'test':
                    mp4, _ = p.test_one(src, int(self.rank.get()))
                    self.write('PREVIEW PRONTO. Assista antes de aprovar: ' + str(mp4))
                    try:
                        os.startfile(str(mp4))
                    except Exception:
                        pass
                elif kind == 'approve':
                    p.approve_test(src)
                    self.write('TESTE APROVADO. Renderização em lote liberada.')
                elif kind == 'all':
                    p.render_all(src, preview=False)
                    self.write('LOTE FINAL CONCLUÍDO.')
            except Exception as e:
                from .source_video import SourceUnavailable
                if isinstance(e, SourceUnavailable):
                    self.q.put({'type':'source_unavailable', 'kind':kind})
                    return
                self.progress({'status':'failed','label':'Erro','detail':str(e),'stage_fraction':0})
                self.write('ERRO: ' + str(e))
                self.after(0, lambda msg=str(e): messagebox.showerror('Erro', msg))
            finally:
                self.q.put({'type':'done'})
        threading.Thread(target=runit, daemon=True).start()

    def open_results(self):
        self._sync()
        p = Path(self.cfg['paths']['output_root'])
        p.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(p))
        except Exception:
            subprocess.Popen(['xdg-open', str(p)])

    def open_series_review(self):
        self._sync()
        from .series_review import SeriesReview
        SeriesReview(self, self.rootp, self.cfg)

    def select_media(self):
        path = filedialog.askopenfilename(title='Selecione a mídia original analisada', filetypes=[('Vídeo', '*.mp4 *.mkv *.webm *.mov')])
        if path:
            self.cfg.setdefault('source_media', {})['path'] = path
            self.status.set('Mídia selecionada. O SHA256 será validado antes do render.')

    def missing_media_dialog(self, kind):
        dialog = tk.Toplevel(self)
        dialog.title('Mídia fonte indisponível')
        ttk.Label(dialog, text='Reutilizar a análise existente com a mídia original.', padding=12).pack()
        def choose(download):
            dialog.destroy()
            if download:
                self.cfg.setdefault('source_media', {})['allow_download'] = True
            else:
                self.select_media()
                if not self.cfg.get('source_media', {}).get('path'):
                    return
            self.after(200, lambda: self.work(kind))
        ttk.Button(dialog, text='Baixar novamente', command=lambda: choose(True)).pack(pady=4)
        ttk.Button(dialog, text='Selecionar arquivo', command=lambda: choose(False)).pack(pady=4)
        ttk.Button(dialog, text='Cancelar', command=dialog.destroy).pack(pady=4)

    def clean_heavy(self):
        if self.busy:
            return
        folder = filedialog.askdirectory(title='Análise/cache para visualizar limpeza')
        if not folder:
            return
        from .storage_dialog import show_cleanup
        result=show_cleanup(self,folder,self.cfg.get('source_media',{}).get('path'))
        if result:
            self.status.set(f'Espaço liberado: {result["removed_bytes"]/1e9:.2f} GB')

def launch(project_root):
    App(project_root).mainloop()
