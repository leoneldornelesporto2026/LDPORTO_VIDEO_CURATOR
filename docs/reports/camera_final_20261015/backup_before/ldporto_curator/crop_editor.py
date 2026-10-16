"""Manual crop geometry and Tk controls over explicitly supplied source frames.

This module never opens media, discovers files or runs visual detectors. Geometry
comes from an observed RGB frame and the evidence already imported by Curator.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import math
import tkinter as tk
from tkinter import ttk

from .render import _crop_dims_for_zoom
from .timeline_editor import timestamp


def _finite(value, label):
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError(f'{label}: número inválido') from exc
    if not math.isfinite(number):
        raise ValueError(f'{label}: número não finito')
    return number


@dataclass(frozen=True)
class FrameFit:
    """Letterboxed mapping from original source pixels to the canvas."""
    width: int
    height: int
    canvas_width: float
    canvas_height: float

    def __post_init__(self):
        if min(self.width, self.height, self.canvas_width, self.canvas_height) <= 0:
            raise ValueError('Dimensões do frame/canvas devem ser positivas')

    @property
    def scale(self):
        return min(self.canvas_width / self.width, self.canvas_height / self.height)

    @property
    def offset(self):
        return ((self.canvas_width - self.width * self.scale) / 2,
                (self.canvas_height - self.height * self.scale) / 2)

    def to_canvas(self, x, y):
        ox, oy = self.offset
        return ox + x * self.scale, oy + y * self.scale

    def to_source(self, x, y, clamp=True):
        ox, oy = self.offset
        x, y = (x - ox) / self.scale, (y - oy) / self.scale
        if clamp:
            return max(0, min(self.width, x)), max(0, min(self.height, y))
        return x, y


@dataclass
class CropModel:
    width: int
    height: int
    episode_duration: float
    x: float = .5
    y: float = .5
    zoom: float = 1.
    points: list = field(default_factory=list)

    def __post_init__(self):
        self.width, self.height = int(self.width), int(self.height)
        self.episode_duration = _finite(self.episode_duration, 'Duração')
        if min(self.width, self.height) < 2 or self.episode_duration <= 0:
            raise ValueError('Frame ou duração inválidos')
        self.set_position(self.x, self.y, self.zoom)
        self.points = self.validate_keyframes(self.points)

    def rectangle(self, point=None):
        point = point or {'x': self.x, 'y': self.y, 'zoom': self.zoom}
        x, y, zoom = (_finite(point.get(k, default), k)
                      for k, default in [('x', .5), ('y', .5), ('zoom', 1)])
        if not 0 <= x <= 1 or not 0 <= y <= 1 or not 1 <= zoom <= 1.13:
            raise ValueError('Crop fora dos limites físicos: x/y 0–1, zoom 1–1,13')
        cw, ch = _crop_dims_for_zoom(self.width, self.height, 9 / 16, zoom)
        left = max(0., min(self.width - cw, x * self.width - cw / 2))
        top = max(0., min(self.height - ch, y * self.height - ch / 2))
        return {'x': left, 'y': top, 'width': cw, 'height': ch}

    def set_position(self, x, y, zoom=None):
        zoom = self.zoom if zoom is None else _finite(zoom, 'Zoom')
        rect = self.rectangle({'x': x, 'y': y, 'zoom': zoom})
        # Store the visible center, matching the renderer's physical clamping.
        self.x = (rect['x'] + rect['width'] / 2) / self.width
        self.y = (rect['y'] + rect['height'] / 2) / self.height
        self.zoom = zoom
        return rect

    def fit(self, canvas_width, canvas_height):
        return FrameFit(self.width, self.height, canvas_width, canvas_height)

    def validate_keyframes(self, points):
        result = []
        for original in points:
            if not isinstance(original, dict):
                raise ValueError('Keyframe deve ser um objeto')
            point = deepcopy(original)
            for key, default in [('time', None), ('x', .5), ('y', .5), ('zoom', 1.)]:
                point[key] = _finite(point.get(key, default), key)
            if not 0 <= point['time'] < self.episode_duration:
                raise ValueError('Keyframe deve ficar dentro do episódio, antes do fim')
            self.rectangle(point)
            if result:
                previous = result[-1]
                dt = point['time'] - previous['time']
                if dt <= 0:
                    raise ValueError('Keyframes devem seguir ordem temporal, sem duplicatas')
                # Smoothstep derivative reaches 1.5, unlike average speed.
                if (1.5 * abs(point['x'] - previous['x']) / dt > .18 + 1e-12 or
                    1.5 * abs(point['y'] - previous['y']) / dt > .12 + 1e-12):
                    raise ValueError('Pico de velocidade excede pan 0,18/tilt 0,12 por segundo')
            result.append(point)
        return result

    def set_keyframes(self, points):
        validated = self.validate_keyframes(points)
        self.points = validated
        return deepcopy(validated)

    def at(self, relative_time):
        """Match smooth positional motion and the renderer's per-segment zoom."""
        time = max(0, min(self.episode_duration, _finite(relative_time, 'Tempo')))
        if not self.points:
            return {'time': time, 'x': self.x, 'y': self.y, 'zoom': self.zoom}
        previous = self.points[0]
        for following in self.points[1:]:
            if time < following['time']:
                fraction = max(0, (time - previous['time']) / (following['time'] - previous['time']))
                eased = fraction * fraction * (3 - 2 * fraction)
                return {'time': time,
                        'x': previous['x'] + (following['x'] - previous['x']) * eased,
                        'y': previous['y'] + (following['y'] - previous['y']) * eased,
                        'zoom': previous['zoom']}
            previous = following
        return {**previous, 'time': time}


