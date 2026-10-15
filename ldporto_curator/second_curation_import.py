"""Direct, bounded and checksum-verified import; existing outputs stay untouched."""
import hashlib
import json
import re
import stat
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from .utils import load_json, write_json
from .second_curation_decisions import compile_decisions


def read_package(path):
    path = Path(path)
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        names = [m.filename for m in members]
        if len(names) != len(set(n.casefold() for n in names)) or len(names) > 5000 or sum(m.file_size for m in members) > 256 * 1024 ** 2:
            raise ValueError('Pacote duplicado ou acima do limite de tamanho')
        for member in members:
            name = member.filename
            if PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts or '\\' in name or ':' in name:
                raise ValueError('Caminho inválido no pacote')
            if stat.S_ISLNK(member.external_attr >> 16) or (Path(name).suffix.lower() not in {'.json', '.jsonl', '.jpg', '.jpeg', '.png', '.webp', '.txt', '.md', '.srt'} and name != 'NARRATIVE_REVIEW.html') or (name == 'NARRATIVE_REVIEW.html' and member.file_size > 3 * 1024 ** 2):
                raise ValueError('Tipo de arquivo inválido no pacote')
        files = {name: archive.read(name) for name in names}
    manifest = json.loads(files['SECOND_CURATION_MANIFEST.json'])
    listed = {r['path']: r for r in manifest['files']}
    if set(listed) != set(files) - {'SECOND_CURATION_MANIFEST.json'} or len(listed) != len(manifest['files']):
        raise ValueError('Manifest não corresponde aos arquivos')
    for name, row in listed.items():
        if len(files[name]) != row['bytes'] or hashlib.sha256(files[name]).hexdigest() != row['sha256']:
            raise ValueError('Checksum inválido: ' + name)
    metadata = json.loads(files['source/metadata.json'])
    if manifest.get('source_hash') != metadata.get('sha256'):
        raise ValueError('Origem inconsistente')
    catalog = json.loads(files['editorial/candidate_catalog.json'])
    ids = [r['candidate_id'] for r in catalog['candidates']]
    if len(ids) != len(set(ids)) or any(not re.fullmatch(r'[A-Za-z0-9_-]{1,160}', cid) for cid in ids):
        raise ValueError('Candidate IDs inválidos')
    for row in catalog['candidates']:
        if not 0 <= row['start'] < row['end'] <= metadata['duration']:
            raise ValueError('Intervalo fora da fonte')
        if any(ref not in files for ref in row.get('visual_refs', []) + row.get('file_refs', [])):
            raise ValueError('Referência de arquivo não resolvida')
    segments = [json.loads(line) for line in files['transcript/relevant_segments.jsonl'].decode('utf-8-sig').splitlines() if line]
    refs = {r['segment_id'] for r in segments}
    if any(not set(r.get('segment_ids', [])) <= refs for r in catalog['candidates']):
        raise ValueError('Referência de segmento não resolvida')
    return {'files': files, 'manifest': manifest, 'metadata': metadata, 'catalog': catalog,
            'segments': segments, 'package_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def registered_input(project_root, source_input):
    entries = load_json(Path(project_root) / '.cache/second_curation_registry.json', {}) or {}
    for row in entries.values():
        if source_input in {row.get('video_id'), row.get('source_url'), row.get('source_sha256')}:
            return row
    return None


def import_second_curation(path, project_root, analysis_root=None):
    path, project_root = Path(path), Path(project_root)
    registry_path = project_root / '.cache/second_curation_registry.json'
    registry = load_json(registry_path, {}) or {}
    if path.suffix.lower() == '.zip':
        package = read_package(path)
        folder = project_root / '.cache/imported_second_curation' / package['package_sha256']
        folder.mkdir(parents=True, exist_ok=True)
        for name, payload in package['files'].items():
            target = (folder / name).resolve()
            if not target.is_relative_to(folder.resolve()) or target.is_symlink():
                raise ValueError('Destino inválido')
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                target.write_bytes(payload)
        metadata = package['metadata']
        source = metadata.get('source') or {}
        analysis = {'metadata': metadata, 'transcript_segments': package['segments'], 'second_curation_import': True}
        write_json(folder / 'analysis.json', analysis)
        write_json(folder / 'second_curation_decision_ref.json', {'path': None})
        if 'transcript/relevant_words.jsonl' in package['files']:
            write_json(folder / 'words.json', [json.loads(line) for line in package['files']['transcript/relevant_words.jsonl'].decode('utf-8-sig').splitlines() if line])
        report = {'analysis_dir': str(folder), 'source_sha256': metadata['sha256'], 'video_id': source.get('id') or metadata['sha256'][:12],
                  'source_url': source.get('url'), 'curation_source': 'FIRST_PASS', 'package_sha256': package['package_sha256']}
        registry[metadata['sha256']] = report
    else:
        document = load_json(path, {}) or {}
        if not document:
            raise ValueError('Arquivo de decisões vazio ou JSON inválido')
        if document.get('schema_version') != '4.4.0':
            # Legacy overrides are copied into their own import file, never into the user's original.
            if not isinstance(document, dict) or not all(isinstance(v, list) for v in document.values()):
                raise ValueError('Schema de decisão ou override desconhecido')
            destination = project_root / '.cache/imported_overrides' / (uuid.uuid4().hex + '.json')
            write_json(destination, document)
            report = {'curation_source': 'MANUAL_OVERRIDE', 'override_path': str(destination), 'video_ids': list(document)}
            write_json(project_root / '.cache/active_override_import.json', report)
            return report
        source_hash = document['source_sha256']
        report = registry.get(source_hash)
        if report is None and analysis_root:
            for candidate in Path(analysis_root).glob('*/analysis.json'):
                analysis = load_json(candidate, {}) or {}
                metadata = analysis.get('metadata') or {}
                if metadata.get('sha256') == source_hash:
                    source = metadata.get('source') or {}
                    report = {'analysis_dir': str(candidate.parent), 'source_sha256': source_hash,
                              'video_id': source.get('id') or source_hash[:12], 'source_url': source.get('url')}
                    break
        if report is None:
            raise ValueError('Importe primeiro o pacote ou selecione a pasta analysis correspondente')
        folder = Path(report['analysis_dir'])
        analysis = load_json(folder / 'analysis.json', {}) or {}
        catalog = load_json(folder / 'editorial/candidate_catalog.json', {}) or load_json(folder / 'second_curation_package.json', {})
        segments = analysis.get('transcript_segments') or load_json(folder / 'transcript_segments.json', [])
        if document.get('input_package_sha256') and document['input_package_sha256'] != report.get('package_sha256'):
            raise ValueError('Decisão pertence a outro pacote')
        compiled = compile_decisions(document, catalog, analysis['metadata'], segments)
        from .feedback import record_feedback
        feedback_path = record_feedback(document, catalog, compiled, project_root)
        destination = project_root / '.cache/second_curation_decisions' / (uuid.uuid4().hex + '.json')
        write_json(destination, document)
        if folder.resolve().is_relative_to((project_root / '.cache/imported_second_curation').resolve()):
            write_json(folder / 'second_curation_decision_ref.json', {'path': str(destination)})
        report = {**report, 'decision_path': str(destination), 'curation_source': 'SECOND_CURATOR' if document['provider'] == 'manual_json' else 'AI_SECOND_CURATOR',
                  'approved_count': len(compiled), 'feedback_path':str(feedback_path)}
        registry[source_hash] = report
    write_json(registry_path, registry)
    return report
