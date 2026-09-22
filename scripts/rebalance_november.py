import csv
import hashlib
import json
from decimal import Decimal
from pathlib import Path

from crypto_index.calculation import (
    index_level,
    portfolio_value,
    rebalance,
)
from crypto_index.historical_prices import monthly_open_prices

root = Path("runs/historical")
prior_path = root / "portfolio_2025-10-31.json"
daily_path = (
    root / "november/20260921T052336444672Z/daily_index.csv"
)
probe_path = (
    root / "binance/20260921T052652529527Z/summary.csv"
)
checks_path = (
    root / "binance/20260921T052652529527Z/"
    "archive_checks_20260921T052750491635Z.json"
)
ranking_path = root / "2025-11-29/cmc.json"
destination = root / "portfolio_2025-11-30.json"

cutoff_utc = "2025-11-30T13:00:00+00:00"
date = "2025-11-30"
tolerance = Decimal("1e-18")

assets = [
    "BTC", "ETH", "XRP", "BNB", "SOL",
    "TRX", "ADA", "BCH", "LINK", "XLM",
]


def read_csv(path):
    with path.open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


prior = json.loads(prior_path.read_text(encoding="utf-8"))
if prior["cutoff_utc"] != "2025-10-31T13:00:00+00:00":
    raise ValueError("La cartera anterior no corresponde al corte esperado.")

daily_rows = [
    row for row in read_csv(daily_path)
    if row["date"] == date
]
if len(daily_rows) != 1:
    raise ValueError("Falta una valoración única del corte.")

expected_value = Decimal(daily_rows[0]["value_usdt"])
expected_level = Decimal(daily_rows[0]["index_level"])

probe_rows = read_csv(probe_path)
quotes = {row["asset"]: row for row in probe_rows}
if len(quotes) != len(probe_rows):
    raise ValueError("Precios duplicados en la consulta.")

quantities = {
    position["asset"]: position["quantity"]
    for position in prior["positions"]
}
if len(quantities) != len(prior["positions"]):
    raise ValueError("Activos duplicados en la cartera anterior.")

prices = {}

for asset in sorted(set(quantities) | set(assets)):
    row = quotes[asset]
    if (
        row["status"] != "PRICE_CONFIRMED"
        or row["cutoff_utc"] != cutoff_utc
        or row["pair"] != asset + "USDT"
    ):
        raise ValueError(f"Consulta inválida para {asset}")

    api_price = Decimal(row["open_usdt"])
    archive = root / "archives" / f"{asset}USDT-1m-2025-11.zip"
    archived_price = monthly_open_prices(archive, 2025, 11)[date]

    if api_price != archived_price:
        raise ValueError(f"API y archivo mensual difieren: {asset}")

    prices[asset] = api_price

value_before = portfolio_value(
    quantities, prices, prior["cash_usdt"]
)
if abs(value_before - expected_value) > tolerance:
    raise ValueError("La valoración previa no concilia.")

result = rebalance(value_before, assets, prices)
level_after = index_level(
    result["value_after"],
    prior["initial_value_usdt"],
    prior["base_level"],
)
if abs(level_after - expected_level) > tolerance:
    raise ValueError("El rebalanceo introduce un salto en el índice.")

positions = [
    {
        "asset": asset,
        "pair": asset + "USDT",
        "quantity": str(result["quantities"][asset]),
        "rebalance_price_usdt": str(prices[asset]),
        "target_weight_pct": 10,
    }
    for asset in assets
]

sources = [
    prior_path, daily_path, probe_path, checks_path, ranking_path
]

report = {
    "status": "research_provisional",
    "cutoff_local": "2025-11-30T07:00:00-06:00",
    "cutoff_utc": cutoff_utc,
    "ranking_date": "2025-11-29",
    "base_level": prior["base_level"],
    "initial_value_usdt": prior["initial_value_usdt"],
    "value_before_usdt": str(value_before),
    "value_after_usdt": str(result["value_after"]),
    "index_level": str(level_after),
    "cash_usdt": str(result["cash"]),
    "fees_included": False,
    "price_reference": "Binance Spot 1-minute candle open",
    "assumptions": [
        "User accepted provisional exclusion of HYPE and LEO "
        "for this cutoff: unresolved API queries and HTTP 404 "
        "daily archives do not conclusively prove historical absence.",
        "XMR remains unresolved but does not affect the selected ten.",
        "Previous UTC day's CMC ranking approximates the selection cutoff.",
        "Fractional theoretical quantities; no fees or slippage.",
    ],
    "sources": {
        path.as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sources
    },
    "positions": positions,
}

with destination.open("x", encoding="utf-8") as file:
    json.dump(report, file, indent=2)

print("PASS: precios API y archivos mensuales coinciden.")
print("PASS: valoración conciliada y nivel conservado.")
print(f"Valor antes: {value_before:.8f} USDT")
print(f"Valor después: {result['value_after']:.8f} USDT")
print(f"Nivel del índice: {level_after:.8f}")
print("Composición: mismas diez monedas, pesos restablecidos al 10%.")
print("Guardado:", destination)
