"""Build a theoretical month-end portfolio from a captured selection. No orders."""

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from crypto_index.archive_download import download_bytes
from crypto_index.calculation import index_level, number, portfolio_value, rebalance
from crypto_index.cli import build, timestamp
from crypto_index.portfolio_transition import (
    cutoff_date, load_next_portfolio, positions, reconcile,
)

ZONE = ZoneInfo('America/Mexico_City')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read_selection(directory, cutoff):
    raw = (directory / 'report.json').read_bytes()
    report = json.loads(raw)
    if report['mode'] != 'scheduled' or report['status'] != 'composition_ready':
        raise ValueError('Se requiere una selección programada y lista.')
    generated = timestamp(report['generated_utc'])
    for field in ('generated_utc', 'cmc_received_utc', 'binance_received_utc'):
        captured = timestamp(report[field])
        if not cutoff <= captured < cutoff + timedelta(minutes=15):
            raise ValueError('Selección fuera de la ventana del corte.')
    cmc_time = timestamp(report['cmc_received_utc'])
    binance_time = timestamp(report['binance_received_utc'])
    if not 0 <= (binance_time - cmc_time).total_seconds() <= 120:
        raise ValueError('Capturas de fuentes demasiado separadas.')
    if generated != binance_time:
        raise ValueError('Fecha de generación inconsistente.')
    inputs = {}
    hashes = {'report.json': digest(raw)}
    for name in ('cmc.json', 'binance.json', 'registry.json'):
        source = (directory / name).read_bytes()
        hashes[name] = digest(source)
        if hashes[name] != report['sha256'][name]:
            raise ValueError(f'Fuente modificada: {name}')
        inputs[name] = json.loads(source)
    rebuilt = build(inputs['cmc.json'], inputs['binance.json'],
                    inputs['registry.json'], generated)
    for field in ('status', 'portfolio', 'universe', 'cash_weight_pct'):
        if rebuilt.get(field) != report.get(field):
            raise ValueError(f'Selección no reproducible: {field}')
    return [p for p in rebuilt['portfolio'] if p['asset'] != 'USDT'], hashes


def quote(pair, cutoff, fetch):
    start = int(cutoff.timestamp() * 1000)
    url = 'https://api.binance.com/api/v3/klines?' + urlencode({
        'symbol': pair, 'interval': '1m', 'startTime': start,
        'endTime': start + 59999, 'limit': 1,
    })
    raw = fetch(url)
    candles = json.loads(raw)
    if not isinstance(candles, list) or len(candles) != 1:
        raise ValueError(f'Falta vela única: {pair}')
    candle = candles[0]
    if not isinstance(candle, list) or len(candle) < 9:
        raise ValueError(f'Vela mal formada: {pair}')
    if number(candle[0]) not in (start, start * 1000):
        raise ValueError(f'Corte incorrecto: {pair}')
    price, volume, trades = map(number, (candle[1], candle[5], candle[8]))
    if price <= 0 or volume <= 0 or trades <= 0 or trades != trades.to_integral_value():
        raise ValueError(f'Vela sin precio o transacciones válidas: {pair}')
    return price, {'pair': pair, 'url': url, 'response_text': raw.decode('utf-8'),
                   'sha256': digest(raw),
                   'retrieved_utc': datetime.now(timezone.utc).isoformat()}


