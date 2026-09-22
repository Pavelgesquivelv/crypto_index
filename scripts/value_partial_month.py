import argparse
import csv
import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from crypto_index.archive_download import download_bytes
from crypto_index.calculation import (
    index_level,
    portfolio_value,
    return_pct,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--portfolio", type=Path, required=True)
    args = parser.parse_args()

    raw_portfolio = args.portfolio.read_bytes()
    portfolio = json.loads(raw_portfolio)

    zone = ZoneInfo("America/Mexico_City")
    prior_cutoff = datetime.fromisoformat(
        portfolio["cutoff_utc"]
    ).astimezone(zone)

    first = prior_cutoff + timedelta(days=1)
    if first.day != 1 or (first.hour, first.minute) != (7, 0):
        raise ValueError("Se requiere una cartera de cierre mensual a las 07:00.")

    now = datetime.now(timezone.utc)
    local_now = now.astimezone(zone)
    last = local_now.replace(hour=7, minute=0, second=0, microsecond=0)

    # La vela del corte debe haber terminado.
    if now < (last + timedelta(minutes=1)).astimezone(timezone.utc):
        last -= timedelta(days=1)

    if last < first or (last.year, last.month) != (first.year, first.month):
        raise ValueError("La cartera no corresponde al mes actual.")

    positions = portfolio["positions"]
    quantities = {p["asset"]: p["quantity"] for p in positions}
    pairs = {p["asset"]: p["pair"] for p in positions}

    if len(quantities) != len(positions):
        raise ValueError("Activos duplicados.")
    if len(set(pairs.values())) != len(pairs):
        raise ValueError("Pares duplicados.")

    root = Path("runs/historical")
    cache = root / "daily_api"
    cache.mkdir(parents=True, exist_ok=True)

    previous_value = Decimal(portfolio["value_after_usdt"])
    results = []
    evidence = []

    cutoff = first
    while cutoff <= last:
        day = cutoff.date().isoformat()
        start_ms = int(cutoff.timestamp() * 1000)
        prices = {}

        for asset, pair in pairs.items():
            if (
                not pair.isascii()
                or not pair.isalnum()
                or not pair.endswith("USDT")
            ):
                raise ValueError(f"Par inválido: {pair}")

            path = cache / f"{pair}-{day}-0700-CDMX.json"
            query = urlencode({
                "symbol": pair,
                "interval": "1m",
                "startTime": start_ms,
                "endTime": start_ms + 59_999,
                "limit": 1,
            })
            url = "https://api.binance.com/api/v3/klines?" + query

            cached = path.exists()
            raw = path.read_bytes() if cached else download_bytes(url)
            candles = json.loads(raw)

            if not isinstance(candles, list) or len(candles) != 1:
                raise ValueError(f"Falta vela única: {pair}, {day}")

            candle = candles[0]
            if int(candle[0]) not in (start_ms, start_ms * 1000):
                raise ValueError(f"Fecha incorrecta: {pair}, {day}")

            price = Decimal(candle[1])
            volume = Decimal(candle[5])
            if (
                not price.is_finite() or price <= 0
                or not volume.is_finite() or volume <= 0
                or int(candle[8]) <= 0
            ):
                raise ValueError(f"Vela inválida: {pair}, {day}")

            if not cached:
                with path.open("xb") as file:
                    file.write(raw)

            prices[asset] = price
            evidence.append({
                "date": day,
                "pair": pair,
                "url": url,
                "file": path.as_posix(),
                "sha256": hashlib.sha256(raw).hexdigest(),
            })

        value = portfolio_value(
            quantities, prices, portfolio["cash_usdt"]
        )
        level = index_level(
            value,
            portfolio["initial_value_usdt"],
            portfolio["base_level"],
        )
        results.append({
            "date": day,
            "value_usdt": value,
            "index_level": level,
            "daily_return_pct": return_pct(value, previous_value),
            "cumulative_return_pct": return_pct(
                value, portfolio["initial_value_usdt"]
            ),
        })

        previous_value = value
        print(f"{day} | nivel {level:.8f}", flush=True)
        cutoff += timedelta(days=1)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = root / f"{first.year:04d}-{first.month:02d}" / stamp
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
        "cutoff_timezone": "America/Mexico_City",
        "cutoff_time": "07:00",
        "start_date": results[0]["date"],
        "end_date": results[-1]["date"],
        "daily_observations": len(results),
        "portfolio_source": args.portfolio.as_posix(),
        "portfolio_sha256": hashlib.sha256(raw_portfolio).hexdigest(),
        "assumptions": portfolio["assumptions"],
        "price_reference": "Binance Spot 1-minute candle open",
        "rebalance_applied": False,
        "fees_included": False,
        "sources": evidence,
    }
    (output / "audit.json").write_text(
        json.dumps(audit, indent=2),
        encoding="utf-8",
    )

    print(f"\nPASS: {len(results)} valoraciones.")
    print("Último corte:", results[-1]["date"])
    print("Nivel final:", results[-1]["index_level"])
    print("Rendimiento acumulado (%):", results[-1]["cumulative_return_pct"])
    print("Resultados:", output)


if __name__ == "__main__":
    main()