def _bbox(row, width, height):
    """Read documented box shapes; ambiguous array geometry stays unknown."""
    box = row.get('bbox', row.get('box', row))
    if isinstance(box, (list, tuple)):
        if len(box) != 4 or row.get('bbox_format') not in {'xyxy', 'xywh'}:
            return None
        box = (dict(zip(('x_start', 'y_start', 'x_end', 'y_end'), box))
               if row['bbox_format'] == 'xyxy' else dict(zip(('x', 'y', 'width', 'height'), box)))
    if not isinstance(box, dict):
        return None
    if all(key in box for key in ('x', 'y', 'width', 'height')):
        values = [box['x'], box['y'], box['width'], box['height']]
        form = 'xywh'
    elif all(key in box for key in ('x_start', 'y_start', 'x_end', 'y_end')):
        values = [box['x_start'], box['y_start'], box['x_end'], box['y_end']]
        form = 'xyxy'
    elif all(key in box for key in ('x1', 'y1', 'x2', 'y2')):
        values = [box['x1'], box['y1'], box['x2'], box['y2']]
        form = 'xyxy'
    else:
        return None
    try:
        values = [_finite(value, 'BBox') for value in values]
    except ValueError:
        return None
    units = box.get('units', row.get('bbox_units', row.get('coordinate_space')))
    if units in {'normalized', 'relative'} or (units is None and all(0 <= v <= 1 for v in values)):
        values = [values[0] * width, values[1] * height, values[2] * width, values[3] * height]
    elif units not in {'pixel', 'pixels', 'source_pixels'}:
        return None
    x, y, right, bottom = values
    if form == 'xywh':
        right, bottom = x + right, y + bottom
    if not 0 <= x < right <= width or not 0 <= y < bottom <= height:
        return None
    return {'x': x, 'y': y, 'width': right - x, 'height': bottom - y}


