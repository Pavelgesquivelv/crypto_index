"""Resolve explicitly approved missing identities using the original captured data."""
import argparse
import json
from pathlib import Path
from crypto_index.selection_review import review


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--selection', type=Path, required=True)
    parser.add_argument('--registry', type=Path, default=Path('config/assets.json'))
    parser.add_argument('--add-id', nargs='+', required=True)
    args = parser.parse_args()
    directory = review(args.selection, args.registry, args.add_id)
    report = json.loads((directory / 'report.json').read_bytes())
    print('PASS: revisión lista; fuentes originales conservadas, sin consultas nuevas.')
    print('Selección:', report['selection_date'], '| Rebalanceo:', report['rebalance_date'])
    for item in report['portfolio']:
        print(item['asset'], str(item['weight_pct']) + '%', sep=' | ')
    print('Guardado:', directory / 'report.json')


if __name__ == '__main__':
    main()
