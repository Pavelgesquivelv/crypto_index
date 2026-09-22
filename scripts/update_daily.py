"""Append daily valuations without changing existing observations."""

import calendar
import csv
import hashlib
import io
import json
import os
from datetime import date, datetime, timedelta, timezone
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
from crypto_index.portfolio_transition import load_next_portfolio

ROOT = Path("runs/daily")
ZONE = ZoneInfo("America/Mexico_City")

def advance_portfolio(day, portfolio, portfolio_hash, closing_record):
    """Select the portfolio valid for a daily valuation."""
    cutoff = datetime.fromisoformat(
        portfolio["cutoff_utc"]
    ).astimezone(ZONE)
    first_day = cutoff.date() + timedelta(days=1)
    valid_until = date(
        first_day.year,
        first_day.month,
        calendar.monthrange(first_day.year, first_day.month)[1],
    )

    if day <= valid_until:
        return portfolio, portfolio_hash

    if day != valid_until + timedelta(days=1):
        raise ValueError("No se puede saltar una transición mensual.")
    if closing_record is None or closing_record["date"] != valid_until.isoformat():
        raise ValueError("Falta la valoración de cierre para cambiar de cartera.")

    return load_next_portfolio(
        ROOT / "portfolios",
        portfolio,
        portfolio_hash,
        closing_record,
    )

