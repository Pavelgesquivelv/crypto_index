"""Send a fixed index service failure alert to Pushover; never forwards logs."""
import argparse
import json
import os
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from crypto_index.portfolio_transition import load_next_portfolio

SERVICES = {
    'crypto-index-daily.service': 'La valoración diaria no terminó correctamente.',
    'crypto-index-capture.service': 'La selección mensual falló o requiere revisión.',
    'crypto-index-monthly.service': 'No se pudo completar la cartera mensual.',
    'crypto-index-dashboard.service': 'No se pudo actualizar el dashboard público.',
    'crypto-index-monthly-success.service': 'Falló la confirmación del rebalanceo; revisa su envío. Esto no implica que la cartera haya fallado.',
}


def send(service, environment=None, opener=None):
    if service not in SERVICES:
        raise ValueError('Servicio no reconocido.')
    send_message('Crypto Index · Revisión requerida',
                 SERVICES[service] + ' Revisa el servicio en el servidor.', environment, opener)


def send_message(title, message, environment=None, opener=None):
    environment = os.environ if environment is None else environment
    opener = urlopen if opener is None else opener
    token, user = environment.get('PUSHOVER_TOKEN'), environment.get('PUSHOVER_USER')
    if not token or not user:
        raise ValueError('Faltan las credenciales de Pushover.')
    body = urlencode({'token': token, 'user': user, 'title': title,
                      'message': message,
                      'priority': 0}).encode()
    request = Request('https://api.pushover.net/1/messages.json', data=body, method='POST')
    try:
        with opener(request, timeout=20) as response:
            result = json.load(response)
        if result.get('status') != 1:
            raise ValueError('Pushover no confirmó la notificación.')
    except Exception:
        # Provider errors can contain secrets; do not relay bodies or chained exceptions.
        raise RuntimeError('No se pudo confirmar el envío a Pushover.') from None


def send_monthly(root, monthly, day, environment=None, opener=None):
    """Confirm a validated publication once; ambiguous sends require manual review."""
    root, monthly = Path(root), Path(monthly)
    day = datetime.strptime(day, '%Y-%m-%d').date().isoformat()
    destination = root / 'portfolios' / f'portfolio_{day}.json'
    successes = [json.loads(p.read_bytes()) for p in monthly.glob(f'{day}-finalize-*.json')]
    if not any(r.get('status') == 'portfolio_ready' and r.get('cutoff') == day
               for r in successes):
        raise ValueError('No existe un cierre mensual confirmado.')
    raw = destination.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    closing = json.loads((root / 'observations' / f'{day}.json').read_bytes())
    manifest = json.loads((root / 'manifest.json').read_bytes())
    for name, expected in manifest['sha256'].items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != expected:
            raise ValueError('Semilla modificada.')
    candidates = [root / manifest['portfolio_file'],
                  *sorted((root / 'portfolios').glob('portfolio_*.json'))]
    matches = [p for p in candidates if p != destination and
               hashlib.sha256(p.read_bytes()).hexdigest() == closing['portfolio_sha256']]
    if len(matches) != 1:
        raise ValueError('No se identificó la cartera anterior.')
    prior = json.loads(matches[0].read_bytes())
    successor, verified_hash = load_next_portfolio(destination.parent, prior,
                                                   closing['portfolio_sha256'], closing)
    if digest != verified_hash:
        raise ValueError('La cartera cambió durante la lectura.')
    old = {p['asset'] for p in prior['positions']}
    new = {p['asset'] for p in successor['positions']}
    entries, exits = sorted(new - old), sorted(old - new)
    message = (f'Rebalanceo mensual del {day} completado sin problemas.\n'
               f"Entran: {', '.join(entries) or 'Ninguna'}.\n"
               f"Salen: {', '.join(exits) or 'Ninguna'}.\n"
               + ('Mismas criptomonedas; pesos restablecidos.\n' if not entries and not exits else '')
               + 'Cartera teórica del índice; no se enviaron órdenes.')
    receipts = monthly / 'notifications'
    receipts.mkdir(exist_ok=True)
    receipt = receipts / f'{day}.json'
    lock = receipts / f'{day}.lock'
    with lock.open('x', encoding='utf-8') as stream:
        stream.write(str(os.getpid()))
    try:
        if receipt.exists():
            previous = json.loads(receipt.read_bytes())
            if previous.get('portfolio_sha256') != digest:
                raise ValueError('Existe una confirmación para otra versión de la cartera.')
            if previous.get('status') == 'sent':
                return 'already_sent'
            raise ValueError('Envío previo incierto; revisar Pushover antes de reintentar.')
        # Validate credentials before creating the pending receipt.
        env = os.environ if environment is None else environment
        if not env.get('PUSHOVER_TOKEN') or not env.get('PUSHOVER_USER'):
            raise ValueError('Faltan las credenciales de Pushover.')
        record = {'status': 'pending', 'cutoff': day, 'portfolio_sha256': digest,
                  'created_utc': datetime.now(timezone.utc).isoformat()}
        with receipt.open('x', encoding='utf-8') as stream:
            json.dump(record, stream)
        send_message('Crypto Index · Rebalanceo completado', message, env, opener)
        record['status'] = 'sent'
        record['sent_utc'] = datetime.now(timezone.utc).isoformat()
        temporary = receipt.with_suffix('.tmp')
        temporary.write_text(json.dumps(record), encoding='utf-8')
        temporary.replace(receipt)
        return 'sent'
    finally:
        lock.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--service', choices=sorted(SERVICES))
    mode.add_argument('--monthly', action='store_true')
    parser.add_argument('--root', type=Path, default=Path('runs/daily'))
    parser.add_argument('--monthly-dir', type=Path, default=Path('runs/monthly'))
    parser.add_argument('--cutoff', default=None)
    args = parser.parse_args()
    if args.monthly:
        day = args.cutoff or datetime.now(ZoneInfo('America/Mexico_City')).date().isoformat()
        result = send_monthly(args.root, args.monthly_dir, day)
        print('PASS: confirmación mensual:', result)
    else:
        send(args.service)
        print('PASS: Pushover aceptó la notificación.')


if __name__ == '__main__':
    main()