def protected_regions(evidence, episode, width, height, source_timestamp=None):
    """Return actual critical geometry plus explicit unknown-geometry warnings.

    An untimed critical observation applies conservatively to the episode. The
    fallback is a diagnostic, never a fabricated full-frame detection.
    """
    regions, unknown = [], []
    start, end = episode['source_start'], episode['source_end']
    critical_tokens = ('map', 'mapa', 'instrument', 'cockpit', 'diagram', 'gráfico',
                       'grafico', 'screen', 'tela', 'slide')

    def active(row):
        try:
            a, b = row.get('start'), row.get('end')
            if a is not None and b is not None:
                a, b = _finite(a, 'Início'), _finite(b, 'Fim')
                return b > start and a < end and (source_timestamp is None or a <= source_timestamp < b)
            time = row.get('time', row.get('timestamp'))
            if time is not None:
                time = _finite(time, 'Tempo')
                return start <= time <= end and (source_timestamp is None or abs(time - source_timestamp) <= .001)
        except ValueError:
            return True  # Malformed timing cannot erase a known critical warning.
        return True

    def visit(row, component, index, inherited=False):
        if not isinstance(row, dict) or not active(row):
            return
        label = str(row.get('kind', row.get('type', row.get('label', ''))))
        critical = (inherited or component in {'ocr', 'graphics', 'protected_regions'} or
                    row.get('critical_content') is True or row.get('critical_text') is True or
                    row.get('crop_risk') in {'high', 'critical'} or
                    any(token in label.casefold() for token in critical_tokens))
        children = []
        for key in ('regions', 'graphics_regions', 'protected_regions', 'objects', 'ocr'):
            value = row.get(key, [])
            if isinstance(value, list):
                children += [(child, key) for child in value]
        if critical:
            geometry = _bbox(row, width, height)
            origin = str(row.get('scene_id', row.get('frame_sample_id', row.get('id', f'{component}:{index}'))))
            if geometry:
                regions.append({**geometry, 'evidence_id': origin, 'component': component,
                                'label': label or component, 'geometry_status': 'available'})
            elif not children:
                unknown.append({'evidence_id': origin, 'component': component,
                                'reason': 'critical_geometry_unknown', 'fallback': 'SOURCE_PRESERVE'})
        for at, (child, kind) in enumerate(children):
            visit(child, 'graphics' if kind == 'graphics_regions' else kind, f'{index}.{at}', critical)

    for component in ('scenes', 'timeline', 'frame_samples', 'ocr', 'graphics', 'protected_regions'):
        rows = evidence.get(component, [])
        if isinstance(rows, dict):
            rows = rows.get('intervals', rows.get('regions', []))
        if isinstance(rows, list):
            for index, row in enumerate(rows):
                visit(row, component, index)
    if 'critical_visuals_need_source_preservation' in episode.get('risk_flags', []) and not (regions or unknown):
        unknown.append({'evidence_id': episode.get('episode_id', 'episode'), 'component': 'risk_flags',
                        'reason': 'critical_geometry_unknown', 'fallback': 'SOURCE_PRESERVE'})
    return regions, unknown


def crop_diagnostic(model, points, evidence, episode):
    """Check each trajectory against actual regions without inventing certainty."""
    points = model.validate_keyframes(points)
    regions, unknown = protected_regions(evidence, episode, model.width, model.height)
    clipped = []
    for point in points:
        rect = model.rectangle(point)
        for region in regions:
            if not (rect['x'] <= region['x'] + 1e-8 and rect['y'] <= region['y'] + 1e-8 and
                    rect['x'] + rect['width'] >= region['x'] + region['width'] - 1e-8 and
                    rect['y'] + rect['height'] >= region['y'] + region['height'] - 1e-8):
                clipped.append({'time': point['time'], 'evidence_id': region['evidence_id'],
                                'reason': 'protected_region_would_be_clipped'})
    return {'status': 'fallback_required' if clipped or unknown else 'needs_human_review',
            'recommended_mode': 'SOURCE_PRESERVE' if clipped or unknown else 'MANUAL_KEYFRAMES',
            'manual_apply_allowed': bool(points) and not (clipped or unknown),
            'protected_regions': regions, 'unknown_geometry': unknown, 'clipped_regions': clipped,
            'observation_scope': 'supplied_frames_and_imported_geometry',
            'unobserved_frames': 'unknown', 'interpolation': 'smoothstep_position_zoom_per_segment'}


