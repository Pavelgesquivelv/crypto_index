"""Download and preserve a historical CoinMarketCap ranking."""

import argparse
import json
import os
from datetime import date
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, type=date.fromisoformat)
    args = parser.parse_args()

    day = args.date.isoformat()
    path = Path("runs/historical") / day / "cmc.json"

    if path.exists():
        result = json.loads(path.read_text(encoding="utf-8"))
        raw = None
        print("Usando captura existente:", path)
    else:
        key = os.environ.get("CMC_API_KEY")
        if not key:
            raise SystemExit("Carga CMC_API_KEY en esta terminal.")

        query = urlencode({
            "date": day,
            "start": 1,
            "limit": 100,
            "convert": "USD",
        })
        url = (
            "https://pro-api.coinmarketcap.com"
            "/v1/cryptocurrency/listings/historical?" + query
        )
        request = Request(url, headers={
            "X-CMC_PRO_API_KEY": key,
            "Accept": "application/json",
        })

        try:
            with urlopen(request, timeout=30) as response:
                raw = response.read()
        except HTTPError as error:
            print("HTTP:", error.code)
            print(error.read().decode("utf-8"))
            raise SystemExit(1)

        result = json.loads(raw)

    if str(result.get("status", {}).get("error_code", 0)) != "0":
        raise ValueError(str(result.get("status")))

    coins = result.get("data")
    if not isinstance(coins, list) or not coins:
        raise ValueError("Respuesta sin ranking válido.")

    if raw is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as file:
            file.write(raw)
        print("Guardado:", path)

    excluded_tags = {
        "stablecoin", "memes", "wrapped-tokens", "wrapped",
        "liquid-staking-tokens", "asset-backed-tokens",
        "tokenized-gold", "tokenized-stock",
    }

    print("\nRango | ID CMC | Activo | Etiquetas de exclusión")
    for coin in coins[:25]:
        reasons = sorted(
            excluded_tags.intersection(coin.get("tags", []))
        )
        print(
            coin["cmc_rank"], coin["id"], coin["symbol"],
            ", ".join(reasons) or "Revisar elegibilidad",
            sep=" | ",
        )


if __name__ == "__main__":
    main()
