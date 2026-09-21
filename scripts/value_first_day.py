import json
from datetime import datetime, timezone
from decimal import Decimal, getcontext
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen
from zoneinfo import ZoneInfo

getcontext().prec = 28

initial = json.loads(
    Path("runs/historical/initial_portfolio.json")
    .read_text(encoding="utf-8")
)

cutoff = datetime(
    2025, 10, 1, 7, 0,
    tzinfo=ZoneInfo("America/Mexico_City"),
)
start_ms = int(cutoff.timestamp() * 1000)

run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
folder = Path("runs/historical/valuations/2025-10-01") / run_id
folder.mkdir(parents=True, exist_ok=False)

positions = []
cash = Decimal(initial["cash_usdt"])
total = cash

for position in initial["positions"]:
    pair = position["pair"]
    query = urlencode({
        "symbol": pair,
        "interval": "1m",
        "startTime": start_ms,
        "endTime": start_ms + 59_999,
        "limit": 1,
    })
    url = "https://api.binance.com/api/v3/klines?" + query

    with urlopen(url, timeout=30) as response:
        raw = response.read()
    (folder / f"{pair}.json").write_bytes(raw)

    candles = json.loads(raw)
    if not isinstance(candles, list) or len(candles) != 1:
        raise ValueError(f"Falta una vela única para {pair}")

    candle = candles[0]
    if int(candle[0]) not in (start_ms, start_ms * 1000):
        raise ValueError(f"Fecha incorrecta para {pair}")
    if int(candle[8]) <= 0:
        raise ValueError(f"Sin operaciones para {pair}")

    price = Decimal(candle[1])
    volume = Decimal(candle[5])
    if (
        not price.is_finite() or price <= 0
        or not volume.is_finite() or volume <= 0
    ):
        raise ValueError(f"Precio o volumen inválido para {pair}")

    quantity = Decimal(position["quantity"])
    value = quantity * price
    total += value

    positions.append({
        "asset": position["asset"],
        "quantity": str(quantity),
        "price_usdt": str(price),
        "value_usdt": str(value),
    })

initial_value = Decimal(initial["initial_value_usdt"])
level = Decimal(initial["base_level"]) * total / initial_value
daily_return = (total / initial_value - 1) * 100

for position in positions:
    position["weight_pct"] = str(
        Decimal(position["value_usdt"]) / total * 100
    )

report = {
    "status": "research_provisional",
    "cutoff_local": cutoff.isoformat(),
    "cutoff_utc": cutoff.astimezone(timezone.utc).isoformat(),
    "value_usdt": str(total),
    "index_level": str(level),
    "daily_return_pct": str(daily_return),
    "cash_usdt": str(cash),
    "rebalanced": False,
    "assumptions": initial["assumptions"],
    "positions": positions,
}

(folder / "valuation.json").write_text(
    json.dumps(report, indent=2),
    encoding="utf-8",
)

print(f"Nivel del índice: {level:.8f}")
print(f"Rendimiento diario: {daily_return:.6f}%")
print("\nActivo | Peso después del movimiento de precios")
for position in positions:
    print(
        position["asset"],
        f'{Decimal(position["weight_pct"]):.4f}%',
        sep=" | ",
    )
print("\nGuardado:", folder / "valuation.json")
