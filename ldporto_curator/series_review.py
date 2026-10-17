"""Additive V5 review window: projects, paged episodes, local player and approvals."""
from __future__ import annotations
from copy import deepcopy
import json
import math
from pathlib import Path
from uuid import uuid4
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


def _production_source(project):
    record = project.plan.get('production_import') or {}
    media = record.get('media_reference') or project.plan.get('media_reference') or {}
    selected = (record.get('source_path') or record.get('media_path') or media.get('path')
                or project.cfg.get('source_media', {}).get('path'))
    return Path(selected).resolve() if selected and Path(selected).is_file() else None


def _production_summary(summary, project, source_path=None):
    """Display recorded values; missing facts remain explicit in the import report."""
    source = project.evidence.get('source') or {}
    heading = summary.get('title') or summary.get('video_title') or source.get('title') or 'Projeto de produção'
    media = 'mídia localizada e verificada pelo importador' if source_path else 'mídia ausente; selecione o original para validar'
    counts = summary.get('counts') or {}
    fields = [f'{label}: {counts[key]}' for key, label in (('reels', 'Reels'), ('stories', 'Stories / partes'), ('series', 'Séries')) if key in counts]
    for label, keys in (
        ('Formato', ('format', 'package_format', 'package_type')),
        ('Reels', ('reels', 'reel_count', 'candidate_count')),
        ('Stories independentes', ('independent_stories', 'independent_story_count', 'standalone_story_count')),
        ('Partes propostas', ('story_parts', 'story_part_count', 'story_parts_proposed_count', 'stories')),
        ('Séries', ('series', 'series_count', 'story_series_count')),
        ('Bloqueados', ('blocked', 'blocked_count', 'blocked_candidates')),
        ('Legendas', ('caption_status_counts', 'caption_states', 'caption_preflight_summary')),
        ('Revisão', ('revision_id', 'revision', 'plan_revision', 'package_revision')),
    ):
        value = next((summary[k] for k in keys if k in summary), None)
        if value is not None:
            fields.append(label + ': ' + (json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)))
    return (str(heading) + ' | ' + media + '\n' + ' · '.join(fields)
            + '\nSHA256: ' + str(source.get('sha256') or summary.get('source_sha256') or 'não informado')
            + '\nImportação técnica não aprova prévias nem publicação. Consulte as pendências por candidato.')


def _camera_inspection_rows(episode):
    plan = episode.get('camera_plan') or {}
    segments = plan.get('segments') or [dict(plan, start=0., end=episode['duration'])]
    rows = []
    for index, segment in enumerate(segments):
        start, end = float(segment.get('start', 0)), float(segment.get('end', episode['duration']))
        if not (math.isfinite(start) and math.isfinite(end) and 0 <= start < end <= episode['duration'] + 1e-7):
            continue
        target = (segment.get('target_id') or segment.get('person_id') or segment.get('visual_target')
                  or segment.get('subject_id') or 'não identificado')
        safety = segment.get('crop_safe', segment.get('safety_status', plan.get('crop_safe', 'não informado')))
        zoom = segment.get('zoom_start', segment.get('zoom', 1))
        if 'zoom_end' in segment:
            zoom = str(zoom) + ' → ' + str(segment['zoom_end'])
        rows.append({'index': index, 'start': start, 'end': end,
            'source_start': episode['source_start'] + start, 'source_end': episode['source_start'] + end,
            'mode': segment.get('mode') or plan.get('mode') or 'sem plano', 'target': str(target),
            'zoom': str(zoom), 'safety': str(safety),
            'reason': segment.get('reason') or segment.get('fallback_reason') or plan.get('reason') or '',
            'segment': segment})
    return rows


