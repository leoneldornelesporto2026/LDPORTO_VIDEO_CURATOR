from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import math
import re

from .title_card import _load_font


def ass_time(sec):
    sec=max(0,float(sec)); h=int(sec//3600); sec-=h*3600; m=int(sec//60); sec-=m*60
    return f"{h}:{m:02d}:{sec:05.2f}"


def srt_time(sec):
    ms=int(round(max(0,float(sec))*1000)); h=ms//3600000; ms%=3600000; m=ms//60000; ms%=60000; s=ms//1000; ms%=1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def esc_ass(s):
    return str(s).replace('\\','\\\\').replace('{','\\{').replace('}','\\}').replace('\n','\\N')


def _ass_wrapped_text(text):
    return esc_ass(text).replace('\\\\N', '\\N')


def wrap_caption(text, max_chars=28):
    """Legacy helper kept for callers; render safety uses measured pixel widths."""
    words=str(text).strip().split(); lines=[]; cur=[]
    for w in words:
        if cur and len(' '.join(cur+[w]))>max_chars:
            lines.append(' '.join(cur)); cur=[w]
        else:
            cur.append(w)
    if cur:
        lines.append(' '.join(cur))
    if len(lines)>2:
        best=None
        for i in range(1,len(words)):
            a=' '.join(words[:i]); b=' '.join(words[i:])
            score=max(len(a),len(b))+abs(len(a)-len(b))*0.25
            if best is None or score<best[0]: best=(score,a,b)
        lines=[best[1],best[2]] if best else lines[:2]
    return '\\N'.join(lines[:2])


def _normalized_word(word):
    return re.sub(r'[^\w]', '', str(word).casefold(), flags=re.UNICODE)


def _collect_aligned_words(caption, word_index):
    """Use only checked timings; never distribute segment time among guessed words."""
    raw = caption.get('words') or word_index.get(str(caption.get('segment_id') or ''), [])
    literal = str(caption.get('display_text') or caption.get('text') or '').strip()
    tokens = literal.split()
    if not isinstance(raw, list) or len(tokens) != len(raw) or not tokens:
        return []
    aligned = []
    previous_start = -1.0
    for token, item in zip(tokens, raw):
        if not isinstance(item, dict):
            return []
        word = str(item.get('word') or item.get('raw') or '').strip()
        if not word or _normalized_word(token) != _normalized_word(word):
            return []
        try:
            a, b = float(item['start']), float(item['end'])
        except (KeyError, ValueError, TypeError):
            return []
        if not (math.isfinite(a) and math.isfinite(b) and a <= b and a >= previous_start):
            return []
        aligned.append(dict(text=token, start=a, end=b))
        previous_start = a
    return aligned


def _measured_lines(text, font_size, max_width, font_name):
    """Return one/two complete lines only if they fit the actual font measurements."""
    font = _load_font(int(font_size), font_name)
    tokens = text.split()
    def width(value):
        box = font.getbbox(value)
        return box[2] - box[0]
    if width(text) <= max_width:
        return [text], None
    best = None
    for i in range(1, len(tokens)):
        a, b = ' '.join(tokens[:i]), ' '.join(tokens[i:])
        w1, w2 = width(a), width(b)
        if w1 <= max_width and w2 <= max_width:
            score = max(w1, w2) + 0.2*abs(w1-w2)
            if best is None or score < best[0]:
                best = score, [a,b], i
    if best is None:
        return None, None
    return best[1], best[2]


def _fitted_text(tokens, requested_size, min_size, max_width, font_name):
    text = ' '.join(tokens)
    for font_size in range(requested_size, min_size-1, -1):
        lines, split = _measured_lines(text, font_size, max_width, font_name)
        if lines is not None:
            return font_size, lines, split
    return None


def measured_karaoke_body(literal, words, event_start, *, break_offsets=(),
                          initial_color='#FFD700', spoken_color='#FFFFFF', uppercase=False):
    """One stable phrase, with permanent color steps at measured word onsets.

    Both Reels and Stories call this serializer. ``event_start`` is the absolute
    source time represented by the serialized ASS Dialogue start, not its
    unrounded canonical time. Absolute onsets preserve real pauses and avoid the
    drift introduced by adding rounded word durations. Rounding a color step up
    to a millisecond ensures that a word cannot turn white before its onset.
    """
    def color(value):
        value = value.lstrip('#')
        return '&H' + value[4:6] + value[2:4] + value[0:2] + '&'

    yellow, white = color(initial_color), color(spoken_color)
    breaks = set(break_offsets)
    edges = sorted({0, len(literal), *breaks,
                    *[word[key] for word in words for key in ('char_start', 'char_end')]})
    parts = []
    for left, right in zip(edges, edges[1:]):
        if left in breaks:
            parts.append('\\N')
        # A reset before every fragment prevents a preceding word's transform
        # from leaking into future words or literal separator characters.
        parts.append('{\\1c' + yellow + '}')
        word = next((word for word in words if word['char_start'] <= left < word['char_end']), None)
        if word is not None:
            onset = float(word.get('source_start', word.get('start')))
            offset_ms = max(0, math.ceil((onset - event_start)*1000 - 1e-7))
            if offset_ms == 0:
                # libass treats t(0,0,...) as a duration-long transform.
                parts.append('{\\1c' + white + '}')
            else:
                parts.append(f'{{\\t({offset_ms},{offset_ms},\\1c{white})}}')
        text = literal[left:right]
        parts.append(esc_ass(text.upper() if uppercase else text))
    return ''.join(parts)


def _karaoke_chunk(tokens, timings, split, start, end, *, ass_start=None):
    literal = ' '.join(tokens)
    words, cursor = [], 0
    for token, timing in zip(tokens, timings):
        words.append(dict(timing, char_start=cursor, char_end=cursor+len(token)))
        cursor += len(token)+1
    breaks = [words[split]['char_start']] if split is not None else []
    return measured_karaoke_body(literal, words, start if ass_start is None else ass_start,
                                 break_offsets=breaks)


def write_subtitles(bundle, clip, out_dir: Path, cfg, preview=False):
    """Safe legacy Reels subtitles: validated word windows and no off-screen text.

    SRT keeps the literal transcript. On missing word alignment a long caption is
    explicitly blocked instead of faking word timings or rendering off screen.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    st,en = float(clip['source_start']), float(clip['source_end'])
    caps=[c for c in bundle.captions if c.get('end',0)>st and c.get('start',1e9)<en]
    W,H=(540,960) if preview else (1080,1920)
    subcfg=cfg.get('subtitles',{})
    fs=int(subcfg.get('font_size_preview' if preview else 'font_size_final',36 if preview else 72))
    # Safe legibility default: stay under 60px at 1080x1920 for speech subtitles.
    fs=min(fs,30 if preview else 60)
    min_fs=24 if preview else 48
    margin=int((clip.get('subtitle_plan', {}).get('margin_v_final') or subcfg.get('margin_v_final',320))*(0.5 if preview else 1))
    margin=max(0, min(margin, int(H*0.35)))
    outline=max(2,int(subcfg.get('outline_final',6)*(0.5 if preview else 1)))
    shadow=max(1,int(subcfg.get('shadow_final',2)*(0.5 if preview else 1)))
    # Approx 11% left/right inset. Libass applies margins separately too.
    side_margin=max(65 if preview else 130, int(W*.12))
    max_width=W-2*side_margin - 2*(outline+shadow+4)
    family=str(subcfg.get('font','Segoe UI'))
    # Use a family name for libass and let the Windows font resolver choose locally.
    header=f"""[Script Info]\nScriptType: v4.00+\nPlayResX: {W}\nPlayResY: {H}\nScaledBorderAndShadow: yes\nWrapStyle: 2\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Sub,{family},{fs},&H00FFFFFF,&H0000D7FF,&H00101010,&H60000000,-1,0,0,0,100,100,0,0,1,{outline},{shadow},2,{side_margin},{side_margin},{margin},1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"""
    index=defaultdict(list)
    for row in getattr(bundle, 'words', []) or []:
        if isinstance(row,dict) and row.get('segment_id'):
            index[str(row['segment_id'])].append(row)
    lines=[header]; srt=[]; event_count=0
    for c in caps:
        a=max(st,float(c.get('start',st))); b=min(en,float(c.get('end',en)))
        if b<=a:
            continue
        txt=str(c.get('display_text') or c.get('text') or '').strip()
        if not txt:
            continue
        aligned=_collect_aligned_words(c,index)
        if aligned:
            visible=[w for w in aligned if float(w['end']) > st and float(w['start']) < en]
            if not visible:
                continue
            cursor=0
            while cursor < len(visible):
                group=[]; fitted=None
                for token in visible[cursor:cursor+7]:
                    candidate=group+[token]
                    proposed=_fitted_text([r['text'] for r in candidate],fs,min_fs,max_width,None)
                    dur=min(en,float(candidate[-1]['end']))-max(st,float(candidate[0]['start']))
                    if proposed is None or (group and dur>2.6):
                        break
                    group=candidate; fitted=proposed
                if not group or fitted is None:
                    raise ValueError('Legenda precisa revisão: palavra longa demais para área segura.')
                ga=max(st,float(group[0]['start'])); gb=min(en,float(group[-1]['end']))
                if gb<=ga:
                    cursor+=len(group)
                    continue
                used_fs,display,split=fitted
                phrase=' '.join(r['text'] for r in group)
                # Color onsets are relative to the serialized centisecond start.
                h,m,s=ass_time(ga-st).split(':')
                serialized_start=st+int(h)*3600+int(m)*60+float(s)
                body=_karaoke_chunk([r['text'] for r in group],group,split,ga,gb,ass_start=serialized_start)
                # Fonts are measured before writing and a per-event override is safe.
                ass_txt=f'{{\\fs{used_fs}}}'+body
                lines.append(f"Dialogue: 0,{ass_time(ga-st)},{ass_time(gb-st)},Sub,,0,0,0,,{ass_txt}\n")
                event_count+=1
                srt.append(f"{event_count}\n{srt_time(ga-st)} --> {srt_time(gb-st)}\n{phrase}\n\n")
                cursor+=len(group)
        else:
            # No verified word evidence: do NOT fabricate granular timestamps.
            fit=_fitted_text(txt.split(),fs,min_fs,max_width,None)
            if fit is None:
                raise ValueError('Legenda longa sem alinhamento confiável; necessária revisão do áudio/segmentação antes do preview.')
            used_fs,display,_=fit
            body='\\N'.join(esc_ass(row) for row in display)
            lines.append(f"Dialogue: 0,{ass_time(a-st)},{ass_time(b-st)},Sub,,0,0,0,,{{\\fs{used_fs}}}{body}\n")
            event_count+=1
            srt.append(f"{event_count}\n{srt_time(a-st)} --> {srt_time(b-st)}\n{txt}\n\n")
    ass=out_dir/('subtitles_preview.ass' if preview else 'subtitles.ass')
    ass.write_text(''.join(lines),encoding='utf-8-sig')
    srtp=out_dir/'subtitles.srt'; srtp.write_text(''.join(srt),encoding='utf-8')
    return ass
