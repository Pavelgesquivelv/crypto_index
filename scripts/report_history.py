import argparse
import calendar
import csv
import hashlib
import json
import math
import statistics
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()

    raw = args.input.read_bytes()
    with args.input.open(encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))

    dates = [date.fromisoformat(row["date"]) for row in rows]
    levels = [float(row["index_level"]) for row in rows]

    if len(rows) < 3:
        raise ValueError("Se requieren al menos tres observaciones.")
    if any(not math.isfinite(value) or value <= 0 for value in levels):
        raise ValueError("Niveles inválidos.")
    if any(
        current != previous + timedelta(days=1)
        for previous, current in zip(dates, dates[1:])
    ):
        raise ValueError("Fechas desordenadas, duplicadas o incompletas.")

    returns = [
        current / previous - 1
        for previous, current in zip(levels, levels[1:])
    ]

    peak = levels[0]
    peak_index = 0
    max_drawdown = 0.0
    worst_peak = 0
    worst_trough = 0
    drawdowns = []

    for i, level in enumerate(levels):
        if level > peak:
            peak = level
            peak_index = i

        drawdown = level / peak - 1
        drawdowns.append(drawdown)

        if drawdown < max_drawdown:
            max_drawdown = drawdown
            worst_peak = peak_index
            worst_trough = i

    recovery = None
    if max_drawdown < 0:
        recovery = next(
            (
                dates[i].isoformat()
                for i in range(worst_trough + 1, len(levels))
                if levels[i] >= levels[worst_peak]
            ),
            None,
        )

    monthly = []
    previous_end = 0
    first_return_index = 1

    while first_return_index < len(rows):
        current_month = (
            dates[first_return_index].year,
            dates[first_return_index].month,
        )
        last_index = first_return_index

        while (
            last_index + 1 < len(rows)
            and (
                dates[last_index + 1].year,
                dates[last_index + 1].month,
            ) == current_month
        ):
            last_index += 1

        year, month = current_month
        month_start = date(year, month, 1)
        month_end = date(
            year, month, calendar.monthrange(year, month)[1]
        )
        complete = (
            dates[previous_end] == month_start - timedelta(days=1)
            and dates[last_index] == month_end
        )

        monthly.append({
            "month": f"{year:04d}-{month:02d}",
            "start_cutoff": dates[previous_end].isoformat(),
            "end_cutoff": dates[last_index].isoformat(),
            "return_pct": (
                levels[last_index] / levels[previous_end] - 1
            ) * 100,
            "coverage": "complete" if complete else "partial",
        })

        previous_end = last_index
        first_return_index = last_index + 1

    metrics = {
        "status": "research_provisional",
        "start_date": dates[0].isoformat(),
        "end_date": dates[-1].isoformat(),
        "observations": len(rows),
        "daily_returns": len(returns),
        "initial_level": levels[0],
        "final_level": levels[-1],
        "cumulative_return_pct": (levels[-1] / levels[0] - 1) * 100,
        "max_drawdown_pct": max_drawdown * 100,
        "drawdown_peak_date": (
            dates[worst_peak].isoformat() if max_drawdown < 0 else None
        ),
        "drawdown_trough_date": (
            dates[worst_trough].isoformat() if max_drawdown < 0 else None
        ),
        "drawdown_recovery_date": recovery,
        "annualized_volatility_pct": (
            statistics.stdev(returns) * math.sqrt(365) * 100
        ),
        "volatility_method": (
            "Sample standard deviation of simple daily returns "
            "multiplied by sqrt(365)"
        ),
        "valuation_time": "07:00 America/Mexico_City",
        "fees_included": False,
        "source": args.input.as_posix(),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "limitations": [
            "Theoretical gross reconstruction with documented "
            "provisional historical exclusions.",
            "Historical ranking timing and category limitations "
            "remain as documented in source audits.",
            "Drawdown is measured at daily cutoffs, not intraday.",
            "Annualized volatility is a scaling convention, "
            "not a return forecast.",
        ],
    }

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = Path("runs/reports") / stamp
    output.mkdir(parents=True, exist_ok=False)

    (output / "metrics.json").write_text(
        json.dumps(metrics, indent=2),
        encoding="utf-8",
    )

    with (output / "monthly_returns.csv").open(
        "w", newline="", encoding="utf-8"
    ) as file:
        writer = csv.DictWriter(file, fieldnames=list(monthly[0]))
        writer.writeheader()
        writer.writerows(monthly)

    fig, axes = plt.subplots(
        2, 1, figsize=(12, 7), sharex=True,
        gridspec_kw={"height_ratios": [2, 1]},
    )

    axes[0].plot(dates, levels, color="#176B87", linewidth=1.8)
    axes[0].axhline(
        levels[0], color="gray", linestyle="--", linewidth=0.8
    )
    axes[0].set_ylabel("Nivel del índice")
    axes[0].set_title(
        "Índice cripto equiponderado — histórico teórico bruto\n"
        f"{dates[0]} a {dates[-1]} | Base {levels[0]:g}"
    )

    drawdown_pct = [value * 100 for value in drawdowns]
    axes[1].fill_between(
        dates, drawdown_pct, 0, color="#B64040", alpha=0.65
    )
    axes[1].set_ylabel("Caída desde\nmáximo (%)")
    axes[1].set_xlabel("Fecha del corte diario — 07:00 CDMX")

    for axis in axes:
        axis.grid(alpha=0.2)

    fig.text(
        0.5, 0.015,
        "Reconstrucción provisional · Sin comisiones ni deslizamiento"
        " · No representa resultados de operaciones reales",
        ha="center", fontsize=9,
    )
    fig.autofmt_xdate()
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.savefig(output / "index_history.png", dpi=180)
    fig.savefig(output / "index_history.pdf")
    plt.close(fig)

    print(f"Observaciones: {len(rows)}")
    print(f"Nivel final: {levels[-1]:.8f}")
    print(
        f"Rendimiento acumulado: "
        f"{metrics['cumulative_return_pct']:.6f}%"
    )
    print(f"Máxima caída: {metrics['max_drawdown_pct']:.6f}%")
    print(
        f"Volatilidad anualizada: "
        f"{metrics['annualized_volatility_pct']:.6f}%"
    )
    print("Máximo previo:", metrics["drawdown_peak_date"])
    print("Mínimo posterior:", metrics["drawdown_trough_date"])
    print("Recuperación del máximo:", recovery or "No registrada")

    print("\nMes | Rendimiento | Cobertura")
    for row in monthly:
        print(
            row["month"],
            f'{row["return_pct"]:.4f}%',
            row["coverage"],
            sep=" | ",
        )

    print("\nResultados:", output)


if __name__ == "__main__":
    main()
