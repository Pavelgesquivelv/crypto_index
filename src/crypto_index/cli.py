"""Public-data snapshot generator. Never submits orders."""
import argparse
import calendar
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

CMC = 'https://pro-api.coinmarketcap.com/public-api/v3/cryptocurrency/listings/latest?start=1&limit=500&convert=USD&sort=market_cap&sort_dir=desc'
BINANCE = 'https://api.binance.com/api/v3/exchangeInfo'
EXCLUDED = {'stablecoin', 'memes', 'wrapped-tokens', 'wrapped',
            'liquid-staking-tokens',
            'asset-backed-tokens', 'tokenized-gold', 'tokenized-stock'}


def utcnow():
    return datetime.now(timezone.utc)


def timestamp(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Timestamp must include timezone')
    return result


def due(now):
    local = now.astimezone(ZoneInfo('America/Mexico_City'))
    return (local.day == calendar.monthrange(local.year, local.month)[1]
            and local.hour == 7 and local.minute < 15)


def fetch(url):
    headers = {'Accept': 'application/json', 'User-Agent': 'crypto-index-rebalancer/0.1'}
    if url == CMC and os.environ.get('CMC_API_KEY'):
        url = url.replace('/public-api', '')
        headers['X-CMC_PRO_API_KEY'] = os.environ['CMC_API_KEY']
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers=headers), timeout=30) as response:
                return response.read()
        except HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise RuntimeError(f'Data provider HTTP error {exc.code}') from None
        except (URLError, TimeoutError):
            if attempt == 2:
                raise RuntimeError('Data provider connection failed') from None
        time.sleep(2 ** attempt)


