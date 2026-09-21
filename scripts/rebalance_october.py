import csv
import json
from decimal import Decimal, getcontext
from pathlib import Path

getcontext().prec = 28
TOLERANCE = Decimal("1e-18")

root = Path("runs/historical")
monthly = root / "october/20260921T045153023704Z"
probe = root / "binance/20260921T045532902455Z/summary.csv"
destination = root / "portfolio_2025-10-31.json"

cutoff_local = "2025-10-31T07:00:00-06:00"
cutoff_utc = "2025-10-31T13:00:00+00:00"

assets = [
    "BTC", "ETH", "BNB", "XRP", "SOL",
    "TRX", "ADA", "LINK", "BCH", "XLM",
]


def read_csv(path):
    with path.open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


initial = json.loads(
    (root / "initial_portfolio.json").read_text(encoding="utf-8")
)

daily = [
    row for row in read_csv(monthly / "daily_index.csv")
    if row["cutoff_local"] == cutoff_local
]
if len(daily) != 1:
    raise ValueError("Falta una valoración única del corte.")

previous = daily[0]
value_before = Decimal(previous["value_usdt"])
level_before = Decimal(previous["index_level"])
cash_before = Decimal(previous["cash_usdt"])

if not value_before.is_finite() or value_before <= 0:
    raise ValueError("Valor de cartera inválido.")

probe_rows = read_csv(probe)
quotes = {}

for row in probe_rows:
    asset = row["asset"]
    if asset in quotes:
        raise ValueError(f"Registro duplicado: {asset}")
    quotes[asset] = row


def confirmed_price(asset):
    row = quotes[asset]
    if row["status"] != "PRICE_CONFIRMED":
        raise ValueError(f"Precio no confirmado: {asset}")
    if row["cutoff_utc"] != cutoff_utc:
        raise ValueError(f"Fecha incorrecta: {asset}")
    if row["pair"] != asset + "USDT":
        raise ValueError(f"Par incorrecto: {asset}")

    price = Decimal(row["open_usdt"])
    if not price.is_finite() or price <= 0:
        raise ValueError(f"Precio inválido: {asset}")
    return price


old_positions = [
    row for row in read_csv(monthly / "daily_positions.csv")
    if row["cutoff_local"] == cutoff_local
]

expected_assets = {p["asset"] for p in initial["positions"]}
if (
    len(old_positions) != len(expected_assets)
    or {p["asset"] for p in old_positions} != expected_assets
):
    raise ValueError("La cartera anterior está incompleta o duplicada.")

old_quantities = {}
recalculated = cash_before

for row in old_positions:
    asset = row["asset"]
    price = confirmed_price(asset)
    archived_price = Decimal(row["price_usdt"])

    if price != archived_price:
        raise ValueError(f"API y archivo mensual difieren: {asset}")

    quantity = Decimal(row["quantity"])
    old_quantities[asset] = quantity
    recalculated += quantity * price

if abs(recalculated - value_before) > TOLERANCE:
    raise ValueError("La valoración anterior no concilia.")

allocation = value_before / Decimal("10")
positions = []

for asset in assets:
    price = confirmed_price(asset)
    quantity = allocation / price

    positions.append({
        "asset": asset,
        "pair": asset + "USDT",
        "rebalance_price_usdt": str(price),
        "quantity": str(quantity),
        "target_weight_pct": 10,
    })

value_after = sum(
    Decimal(p["quantity"]) * Decimal(p["rebalance_price_usdt"])
    for p in positions
)

if abs(value_after - value_before) > TOLERANCE:
    raise ValueError("El rebalanceo modifica el valor total.")

level_after = (
    Decimal(initial["base_level"])
    * value_after
    / Decimal(initial["initial_value_usdt"])
)

if abs(level_after - level_before) > TOLERANCE:
    raise ValueError("El rebalanceo introduce un salto en el índice.")

new_quantities = {
    p["asset"]: Decimal(p["quantity"])
    for p in positions
}

changes = []
for asset in sorted(set(old_quantities) | set(new_quantities)):
    before = old_quantities.get(asset, Decimal("0"))
    after = new_quantities.get(asset, Decimal("0"))
    changes.append({
        "asset": asset,
        "quantity_before": str(before),
        "quantity_after": str(after),
        "quantity_change": str(after - before),
    })

report = {
    "status": "research_provisional",
    "cutoff_local": cutoff_local,
    "cutoff_utc": cutoff_utc,
    "ranking_date": "2025-10-30",
    "base_level": initial["base_level"],
    "initial_value_usdt": initial["initial_value_usdt"],
    "value_before_usdt": str(value_before),
    "value_after_usdt": str(value_after),
    "index_level": str(level_after),
    "cash_usdt": "0",
    "fees_included": False,
    "price_reference": "Binance Spot 1-minute candle open",
    "assumptions": [
        "HYPE provisionally excluded at this cutoff with user acceptance: "
        "invalid symbol from current API and HTTP 404 for daily Spot archive; "
        "historical absence is not conclusively proven.",
        "LEO remains unresolved but does not affect the first ten selections.",
        "Previous UTC day's CMC ranking approximates the selection cutoff.",
        "Theoretical fractional quantities; no fees, slippage or order filters.",
    ],
    "sources": {
        "ranking": "runs/historical/2025-10-30/cmc.json",
        "daily_valuation": (monthly / "daily_index.csv").as_posix(),
        "prices": probe.as_posix(),
    },
    "positions": positions,
    "quantity_changes": changes,
}

with destination.open("x", encoding="utf-8") as file:
    json.dump(report, file, indent=2)

print("PASS: precios de API y archivo mensual coinciden.")
print("PASS: valor conservado y continuidad del índice.")
print(f"Valor antes: {value_before:.8f} USDT")
print(f"Valor después: {value_after:.8f} USDT")
print(f"Nivel del índice: {level_after:.8f}")
print(f"Asignación por componente: {allocation:.8f} USDT")
print("Entra: BCH | Sale: AVAX")
print("Guardado:", destination)