def run(root, prior_path, selection, day, now=None, fetch=None):
    now = now or datetime.now(timezone.utc)
    fetch = fetch or download_bytes
    cutoff = datetime.strptime(day, '%Y-%m-%d').replace(hour=7, tzinfo=ZONE)
    cutoff_date({'cutoff_utc': cutoff.isoformat()})
    if now < cutoff + timedelta(minutes=1):
        raise ValueError('La vela del corte todavía no está completa.')
    destination = root / 'portfolios' / f'portfolio_{day}.json'
    if destination.exists():
        raise FileExistsError(f'No se sobrescribirá: {destination}')

    # Share the updater lock to prevent publishing while it replays portfolios.
    lock = root / 'update.lock'
    with lock.open('x', encoding='utf-8') as stream:
        stream.write(str(os.getpid()))
    try:
        prior_raw = prior_path.read_bytes()
        prior = json.loads(prior_raw)
        closing_path = root / 'observations' / f'{day}.json'
        closing_raw = closing_path.read_bytes()
        closing = json.loads(closing_raw)
        if closing['date'] != day or timestamp(closing['cutoff_local']) != cutoff:
            raise ValueError('Observación de cierre incorrecta.')
        if closing['portfolio_sha256'] != digest(prior_raw):
            raise ValueError('El cierre pertenece a otra cartera.')
        selected, selection_hashes = read_selection(selection, cutoff)
        quantities = positions(prior)
        pairs = {p['asset']: p['pair'] for p in prior['positions']}
        for entry in selected:
            asset, pair = entry['asset'], entry['pair']
            if asset in pairs and pairs[asset] != pair:
                raise ValueError(f'Cambio de par pendiente de revisión: {asset}')
            pairs[asset] = pair
        prices, evidence = {}, []
        for asset, pair in pairs.items():
            prices[asset], source = quote(pair, cutoff, fetch)
            evidence.append(source)
            if asset in quantities:
                reconcile(prices[asset], closing['prices_usdt'][asset], asset)
        value = portfolio_value(quantities, prices, prior['cash_usdt'])
        reconcile(value, closing['value_usdt'], 'valor de cierre')
        result = rebalance(value, [p['asset'] for p in selected], prices)
        level = index_level(value, prior['initial_value_usdt'], prior['base_level'])
        reconcile(level, closing['index_level'], 'nivel de cierre')
        report = {
            'status': 'research_provisional', 'cutoff_local': cutoff.isoformat(),
            'cutoff_utc': cutoff.astimezone(timezone.utc).isoformat(),
            'initial_value_usdt': prior['initial_value_usdt'], 'base_level': prior['base_level'],
            'value_before_usdt': str(value), 'value_after_usdt': str(result['value_after']),
            'index_level': str(level), 'cash_usdt': str(result['cash']),
            'fees_included': False, 'price_reference': 'Binance Spot 1-minute candle open',
            'selection_method': 'Rebuilt from captured CMC, Binance and reviewed registry',
            'assumptions': ['Selection captured during 07:00-07:14 CDMX, not exactly at 07:00.',
                            'Theoretical fractional portfolio; no fees or slippage; no orders.'],
            'sources': {'prior': {'path': str(prior_path), 'sha256': digest(prior_raw)},
                        'closing': {'path': str(closing_path), 'sha256': digest(closing_raw)},
                        'selection': {'path': str(selection), 'sha256': selection_hashes}},
            'price_evidence': evidence,
            'positions': [{'asset': p['asset'], 'cmc_id': p['cmc_id'], 'pair': p['pair'],
                           'quantity': str(result['quantities'][p['asset']]),
                           'rebalance_price_usdt': str(prices[p['asset']]),
                           'target_weight_pct': 10} for p in selected],
        }
        destination.parent.mkdir(exist_ok=True)
        # Validate before publication; hard link provides atomic no-overwrite publication.
        with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
            staged = Path(temporary) / destination.name
            staged.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
            load_next_portfolio(Path(temporary), prior, digest(prior_raw), closing)
            os.link(staged, destination)
        return destination
    finally:
        lock.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('runs/daily'))
    parser.add_argument('--portfolio', type=Path, required=True)
    parser.add_argument('--selection', type=Path, required=True,
                        help='Directory containing a scheduled report and its raw sources')
    parser.add_argument('--cutoff', required=True, help='Month-end YYYY-MM-DD')
    args = parser.parse_args()
    path = run(args.root, args.portfolio, args.selection, args.cutoff)
    print('PASS: selección reproducida, precios conciliados y transición validada.')
    print('Guardado:', path)


if __name__ == '__main__':
    main()
