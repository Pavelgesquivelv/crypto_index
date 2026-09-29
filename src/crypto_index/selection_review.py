"""Offline, additive identity review preserving original market captures."""
import hashlib
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from crypto_index.cli import build, timestamp


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def verified_original(directory):
    raw_report = (directory / 'report.json').read_bytes()
    report = json.loads(raw_report)
    sources = {name: (directory / name).read_bytes()
               for name in ('cmc.json', 'binance.json', 'registry.json')}
    for name, raw in sources.items():
        if digest(raw) != report['sha256'][name]:
            raise ValueError(f'Fuente original modificada: {name}')
    return raw_report, report, sources


def resolve_selection(directory):
    directory = Path(directory)
    reviewed = directory / 'reviewed'
    if not reviewed.exists():
        return directory
    raw_report, original, sources = verified_original(directory)
    report = json.loads((reviewed / 'report.json').read_bytes())
    audit = report['identity_review']
    if audit['original_report_sha256'] != digest(raw_report):
        raise ValueError('La revisión pertenece a otro informe original.')
    for name in ('cmc.json', 'binance.json'):
        raw = (reviewed / name).read_bytes()
        if raw != sources[name] or digest(raw) != report['sha256'][name]:
            raise ValueError('La revisión alteró los datos de mercado originales.')
    for field in ('generated_utc', 'cmc_received_utc', 'binance_received_utc', 'mode',
                  'selection_policy', 'selection_date', 'rebalance_date'):
        if report.get(field) != original.get(field):
            raise ValueError(f'La revisión alteró el corte: {field}')
    raw_registry = (reviewed / 'registry.json').read_bytes()
    if digest(raw_registry) != report['sha256']['registry.json']:
        raise ValueError('Registro revisado modificado.')
    before, after = json.loads(sources['registry.json']), json.loads(raw_registry)
    additions = audit['added_ids']
    if not additions or set(after) - set(before) != set(additions):
        raise ValueError('Adiciones al registro inconsistentes.')
    if any(after.get(key) != value for key, value in before.items()):
        raise ValueError('La revisión modificó una identidad ya registrada.')
    rebuilt = build(json.loads(sources['cmc.json']), json.loads(sources['binance.json']),
                    after, timestamp(original['generated_utc']))
    if rebuilt['status'] != 'composition_ready':
        raise ValueError('La revisión todavía requiere atención.')
    for key, value in rebuilt.items():
        if report.get(key) != value:
            raise ValueError('Informe revisado no reproducible.')
    return reviewed


def review(directory, registry_path, added_ids):
    directory = Path(directory)
    raw_report, original, sources = verified_original(directory)
    if original['status'] != 'review_required':
        raise ValueError('Solo se revisan capturas pendientes de identidad.')
    destination = directory / 'reviewed'
    if destination.exists():
        raise FileExistsError('La revisión ya existe; no se sobrescribirá.')
    registry = json.loads(sources['registry.json'])
    approved = json.loads(Path(registry_path).read_bytes())
    additions = [str(value) for value in added_ids]
    if not additions or len(set(additions)) != len(additions):
        raise ValueError('Se requieren identificadores únicos.')
    coins = {str(c['id']): c for c in json.loads(sources['cmc.json'])['data']}
    for key in additions:
        if key in registry or key not in coins or key not in approved:
            raise ValueError('La adición debe ser una identidad nueva presente en la captura.')
        entry = approved[key]
        if entry['classification'] != 'eligible' or entry['symbol'] != coins[key]['symbol']:
            raise ValueError('Identidad aprobada incompatible con la captura.')
        registry[key] = entry
    rebuilt = build(json.loads(sources['cmc.json']), json.loads(sources['binance.json']),
                    registry, timestamp(original['generated_utc']))
    if rebuilt['status'] != 'composition_ready':
        raise ValueError('Persisten pendientes; no se publicó ninguna revisión.')
    report = {**original, **rebuilt}
    registry_raw = (json.dumps(registry, indent=2) + '\n').encode()
    report['sha256'] = {**original['sha256'], 'registry.json': digest(registry_raw)}
    report['identity_review'] = {'added_ids': additions,
                                 'original_report_sha256': digest(raw_report),
                                 'reviewed_utc': datetime.now(timezone.utc).isoformat()}
    # Publish the complete directory in one rename. Original files stay unchanged.
    with tempfile.TemporaryDirectory(dir=directory, prefix='.review-') as temporary:
        staged = Path(temporary) / 'reviewed'
        staged.mkdir()
        for name in ('cmc.json', 'binance.json'):
            (staged / name).write_bytes(sources[name])
        (staged / 'registry.json').write_bytes(registry_raw)
        (staged / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        staged.rename(destination)
    return resolve_selection(directory)
