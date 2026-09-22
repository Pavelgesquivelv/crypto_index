"""Coordinate monthly selection and portfolio publication. Never submits orders."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from crypto_index.cli import due
from crypto_index.portfolio_transition import cutoff_date, load_next_portfolio

PROJECT = Path(__file__).resolve().parents[1]
ZONE = ZoneInfo('America/Mexico_City')


def execute(arguments):
    subprocess.run([sys.executable, *arguments], cwd=PROJECT, check=True)


def run(phase, cutoff=None, now=None, execute_step=None):
    now = now or datetime.now(timezone.utc)
    execute_step = execute_step or execute
    local = now.astimezone(ZONE)
    day = cutoff or local.date().isoformat()
    instant = datetime.strptime(day, '%Y-%m-%d').replace(hour=7, tzinfo=ZONE)
    # A missed capture cannot be reconstructed using today's ranking.
    if phase == 'capture' and (not due(now) or day != local.date().isoformat()):
        raise ValueError('La captura requiere fin de mes entre 07:00 y 07:14 CDMX.')
    cutoff_date({'cutoff_utc': instant.isoformat()})
    if now < instant:
        raise ValueError('El corte todavía no ha ocurrido.')

    daily = PROJECT / 'runs' / 'daily'
    output = PROJECT / 'runs' / 'monthly'
    output.mkdir(parents=True, exist_ok=True)
    lock = output / 'cycle.lock'
    with lock.open('x', encoding='utf-8') as stream:
        stream.write(str(os.getpid()))
    selection = output / 'selections' / day[:7]
    stage = phase
    try:
        if phase == 'capture':
            execute_step(['-m', 'crypto_index.cli', '--scheduled',
                          '--output', str(selection.parent),
                          '--registry', str(PROJECT / 'config' / 'assets.json')])
        report_path = selection / 'report.json'
        if not report_path.exists():
            raise ValueError('Falta la captura mensual. No se sustituirá por datos actuales.')
        report = json.loads(report_path.read_bytes())
        if report.get('status') != 'composition_ready':
            raise ValueError(f"Selección pendiente de revisión: {report.get('status')}")

        destination = daily / 'portfolios' / f'portfolio_{day}.json'
        if phase == 'finalize':
            stage = 'closing_valuation'
            closing_path = daily / 'observations' / f'{day}.json'
            if not closing_path.exists():
                if local.date() != instant.date():
                    raise ValueError('Falta el cierre histórico; requiere recuperación supervisada.')
                if now < instant.replace(minute=1):
                    raise ValueError('La vela del corte todavía no está completa.')
                execute_step(['scripts/update_daily.py'])
            closing = json.loads(closing_path.read_bytes())
            if closing['date'] != day:
                raise ValueError('Fecha de cierre incorrecta.')
            manifest = json.loads((daily / 'manifest.json').read_bytes())
            for name, expected in manifest['sha256'].items():
                if hashlib.sha256((daily / name).read_bytes()).hexdigest() != expected:
                    raise ValueError(f'Semilla modificada: {name}')
            candidates = [daily / manifest['portfolio_file'],
                          *sorted((daily / 'portfolios').glob('portfolio_*.json'))]
            matches = [path for path in candidates if path != destination and
                       hashlib.sha256(path.read_bytes()).hexdigest() == closing['portfolio_sha256']]
            if len(matches) != 1:
                raise ValueError('No se identificó una cartera anterior única.')
            prior = matches[0]
            stage = 'rebalance'
            if not destination.exists():
                execute_step(['scripts/rebalance_daily.py', '--root', str(daily),
                              '--portfolio', str(prior), '--selection', str(selection),
                              '--cutoff', day])
            # Verify existing publications as well; never overwrite on retry.
            load_next_portfolio(destination.parent, json.loads(prior.read_bytes()),
                                closing['portfolio_sha256'], closing)
        status = {'status': 'selection_ready' if phase == 'capture' else 'portfolio_ready',
                  'phase': phase, 'cutoff': day, 'selection': str(selection),
                  'portfolio': str(destination) if phase == 'finalize' else None}
    except Exception as exc:
        # The detailed review list remains in the selection report, if available.
        status = {'status': 'action_required', 'phase': phase, 'stage': stage,
                  'cutoff': day, 'error_type': type(exc).__name__, 'message': str(exc),
                  'selection': str(selection)}
        raise
    finally:
        try:
            if 'status' in locals():
                status['recorded_utc'] = datetime.now(timezone.utc).isoformat()
                name = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
                with (output / f'{day}-{phase}-{name}.json').open('x', encoding='utf-8') as stream:
                    json.dump(status, stream, indent=2)
                print(json.dumps(status, ensure_ascii=False), flush=True)
        finally:
            lock.unlink(missing_ok=True)
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['capture', 'finalize'])
    parser.add_argument('--cutoff', help='Explicit month-end for recovery using saved evidence')
    args = parser.parse_args()
    run(args.phase, args.cutoff)


if __name__ == '__main__':
    main()
