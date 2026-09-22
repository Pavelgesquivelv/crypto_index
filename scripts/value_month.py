import argparse
import calendar
import csv
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from crypto_index.archive_download import ensure_monthly_archive
from crypto_index.monthly_valuation import value_month


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--month", type=int, required=True)
    parser.add_argument("--portfolio", type=Path, required=True)
    args = parser.parse_args()

    first_day = date(args.year, args.month, 1)
    previous_day = first_day - timedelta(days=1)
    expected_cutoff = f"{previous_day.isoformat()}T13:00:00+00:00"

    raw = args.portfolio.read_bytes()
    portfolio = json.loads(raw)

    if portfolio["cutoff_utc"] != expected_cutoff:
        raise ValueError(
            f"La cartera debe corresponder a {expected_cutoff}"
        )

    positions = portfolio["positions"]
    quantities = {p["asset"]: p["quantity"] for p in positions}
    pairs = {p["asset"]: p["pair"] for p in positions}

    if len(quantities) != len(positions):
        raise ValueError("Activos duplicados en la cartera.")

    root = Path("runs/historical")
    archives = root / "archives"
    evidence = []

    for asset, pair in pairs.items():
        path = ensure_monthly_archive(
            pair, args.year, args.month, archives
        )
        evidence.append({
            "asset": asset,
            "pair": pair,
            "archive": path.as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
        print(f"{pair}: archivo verificado")

    results = value_month(
        quantities=quantities,
        pairs=pairs,
        cash=portfolio["cash_usdt"],
        archive_directory=archives,
        year=args.year,
        month=args.month,
        previous_value=portfolio["value_after_usdt"],
        initial_value=portfolio["initial_value_usdt"],
        base_level=portfolio["base_level"],
    )

    expected_days = calendar.monthrange(args.year, args.month)[1]
    if len(results) != expected_days:
        raise ValueError("Serie mensual incompleta.")

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = root / f"{args.year:04d}-{args.month:02d}" / run_id
    output.mkdir(parents=True, exist_ok=False)

    with (output / "daily_index.csv").open(
        "w", newline="", encoding="utf-8"
    ) as file:
        writer = csv.DictWriter(file, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(results)

    audit = {
        "status": "research_provisional",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "valuation_time": "07:00 America/Mexico_City",
        "daily_observations": len(results),
        "portfolio_source": args.portfolio.as_posix(),
        "portfolio_sha256": hashlib.sha256(raw).hexdigest(),
        "assumptions": portfolio["assumptions"],
        "archives": evidence,
        "rebalance_applied": False,
        "fees_included": False,
        "last_observation": "Before month-end rebalance",
    }

    (output / "audit.json").write_text(
        json.dumps(audit, indent=2),
        encoding="utf-8",
    )

    print(f"\nPASS: {len(results)} valoraciones con cantidades constantes.")
    print("Nivel inicial del mes:", results[0]["index_level"])
    print("Nivel final del mes:", results[-1]["index_level"])
    print(
        "Rendimiento acumulado (%):",
        results[-1]["cumulative_return_pct"],
    )
    print("Resultados:", output)


if __name__ == "__main__":
    main()
