"""Generate a static dashboard; only this output directory should be served publicly."""
import argparse
import os
import tempfile
from pathlib import Path
from crypto_index.dashboard import public_data, render


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('runs/daily'))
    parser.add_argument('--monthly', type=Path, default=Path('runs/monthly'))
    parser.add_argument('--output', type=Path, default=Path('runs/dashboard'))
    args = parser.parse_args()
    page = render(public_data(args.root, args.monthly))
    args.output.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=args.output, suffix='.tmp')
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            stream.write(page)
        os.replace(name, args.output / 'index.html')
    finally:
        Path(name).unlink(missing_ok=True)
    print('PASS: dashboard exportado:', args.output / 'index.html')


if __name__ == '__main__':
    main()
