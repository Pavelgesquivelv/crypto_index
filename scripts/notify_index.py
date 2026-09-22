"""Send a fixed index service failure alert to Pushover; never forwards logs."""
import argparse
import json
import os
from urllib.parse import urlencode
from urllib.request import Request, urlopen

SERVICES = {
    'crypto-index-daily.service': 'La valoración diaria no terminó correctamente.',
    'crypto-index-capture.service': 'La selección mensual falló o requiere revisión.',
    'crypto-index-monthly.service': 'No se pudo completar la cartera mensual.',
    'crypto-index-dashboard.service': 'No se pudo actualizar el dashboard público.',
}


def send(service, environment=None, opener=None):
    environment = os.environ if environment is None else environment
    opener = urlopen if opener is None else opener
    if service not in SERVICES:
        raise ValueError('Servicio no reconocido.')
    token, user = environment.get('PUSHOVER_TOKEN'), environment.get('PUSHOVER_USER')
    if not token or not user:
        raise ValueError('Faltan las credenciales de Pushover.')
    body = urlencode({'token': token, 'user': user, 'title': 'Crypto Index · Revisión requerida',
                      'message': SERVICES[service] + ' Revisa el servicio en el servidor.',
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--service', required=True, choices=sorted(SERVICES))
    args = parser.parse_args()
    send(args.service)
    print('PASS: Pushover aceptó la notificación.')


if __name__ == '__main__':
    main()