def main():
    manifest = json.loads(
        (ROOT / "manifest.json").read_text(encoding="utf-8")
    )

    # Verify that the original inputs have not changed.
    for filename, expected in manifest["sha256"].items():
        actual = hashlib.sha256((ROOT / filename).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"Archivo inicial modificado: {filename}")

    history = list(csv.DictReader(io.StringIO(
        (ROOT / manifest["history_file"]).read_text(encoding="utf-8-sig")
    )))
    portfolio = json.loads(
        (ROOT / manifest["portfolio_file"]).read_text(encoding="utf-8")
    )
    portfolio_hash = manifest["sha256"][manifest["portfolio_file"]]

    quantities = {
        p["asset"]: p["quantity"] for p in portfolio["positions"]
    }
    pairs = {p["asset"]: p["pair"] for p in portfolio["positions"]}
    if len(quantities) != len(portfolio["positions"]):
        raise ValueError("Posiciones duplicadas.")
    if len(set(pairs.values())) != len(pairs):
        raise ValueError("Pares duplicados.")

    previous_date = date.fromisoformat(history[-1]["date"])
    previous_value = Decimal(history[-1]["value_usdt"])

    # This first version supports the seed portfolio's next month.
    portfolio_cutoff = datetime.fromisoformat(
        portfolio["cutoff_utc"]
    ).astimezone(ZONE)
    first_day = portfolio_cutoff.date() + timedelta(days=1)
    if first_day.day != 1:
        raise ValueError("La cartera inicial no es de cierre mensual.")

    valid_until = date(
        first_day.year,
        first_day.month,
        calendar.monthrange(first_day.year, first_day.month)[1],
    )

    now = datetime.now(timezone.utc)
    local_now = now.astimezone(ZONE)
    latest = local_now.replace(hour=7, minute=0, second=0, microsecond=0)
    if now < (latest + timedelta(minutes=1)).astimezone(timezone.utc):
        latest -= timedelta(days=1)
    latest_date = latest.date()

    observations = ROOT / "observations"
    closing_record = None

    # Resume only from a complete, consistent sequence.
    for path in sorted(observations.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        recorded_date = date.fromisoformat(record["date"])

        if path.stem != record["date"]:
            raise ValueError("Nombre de observación incorrecto.")
        if recorded_date != previous_date + timedelta(days=1):
            raise ValueError("Secuencia diaria incompleta o duplicada.")
        if recorded_date > latest_date:
            raise ValueError("Observación fuera del período permitido.")

        portfolio, portfolio_hash = advance_portfolio(
            recorded_date, portfolio, portfolio_hash, closing_record
        )
        quantities = {
            p["asset"]: p["quantity"] for p in portfolio["positions"]
        }
        pairs = {p["asset"]: p["pair"] for p in portfolio["positions"]}
        if record["portfolio_sha256"] != portfolio_hash:
            raise ValueError("La observación usa otra cartera.")

        prices = {
            asset: Decimal(value)
            for asset, value in record["prices_usdt"].items()
        }
        value = portfolio_value(quantities, prices, portfolio["cash_usdt"])
        expected = {
            "value_usdt": value,
            "index_level": index_level(
                value, portfolio["initial_value_usdt"],
                portfolio["base_level"],
            ),
            "daily_return_pct": return_pct(value, previous_value),
            "cumulative_return_pct": return_pct(
                value, portfolio["initial_value_usdt"]
            ),
        }
        for field, calculated in expected.items():
            if abs(calculated - Decimal(record[field])) > Decimal("1e-18"):
                raise ValueError(f"Observación inconsistente: {path}, {field}")

        previous_date = recorded_date
        previous_value = value
        closing_record = record

    target = latest_date
    created = 0

    while previous_date < target:
        day = previous_date + timedelta(days=1)
        portfolio, portfolio_hash = advance_portfolio(
            day, portfolio, portfolio_hash, closing_record
        )
        quantities = {
            p["asset"]: p["quantity"] for p in portfolio["positions"]
        }
        pairs = {p["asset"]: p["pair"] for p in portfolio["positions"]}
        cutoff = datetime(day.year, day.month, day.day, 7, tzinfo=ZONE)
        start_ms = int(cutoff.timestamp() * 1000)
        prices = {}
        evidence = []

        for asset, pair in pairs.items():
            query = urlencode({
                "symbol": pair,
                "interval": "1m",
                "startTime": start_ms,
                "endTime": start_ms + 59_999,
                "limit": 1,
            })
            url = "https://api.binance.com/api/v3/klines?" + query
            raw = download_bytes(url)
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

            prices[asset] = price
            evidence.append({
                "pair": pair,
                "url": url,
                "response_text": raw.decode("utf-8"),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "retrieved_utc": datetime.now(timezone.utc).isoformat(),
            })

        value = portfolio_value(quantities, prices, portfolio["cash_usdt"])
        level = index_level(
            value, portfolio["initial_value_usdt"], portfolio["base_level"]
        )
        record = {
            "status": "research_provisional",
            "date": day.isoformat(),
            "cutoff_local": cutoff.isoformat(),
            "value_usdt": str(value),
            "index_level": str(level),
            "daily_return_pct": str(return_pct(value, previous_value)),
            "cumulative_return_pct": str(
                return_pct(value, portfolio["initial_value_usdt"])
            ),
            "portfolio_sha256": portfolio_hash,
            "prices_usdt": {a: str(p) for a, p in prices.items()},
            "rebalance_applied": False,
            "fees_included": False,
            "sources": evidence,
        }

        destination = observations / f"{day.isoformat()}.json"
        if destination.exists():
            raise FileExistsError(f"No se sobrescribirá: {destination}")

        temporary = observations / f"{day.isoformat()}.tmp"
        temporary.write_text(
            json.dumps(record, indent=2), encoding="utf-8"
        )
        temporary.replace(destination)

        print(f"{day} | nivel {level:.8f}", flush=True)
        previous_date = day
        previous_value = value
        created += 1
        closing_record = record

    print("Observaciones nuevas:", created)
    print("Último corte registrado:", previous_date)

    print("PASS: serie al día hasta la última vela de corte completada.")


if __name__ == "__main__":
    lock = ROOT / "update.lock"
    try:
        with lock.open("x", encoding="utf-8") as file:
            file.write(str(os.getpid()))
    except FileExistsError:
        raise SystemExit(
            "Existe un bloqueo. Comprueba que no haya otra ejecución activa."
        )

    try:
        main()
    finally:
        lock.unlink(missing_ok=True)
