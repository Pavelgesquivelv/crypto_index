import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen
from zoneinfo import ZoneInfo

ASSETS = [
    "BTC", "ETH", "BNB", "XRP", "SOL",
    "TRX", "ADA", "BCH", "HYPE", "LINK",
    "ZEC", "LEO", "XMR", "XLM", "LTC",
]

cutoff = datetime(
    2025, 12, 31, 7, 0,
    tzinfo=ZoneInfo("America/Mexico_City"),
)
start_ms = int(cutoff.timestamp() * 1000)

run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
folder = Path("runs/historical/binance") / run_id
folder.mkdir(parents=True, exist_ok=False)

rows = []

for asset in ASSETS:
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
        "cutoff_utc": cutoff.astimezone(timezone.utc).isoformat(),
        "status": "UNRESOLVED",
        "open_usdt": "",
        "trades": "",
        "detail": "",
    }

    try:
        with urlopen(url, timeout=30) as response:
            raw = response.read()

        (folder / f"{pair}.json").write_bytes(raw)
        data = json.loads(raw)

        if not isinstance(data, list) or not data:
            row["detail"] = "No candle returned; investigate archives"
        else:
            candle = data[0]
            open_time = int(candle[0])

            # Accept milliseconds or microseconds explicitly.
            if open_time == start_ms * 1000:
                open_time //= 1000

            if open_time != start_ms:
                row["detail"] = "Returned candle does not match cutoff"
            elif int(candle[8]) <= 0:
                row["detail"] = "Candle has no trades"
            elif float(candle[1]) <= 0 or float(candle[5]) <= 0:
                row["detail"] = "Invalid price or volume"
            else:
                row.update(
                    status="PRICE_CONFIRMED",
                    open_usdt=candle[1],
                    trades=candle[8],
                    detail="Spot trades recorded in cutoff minute",
                )

    except HTTPError as error:
        raw = error.read()
        (folder / f"{pair}-error.json").write_bytes(raw)
        row["detail"] = (
            f"HTTP {error.code}; does not establish historical absence"
        )
    except (URLError, TimeoutError):
        row["detail"] = "Connection failed; retry required"
    except (ValueError, KeyError, IndexError, TypeError):
        row["detail"] = "Unexpected response; inspect saved data"

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
        "interval": "1m",
        "price_reference": "open",
        "source": "https://api.binance.com/api/v3/klines",
        "assets": ASSETS,
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
    }, indent=2),
    encoding="utf-8",
)

print("\nEvidencia guardada en:", folder)
