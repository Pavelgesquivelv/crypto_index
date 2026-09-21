import csv
import json
from decimal import Decimal, getcontext
from pathlib import Path

getcontext().prec = 28

source = Path(
    "runs/historical/binance/20260921T044530650706Z/summary.csv"
)
destination = Path("runs/historical/initial_portfolio.json")

assets = [
    "BTC", "ETH", "XRP", "BNB", "SOL",
    "TRX", "ADA", "LINK", "AVAX", "XLM",
]
cutoff = "2025-09-30T13:00:00+00:00"

with source.open(encoding="utf-8", newline="") as file:
    rows = list(csv.DictReader(file))

portfolio = []

for asset in assets:
    matches = [row for row in rows if row["asset"] == asset]
    if len(matches) != 1:
        raise ValueError(f"Registro ausente o duplicado: {asset}")

    row = matches[0]
    if row["status"] != "PRICE_CONFIRMED":
        raise ValueError(f"Precio no confirmado: {asset}")
    if row["cutoff_utc"] != cutoff:
        raise ValueError(f"Fecha incorrecta: {asset}")
    if row["pair"] != asset + "USDT":
        raise ValueError(f"Par incorrecto: {asset}")

    price = Decimal(row["open_usdt"])
    if not price.is_finite() or price <= 0:
        raise ValueError(f"Precio inválido: {asset}")

    quantity = Decimal("10") / price
    portfolio.append({
        "asset": asset,
        "pair": row["pair"],
        "initial_price_usdt": str(price),
        "quantity": str(quantity),
        "target_weight_pct": 10,
    })

value = sum(
    Decimal(p["quantity"]) * Decimal(p["initial_price_usdt"])
    for p in portfolio
)
if abs(value - Decimal("100")) > Decimal("0.000000000001"):
    raise ValueError(f"Valor inicial inconsistente: {value}")

result = {
    "status": "research_provisional",
    "start_local": "2025-09-30T07:00:00-06:00",
    "start_utc": cutoff,
    "ranking_date": "2025-09-29",
    "base_level": "100",
    "initial_value_usdt": "100",
    "cash_usdt": "0",
    "price_reference": "Binance Spot 1-minute candle open",
    "fees_included": False,
    "source_summary": source.as_posix(),
    "assumptions": [
        "HYPE and LEO excluded provisionally for this initial cutoff: "
        "current API reports invalid symbols and daily Spot archives "
        "returned HTTP 404; historical absence is not conclusively proven.",
        "Previous UTC day's CMC ranking approximates the ranking "
        "available before the rebalance.",
    ],
    "positions": portfolio,
}

destination.parent.mkdir(parents=True, exist_ok=True)
with destination.open("x", encoding="utf-8") as file:
    json.dump(result, file, indent=2)

print("Activo | Cantidad inicial | Peso")
for position in portfolio:
    print(
        position["asset"],
        position["quantity"],
        "10%",
        sep=" | ",
    )

print("\nNivel inicial: 100")
print("Efectivo USDT: 0")
print("Guardado:", destination)