def build(cmc, exchange, registry, now):
    if str(cmc.get('status', {}).get('error_code', 0)) != '0':
        raise ValueError('CMC returned an API error')
    coins = cmc['data']
    if not isinstance(coins, list) or not isinstance(exchange['symbols'], list):
        raise ValueError('Unexpected provider schema')
    coins = sorted(coins, key=lambda c: c['cmc_rank'])
    ranks = [c['cmc_rank'] for c in coins]
    if ranks != list(range(1, len(coins) + 1)):
        raise ValueError('Ranking has gaps or duplicates')
    if len({c['id'] for c in coins}) != len(coins):
        raise ValueError('Duplicate CMC identity')
    universe, excluded, review = [], [], []
    for c in coins:
        age = (now - timestamp(c['last_updated'])).total_seconds()
        if not -120 <= age <= 1800:
            raise ValueError(f'Stale or future CMC data for ID {c["id"]}')
        tags = c.get('tags')
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            raise ValueError('Missing or malformed classification tags')
        entry = registry.get(str(c['id']))
        reasons = sorted(EXCLUDED.intersection(tags))
        if entry and entry['classification'] == 'excluded':
            reasons.append('reviewed-exclusion')
        if reasons:
            excluded.append({'cmc_id': c['id'], 'symbol': c['symbol'], 'reasons': reasons})
            continue
        if not entry or entry['classification'] != 'eligible' or entry['symbol'] != c['symbol']:
            review.append({'cmc_id': c['id'], 'symbol': c['symbol'], 'rank': c['cmc_rank']})
            break  # Unknown eligibility could change the entire top 15.
        quotes = c['quote']
        quote = next(q for q in quotes if q['symbol'] == 'USD') if isinstance(quotes, list) else quotes['USD']
        cap = quote['market_cap']
        if not isinstance(cap, (int, float)) or not math.isfinite(cap) or cap <= 0:
            raise ValueError('Invalid circulating market capitalization')
        pairs = [s for s in exchange['symbols'] if s['baseAsset'] == entry['binance_base']]
        active = [s for s in pairs if s['status'] == 'TRADING' and s.get('isSpotTradingAllowed') is True]
        direct = next((s for s in active if s['quoteAsset'] == 'USDT'), None)
        universe.append({'cmc_id': c['id'], 'symbol': c['symbol'], 'cmc_rank': c['cmc_rank'],
                         'eligible_rank': len(universe) + 1, 'market_cap_usd': cap,
                         'source_updated_utc': c['last_updated'],
                         'spot_available': bool(active), 'pair': direct['symbol'] if direct else None,
                         'status': 'available' if direct else 'route_review' if active else 'unavailable',
                         'filters': direct.get('filters', []) if direct else [],
                         'permission_sets': direct.get('permissionSets', []) if direct else []})
        if len(universe) == 15:
            break
    if review:
        return {'status': 'review_required', 'review': review, 'universe': universe,
                'excluded': excluded, 'portfolio': []}
    if len(universe) != 15:
        raise ValueError('Insufficient data to establish 15 eligible assets')
    available = [c for c in universe if c['spot_available']][:10]
    if any(c['status'] == 'route_review' for c in available):
        return {'status': 'route_review_required', 'universe': universe,
                'excluded': excluded, 'portfolio': []}
    portfolio = [{'asset': c['symbol'], 'cmc_id': c['cmc_id'], 'pair': c['pair'], 'weight_pct': 10}
                 for c in available]
    if len({c['pair'] for c in portfolio}) != len(portfolio):
        raise ValueError('Duplicate mapped Binance identity')
    cash = (10 - len(portfolio)) * 10
    if cash:
        portfolio.append({'asset': 'USDT', 'cmc_id': None, 'pair': None, 'weight_pct': cash})
    assert sum(c['weight_pct'] for c in portfolio) == 100
    return {'status': 'composition_ready', 'universe': universe, 'excluded': excluded,
            'portfolio': portfolio, 'cash_weight_pct': cash,
            'execution_ready': False,
            'limitations': ['Account permissions not checked', 'No capital, liquidity or order-size validation',
                            'No orders submitted; no historical performance claim']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--registry', type=Path, default=Path('config/assets.json'))
    parser.add_argument('--output', type=Path, default=Path('runs'))
    parser.add_argument('--scheduled', action='store_true', help='Only run on month-end, 07:00-07:14 CDMX')
    args = parser.parse_args()
    now = utcnow()
    if args.scheduled and not due(now):
        print('Outside month-end rebalance window; no data fetched.')
        return 0
    run_id = now.astimezone(ZoneInfo('America/Mexico_City')).strftime('%Y-%m') if args.scheduled else now.strftime('%Y%m%dT%H%M%S%fZ')
    target = args.output / run_id
    args.output.mkdir(parents=True, exist_ok=True)
    lock = args.output / (run_id + '.lock')
    try:
        with lock.open('x') as stream:
            stream.write(str(os.getpid()))
    except FileExistsError:
        print('Run is locked; inspect existing process before recovering lock.', file=sys.stderr)
        return 2
    try:
        if (target / 'report.json').exists():
            print('Completed run exists; preserving original snapshot.')
            previous = json.loads((target / 'report.json').read_text(encoding='utf-8'))
            return 0 if previous['status'] == 'composition_ready' else 2
        target.mkdir(exist_ok=True)
        raw_registry = args.registry.read_bytes()
        raw_cmc = fetch(CMC)
        cmc_received = utcnow()
        raw_binance = fetch(BINANCE)
        fetched = utcnow()
        if args.scheduled and not due(fetched):
            raise ValueError('Data retrieval exceeded rebalance window')
        if (fetched - cmc_received).total_seconds() > 120:
            raise ValueError('Source captures are too far apart')
        for name, data in [('cmc.json', raw_cmc), ('binance.json', raw_binance), ('registry.json', raw_registry)]:
            (target / name).write_bytes(data)
        report = build(json.loads(raw_cmc), json.loads(raw_binance), json.loads(raw_registry), fetched)
        report.update(version='0.1.0', generated_utc=fetched.isoformat(), mode='scheduled' if args.scheduled else 'preview',
                      cmc_received_utc=cmc_received.isoformat(), binance_received_utc=fetched.isoformat(),
                      sources={'cmc': CMC, 'binance': BINANCE},
                      sha256={name: hashlib.sha256(data).hexdigest() for name, data in
                              [('cmc.json', raw_cmc), ('binance.json', raw_binance), ('registry.json', raw_registry)]})
        if report['portfolio']:
            with (target / 'portfolio.csv').open('w', newline='', encoding='utf-8') as stream:
                writer = csv.DictWriter(stream, fieldnames=['asset', 'cmc_id', 'pair', 'weight_pct'])
                writer.writeheader()
                writer.writerows(report['portfolio'])
        temporary = target / 'report.tmp'
        temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        temporary.replace(target / 'report.json')
        print(f'{report["status"]}: {target / "report.json"}')
        return 0 if report['status'] == 'composition_ready' else 2
    except (ValueError, KeyError, StopIteration, TypeError, RuntimeError, OSError) as exc:
        print(f'Run failed: {exc}', file=sys.stderr)
        return 1
    finally:
        lock.unlink(missing_ok=True)


if __name__ == '__main__':
    sys.exit(main())
