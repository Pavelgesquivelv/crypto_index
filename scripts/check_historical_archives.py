import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe", type=Path, required=True)
    args = parser.parse_args()

    metadata = json.loads(
        (args.probe / "metadata.json").read_text(encoding="utf-8")
    )
    utc_date = datetime.fromisoformat(
        metadata["cutoff_utc"]
    ).astimezone(timezone.utc).date().isoformat()

    with (args.probe / "summary.csv").open(
        encoding="utf-8", newline=""
    ) as file:
        rows = list(csv.DictReader(file))

    pairs = list(dict.fromkeys(
        ["BTCUSDT"]
        + [
            row["pair"] for row in rows
            if row["status"] == "UNRESOLVED"
        ]
    ))
    results = []

    for pair in pairs:
        url = (
            "https://data.binance.vision/data/spot/daily/klines/"
            f"{pair}/1m/{pair}-1m-{utc_date}.zip"
        )
        result = {"pair": pair, "url": url}

        try:
            with urlopen(
                Request(url, method="HEAD"), timeout=30
            ) as response:
                result["http_status"] = response.status
        except HTTPError as error:
            result["http_status"] = error.code
        except (URLError, TimeoutError):
            result["http_status"] = None
            result["error"] = "Connection failed; inconclusive"

        result["checked_at_utc"] = (
            datetime.now(timezone.utc).isoformat()
        )
        results.append(result)
        print(pair, "| HTTP", result["http_status"])

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = args.probe / f"archive_checks_{stamp}.json"
    with path.open("x", encoding="utf-8") as file:
        json.dump(results, file, indent=2)

    print("Evidencia guardada:", path)


if __name__ == "__main__":
    main()
