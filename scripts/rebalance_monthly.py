"""Rebalance a historical portfolio using reviewed selection and prices."""

import argparse
import csv
import hashlib
import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from crypto_index.archive_download import ensure_monthly_archive
from crypto_index.calculation import index_level, portfolio_value, rebalance
from crypto_index.historical_prices import monthly_open_prices


def read_csv(path):
    with path.open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cutoff", required=True)
    parser.add_argument("--portfolio", type=Path, required=True)
    parser.add_argument("--valuation", type=Path, required=True)
    parser.add_argument("--probe", type=Path, required=True)
    parser.add_argument("--checks", type=Path, required=True)
    parser.add_argument("--ranking", type=Path, required=True)
    parser.add_argument("--assets", nargs="+", required=True)
    parser.add_argument("--provisional-exclusions", nargs="+", required=True)
    args = parser.parse_args()

    cutoff = datetime.strptime(args.cutoff, "%Y-%m-%d").replace(
        hour=7, tzinfo=ZoneInfo("America/Mexico_City")
    )
    if (cutoff + timedelta(days=1)).month == cutoff.month:
        raise ValueError("El corte debe ser el último día del mes.")

    assets = [asset.upper() for asset in args.assets]
    exclusions = [asset.upper() for asset in args.provisional_exclusions]
    if set(assets) & set(exclusions):
        raise ValueError("Un activo no puede seleccionarse y excluirse.")

    root = Path("runs/historical")
    destination = root / f"portfolio_{args.cutoff}.json"
    if destination.exists():
        raise FileExistsError(f"Ya existe: {destination}")

    prior = json.loads(args.portfolio.read_text(encoding="utf-8"))
    prior_cutoff = datetime.fromisoformat(prior["cutoff_utc"])
    expected_prior = cutoff.replace(day=1) - timedelta(days=1)
    if prior_cutoff != expected_prior:
        raise ValueError("La cartera anterior no corresponde al mes previo.")

    daily = [
        row for row in read_csv(args.valuation)
        if row["date"] == args.cutoff
    ]
    if len(daily) != 1:
        raise ValueError("Falta una valoración única del corte.")

    probe_rows = read_csv(args.probe / "summary.csv")
    quotes = {row["asset"]: row for row in probe_rows}
    if len(quotes) != len(probe_rows):
        raise ValueError("Activos duplicados en la consulta.")

    metadata = json.loads(
        (args.probe / "metadata.json").read_text(encoding="utf-8")
    )
    if datetime.fromisoformat(metadata["cutoff_local"]) != cutoff:
        raise ValueError("La consulta corresponde a otra fecha.")

    checks = json.loads(args.checks.read_text(encoding="utf-8"))
    for asset in exclusions:
        if quotes[asset]["status"] != "UNRESOLVED":
            raise ValueError(f"La exclusión contradice la consulta: {asset}")

        expected_url = (
            "https://data.binance.vision/data/spot/daily/klines/"
            f"{asset}USDT/1m/{asset}USDT-1m-{args.cutoff}.zip"
        )
        if not any(
            item.get("url") == expected_url
            and item.get("http_status") == 404
            for item in checks
        ):
            raise ValueError(f"Falta evidencia 404 del corte: {asset}")

    quantities = {
        p["asset"]: p["quantity"] for p in prior["positions"]
    }
    if len(quantities) != len(prior["positions"]):
        raise ValueError("Posiciones anteriores duplicadas.")

    prices = {}
    archives = []

    for asset in sorted(set(quantities) | set(assets)):
        row = quotes[asset]
        if (
            row["status"] != "PRICE_CONFIRMED"
            or row["pair"] != asset + "USDT"
            or datetime.fromisoformat(row["cutoff_utc"]) != cutoff
        ):
            raise ValueError(f"Precio no confirmado en el corte: {asset}")

        path = ensure_monthly_archive(
            asset + "USDT", cutoff.year, cutoff.month, root / "archives"
        )
        archived = monthly_open_prices(
            path, cutoff.year, cutoff.month
        )[args.cutoff]

        if archived != Decimal(row["open_usdt"]):
            raise ValueError(f"API y archivo difieren: {asset}")

        prices[asset] = archived
        archives.append(path)

    value_before = portfolio_value(
        quantities, prices, prior["cash_usdt"]
    )
    tolerance = Decimal("1e-18")
    if abs(value_before - Decimal(daily[0]["value_usdt"])) > tolerance:
        raise ValueError("La valoración previa no concilia.")

    result = rebalance(value_before, assets, prices)
    level = index_level(
        result["value_after"],
        prior["initial_value_usdt"],
        prior["base_level"],
    )
    if abs(level - Decimal(daily[0]["index_level"])) > tolerance:
        raise ValueError("El rebalanceo introduce un salto en el índice.")

    sources = [
        args.portfolio, args.valuation, args.ranking, args.checks,
        args.probe / "summary.csv", args.probe / "metadata.json",
        *archives,
    ]

    report = {
        "status": "research_provisional",
        "cutoff_local": cutoff.isoformat(),
        "cutoff_utc": metadata["cutoff_utc"],
        "ranking_date": (cutoff.date() - timedelta(days=1)).isoformat(),
        "selection_method": "Manually reviewed CMC universe and selection",
        "provisional_exclusions": exclusions,
        "base_level": prior["base_level"],
        "initial_value_usdt": prior["initial_value_usdt"],
        "value_before_usdt": str(value_before),
        "value_after_usdt": str(result["value_after"]),
        "index_level": str(level),
        "cash_usdt": str(result["cash"]),
        "fees_included": False,
        "price_reference": "Binance Spot 1-minute candle open",
        "assumptions": [
            "Provisional exclusions accepted for this cutoff: "
            + ", ".join(exclusions)
            + ". Unresolved API queries and missing archives do not "
            "conclusively establish historical absence.",
            "Previous UTC day's CMC ranking approximates the cutoff.",
            "Manual eligibility review; historical category timing unverified.",
            "Fractional theoretical quantities; no fees or slippage.",
        ],
        "sources": {
            path.as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sources
        },
        "positions": [
            {
                "asset": asset,
                "pair": asset + "USDT",
                "quantity": str(result["quantities"][asset]),
                "rebalance_price_usdt": str(prices[asset]),
                "target_weight_pct": 10,
            }
            for asset in assets
        ],
    }

    with destination.open("x", encoding="utf-8") as file:
        json.dump(report, file, indent=2)

    print("PASS: precios conciliados y valor conservado.")
    print(f"Valor antes: {value_before:.8f} USDT")
    print(f"Valor después: {result['value_after']:.8f} USDT")
    print(f"Nivel del índice: {level:.8f}")
    print("Entran:", sorted(set(assets) - set(quantities)))
    print("Salen:", sorted(set(quantities) - set(assets)))
    print("Guardado:", destination)


if __name__ == "__main__":
    main()