def _inspection_pose(segment, relative_time):
    """Read the existing renderer's center/zoom envelope for a static inspection."""
    duration = max(.001, float(segment['end']) - float(segment['start']))
    local = max(0., min(duration, relative_time - float(segment['start'])))
    fraction = local / duration
    if segment.get('motion_easing') == 'smoothstep':
        fraction = fraction * fraction * (3 - 2 * fraction)
    x0 = float(segment.get('center_x_start', segment.get('center_x', .5)))
    y0 = float(segment.get('center_y_start', segment.get('center_y', .5)))
    x = x0 + (float(segment.get('center_x_end', x0)) - x0) * fraction
    y = y0 + (float(segment.get('center_y_end', y0)) - y0) * fraction
    zoom = float(segment.get('zoom', 1.))
    if 'zoom_start' in segment or 'zoom_end' in segment:
        delay = float(segment.get('zoom_transition_start', 0.))
        length = float(segment.get('zoom_transition_duration', duration))
        if length <= 0:
            raise ValueError('Envelope de zoom inválido para inspeção')
        amount = max(0., min(1., (local - delay) / length))
        amount = amount * amount * (3 - 2 * amount)
        z0 = float(segment.get('zoom_start', 1.))
        zoom = z0 + (float(segment.get('zoom_end', zoom)) - z0) * amount
    target_y = float(segment.get('subject_screen_y', .5))
    if not all(math.isfinite(value) for value in (x, y, zoom, target_y)):
        raise ValueError('Geometria não finita no plano de câmera')
    return x, y, zoom, target_y


def _read_inspection_frame(project, episode_id, media, requested):
    """Decode one verified original frame; report backend time without claiming measured PTS."""
    import cv2
    episode = project.episode(episode_id)
    requested = float(requested)
    if not math.isfinite(requested) or not episode['source_start'] <= requested < episode['source_end']:
        raise ValueError('Selecione um tempo dentro do episódio para abrir um frame original')
    source = project._media(media)
    capture = cv2.VideoCapture(str(source))
    try:
        if not capture.isOpened():
            raise ValueError('Não foi possível abrir a mídia original para inspeção')
        capture.set(cv2.CAP_PROP_POS_MSEC, requested * 1000)
        ok, frame = capture.read()
        observed = float(capture.get(cv2.CAP_PROP_POS_MSEC)) / 1000
        if not ok or frame is None:
            raise ValueError('O decodificador não entregou o frame solicitado')
        if not math.isfinite(observed) or not episode['source_start'] <= observed < episode['source_end']:
            raise ValueError('O tempo informado pelo decodificador ficou fora do episódio; tente outro frame')
        return {'episode_id': episode_id, 'requested': requested, 'timestamp': observed,
            'frame': cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), 'source': str(source),
            'pts_status': 'posição informada pelo OpenCV; PTS do frame não homologado'}
    finally:
        capture.release()


def _load_review_project(directory, cfg, source_path=None, *, log=print, progress=None, cancel=None):
    """Restore a recovered preview's verified settings without saving its plan."""
    from .utils import load_json
    header = load_json(Path(directory) / 'series_index.json', {}) or {}
    if header.get('production_import'):
        from .production_package import load_production_project
        project = load_production_project(directory, log=log, progress=progress, cancel=cancel)
        return project, _production_source(project)
    project = SeriesProject(directory, cfg, log=log, progress=progress, cancel=cancel)
    recovery = project.plan.get('story06_recovery')
    if not recovery:
        return project, None
    if not isinstance(recovery, dict) or not recovery.get('parent_project'):
        raise ValueError('Revisão recuperada sem vínculo verificável com o projeto original')
    pinned = recovery.get('render_settings')
    if pinned is not None and not isinstance(pinned, dict):
        raise ValueError('Configuração congelada da recuperação inválida')
    selected = (source_path or (pinned or {}).get('source_media', {}).get('path')
                or cfg.get('source_media', {}).get('path'))
    if not selected:
        from .utils import load_json, safe_name
        source = project.evidence.get('source') or {}
        video_id = project.plan.get('project_id') or source.get('video_id') or source.get('id')
        output_root = cfg.get('paths', {}).get('output_root')
        if output_root and video_id:
            state = load_json(Path(output_root) / 'curation' / safe_name(video_id) /
                              'EDIT_DECISIONS.json', {}) or {}
            selected = state.get('source_media_path')
    if not selected or not Path(selected).is_file():
        raise ValueError('Selecione a mídia original e retome esta revisão antes de aprovar o Story 6')
    source = Path(selected).resolve()
    from .combined_batch import _recovered_preview_info, _STORY06_ID
    parent = SeriesProject(recovery['parent_project'], cfg, log=log)
    verified = _recovered_preview_info(parent, parent.episode(_STORY06_ID), source,
                                       explicit_revision=project.directory)
    if not verified:
        raise ValueError('Revisão recuperada sem prévia íntegra para aprovação humana')
    project = verified['project']
    project.log = log
    project.progress = progress or (lambda fraction, detail='': None)
    project.cancel = cancel
    return project, source