class CropEditor(ttk.Frame):
    """A draft editor; only Apply calls the caller's persisted edit operation."""
    def __init__(self, master, on_apply=None, on_keyframe_change=None):
        super().__init__(master)
        self.on_apply = on_apply or (lambda points, mode, diagnostic: None)
        self.on_keyframe_change = on_keyframe_change or (lambda points: None)
        self.episode, self.evidence, self.model = {}, {}, None
        self._points, self._frame, self._photo = [], None, None
        self.current_frame = None
        self._drag_origin, self._pose_dirty = None, False
        self.zoom_value = tk.DoubleVar(value=1.)
        self.safe_zone = tk.BooleanVar(value=True)
        self.info = tk.StringVar(value='Abra um frame real da fonte para ajustar o crop.')
        self.draft = tk.StringVar(value='Sem frame observado; SOURCE_PRESERVE disponível.')
        controls = ttk.Frame(self)
        controls.pack(fill='x')
        ttk.Label(controls, text='Zoom').pack(side='left')
        ttk.Scale(controls, from_=1, to=1.13, variable=self.zoom_value,
                  command=self._zoom, length=140).pack(side='left', padx=4)
        ttk.Checkbutton(controls, text='Safe zone de referência', variable=self.safe_zone,
                        command=self.draw).pack(side='left', padx=4)
        ttk.Button(controls, text='Preservar fonte', command=self.apply_source_preserve).pack(side='right')
        self.canvas = tk.Canvas(self, width=600, height=270, bg='#171b22', highlightthickness=0)
        self.canvas.pack(fill='both', expand=True, pady=4)
        self.canvas.bind('<Configure>', lambda event: self.draw())
        self.canvas.bind('<ButtonPress-1>', self._press)
        self.canvas.bind('<B1-Motion>', self._drag)
        self.canvas.bind('<ButtonRelease-1>', lambda event: setattr(self, '_drag_origin', None))
        ttk.Label(self, textvariable=self.info, wraplength=1000).pack(anchor='w')
        self.keyframe_canvas = tk.Canvas(self, height=30, bg='#e5e7eb', highlightthickness=0)
        self.keyframe_canvas.pack(fill='x', pady=3)
        self.keyframe_canvas.bind('<Configure>', lambda event: self._draw_keyframes())
        row = ttk.Frame(self)
        row.pack(fill='x')
        self.listbox = tk.Listbox(row, height=3, exportselection=False, width=55)
        self.listbox.pack(side='left', fill='x', expand=True)
        self.listbox.bind('<<ListboxSelect>>', self._select_point)
        for text, command in [('Adicionar/atualizar no frame', self.add_keyframe),
                              ('Excluir selecionado', self.delete_keyframe),
                              ('Aplicar crop', self.apply)]:
            ttk.Button(row, text=text, command=command).pack(side='left', padx=3)
        ttk.Label(self, textvariable=self.draft, wraplength=1000).pack(anchor='w', pady=3)

    @property
    def points(self):
        return deepcopy(self._points)

    @points.setter
    def points(self, points):
        if self.model:
            points = self.model.set_keyframes(points)
        self._points = deepcopy(points)
        self._refresh_points()

    def set_episode(self, episode, evidence):
        self.episode, self.evidence = deepcopy(episode), evidence
        self._points = deepcopy(episode.get('camera_keyframes') or [])
        self.model, self.current_frame, self._frame, self._photo = None, None, None, None
        self._pose_dirty = False
        self.info.set('Abra a fonte no player para observar um frame real deste episódio.')
        self.draft.set('Ajustes visuais só alteram o episódio após Aplicar; interpolação suave de posição.')
        self._refresh_points()
        self.draw()

    def show_frame(self, rgb_frame, source_timestamp, pts_status='not_measured'):
        from PIL import Image
        time = _finite(source_timestamp, 'Timestamp original')
        start, end = self.episode.get('source_start'), self.episode.get('source_end')
        if start is None or end is None or not start <= time <= end:
            raise ValueError('Frame fora do episódio selecionado')
        frame = rgb_frame if isinstance(rgb_frame, Image.Image) else Image.fromarray(rgb_frame)
        if frame.mode != 'RGB':
            raise ValueError('Forneça frame RGB original decodificado')
        width, height = frame.size
        if not self.model or (self.model.width, self.model.height) != (width, height):
            self.model = CropModel(width, height, end - start)
            try:
                self.model.set_keyframes(self._points)
            except ValueError as exc:
                self.draft.set(f'Keyframes importados requerem revisão: {exc}')
        self._frame = frame.copy()
        self.current_frame = {'source_timestamp': time, 'relative_time': time - start,
                              'episode_id': self.episode.get('episode_id'), 'source_start': start,
                              'width': width, 'height': height, 'pts_status': pts_status,
                              'observation': 'supplied_decoded_rgb_frame'}
        if not self._pose_dirty:
            point = self.model.at(time - start)
            self.model.set_position(point['x'], point['y'], point['zoom'])
            self.zoom_value.set(point['zoom'])
        self.info.set(f'Original {timestamp(time)} · episódio +{timestamp(time-start)} · '
                      f'{width}×{height} · PTS {pts_status}')
        self.draw()

    def _refresh_points(self):
        self.listbox.delete(0, 'end')
        for point in self._points:
            self.listbox.insert('end', f"+{timestamp(point['time'])}  x={point.get('x', .5):.3f}  "
                                f"y={point.get('y', .5):.3f}  zoom={point.get('zoom', 1):.3f}")
        self._draw_keyframes()

    def _draw_keyframes(self):
        canvas = self.keyframe_canvas
        canvas.delete('all')
        width = max(1, canvas.winfo_width() - 16)
        duration = self.episode.get('source_end', 1) - self.episode.get('source_start', 0)
        if duration <= 0:
            return
        canvas.create_line(8, 15, width + 8, 15, fill='#64748b')
        for point in self._points:
            x = 8 + width * point['time'] / duration
            canvas.create_polygon(x, 5, x+5, 15, x, 25, x-5, 15, fill='#b91c1c')
        if self.current_frame:
            x = 8 + width * self.current_frame['relative_time'] / duration
            canvas.create_line(x, 0, x, 30, fill='#2563eb', width=2)

    def _zoom(self, value):
        if self.model:
            self.model.set_position(self.model.x, self.model.y, float(value))
            self._pose_dirty = True
            self.draft.set('Crop em rascunho; adicione/atualize um keyframe e clique Aplicar.')
            self.draw()

    def _press(self, event):
        if not self.model or not self.current_frame:
            return
        fit = self.model.fit(max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height()))
        px, py = fit.to_source(event.x, event.y, clamp=False)
        rect = self.model.rectangle()
        if rect['x'] <= px <= rect['x'] + rect['width'] and rect['y'] <= py <= rect['y'] + rect['height']:
            self._drag_origin = (px, py, self.model.x, self.model.y)

    def _drag(self, event):
        if not self._drag_origin or not self.model:
            return
        fit = self.model.fit(max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height()))
        px, py = fit.to_source(event.x, event.y)
        ox, oy, cx, cy = self._drag_origin
        self.model.set_position(max(0, min(1, cx + (px-ox)/self.model.width)),
                                max(0, min(1, cy + (py-oy)/self.model.height)))
        self._pose_dirty = True
        self.draft.set('Posição em rascunho; adicione/atualize um keyframe e clique Aplicar.')
        self.draw()

    def _select_point(self, event=None):
        selected = self.listbox.curselection()
        if selected and self.model:
            point = self._points[selected[0]]
            self.model.set_position(point.get('x', .5), point.get('y', .5), point.get('zoom', 1))
            self.zoom_value.set(self.model.zoom)
            self._pose_dirty = True
            self.draw()

    def add_keyframe(self):
        if not self.current_frame or not self.model:
            self.draft.set('Observe um frame real da fonte antes de adicionar keyframe.')
            return
        time = self.current_frame['relative_time']
        point = {'time': time, 'x': self.model.x, 'y': self.model.y, 'zoom': self.model.zoom,
                 'episode_id': self.episode.get('episode_id'),
                 'original_episode_id': self.episode.get('original_episode_id', self.episode.get('episode_id')),
                 'source_start': self.episode['source_start'],
                 'source_timestamp': self.current_frame['source_timestamp']}
        points = [p for p in self._points if abs(p['time'] - time) > .001] + [point]
        points.sort(key=lambda p: p['time'])
        try:
            self.points = points
        except ValueError as exc:
            self.draft.set(str(exc))
            return
        self._pose_dirty = False
        self.draft.set('Keyframes em rascunho; nenhuma prévia/aprovação mudou até Aplicar.')
        self.on_keyframe_change(self.points)

    def delete_keyframe(self):
        selected = self.listbox.curselection()
        if not selected:
            return
        points = self.points
        del points[selected[0]]
        try:
            self.points = points
        except ValueError as exc:
            self.draft.set(str(exc))
            return
        self.draft.set('Exclusão em rascunho; clique Aplicar para persistir.')
        self.on_keyframe_change(self.points)

    def apply(self):
        if not self.model or not self.current_frame:
            self.draft.set('Observe um frame real da fonte antes de aplicar crop manual.')
            return
        try:
            diagnostic = crop_diagnostic(self.model, self.points, self.evidence, self.episode)
        except ValueError as exc:
            self.draft.set(str(exc))
            return
        if not diagnostic['manual_apply_allowed']:
            self.draft.set('Crop bloqueado: região crítica cortada/desconhecida ou sem keyframes. Use Preservar fonte.')
            return
        self.on_apply(self.points, 'MANUAL_KEYFRAMES', diagnostic)
        self.draft.set('Crop aplicado para revisão; gere e assista à nova prévia.')

    def apply_source_preserve(self):
        self.on_apply(self.points, 'SOURCE_PRESERVE', {'status': 'source_preserved',
                      'recommended_mode': 'SOURCE_PRESERVE', 'crop_safe': False})

    def draw(self):
        from PIL import Image, ImageTk
        canvas = self.canvas
        canvas.delete('all')
        cw, ch = max(1, canvas.winfo_width()), max(1, canvas.winfo_height())
        if not self.model or self._frame is None:
            canvas.create_text(cw/2, ch/2, text='Frame real da fonte ainda não observado', fill='white')
            return
        fit = self.model.fit(cw, ch)
        size = (max(1, round(self.model.width * fit.scale)), max(1, round(self.model.height * fit.scale)))
        self._photo = ImageTk.PhotoImage(self._frame.resize(size, Image.Resampling.BILINEAR))
        canvas.create_image(*fit.offset, image=self._photo, anchor='nw')
        rect = self.model.rectangle()

        def box(item, **kwargs):
            canvas.create_rectangle(*fit.to_canvas(item['x'], item['y']),
                                    *fit.to_canvas(item['x']+item['width'], item['y']+item['height']), **kwargs)

        box(rect, outline='#ff3b30', width=3)
        if self.safe_zone.get():
            # Platform controls differ: this is an editable-composition reference.
            safe = {'x': rect['x']+rect['width']*.08, 'y': rect['y']+rect['height']*.08,
                    'width': rect['width']*.80, 'height': rect['height']*.72}
            box(safe, outline='#a3e635', width=1, dash=(4, 3))
        regions, unknown = protected_regions(self.evidence, self.episode, self.model.width,
                                               self.model.height, self.current_frame['source_timestamp'])
        for region in regions:
            box(region, outline='#fbbf24', width=2, dash=(6, 3))
            canvas.create_text(*fit.to_canvas(region['x'], region['y']),
                               text=region['label'], fill='#fbbf24', anchor='nw')
        if unknown:
            canvas.create_text(cw/2, 12, text='Geometria crítica desconhecida: preservar fonte', fill='#fbbf24')
        self._draw_keyframes()
