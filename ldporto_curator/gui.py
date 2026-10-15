from __future__ import annotations
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
import threading, queue, subprocess, os, time, json
from copy import deepcopy
from uuid import uuid4
from .config import load_config

def Pipeline(*args, **kwargs):
    """Import the heavy rendering pipeline on demand, never while opening Tk."""
    from .pipeline import Pipeline as CuratorPipeline
    return CuratorPipeline(*args, **kwargs)

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
        self._active_operation = None
        self._last_finished_operation = None
        self._pending_source_unavailable = None
        self.operation_started = None
        self.stage_started = None
        self.current_stage_key = None
        self.eta_smoothed = None
        self.stage_eta_smoothed = None
        self.action_buttons = []
        self.mutating_widgets = []
        self.title('L.D.PORTO VIDEO CURATOR')
        self.geometry('1220x920')
        self.minsize(1050, 760)
        self.configure(bg='#151519')
        self._build()
        self._state_refresh_job = None
        self._state_request_generation = 0
        self._restore_session()
        self.src.trace_add('write', self._schedule_state_refresh)
        self.output_root.trace_add('write', self._schedule_state_refresh)
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
        rank_box = ttk.Spinbox(opts, from_=1, to=12, textvariable=self.rank, width=5)
        rank_box.pack(side='left', padx=8)
        ollama_check = ttk.Checkbutton(opts, text='Usar Ollama na curadoria genérica', variable=self.use_ollama)
        ollama_check.pack(side='left', padx=18)
        self.mutating_widgets.extend([rank_box, ollama_check])
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
        series_button = ttk.Button(f, text='V5.1 · Séries, estilos e dossiê ChatGPT', command=self.open_series_review)
        series_button.pack(anchor='w', pady=4)
        self.mutating_widgets.append(series_button)
        media_row = ttk.Frame(f)
        media_row.pack(fill='x', pady=4)
        media_button = ttk.Button(media_row, text='Selecionar mídia original', command=self.select_media)
        media_button.pack(side='left', padx=4)
        cleanup_button = ttk.Button(media_row, text='LIMPAR ARQUIVOS PESADOS', command=self.clean_heavy)
        cleanup_button.pack(side='left', padx=4)
        self.mutating_widgets.extend([media_button, cleanup_button])
        revise_button = ttk.Button(media_row, text='Aplicar configurações ao plano', command=lambda: self.work('revise'))
        revise_button.pack(side='left', padx=8)
        self.action_buttons.append(revise_button)
        self.curation_source = tk.StringVar(value='Curadoria: FIRST_PASS')
        ttk.Label(f, textvariable=self.curation_source, foreground='#b8c7ff').pack(anchor='w')
        self.plan_state = tk.StringVar(value='Estado: SEM_PLANO | execute CURAR para persistir uma revisão.')
        ttk.Label(f, textvariable=self.plan_state, foreground='#ffd36b', wraplength=1160, justify='left').pack(anchor='w', pady=(2, 4))

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
        entry = ttk.Entry(box, textvariable=var)
        entry.pack(side='left', fill='x', expand=True)
        self.mutating_widgets.append(entry)
        def pick():
            if self.busy:
                return
            p = filedialog.askdirectory() if isdir else filedialog.askopenfilename(filetypes=[('Vídeos', '*.mp4 *.mkv *.mov *.webm'), ('Todos', '*.*')])
            if p:
                var.set(p)
        if isdir:
            pick_button = ttk.Button(box, text='Escolher...', command=pick)
            pick_button.pack(side='left', padx=8)
            self.mutating_widgets.append(pick_button)

    def write(self, msg, operation_id=None):
        self.q.put({'type': 'log', 'message': str(msg), 'operation_id': operation_id})

    def progress(self, event, operation_id=None):
        data = dict(event or {})
        data['type'] = 'progress'
        data['operation_id'] = operation_id
        self.q.put(data)

    def _set_buttons(self, enabled):
        for b in self.action_buttons + getattr(self, 'mutating_widgets', []):
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
        if e.get('event') == 'plan_state':
            state = e.get('approval_state') or 'SEM_PLANO'
            project = e.get('project_id') or '—'
            revision = e.get('plan_revision') or '—'
            fingerprint = e.get('plan_fingerprint') or '—'
            reason = e.get('invalidation_reason')
            approved_revision = e.get('approved_revision')
            instruction = ''
            if state == 'APPROVAL_INVALIDATED' and approved_revision:
                instruction += ' | revisão aprovada anteriormente: ' + str(approved_revision)
            if reason and str(reason).startswith('Configuração de render mudou:'):
                instruction += ' | Aplicar configurações ao plano → TESTAR 1 CORTE → APROVAR TESTE.'
            self.plan_state.set(f'Estado: {state} | projeto: {project} | revisão: {revision} | plano: {fingerprint}' + (f' | revisão necessária: {reason}' if reason else '') + instruction)
            return
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
                operation_id = item.get('operation_id')
                if operation_id is not None and operation_id != self._active_operation:
                    continue
                if item.get('type') == 'progress':
                    self._handle_progress(item)
                elif item.get('type') == 'state_lookup':
                    # State checks may hash large snapshots. Apply only the latest
                    # completed lookup, on Tk's main thread, outside an operation.
                    if (not self.busy and self._active_operation is None
                            and item['generation'] == getattr(self, '_state_request_generation', 0)
                            and item['source'] == self.src.get().strip()):
                        if item.get('state_event'):
                            self._handle_progress(item['state_event'])
                        elif item.get('error_kind') == 'missing':
                            self.plan_state.set('Estado: SEM_PLANO | ' + item['error'])
                        elif item.get('error'):
                            self.plan_state.set('Estado: APPROVAL_INVALIDATED | ' + item['error'])
                elif item.get('type') == 'imported':
                    report = item['report']
                    self.curation_source.set('Curadoria: ' + report['curation_source'])
                    if report.get('source_url') or report.get('video_id'):
                        self.src.set(report.get('source_url') or report['video_id'])
                    self._remember_session(self.src.get().strip(), int(self.rank.get()))
                    self.plan_state.set('Estado: SEM_PLANO | pacote importado; execute CURAR para persistir a revisão.')
                    self.status.set('Segunda curadoria importada. Gere e revise o preview.')
                elif item.get('type') == 'done':
                    if operation_id is None or operation_id != self._active_operation:
                        continue
                    self.busy = False
                    self._active_operation = None
                    self._last_finished_operation = operation_id
                    self._set_buttons(True)
                    if self._pending_source_unavailable is not None:
                        kind = self._pending_source_unavailable
                        self._pending_source_unavailable = None
                        self.after(200, lambda k=kind, token=operation_id: self._show_missing_media(k, token))
                elif item.get('type') == 'source_unavailable':
                    self._pending_source_unavailable = item['kind']
                elif item.get('type') == 'error':
                    messagebox.showerror('Erro', item['message'], parent=self)
                elif item.get('type') == 'preview_ready':
                    try:
                        os.startfile(str(item['path']))
                    except Exception:
                        pass
                else:
                    m = str(item.get('message', ''))
                    if m:
                        self.log.insert('end', m + '\n')
                        self.log.see('end')
                        self.status.set(m)
        except queue.Empty:
            pass
        self.after(120, self._poll)

    def _show_missing_media(self, kind, operation_id):
        if not self.busy and self._last_finished_operation == operation_id:
            self.missing_media_dialog(kind)

    def _remember_session(self, source_input, rank):
        session = {'source_input': source_input, 'rank': rank,
                   'output_root': self.cfg['paths']['output_root']}
        path = self.rootp / '.cache' / 'gui_session_v52.json'
        temporary = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding='utf-8')
            os.replace(temporary, path)
        except OSError as exc:
            self.write('Sessão da interface não foi salva: ' + str(exc))

    def _restore_session(self):
        path = self.rootp / '.cache' / 'gui_session_v52.json'
        try:
            session = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(session, dict):
                raise ValueError('sessão inválida')
            if isinstance(session.get('source_input'), str):
                self.src.set(session['source_input'])
            if isinstance(session.get('output_root'), str):
                self.output_root.set(session['output_root'])
            if isinstance(session.get('rank'), int) and session['rank'] >= 1:
                self.rank.set(session['rank'])
        except (OSError, ValueError, TypeError):
            return
        self._refresh_plan_state()

    def _schedule_state_refresh(self, *_):
        if self.busy:
            return
        # Invalidate an existing check immediately, not only when the debounce
        # fires: a late result must never overwrite the new URL's state.
        self._state_request_generation = getattr(self, '_state_request_generation', 0) + 1
        previous = getattr(self, '_state_refresh_job', None)
        if previous is not None:
            self.after_cancel(previous)
        self._state_refresh_job = self.after(450, self._refresh_plan_state)

    def _refresh_plan_state(self):
        self._state_refresh_job = None
        if self.busy:
            return
        # Capture all Tk values before starting the worker. Never call Tk,
        # including after()/StringVar.set(), from a background thread.
        self._sync()
        source_input = self.src.get().strip()
        cfg_snapshot = deepcopy(self.cfg)
        root = self.rootp
        request = getattr(self, '_state_request_generation', 0) + 1
        self._state_request_generation = request
        if not source_input:
            self.plan_state.set('Estado: SEM_PLANO | informe uma URL ou arquivo.')
            return
        self.plan_state.set('Estado: verificando revisão salva...')
        events = self.q

        def read_saved_state():
            state_event = None
            error = None
            error_kind = None

            def capture(event):
                nonlocal state_event
                if event.get('event') == 'plan_state':
                    state_event = dict(event)

            try:
                pipeline = Pipeline(cfg_snapshot, root, log=lambda *_: None, progress=capture)
                reader = getattr(pipeline, 'read_state', None)
                if reader is None:
                    error_kind = 'missing'
                    error = 'Leitura de estado indisponível.'
                else:
                    doc = reader(source_input)
                    if state_event is None:
                        state_event = {
                            'event': 'plan_state',
                            'project_id': doc.get('project_id') or doc.get('video_id'),
                            'plan_revision': doc.get('plan_revision'),
                            'plan_fingerprint': (doc.get('plan_signature') or doc.get('plan_fingerprint')
                                                 or doc.get('editorial_plan_fingerprint')),
                            'approval_state': doc.get('approval_state'),
                            'invalidation_reason': doc.get('invalidation_reason')}
            except FileNotFoundError as exc:
                error_kind, error = 'missing', str(exc)
            except Exception as exc:
                # Keep an invalidation event emitted by the pipeline if present;
                # it carries the original revision and exact mismatch reason.
                error_kind, error = 'invalid', str(exc)
            events.put({'type': 'state_lookup', 'generation': request,
                        'source': source_input, 'state_event': state_event,
                        'error_kind': error_kind, 'error': error})

        threading.Thread(target=read_saved_state, daemon=True,
                         name='ldporto-plan-status').start()

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
        # A slow lookup of the previous project must not change the state of
        # this user action, even if it completes while the worker is running.
        self._state_request_generation = getattr(self, '_state_request_generation', 0) + 1
        previous = getattr(self, '_state_refresh_job', None)
        if previous is not None:
            self.after_cancel(previous)
            self._state_refresh_job = None
        source_input = self.src.get().strip()
        rank = int(self.rank.get())
        cfg_snapshot = deepcopy(self.cfg)
        self._remember_session(source_input, rank)
        labels = {'curate':'Curando vídeo...', 'test':'Gerando preview do corte...', 'approve':'Registrando aprovação...', 'all':'Renderizando lote final...', 'revise':'Aplicando configurações à nova revisão...'}
        self._reset_progress(labels.get(kind, 'Processando...'))
        self.busy = True
        operation_id = uuid4().hex
        self._active_operation = operation_id
        self._pending_source_unavailable = None
        self._set_buttons(False)

        # These callbacks touch only Queue. Tk values and configuration are captured
        # on the main thread so a late worker cannot read another operation's form.
        event_queue = self.q
        project_root = self.rootp
        def send(event_type, **data):
            event_queue.put(dict(data, type=event_type, operation_id=operation_id))
        def write(message):
            send('log', message=str(message))
        def progress(event):
            send('progress', **dict(event or {}))

        def runit():
            try:
                p = Pipeline(cfg_snapshot, project_root, write, progress=progress)
                if kind == 'import':
                    from .second_curation_import import import_second_curation
                    report = import_second_curation(import_path, project_root, cfg_snapshot['paths']['analysis_root'])
                    send('imported', report=report)
                    write('Importação validada: ' + report['curation_source'])
                elif kind == 'curate':
                    p.curate_only(source_input)
                elif kind == 'test':
                    mp4, _ = p.test_one(source_input, rank)
                    write('PREVIEW PRONTO. Assista antes de aprovar: ' + str(mp4))
                    send('preview_ready', path=str(mp4))
                elif kind == 'approve':
                    p.approve_test(source_input)
                    write('TESTE APROVADO. Renderização em lote liberada.')
                elif kind == 'revise':
                    doc = p.revise_plan(source_input, render_config=cfg_snapshot)
                    write('CONFIGURAÇÕES APLICADAS À REVISÃO ' + str(doc['plan_revision']) + '. Gere e aprove um novo preview.')
                elif kind == 'all':
                    p.render_all(source_input, preview=False)
                    write('LOTE FINAL CONCLUÍDO.')
            except Exception as e:
                from .source_video import SourceUnavailable
                if isinstance(e, SourceUnavailable):
                    write('MÍDIA INDISPONÍVEL: ' + str(e))
                    send('source_unavailable', kind=kind)
                    return
                progress({'status':'failed','label':'Erro','detail':str(e),'stage_fraction':0})
                write('ERRO: ' + str(e))
                send('error', message=str(e))
            finally:
                send('done')
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
        if self.busy:
            return
        self._sync()
        from .series_review import SeriesReview
        SeriesReview(self, self.rootp, self.cfg)

    def select_media(self):
        if self.busy:
            return
        path = filedialog.askopenfilename(title='Selecione a mídia original analisada', filetypes=[('Vídeo', '*.mp4 *.mkv *.webm *.mov')])
        if path:
            self.cfg.setdefault('source_media', {})['path'] = path
            self.status.set('Mídia selecionada. O SHA256 será validado antes do render.')
            return path

    def missing_media_dialog(self, kind):
        origin_operation = self._last_finished_operation
        dialog = tk.Toplevel(self)
        dialog.title('Mídia fonte indisponível')
        ttk.Label(dialog, text='Reutilizar a análise existente com a mídia original.', padding=12).pack()
        def choose(download):
            dialog.destroy()
            if self.busy or self._last_finished_operation != origin_operation:
                return
            if download:
                self.cfg.setdefault('source_media', {})['allow_download'] = True
            else:
                if not self.select_media():
                    return
            def retry():
                if not self.busy and self._last_finished_operation == origin_operation:
                    self.work(kind)
            self.after(200, retry)
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
