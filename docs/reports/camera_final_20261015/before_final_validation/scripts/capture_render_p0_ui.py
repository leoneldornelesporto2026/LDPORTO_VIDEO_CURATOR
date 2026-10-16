"""Exercise real Tk App workers on an isolated synthetic P0 project copy.

Approval is an automated fixture action. Screenshots contain only the App window.
No render, Pipeline, storage or Tk widget is mocked.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml
from PIL import ImageGrab
from ldporto_curator.gui import App
from scripts.validate_render_p0 import EVIDENCE, artifact, file_hash, original_hashes, read_json, save_json


def hashes(directory):
    return {str(path.relative_to(directory)): file_hash(path)
            for path in directory.rglob('*') if path.is_file()}


def capture(app, destination):
    app.lift()
    app.attributes('-topmost', True)
    app.update_idletasks()
    app.update()
    time.sleep(.1)
    app.update()
    x, y = app.winfo_rootx(), app.winfo_rooty()
    bounds = (x, y, x + app.winfo_width(), y + app.winfo_height())
    ImageGrab.grab(bbox=bounds).save(destination)
    app.attributes('-topmost', False)
    return {'path': str(destination), 'sha256': file_hash(destination),
            'app_window_only': True, 'bounds': bounds}


def perform(app, button_index, expected_state, plan_path):
    started = time.monotonic()
    app.action_buttons[button_index].invoke()
    if not app.busy:
        raise AssertionError('Botão da GUI não iniciou o worker real')
    # A watchdog can also close an unexpected native error dialog: it runs in the
    # real Tcl event loop, including its modal sub-loop. Each step is bounded.
    watchdog = app.after(45000, app.destroy)
    try:
        while app.busy:
            if time.monotonic() - started > 44:
                raise TimeoutError('Worker da GUI excedeu 44 segundos')
            app.update()
            time.sleep(.025)
        app.update()
        current = read_json(plan_path)
        if current['approval_state'] != expected_state:
            raise AssertionError(f'Estado esperado {expected_state}; encontrado {current["approval_state"]}; '
                                 + app.log.get('1.0', 'end'))
        if expected_state not in app.plan_state.get():
            raise AssertionError('A GUI não exibiu o estado persistido concluído')
        if any(str(button.cget('state')) != 'normal' for button in app.action_buttons):
            raise AssertionError('Os botões não foram liberados após concluir o worker')
        return current, time.monotonic() - started
    finally:
        try:
            app.after_cancel(watchdog)
        except Exception:
            pass


def instantiate(directory):
    app = App(directory)
    height = min(920, app.winfo_screenheight() - 70)
    width = min(1220, app.winfo_screenwidth() - 60)
    app.geometry(f'{width}x{height}+20+20')
    app.update()
    return app


def close_app(app):
    # The acceptance driver deliberately creates two Tk roots in one Python
    # process. Cancel this root's scheduled callbacks before starting the next.
    try:
        pending = app.tk.call('after', 'info')
        if isinstance(pending, str):
            pending = app.tk.splitlist(pending)
        for callback in pending:
            app.after_cancel(callback)
    finally:
        app.destroy()


def displayed_fingerprint(app):
    return app.plan_state.get().split(' | plano: ', 1)[1].split(' | ', 1)[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', type=Path, default=EVIDENCE / 'acceptance_20261014T040322246282Z/synthetic')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    directory = args.output or EVIDENCE / ('gui_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    directory.mkdir(parents=True, exist_ok=False)
    fixture = args.fixture.resolve()
    initial = read_json(fixture / 'output/curation/P0_SYNTHETIC_FROZEN/EDIT_DECISIONS.json')
    if initial['approval_state'] != 'PLAN_READY' or len(initial['approved_clips']) != 3:
        raise ValueError('Escolha a fixture concluída com nova revisão de três cortes pendente')
    before_originals = original_hashes()
    before_fixture = hashes(fixture)
    shutil.copytree(fixture / 'output', directory / 'output')
    cfg = deepcopy(initial['render_config'])
    cfg['paths'].update(output_root=str(directory / 'output'), analysis_root=str(directory / 'NO_ANALYZER'),
                        source_cache=str(directory / 'EMPTY_SOURCE_CACHE'))
    cfg['source_media'] = {'path': str(fixture / 'SYNTHETIC_ORIGINAL.mp4'), 'allow_download': False}
    (directory / 'config.yaml').write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding='utf-8')
    save_json(directory / '.cache/gui_session_v52.json',
              {'source_input': initial['source_input'], 'rank': 1, 'output_root': str(directory / 'output')})
    plan_path = directory / 'output/curation/P0_SYNTHETIC_FROZEN/EDIT_DECISIONS.json'
    report = {'fixture_only': True, 'automated_fixture_approval': True,
              'human_quality_approval_claimed': False, 'tk_widgets_mocked': False,
              'render_mocked': False, 'pipeline_mocked': False,
              'original_report_fixture': str(fixture), 'new_isolated_gui_project': str(directory)}
    app = None
    logs = []
    try:
        with ExitStack() as stack:
            opened = stack.enter_context(patch('ldporto_curator.gui.os.startfile'))
            forbidden = {name: stack.enter_context(patch(name, side_effect=AssertionError('Inferência/Analyzer proibido na homologação downstream')))
                         for name in ('ldporto_curator.pipeline.find_analysis', 'ldporto_curator.pipeline.load_bundle',
                                      'ldporto_curator.pipeline.curate', 'ldporto_curator.curator.review_candidates',
                                      'ldporto_curator.ollama_client.review_candidates')}
            app = instantiate(directory)
            if 'PLAN_READY' not in app.plan_state.get():
                raise AssertionError('Reabertura não carregou o plano persistido na interface')
            initial_displayed_fingerprint = displayed_fingerprint(app)
            tested, test_seconds = perform(app, 1, 'PREVIEW_READY', plan_path)
            approved, approval_seconds = perform(app, 2, 'TEST_APPROVED', plan_path)
            approved_displayed_fingerprint = displayed_fingerprint(app)
            report['approved_screenshot'] = capture(app, directory / 'APPROVED.png')
            logs.append(app.log.get('1.0', 'end'))
            close_app(app)
            app = instantiate(directory)
            if 'TEST_APPROVED' not in app.plan_state.get():
                raise AssertionError('Reabrir a GUI perdeu a aprovação da revisão')
            reopened_displayed_fingerprint = displayed_fingerprint(app)
            report['reopened_approved_state'] = app.plan_state.get()
            completed, batch_seconds = perform(app, 3, 'BATCH_COMPLETED', plan_path)
            completed_displayed_fingerprint = displayed_fingerprint(app)
            if len({initial_displayed_fingerprint, approved_displayed_fingerprint,
                    reopened_displayed_fingerprint, completed_displayed_fingerprint}) != 1:
                raise AssertionError('A GUI exibiu identidades de plano diferentes após concluir ou reabrir')
            report['completed_screenshot'] = capture(app, directory / 'BATCH_COMPLETED.png')
            logs.append(app.log.get('1.0', 'end'))
            for doc in (tested, approved, completed):
                if doc['plan_revision'] != initial['plan_revision'] or doc['approved_clips'] != initial['approved_clips']:
                    raise AssertionError('Botões ou reabertura mudaram seleção/revisão da fixture')
            if len(completed['results']) != 3:
                raise AssertionError('Worker da GUI não concluiu os três finais reais')
            report.update(status='passed', project_id=initial['project_id'], plan_revision=initial['plan_revision'],
                          states=['PLAN_READY', 'PREVIEW_READY', 'TEST_APPROVED', 'TEST_APPROVED', 'BATCH_COMPLETED'],
                          revision_and_clips_preserved=True,
                          displayed_plan_fingerprint_unchanged=True,
                          displayed_plan_fingerprint=completed_displayed_fingerprint,
                          elapsed_seconds={'test': test_seconds, 'approve': approval_seconds, 'batch': batch_seconds},
                          forbidden_calls={name: mocked.call_count for name, mocked in forbidden.items()},
                          external_player_suppressed_calls=opened.call_count,
                          preview=artifact(tested['preview']['path']),
                          finals=[artifact(row['path'] if isinstance(row, dict) else row) for row in completed['results']],
                          final_gui_state=app.plan_state.get())
            if any(report['forbidden_calls'].values()):
                raise AssertionError('A GUI chamou inferência ou Analyzer nas etapas downstream')
    except Exception as error:
        report['status'] = 'failed'
        report['failure'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        if app is not None:
            try:
                close_app(app)
            except Exception:
                pass
        (directory / 'GUI_WORKERS_LOG.txt').write_text('\n\n'.join(logs), encoding='utf-8')
        report['original_files_unchanged'] = original_hashes() == before_originals
        report['historical_fixture_unchanged'] = hashes(fixture) == before_fixture
        save_json(directory / 'GUI_ACCEPTANCE.json', report)
        print(json.dumps({'status': report.get('status'), 'report': str(directory / 'GUI_ACCEPTANCE.json'),
                          'originals_unchanged': report['original_files_unchanged'],
                          'fixture_unchanged': report['historical_fixture_unchanged']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