class SeriesReview(tk.Toplevel):
    def __init__(self, master, project_root, cfg):
        super().__init__(master)
        self.rootp, self.cfg = Path(project_root), deepcopy(cfg)
        self.project = None
        self.events, self.cancel = queue.Queue(), threading.Event()
        self.busy, self.page = False, 0
        self._task_token = None
        self._closed = False
        self._pending_production_media = None
        self._production_request = None
        self._frame_generation = 0
        self.title('L.D.PORTO V5.2 · Histórias e revisão visual')
        self.geometry('1240x860')
        self.minsize(1020, 720)
        self.protocol('WM_DELETE_WINDOW', self._close)
        self._build()
        self._poll_job = self.after(100, self._poll)

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
        imports = ttk.Frame(main)
        imports.pack(fill='x', pady=4)
        for index, (label, action) in enumerate((
            ('IMPORTAR PACOTE DE PRODUÇÃO', self._import_production),
            ('Importar ZIP V5', self._import_zip), ('Importar Stories 60s', self._import_stories),
            ('Analysis concluído', self._import_directory), ('Retomar projeto', self._resume))):
            ttk.Button(imports, text=label, command=action).grid(row=index//3, column=index%3, sticky='ew', padx=3, pady=2)
        for column in range(3):
            imports.columnconfigure(column, weight=1)
        controls = ttk.Frame(main)
        controls.pack(fill='x', pady=6)
        for index, (label, action) in enumerate((
            ('Selecionar mídia', self._choose_media), ('Novo plano com preferência global', self._replan),
            ('Exportar dossiê ChatGPT', lambda: self._operate('export')), ('Renderizar aprovados', lambda: self._operate('batch')),
            ('Cancelar operação', self.cancel.set), ('Fonte canônica concluída', self._choose_canonical),
            ('Gerar prévias aptas do pacote', self._production_previews))):
            ttk.Button(controls, text=label, command=action).grid(row=index//4, column=index%4, sticky='ew', padx=3, pady=2)
        for column in range(4):
            controls.columnconfigure(column, weight=1)
        self.canonical_path=None
        self.media = tk.StringVar(value=self.cfg.get('source_media', {}).get('path') or '')
        ttk.Label(main, textvariable=self.media).pack(anchor='w')
        self.status = tk.StringVar(value='Importe somente artefatos concluídos. Propostas não autorizam publicação.')
        ttk.Label(main, textvariable=self.status, wraplength=1160).pack(anchor='w', pady=4)
        self.progress = ttk.Progressbar(main, mode='determinate', maximum=100)
        self.progress.pack(fill='x')
        self.production_summary = tk.StringVar(value='Pacotes de produção: importe um ZIP para conferir mídia, câmera e pendências por candidato.')
        ttk.Label(main, textvariable=self.production_summary, wraplength=1160, justify='left').pack(fill='x', pady=4)
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
        columns = ('order', 'kind', 'series', 'start', 'end', 'duration', 'state', 'caption', 'title')
        self.table = ttk.Treeview(edit_tab, columns=columns, show='headings', height=6, selectmode='browse')
        for key, label, width in zip(columns,
                ('Ordem', 'Tipo', 'Série', 'Início', 'Fim', 'Duração', 'Revisão', 'Legenda / bloqueio', 'Título literal/proposta'),
                (55, 85, 90, 75, 75, 70, 130, 195, 280)):
            self.table.heading(key, text=label)
            self.table.column(key, width=width, stretch=(key == 'title'))
        self.table.pack(fill='x')
        table_scroll = ttk.Scrollbar(edit_tab, orient='horizontal', command=self.table.xview)
        table_scroll.pack(fill='x')
        self.table.configure(xscrollcommand=table_scroll.set)
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
        self._build_production_controls(advanced_tab)
        self._build_camera_inspection()

    def _build_production_controls(self, parent):
        settings = ttk.LabelFrame(parent, text='Próxima importação de produção — destinos opcionais', padding=6)
        settings.pack(fill='x', before=self.diagnostic)
        self.production_output = tk.StringVar(value='')
        self.production_library = tk.StringVar(value='')
        self.production_handoff = tk.StringVar(value='')
        for row, (label, variable) in enumerate((
            ('Projetos novos (vazio = Vídeos do usuário)', self.production_output),
            ('Biblioteca de originais (vazio = padrão)', self.production_library),
            ('Dossiê visual associado (opcional)', self.production_handoff))):
            ttk.Label(settings, text=label).grid(row=row, column=0, sticky='w', padx=3, pady=2)
            ttk.Entry(settings, textvariable=variable).grid(row=row, column=1, sticky='ew', padx=3)
            def choose(target=variable):
                if not self.busy:
                    path = filedialog.askdirectory(parent=self, title='Pasta para a próxima importação')
                    if path:
                        target.set(path)
            ttk.Button(settings, text='Escolher…', command=choose).grid(row=row, column=2, padx=3)
        settings.columnconfigure(1, weight=1)

    def _build_camera_inspection(self):
        from .crop_editor import CropEditor
        container = ttk.Frame(self.tabs)
        self.tabs.add(container, text='Câmera por trecho')
        scrollbar = ttk.Scrollbar(container, orient='vertical')
        scrollbar.pack(side='right', fill='y')
        canvas = tk.Canvas(container, highlightthickness=0, yscrollcommand=scrollbar.set)
        canvas.pack(side='left', fill='both', expand=True)
        scrollbar.configure(command=canvas.yview)
        body = ttk.Frame(canvas, padding=6)
        item = canvas.create_window((0, 0), window=body, anchor='nw')
        body.bind('<Configure>', lambda event: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda event: canvas.itemconfigure(item, width=event.width))
        self.camera_context = tk.StringVar(value='Selecione um candidato. A inspeção não aprova o enquadramento.')
        ttk.Label(body, textvariable=self.camera_context, wraplength=1100).pack(fill='x')
        row = ttk.Frame(body)
        row.pack(fill='x', pady=4)
        ttk.Button(row, text='Abrir frame original no tempo selecionado', command=self._inspect_frame).pack(side='left')
        ttk.Button(row, text='Atualizar composição em rascunho', command=self._update_proposal).pack(side='left', padx=5)
        self.camera_segments = ttk.Treeview(body, columns=('piece','source','mode','target','zoom','safe'), show='headings', height=5)
        for key, label, width in (('piece','Peça (relativo)',155), ('source','Original',180), ('mode','Composição',125),
                                  ('target','Alvo',110), ('zoom','Zoom',90), ('safe','Segurança',120)):
            self.camera_segments.heading(key, text=label)
            self.camera_segments.column(key, width=width, stretch=True)
        self.camera_segments.pack(fill='x', pady=4)
        self.camera_segments.bind('<<TreeviewSelect>>', self._camera_segment_selected)
        comparison = ttk.Frame(body)
        comparison.pack(fill='x', pady=4)
        original = ttk.LabelFrame(comparison, text='Original · crop e regiões importadas')
        original.pack(side='left', fill='both', expand=True)
        self.crop_editor = CropEditor(original, on_apply=self._apply_visual_crop)
        self.crop_editor.pack(fill='both', expand=True)
        proposed = ttk.LabelFrame(comparison, text='Proposta estática')
        proposed.pack(side='left', fill='y', padx=4)
        self.proposal_label = ttk.Label(proposed, text='Abra um frame real', width=20, anchor='center')
        self.proposal_label.pack(padx=3, pady=3)
        rendered = ttk.LabelFrame(body, text='Preview renderizado · MP4 real')
        rendered.pack(fill='x', pady=4)
        self.camera_preview_player = LocalPlayer(rendered, 280, 240)
        self.camera_preview_player.pack(side='left')
        ttk.Label(rendered, text='O quadro estático ajuda a revisar o crop.\nMovimento e sincronismo são conferidos no MP4.', wraplength=650).pack(side='left', padx=12)
        self.camera_details = tk.Text(body, height=10, wrap='word')
        self.camera_details.pack(fill='both', expand=True)

    def _task(self, function, *, token=None):
        if self.busy:
            return
        self.busy = True
        self.cancel.clear()
        token = token or uuid4().hex
        self._task_token = token
        self.status.set('Processando dados existentes…')
        events = self.events
        project = self.project
        if isinstance(project, SeriesProject):
            # Import callbacks carry the import token. Each later operation needs
            # its own callbacks so valid encode progress is not treated as stale.
            project.progress = lambda fraction, detail='': events.put(('progress', (fraction, detail), token))
            project.log = lambda message: events.put(('progress', (0., str(message)), token))
        def worker():
            try:
                result = function()
                events.put(('result', result, token))
            except Exception as exc:
                events.put(('error', str(exc), token))
            finally:
                events.put(('done', None, token))
        threading.Thread(target=worker, daemon=True).start()
        return token

    def _poll(self):
        self._poll_job = None
        try:
            for _ in range(100):
                item = self.events.get_nowait()
                kind, value = item[:2]
                if len(item) == 3 and item[2] != self._task_token:
                    continue
                if kind == 'result':
                    if isinstance(value, dict) and value.get('production_import'):
                        self._accept_production_import(value)
                    elif isinstance(value, SeriesProject):
                        self._show_project(value)
                    else:
                        self._refresh()
                        if isinstance(value, dict):
                            rows = value.get('rows') or value.get('results') or value.get('order') or []
                            counts = {}
                            for row in rows if isinstance(rows, list) else []:
                                if isinstance(row, dict):
                                    status = str(row.get('status', 'sem estado'))
                                    counts[status] = counts.get(status, 0) + 1
                            self.status.set('Resultado do lote de produção: ' + json.dumps(counts or value, ensure_ascii=False)[:1600])
                            self.diagnostic.delete('1.0', 'end')
                            self.diagnostic.insert('end', json.dumps(value, ensure_ascii=False, indent=2))
                        else:
                            self.status.set(str(value))
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
                elif kind == 'inspection_frame':
                    self._accept_inspection_frame(value)
                elif kind == 'inspection_error':
                    if value['generation'] == self._frame_generation:
                        self.camera_context.set(value['message'])
                elif kind == 'inspection_done':
                    self._frame_running = False
                    pending = getattr(self, '_pending_frame_request', None)
                    self._pending_frame_request = None
                    if (pending is not None and pending['generation'] == self._frame_generation
                            and not self._closed and not self.busy):
                        self._start_frame_request(pending)
                elif kind == 'done':
                    self.busy = False
                    self._task_token = None
                    if self._pending_production_media is not None:
                        self.after(0, self._request_production_media)
        except queue.Empty:
            pass
        if not self._closed:
            self._poll_job = self.after(100, self._poll)

    def _show_project(self, project, source_path=None):
        self.project, self.page = project, 0
        self._frame_generation += 1
        self.mode.set(project.plan.get('mode', 'SERIE_CRONOLOGICA'))
        key = project.plan.get('duration_preset', PRESET_KEYS[0])
        self.duration.set(PRESET_LABELS[PRESET_KEYS.index(key)] if key in PRESET_KEYS else PRESET_LABELS[0])
        if source_path is not None:
            self.media.set(str(source_path))
        self._refresh()
        self.status.set(str(project.directory))

    def _accept_production_import(self, result):
        project = result['project']
        source = result.get('source_path')
        summary = result.get('summary') or project.plan.get('production_import', {}).get('summary') or {}
        self.media.set(str(source) if source else '')
        self.production_summary.set(_production_summary(summary, project, source))
        self._show_project(project, source)
        self.diagnostic.delete('1.0', 'end')
        self.diagnostic.insert('end', json.dumps(summary, ensure_ascii=False, indent=2))
        if self._production_request is None and project.plan.get('production_import', {}).get('package_path'):
            record = project.plan['production_import']
            options = record.get('import_options') or {}
            self._production_request = {'path': record['package_path'], 'cfg': deepcopy(project.cfg),
                **{key: options.get(key, record.get(key)) for key in ('output_root', 'media_library', 'handoff_dir')}}
        if not source and self._production_request is not None:
            self._pending_production_media = deepcopy(self._production_request)

    def _import_production(self, path=None, *, media_path=None, request=None):
        if self.busy:
            return
        path = path or filedialog.askopenfilename(parent=self, title='IMPORTAR PACOTE DE PRODUÇÃO', filetypes=[('Pacote de produção ZIP', '*.zip')])
        if not path:
            return
        options = deepcopy(request) if request else {
            'path': str(path), 'cfg': deepcopy(self.cfg),
            'output_root': self.production_output.get().strip() or None,
            'media_library': self.production_library.get().strip() or None,
            'handoff_dir': self.production_handoff.get().strip() or None,
        }
        options['path'] = str(path)
        self._production_request = deepcopy(options)
        self._pending_production_media = None
        events, cancel, token = self.events, self.cancel, uuid4().hex
        def create():
            from .production_package import import_production_package
            return import_production_package(options['path'], cfg=options['cfg'],
                output_root=options.get('output_root'), media_library=options.get('media_library'),
                media_path=media_path, handoff_dir=options.get('handoff_dir'), cancel=cancel,
                log=lambda message: events.put(('progress', (0., str(message)), token)),
                progress=lambda fraction, detail='': events.put(('progress', (fraction, detail), token)))
        self._task(create, token=token)

    def _request_production_media(self):
        if self.busy or self._pending_production_media is None or self._closed:
            return
        request = self._pending_production_media
        self._pending_production_media = None
        selected = filedialog.askopenfilename(parent=self,
            title='Mídia ausente — selecione o original para validar SHA256',
            filetypes=[('Vídeo original', '*.mp4 *.mkv *.mov *.webm')])
        if selected:
            self._import_production(request['path'], media_path=selected, request=request)
        else:
            self.status.set('Projeto importado preservado; mídia pendente de seleção e validação SHA256.')

    def _production_previews(self):
        if self.busy or not self.project:
            return
        if not self.project.plan.get('production_import'):
            messagebox.showinfo('Prévia de produção', 'Este comando usa um projeto criado por IMPORTAR PACOTE DE PRODUÇÃO.', parent=self)
            return
        project, media, events, cancel, token = self.project, self.media.get(), self.events, self.cancel, uuid4().hex
        if not media:
            self.status.set('Selecione e valide a mídia original antes de gerar prévias.')
            return
        def render():
            from .production_package import render_production_previews
            return render_production_previews(project, media, cancel=cancel,
                log=lambda message: events.put(('progress', (0., str(message)), token)),
                progress=lambda fraction, detail='': events.put(('progress', (fraction, detail), token)))
        self._task(render, token=token)

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
            from .utils import load_json
            header = load_json(path, {}) or {}
            if header.get('production_import'):
                directory, cfg, cancel, events = Path(path).parent, deepcopy(self.cfg), self.cancel, self.events
                def restore_production():
                    project, source = _load_review_project(directory, cfg, cancel=cancel,
                        progress=lambda fraction, detail='': events.put(('progress', (fraction, detail))))
                    return {'production_import': True, 'project': project, 'source_path': source,
                            'summary': project.plan['production_import'].get('summary', {})}
                self._production_request = None
                self._pending_production_media = None
                self._task(restore_production)
                return
            try:
                project, source = _load_review_project(Path(path).parent, self.cfg,
                    self.media.get(), cancel=self.cancel,
                    progress=lambda f,d='': self.events.put(('progress',(f,d))))
            except (ValueError, OSError, KeyError) as exc:
                self.status.set(str(exc))
                messagebox.showerror('Retomar revisão', str(exc), parent=self)
                return
            self.project = project
            if source is not None:
                self.media.set(str(source))
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
                episode.get('piece_kind', 'EPISÓDIO'), episode.get('series_id', ''),
                f"{episode['source_start']:.3f}", f"{episode['source_end']:.3f}", f"{episode['duration']:.3f}",
                episode.get('state') or episode.get('status'),
                episode.get('production_caption_gate', {}).get('state') or episode.get('subtitle_alignment', ''), title))
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
        else:
            self.preview_player.stop()
            self.preview_player.canvas.delete('all')
            self.preview_player.caption.set('Prévia ainda não gerada para esta peça.')
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
        self._refresh_camera_inspection(episode)

    def _choose_media(self):
        if self.busy:
            return
        path = filedialog.askopenfilename(parent=self,filetypes=[('Vídeo','*.mp4 *.mkv *.webm *.mov')])
        if path:
            if self.project and self.project.plan.get('production_import'):
                if self._production_request is not None:
                    request = deepcopy(self._production_request)
                    self._import_production(request['path'], media_path=path, request=request)
                    return
            self.media.set(path)
            self._select()

    def _refresh_camera_inspection(self, episode):
        self._frame_generation += 1
        self._inspection_rows = _camera_inspection_rows(episode)
        self._inspection_segment = None
        self._inspection_mode = None
        self.crop_editor.set_episode(episode, self.project.evidence)
        self.proposal_label.configure(image='', text='Abra um frame original')
        self._proposal_photo = None
        self.camera_segments.delete(*self.camera_segments.get_children())
        for row in self._inspection_rows:
            self.camera_segments.insert('', 'end', iid=str(row['index']), values=(
                f"+{timestamp(row['start'])} → +{timestamp(row['end'])}",
                f"{timestamp(row['source_start'])} → {timestamp(row['source_end'])}",
                row['mode'], row['target'], row['zoom'], row['safety']))
        preflight = (episode.get('production_caption_gate') or episode.get('caption_preflight')
                     or episode.get('caption_state') or episode.get('subtitle_alignment') or 'consulte o preflight do pacote')
        state = (preflight.get('state') or preflight.get('status') or 'revisão necessária') if isinstance(preflight, dict) else str(preflight)
        self.camera_context.set(f"{episode['episode_id']} · fonte {timestamp(episode['source_start'])} → {timestamp(episode['source_end'])} · legenda: {state}")
        self.camera_details.delete('1.0', 'end')
        self.camera_details.insert('end', json.dumps({
            'episode_id': episode['episode_id'], 'source_start': episode['source_start'],
            'source_end': episode['source_end'], 'camera_plan': episode.get('camera_plan'),
            'camera_keyframes': episode.get('camera_keyframes', []), 'caption_preflight': preflight,
            'subtitle_preset': episode.get('subtitle_preset'), 'subtitle_overrides': episode.get('subtitle_overrides'),
            'title_text': episode.get('title_text'), 'risk_flags': episode.get('risk_flags'),
            'protected_regions': self.project.evidence.get('protected_regions', []),
        }, ensure_ascii=False, indent=2))
        preview = episode.get('preview', {}).get('project_path')
        if preview:
            self.camera_preview_player.show(self.project.directory / preview)
        else:
            self.camera_preview_player.stop()
            self.camera_preview_player.canvas.delete('all')
            self.camera_preview_player.caption.set('Prévia ainda não gerada para esta peça.')

    def _camera_segment_selected(self, _event=None):
        selected = self.camera_segments.selection()
        if not selected or self.busy:
            return
        row = next((r for r in self._inspection_rows if str(r['index']) == selected[0]), None)
        if row:
            self.source_seek.set(row['source_start'])
            self.camera_context.set(f"{row['mode']} · alvo {row['target']} · segurança {row['safety']} · {row['reason']}")
            self._timeline_seek(row['source_start'])

    def _inspect_frame(self):
        if self.busy or not self.project or not self._selected():
            return
        media = self.media.get()
        if not media:
            self.camera_context.set('Selecione a mídia original; o SHA256 será conferido antes de abrir o frame.')
            return
        self._frame_generation += 1
        request = {'generation': self._frame_generation, 'project': self.project,
            'episode_id': self._selected(), 'media': media, 'requested': float(self.source_seek.get())}
        if getattr(self, '_frame_running', False):
            self._pending_frame_request = request
            return
        self._start_frame_request(request)

    def _start_frame_request(self, request):
        self._frame_running = True
        self.camera_context.set('Validando mídia e decodificando um frame original…')
        events = self.events
        def decode():
            try:
                result = _read_inspection_frame(request['project'], request['episode_id'], request['media'], request['requested'])
                result.update(generation=request['generation'], project_directory=str(request['project'].directory))
                events.put(('inspection_frame', result))
            except Exception as exc:
                events.put(('inspection_error', {'generation': request['generation'], 'message': str(exc)}))
            finally:
                events.put(('inspection_done', None))
        threading.Thread(target=decode, daemon=True, name='ldporto-frame-inspection').start()

    def _accept_inspection_frame(self, result):
        if (result['generation'] != self._frame_generation or not self.project
                or result['episode_id'] != self._selected()
                or result['project_directory'] != str(self.project.directory)
                or result['source'] != str(Path(self.media.get()).resolve())):
            return
        try:
            episode = self.project.episode(result['episode_id'])
            self.crop_editor.show_frame(result['frame'], result['timestamp'], result['pts_status'])
            relative = result['timestamp'] - episode['source_start']
            row = next((row for row in self._inspection_rows if row['start'] <= relative < row['end']), None)
            self._inspection_segment = row['segment'] if row else None
            self._inspection_mode = row['mode'] if row else 'sem plano'
            if row and row['mode'] == 'crop' and not episode.get('camera_keyframes'):
                from .render import _crop_dims_for_zoom
                x, y, zoom, target_y = _inspection_pose(row['segment'], relative)
                model = self.crop_editor.model
                cw, ch = _crop_dims_for_zoom(model.width, model.height, 9/16, zoom)
                top = max(0., min(model.height-ch, y*model.height-ch*target_y))
                model.set_position(x, (top + ch/2)/model.height, zoom)
                self.crop_editor.zoom_value.set(zoom)
                self.crop_editor.draw()
            self._update_proposal()
            self.camera_context.set(f"Original solicitado {timestamp(result['requested'])}; backend {timestamp(result['timestamp'])} · {result['pts_status']}")
        except (ValueError, TypeError, KeyError) as exc:
            self.camera_context.set('Inspeção requer revisão: ' + str(exc))

    def _update_proposal(self):
        from PIL import Image, ImageTk, ImageOps, ImageFilter
        editor = self.crop_editor
        if editor.model is None or editor._frame is None:
            return
        source = editor._frame
        mode = 'crop' if editor._pose_dirty or editor.points else self._inspection_mode
        if mode == 'crop':
            rect = editor.model.rectangle()
            bounds = (round(rect['x']), round(rect['y']), round(rect['x']+rect['width']), round(rect['y']+rect['height']))
            proposal = source.crop(bounds).resize((180, 320), Image.Resampling.LANCZOS)
        elif mode in {'full_frame_blur', 'SOURCE_PRESERVE', 'source_preserve'}:
            proposal = ImageOps.fit(source, (180, 320)).filter(ImageFilter.GaussianBlur(12))
            foreground = ImageOps.contain(source, (180, 320))
            proposal.paste(foreground, ((180-foreground.width)//2, (320-foreground.height)//2))
        else:
            self.proposal_label.configure(image='', text=f'{mode or "Sem plano"}\nConfira o preview renderizado')
            self._proposal_photo = None
            return
        self._proposal_photo = ImageTk.PhotoImage(proposal)
        self.proposal_label.configure(image=self._proposal_photo, text='Frame de referência; aprovação pendente', compound='bottom')

    def _apply_visual_crop(self, points, mode, diagnostic):
        key = self._selected()
        if self.busy or not self.project or not key:
            return
        if mode not in {'MANUAL_KEYFRAMES', 'SOURCE_PRESERVE'}:
            raise ValueError('Modo manual incompatível com o editor existente')
        if mode == 'MANUAL_KEYFRAMES' and diagnostic.get('manual_apply_allowed') is not True:
            self.status.set('Crop bloqueado pelo diagnóstico; preserve a fonte e revise as regiões críticas.')
            return
        episode = self.project.episode(key)
        if (episode.get('human_approval') or episode.get('state') in {'PREVIEW_APPROVED','FINAL_RENDERED','PUBLISH_READY'}
                or episode.get('status') in {'PREVIEW_APPROVED','FINAL_RENDERED','PUBLISH_READY'}):
            if not messagebox.askyesno('Nova revisão de câmera', 'Este ajuste invalida a aprovação da peça atual e preserva os arquivos anteriores. Continuar?', parent=self):
                return
        project, captured = self.project, deepcopy(points) if mode == 'MANUAL_KEYFRAMES' else []
        self._task(lambda: (project.edit(key, camera_mode=mode, camera_keyframes=captured, confirm_invalidation=True),
            'Nova revisão de câmera salva; gere e revise outra prévia.')[1])

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
        camera_player = getattr(self, 'camera_preview_player', None)
        if camera_player is not None:
            camera_player.stop()

    def _close(self):
        self._closed = True
        self._task_token = None
        self._frame_generation += 1
        self._pending_frame_request = None
        if self._poll_job is not None:
            self.after_cancel(self._poll_job)
            self._poll_job = None
        self.cancel.set()
        self._stop()
        self.destroy()
