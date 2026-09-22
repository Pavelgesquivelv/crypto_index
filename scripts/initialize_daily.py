"""Prepare a local daily-calculation workspace from validated history."""

import csv
import hashlib
import io
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

root = Path("runs/historical")
history_path = (
    root / "consolidated/20260922T001420457997Z/daily_index.csv"
)
portfolio_path = root / "portfolio_2026-08-31.json"

history_raw = history_path.read_bytes()
portfolio_raw = portfolio_path.read_bytes()

rows = list(csv.DictReader(
    io.StringIO(history_raw.decode("utf-8-sig"))
))
portfolio = json.loads(portfolio_raw)

dates = [date.fromisoformat(row["date"]) for row in rows]
if not dates:
    raise ValueError("La serie está vacía.")
if any(
    current != previous + timedelta(days=1)
    for previous, current in zip(dates, dates[1:])
):
    raise ValueError("Fechas incompletas, duplicadas o desordenadas.")

if dates[-1] != date(2026, 9, 21):
    raise ValueError("El último corte no coincide con el validado.")
if portfolio["cutoff_utc"] != "2026-08-31T13:00:00+00:00":
    raise ValueError("La cartera no corresponde al rebalanceo esperado.")

destination = Path("runs/daily")
if destination.exists():
    raise FileExistsError(
        "runs/daily ya existe; no se sobrescribirá."
    )

manifest = {
    "schema_version": 1,
    "status": "initialized_not_scheduled",
    "created_utc": datetime.now(timezone.utc).isoformat(),
    "timezone": "America/Mexico_City",
    "valuation_time": "07:00",
    "price_reference": "Binance Spot 1-minute candle open",
    "last_seed_date": dates[-1].isoformat(),
    "seed_observations": len(rows),
    "seed_final_level": rows[-1]["index_level"],
    "history_file": "history_seed.csv",
    "portfolio_file": "portfolio_seed.json",
    "seed_sources": {
        "history": history_path.as_posix(),
        "portfolio": portfolio_path.as_posix(),
    },
    "sha256": {
        "history_seed.csv": hashlib.sha256(history_raw).hexdigest(),
        "portfolio_seed.json": hashlib.sha256(portfolio_raw).hexdigest(),
    },
    "policy": {
        "preserve_existing_observations": True,
        "require_completed_cutoff_minute": True,
        "missing_prices": "stop_without_inventing_values",
        "missing_rebalance": "stop_before_using_stale_holdings",
    },
}

destination.mkdir(parents=True, exist_ok=False)
(destination / "history_seed.csv").write_bytes(history_raw)
(destination / "portfolio_seed.json").write_bytes(portfolio_raw)
(destination / "observations").mkdir()

with (destination / "manifest.json").open(
    "x", encoding="utf-8"
) as file:
    json.dump(manifest, file, indent=2)

print("PASS: histórico y cartera copiados sin modificar los originales.")
print("Observaciones iniciales:", len(rows))
print("Último corte:", dates[-1])
print("Nivel inicial de continuidad:", rows[-1]["index_level"])
print("Directorio:", destination)
print("Todavía no se ha instalado ninguna tarea automática.")
