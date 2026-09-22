"""Probe historical Binance Spot candles for a configurable cutoff."""

import argparse
import csv
import json
import re
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen
from zoneinfo import ZoneInfo


def fetch(url):
    """Return HTTP status and response bytes, with bounded retries."""
    for attempt in range(3):
        try:
            with urlopen(url, timeout=30) as response:
                return response.status, response.read()
        except HTTPError as error:
            status, raw = error.code, error.read()
            if status not in (429, 500, 502, 503, 504) or attempt == 2:
                return status, raw
        except (URLError, TimeoutError):
            if attempt == 2:
                raise

        time.sleep(2 ** attempt)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--assets", nargs="+", required=True,
        help="Ordered asset symbols, separated by spaces",
    )
    parser.add_argument(
        "--cutoff", required=True,
        help="Local date: YYYY-MM-DD",
    )
    parser.add_argument(
        "--time", default="07:00",
        help="CDMX time: HH:MM; default 07:00",
    )
    parser.add_argument(
        "--output", type=Path,
        default=Path("runs/historical/binance"),
    )
    args = parser.parse_args()

    assets = [asset.upper() for asset in args.assets]
    if len(set(assets)) != len(assets):
        parser.error("Assets must be unique")
    if any(not re.fullmatch(r"[A-Z0-9]+", asset) for asset in assets):
        parser.error("Assets must contain only letters and numbers")
    if "USDT" in assets:
        parser.error("USDT is cash, not a candidate pair")

    try:
        cutoff = datetime.strptime(
            f"{args.cutoff} {args.time}", "%Y-%m-%d %H:%M"
        ).replace(tzinfo=ZoneInfo("America/Mexico_City"))
    except ValueError:
        parser.error("Use --cutoff YYYY-MM-DD and --time HH:MM")

    cutoff_utc = cutoff.astimezone(timezone.utc)
    start_ms = int(cutoff.timestamp() * 1000)

    # Require a completed minute so trade counts are final.
    if start_ms + 60_000 > int(datetime.now(timezone.utc).timestamp() * 1000):
        parser.error("The cutoff minute must have finished")

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = args.output / run_id
    folder.mkdir(parents=True, exist_ok=False)

    rows = []

    for asset in assets:
        pair = asset + "USDT"
        query = urlencode({
            "symbol": pair,
            "interval": "1m",
            "startTime": start_ms,
            "endTime": start_ms + 59_999,
            "limit": 1,
        })
        url = "https://api.binance.com/api/v3/klines?" + query
        row = {
            "asset": asset,
            "pair": pair,
            "cutoff_utc": cutoff_utc.isoformat(),
            "status": "UNRESOLVED",
            "open_usdt": "",
            "trades": "",
            "detail": "",
            "http_status": "",
            "retrieved_at_utc": "",
        }

        try:
            status, raw = fetch(url)
            row["http_status"] = status
            filename = (
                f"{pair}.json" if status == 200
                else f"{pair}-error.json"
            )
            (folder / filename).write_bytes(raw)

            if status != 200:
                row["detail"] = (
                    f"HTTP {status}; historical absence not established"
                )
            else:
                data = json.loads(raw)

                if not isinstance(data, list) or len(data) != 1:
                    row["detail"] = "No unique candle; investigate"
                else:
                    candle = data[0]
                    stamp = int(candle[0])
                    price = Decimal(candle[1])
                    volume = Decimal(candle[5])
                    trades = int(candle[8])

                    if stamp not in (start_ms, start_ms * 1000):
                        row["detail"] = "Candle timestamp differs from cutoff"
                    elif (
                        not price.is_finite() or price <= 0
                        or not volume.is_finite() or volume <= 0
                        or trades <= 0
                    ):
                        row["detail"] = "Invalid price, volume or trade count"
                    else:
                        row.update(
                            status="PRICE_CONFIRMED",
                            open_usdt=str(price),
                            trades=trades,
                            detail="Spot trades recorded in cutoff minute",
                        )

        except (URLError, TimeoutError):
            row["detail"] = "Connection failed; retry required"
        except (ValueError, ArithmeticError, IndexError, KeyError, TypeError):
            row["detail"] = "Unexpected response; inspect saved data"

        row["retrieved_at_utc"] = datetime.now(timezone.utc).isoformat()
        rows.append(row)
        print(
            pair, row["status"], row["open_usdt"], row["detail"],
            sep=" | ",
        )

    with (folder / "summary.csv").open(
        "w", newline="", encoding="utf-8"
    ) as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    (folder / "metadata.json").write_text(
        json.dumps({
            "cutoff_local": cutoff.isoformat(),
            "cutoff_utc": cutoff_utc.isoformat(),
            "interval": "1m",
            "price_reference": "open",
            "assets": assets,
            "source": "https://api.binance.com/api/v3/klines",
            "scope": "Direct USDT pairs only",
            "note": "Unresolved does not mean historically unavailable",
        }, indent=2),
        encoding="utf-8",
    )

    print("\nEvidencia guardada en:", folder)


if __name__ == "__main__":
    main()
