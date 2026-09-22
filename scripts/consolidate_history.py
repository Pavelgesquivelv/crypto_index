import csv
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, localcontext
from pathlib import Path

ROOT = Path("runs/historical")
FILES = [
    "october/20260921T045153023704Z/daily_index.csv",
    "november/20260921T052336444672Z/daily_index.csv",
    "december/20260921T155538800531Z/daily_index.csv",
    "2026-01/20260921T160512752060Z/daily_index.csv",
    "2026-02/20260921T161854898700Z/daily_index.csv",
    "2026-03/20260921T162326105020Z/daily_index.csv",
    "2026-04/20260921T163021945667Z/daily_index.csv",
    "2026-05/20260921T163312128440Z/daily_index.csv",
    "2026-06/20260921T164437441028Z/daily_index.csv",
    "2026-07/20260921T235559341949Z/daily_index.csv",
    "2026-08/20260921T235837482461Z/daily_index.csv",
    "2026-09/20260922T000609573894Z/daily_index.csv",
]

START = date(2025, 9, 30)
END = date(2026, 9, 21)
TOLERANCE = Decimal("1e-12")


def decimal(value):
    result = Decimal(value)
    if not result.is_finite():
        raise ValueError("Valor numérico no finito")
    return result


def main():
    initial_path = ROOT / "initial_portfolio.json"
    initial = json.loads(initial_path.read_text(encoding="utf-8"))

    if datetime.fromisoformat(initial["start_local"]).date() != START:
        raise ValueError("Fecha inicial incorrecta")

    base = decimal(initial["base_level"])
    initial_value = decimal(initial["initial_value_usdt"])
    if base <= 0 or initial_value <= 0:
        raise ValueError("Base inicial inválida")

    rows_by_date = {}
    sources = [initial_path]

    for relative in FILES:
        path = ROOT / relative
        sources.append(path)

        with path.open(encoding="utf-8", newline="") as file:
            for row in csv.DictReader(file):
                if "date" in row:
                    day = date.fromisoformat(row["date"])
                else:
                    day = datetime.fromisoformat(
                        row["cutoff_local"]
                    ).date()

                if day in rows_by_date:
                    raise ValueError(f"Fecha duplicada: {day}")
                if not START < day <= END:
                    raise ValueError(f"Fecha fuera del período: {day}")

                rows_by_date[day] = row

    expected_dates = []
    day = START + timedelta(days=1)
    while day <= END:
        expected_dates.append(day)
        day += timedelta(days=1)

    missing = sorted(set(expected_dates) - set(rows_by_date))
    if missing:
        raise ValueError(f"Fechas faltantes: {missing}")

    combined = [{
        "date": START.isoformat(),
        "value_usdt": str(initial_value),
        "index_level": str(base),
        "daily_return_pct": "",
        "cumulative_return_pct": "0",
    }]

    with localcontext() as context:
        context.prec = 40
        previous_value = initial_value

        for day in expected_dates:
            row = rows_by_date[day]
            value = decimal(row["value_usdt"])
            if value <= 0:
                raise ValueError(f"Valor no positivo: {day}")

            calculated = {
                "index_level": base * value / initial_value,
                "daily_return_pct": (value / previous_value - 1) * 100,
                "cumulative_return_pct": (value / initial_value - 1) * 100,
            }

            for field, expected in calculated.items():
                observed = decimal(row[field])
                if abs(observed - expected) > TOLERANCE:
                    raise ValueError(
                        f"No concilia {field} en {day}: "
                        f"{observed} frente a {expected}"
                    )

            combined.append({
                "date": day.isoformat(),
                "value_usdt": str(value),
                **{
                    field: str(number)
                    for field, number in calculated.items()
                },
            })
            previous_value = value

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = ROOT / "consolidated" / stamp
    output.mkdir(parents=True, exist_ok=False)

    with (output / "daily_index.csv").open(
        "w", newline="", encoding="utf-8"
    ) as file:
        writer = csv.DictWriter(file, fieldnames=list(combined[0]))
        writer.writeheader()
        writer.writerows(combined)

    audit = {
        "status": "research_provisional",
        "start_date": START.isoformat(),
        "end_date": END.isoformat(),
        "observations_including_base": len(combined),
        "valuation_time": "07:00 America/Mexico_City",
        "fees_included": False,
        "checks": [
            "Unique dates",
            "Complete daily sequence",
            "Index levels reconcile with portfolio values",
            "Daily returns reconcile across month boundaries",
            "Cumulative returns reconcile with original base",
        ],
        "limitations": [
            "Historical exclusions remain provisional as documented "
            "in each rebalance portfolio.",
            "Consolidation validates numerical continuity, not historical "
            "eligibility or provider accuracy.",
        ],
        "source_sha256": {
            path.as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sources
        },
    }
    (output / "audit.json").write_text(
        json.dumps(audit, indent=2),
        encoding="utf-8",
    )

    print("PASS: fechas completas, sin duplicados.")
    print("PASS: niveles y rendimientos conciliados entre meses.")
    print("Observaciones, incluida base inicial:", len(combined))
    print("Período:", START, "a", END)
    print("Nivel final:", combined[-1]["index_level"])
    print("Resultados:", output)


if __name__ == "__main__":
    main()
