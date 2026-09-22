"""Export a public, allowlisted view of the index. Never publishes source files."""

import calendar
import csv
import hashlib
import io
import json
import math
import re
import statistics
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from crypto_index.calculation import index_level, number, portfolio_value, return_pct
from crypto_index.portfolio_transition import cutoff_date, load_next_portfolio, positions


def close(actual, expected):
    if abs(number(actual) - number(expected)) > number('1e-10'):
        raise ValueError('Los datos del índice no concilian.')


def public_data(root, monthly=None):
    root = Path(root)
    manifest = json.loads((root / 'manifest.json').read_bytes())
    for name, expected in manifest['sha256'].items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != expected:
            raise ValueError('La semilla del índice fue modificada.')
    rows = list(csv.DictReader(io.StringIO(
        (root / manifest['history_file']).read_text(encoding='utf-8-sig'))))
    if len(rows) < 2:
        raise ValueError('Se requieren al menos dos observaciones.')
    portfolio = json.loads((root / manifest['portfolio_file']).read_bytes())
    portfolio_hash = manifest['sha256'][manifest['portfolio_file']]
    last_record = None
    for path in sorted((root / 'observations').glob('*.json')):
        record = json.loads(path.read_bytes())
        day = date.fromisoformat(record['date'])
        if path.stem != record['date'] or day != date.fromisoformat(rows[-1]['date']) + timedelta(days=1):
            raise ValueError('Secuencia diaria incompleta.')
        prior_day = cutoff_date(portfolio)
        first = prior_day + timedelta(days=1)
        end = date(first.year, first.month, calendar.monthrange(first.year, first.month)[1])
        if day > end:
            if last_record is None or last_record['date'] != end.isoformat():
                raise ValueError('Falta el cierre para reconstruir la cartera.')
            portfolio, portfolio_hash = load_next_portfolio(
                root / 'portfolios', portfolio, portfolio_hash, last_record)
        if record['portfolio_sha256'] != portfolio_hash:
            raise ValueError('La valoración corresponde a otra cartera.')
        value = portfolio_value(positions(portfolio), record['prices_usdt'], portfolio['cash_usdt'])
        close(record['value_usdt'], value)
        close(record['daily_return_pct'], return_pct(value, rows[-1]['value_usdt']))
        rows.append(record)
        last_record = record

    series = []
    previous = None
    peak = 0.0
    for row in rows:
        day = date.fromisoformat(row['date'])
        value, level = number(row['value_usdt']), number(row['index_level'])
        if level <= 0 or value <= 0:
            raise ValueError('Nivel no positivo.')
        close(level, index_level(value, portfolio['initial_value_usdt'], portfolio['base_level']))
        close(row['cumulative_return_pct'], return_pct(value, portfolio['initial_value_usdt']))
        if previous:
            if day != date.fromisoformat(previous['date']) + timedelta(days=1):
                raise ValueError('Fechas incompletas o duplicadas.')
            close(row['daily_return_pct'], return_pct(value, previous['value_usdt']))
        numeric = float(level)
        if not math.isfinite(numeric):
            raise ValueError('Nivel fuera de rango.')
        peak = max(peak, numeric)
        series.append({'date': day.isoformat(), 'level': numeric,
                       'drawdown': (numeric / peak - 1) * 100})
        previous = row

    # The published target may change after today's closing valuation.
    target = portfolio
    if last_record and (root / 'portfolios' / f"portfolio_{last_record['date']}.json").exists():
        target, _ = load_next_portfolio(root / 'portfolios', portfolio, portfolio_hash, last_record)
    positions(target)
    composition = []
    for item in target['positions']:
        asset = item['asset']
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,30}', asset):
            raise ValueError('Símbolo no válido para publicación.')
        composition.append({'asset': asset, 'target_weight': 10})
    composition.append({'asset': 'USDT', 'target_weight': (10 - len(target['positions'])) * 10})
    measured = None
    if last_record:
        measured = [{'asset': item['asset'], 'weight': float(
            number(item['quantity']) * number(last_record['prices_usdt'][item['asset']])
            / number(last_record['value_usdt']) * 100)} for item in portfolio['positions']]
        measured.append({'asset': 'USDT', 'weight': float(
            number(portfolio['cash_usdt']) / number(last_record['value_usdt']) * 100)})
    returns = [b['level'] / a['level'] - 1 for a, b in zip(series, series[1:])]
    months = []
    for month in sorted({point['date'][:7] for point in series[1:]}):
        indices = [i for i, p in enumerate(series) if i and p['date'].startswith(month)]
        start, end = indices[0], indices[-1]
        year, mon = map(int, month.split('-'))
        complete = (series[start]['date'] == f'{month}-01' and
                    series[end]['date'] == f'{month}-{calendar.monthrange(year, mon)[1]:02}')
        months.append({'month': month,
                       'return_pct': (series[end]['level'] / series[start-1]['level'] - 1) * 100,
                       'complete': complete})
    # Public status is deliberately generic: no logs, paths or provider responses.
    monthly_status = 'Sin información de ejecución mensual'
    if monthly and Path(monthly).exists():
        statuses = []
        for path in Path(monthly).glob('*.json'):
            record = json.loads(path.read_bytes())
            if record.get('status') in {'action_required', 'selection_ready', 'portfolio_ready'}:
                statuses.append(record)
        if statuses:
            latest = max(statuses, key=lambda r: (r['cutoff'], r['recorded_utc']))
            monthly_status = {'action_required': 'Revisión mensual pendiente',
                              'selection_ready': 'Selección capturada; cierre pendiente',
                              'portfolio_ready': 'Cartera mensual generada'}[latest['status']]
    return {'generated_utc': datetime.now(timezone.utc).isoformat(),
            'series': series, 'last_date': series[-1]['date'], 'start_date': series[0]['date'],
            'metrics': {'level': series[-1]['level'], 'daily': returns[-1] * 100,
                        'total': (series[-1]['level'] / series[0]['level'] - 1) * 100,
                        'max_drawdown': min(p['drawdown'] for p in series),
                        'volatility': statistics.stdev(returns) * math.sqrt(365) * 100
                        if len(returns) > 1 else None},
            'months': months, 'composition': composition, 'measured_weights': measured,
            'target_date': cutoff_date(target).isoformat(), 'monthly_status': monthly_status}


def render(data):
    template = Path(__file__).with_name('dashboard.html').read_text(encoding='utf-8')
    payload = json.dumps(data, ensure_ascii=True, allow_nan=False).replace('<', '\\u003c')
    return template.replace('__PUBLIC_DATA__', payload)
