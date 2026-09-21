import csv
import hashlib
import io
import json
import time
import zipfile
from datetime import datetime, timezone
from decimal import Decimal, getcontext
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
from zoneinfo import ZoneInfo

getcontext().prec = 28

root = Path("runs/historical")
initial = json.loads(
    (root / "initial_portfolio.json").read_text(encoding="utf-8")
)
previous = json.loads(
    (
        root / "valuations/2025-10-01/"
        "20260921T044920137978Z/valuation.json"
    ).read_text(encoding="utf-8")
)

cache = root / "archives"
cache.mkdir(parents=True, exist_ok=True)

run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
output = root / "october" / run_id
output.mkdir(parents=True, exist_ok=False)


def download(url):
    for attempt in range(3):
        try:
            with urlopen(url, timeout=60) as response:
                return response.read()
        except HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504):
                raise
            if attempt == 2:
                raise
        except (URLError, TimeoutError):
            if attempt == 2:
                raise
        time.sleep(2 ** attempt)


targets = {}
for day in range(1, 32):
    cutoff = datetime(
        2025, 10, day, 7,
        tzinfo=ZoneInfo("America/Mexico_City"),
    )
    targets[int(cutoff.timestamp() * 1000)] = cutoff.isoformat()

prices = {}
evidence = []

for position in initial["positions"]:
    pair = position["pair"]
    filename = f"{pair}-1m-2025-10.zip"
    url = (
        "https://data.binance.vision/data/spot/monthly/klines/"
        f"{pair}/1m/{filename}"
    )
    path = cache / filename

    raw = path.read_bytes() if path.exists() else download(url)
    checksum = download(url + ".CHECKSUM")
    expected = checksum.decode("utf-8").split()[0].lower()
    actual = hashlib.sha256(raw).hexdigest()

    if actual != expected:
        raise ValueError(f"Checksum incorrecto: {pair}")

    path.write_bytes(raw)
    (cache / (filename + ".CHECKSUM")).write_bytes(checksum)

    selected = {}

    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        csv_names = [
            name for name in archive.namelist()
            if name.endswith(".csv")
        ]
        if len(csv_names) != 1:
            raise ValueError(f"Contenido inesperado: {pair}")

        with archive.open(csv_names[0]) as stream:
            reader = csv.reader(io.TextIOWrapper(stream, encoding="utf-8"))

            for row in reader:
                if not row:
                    continue
                if row[0].lower() in ("open_time", "open time"):
                    continue

                stamp = int(row[0])
                if stamp >= 100_000_000_000_000:
                    if stamp % 1000:
                        raise ValueError(f"Timestamp inesperado: {pair}")
                    stamp //= 1000

                if stamp not in targets:
                    continue
                if stamp in selected:
                    raise ValueError(f"Vela duplicada: {pair}")

                price = Decimal(row[1])
                volume = Decimal(row[5])

                if (
                    not price.is_finite() or price <= 0
                    or not volume.is_finite() or volume <= 0
                    or int(row[8]) <= 0
                ):
                    raise ValueError(f"Vela sin precio válido: {pair}")

                selected[stamp] = price

    if set(selected) != set(targets):
        raise ValueError(f"Faltan cortes diarios para {pair}")

    prices[pair] = selected
    evidence.append({
        "pair": pair,
        "url": url,
        "sha256": actual,
        "cutoffs_found": len(selected),
    })
    print(f"{pair}: 31 cortes confirmados; checksum correcto")


cash = Decimal(initial["cash_usdt"])
base = Decimal(initial["base_level"])
initial_value = Decimal(initial["initial_value_usdt"])
previous_value = initial_value

daily_rows = []
position_rows = []

for stamp, cutoff in sorted(targets.items()):
    total = cash
    holdings = []

    for position in initial["positions"]:
        quantity = Decimal(position["quantity"])
        price = prices[position["pair"]][stamp]
        value = quantity * price
        total += value

        holdings.append({
            "cutoff_local": cutoff,
            "asset": position["asset"],
            "quantity": str(quantity),
            "price_usdt": str(price),
            "value_usdt": str(value),
        })

    level = base * total / initial_value

    daily_rows.append({
        "cutoff_local": cutoff,
        "value_usdt": str(total),
        "index_level": str(level),
        "daily_return_pct": str((total / previous_value - 1) * 100),
        "cumulative_return_pct": str((total / initial_value - 1) * 100),
        "cash_usdt": str(cash),
        "valuation_phase": "before_rebalance",
    })

    for holding in holdings:
        holding["weight_pct"] = str(
            Decimal(holding["value_usdt"]) / total * 100
        )
        position_rows.append(holding)

    previous_value = total

if abs(
    Decimal(daily_rows[0]["index_level"])
    - Decimal(previous["index_level"])
) > Decimal("0.00000001"):
    raise ValueError("El 1 de octubre no coincide con la valoración anterior")

for filename, rows in [
    ("daily_index.csv", daily_rows),
    ("daily_positions.csv", position_rows),
]:
    with (output / filename).open(
        "w", newline="", encoding="utf-8"
    ) as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

(output / "audit.json").write_text(
    json.dumps({
        "status": "research_provisional",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "daily_observations": len(daily_rows),
        "price_reference": "Binance Spot 1-minute candle open",
        "fees_included": False,
        "rebalance_applied": False,
        "assumptions": initial["assumptions"],
        "sources": evidence,
    }, indent=2),
    encoding="utf-8",
)

last = daily_rows[-1]
print("\nPASS: 31 valoraciones; primer día conciliado.")
print("Nivel al 31 de octubre:", last["index_level"])
print("Rendimiento desde el inicio (%):", last["cumulative_return_pct"])
print("Resultados:", output)
