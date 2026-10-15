from __future__ import annotations

from pathlib import Path
import os
from PIL import Image, ImageDraw, ImageFont


def _font_candidates(preferred: str | None = None):
    paths = []
    if preferred:
        p = Path(preferred)
        if p.exists():
            paths.append(p)
    win = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Fonts'
    for name in ('seguisb.ttf', 'segoeuib.ttf', 'arialbd.ttf', 'arial.ttf'):
        paths.append(win / name)
    for p in (
        Path('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'),
        Path('/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf'),
    ):
        paths.append(p)
    return paths


def _load_font(size: int, preferred: str | None = None):
    for p in _font_candidates(preferred):
        try:
            if p.exists():
                return ImageFont.truetype(str(p), size=size)
        except Exception:
            pass
    try:
        return ImageFont.truetype('arialbd.ttf', size=size)
    except Exception:
        return ImageFont.load_default()


def _text_width(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    if not text:
        return 0
    box = draw.textbbox((0, 0), text, font=font)
    return int(box[2] - box[0])


def _balanced_two_lines(draw, text: str, font, max_width: int):
    words = str(text).strip().split()
    if not words:
        return ['']
    whole = ' '.join(words)
    if _text_width(draw, whole, font) <= max_width:
        return [whole]
    best = None
    for i in range(1, len(words)):
        a = ' '.join(words[:i])
        b = ' '.join(words[i:])
        wa = _text_width(draw, a, font)
        wb = _text_width(draw, b, font)
        if wa <= max_width and wb <= max_width:
            score = max(wa, wb) + abs(wa - wb) * 0.18
            if best is None or score < best[0]:
                best = (score, [a, b])
    if best:
        return best[1]
    return None


def create_title_card(clip: dict, out_dir: Path, cfg: dict, preview: bool = False) -> Path | None:
    title = str(clip.get('title_text') or '').strip()
    if not title:
        return None

    out_dir.mkdir(parents=True, exist_ok=True)
    render_cfg = cfg.get('render', {})
    title_cfg = cfg.get('title', {})
    W, H = (
        (int(render_cfg.get('preview_width', 540)), int(render_cfg.get('preview_height', 960)))
        if preview else
        (int(render_cfg.get('final_width', 1080)), int(render_cfg.get('final_height', 1920)))
    )

    scale = W / 1080.0
    max_width_ratio = float(title_cfg.get('card_max_width_ratio', 0.84))
    max_card_width = int(W * max_width_ratio)
    pad_x = max(12, int(float(title_cfg.get('card_padding_x', 34)) * scale))
    pad_y = max(8, int(float(title_cfg.get('card_padding_y', 20)) * scale))
    radius = max(10, int(float(title_cfg.get('card_radius', 28)) * scale))
    shadow = max(2, int(float(title_cfg.get('card_shadow_offset', 6)) * scale))
    top_margin = max(18, int(float(title_cfg.get('top_margin_final', 92)) * scale))
    line_spacing = max(4, int(float(title_cfg.get('line_spacing', 9)) * scale))
    preferred_font = title_cfg.get('font_path')

    base_size = int(title_cfg.get('font_size_final', 64) * scale)
    min_size = max(20, int(title_cfg.get('font_size_min_final', 48) * scale))
    max_text_width = max(100, max_card_width - 2 * pad_x)

    canvas = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    lines = None
    font = None
    for size in range(max(base_size, min_size), min_size - 1, -1):
        candidate_font = _load_font(size, preferred_font)
        candidate_lines = _balanced_two_lines(draw, title, candidate_font, max_text_width)
        if candidate_lines:
            lines = candidate_lines
            font = candidate_font
            break
    if lines is None:
        # Never paint an overlong title outside the card. A too-long editorial
        # proposal must be shortened/reviewed before preview or final render.
        raise ValueError("Título excede a caixa segura; revise o texto antes de renderizar")

    boxes = [draw.textbbox((0, 0), line, font=font) for line in lines]
    widths = [b[2] - b[0] for b in boxes]
    heights = [b[3] - b[1] for b in boxes]
    text_w = int(max(widths) if widths else 1)
    text_h = int(sum(heights) + line_spacing * max(0, len(lines) - 1))
    card_w = min(max_card_width, text_w + 2 * pad_x)
    card_h = text_h + 2 * pad_y
    x0 = (W - card_w) // 2
    y0 = top_margin
    x1 = x0 + card_w
    y1 = y0 + card_h
    # Keep every glyph inside the measured card and away from lower UI/captions.
    if y1 > int(H * 0.35) or text_w > max_text_width:
        raise ValueError("Título excede a região segura de abertura")

    # Soft shadow + solid white rounded card. No transparency in the card itself.
    draw.rounded_rectangle(
        (x0 + shadow, y0 + shadow, x1 + shadow, y1 + shadow),
        radius=radius,
        fill=(0, 0, 0, 82),
    )
    draw.rounded_rectangle((x0, y0, x1, y1), radius=radius, fill=(255, 255, 255, 255))

    y = y0 + pad_y
    for line, box in zip(lines, boxes):
        tw = int(box[2] - box[0])
        th = int(box[3] - box[1])
        tx = (W - tw) // 2
        # Compensate font bbox top so visual centering is stable across fonts.
        draw.text((tx, y - box[1]), line, font=font, fill=(12, 12, 12, 255))
        y += th + line_spacing

    path = out_dir / ('title_card_preview.png' if preview else 'title_card.png')
    canvas.save(path, format='PNG', optimize=True)
    return path
