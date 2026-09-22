"""Validate a monthly portfolio transition against the closing valuation."""

import calendar
import hashlib
import json
from datetime import date, datetime
from decimal import Decimal, localcontext
from pathlib import Path
from zoneinfo import ZoneInfo

from crypto_index.calculation import index_level, portfolio_value

ZONE = ZoneInfo("America/Mexico_City")
TOLERANCE = Decimal("1e-18")


def number(value):
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("Se esperaba un número finito.")
    return result


def reconcile(actual, expected, label):
    if abs(number(actual) - number(expected)) > TOLERANCE:
        raise ValueError(f"No concilia: {label}.")


def cutoff_date(portfolio):
    cutoff = datetime.fromisoformat(portfolio["cutoff_utc"])
    if cutoff.tzinfo is None:
        raise ValueError("El corte necesita zona horaria.")

    local = cutoff.astimezone(ZONE)
    last_day = calendar.monthrange(local.year, local.month)[1]
    if (
        local.day != last_day
        or (local.hour, local.minute, local.second, local.microsecond)
        != (7, 0, 0, 0)
    ):
        raise ValueError("El corte debe ser fin de mes a las 07:00 CDMX.")
    return local.date()


def positions(portfolio):
    rows = portfolio["positions"]
    quantities = {}
    pairs = set()

    if len(rows) > 10:
        raise ValueError("La cartera supera diez posiciones.")

    for row in rows:
        asset = row["asset"]
        pair = row["pair"]
        quantity = number(row["quantity"])

        if (
            not isinstance(asset, str) or not asset
            or asset == "USDT" or asset in quantities
        ):
            raise ValueError("Activo inválido o duplicado.")
        if (
            not isinstance(pair, str)
            or not pair.isascii()
            or not pair.isalnum()
            or pair != pair.upper()
            or not pair.endswith("USDT")
            or pair in pairs
        ):
            raise ValueError("Par inválido o duplicado.")
        if quantity <= 0:
            raise ValueError("La cantidad debe ser positiva.")

        quantities[asset] = quantity
        pairs.add(pair)

    return quantities


def load_next_portfolio(directory, current, current_hash, closing_record):
    """Return the validated successor portfolio and its file hash.

    The closing observation belongs to the outgoing portfolio.
    The successor is used for daily valuations starting the following day.
    """
    with localcontext() as context:
        context.prec = 40

        closing_day = date.fromisoformat(closing_record["date"])
        current_day = cutoff_date(current)

        expected_year = current_day.year + (current_day.month == 12)
        expected_month = current_day.month % 12 + 1
        expected_day = date(
            expected_year,
            expected_month,
            calendar.monthrange(expected_year, expected_month)[1],
        )
        if closing_day != expected_day:
            raise ValueError("El cierre no corresponde al mes siguiente.")
        if closing_record["portfolio_sha256"] != current_hash:
            raise ValueError("El cierre pertenece a otra cartera.")

        old_quantities = positions(current)
        closing_prices = closing_record["prices_usdt"]
        closing_value = portfolio_value(
            old_quantities, closing_prices, current["cash_usdt"]
        )
        if closing_value <= 0:
            raise ValueError("El valor del cierre debe ser positivo.")

        reconcile(
            closing_record["value_usdt"], closing_value, "valor del cierre"
        )
        closing_level = index_level(
            closing_value,
            current["initial_value_usdt"],
            current["base_level"],
        )
        reconcile(
            closing_record["index_level"], closing_level, "nivel del cierre"
        )

        path = Path(directory) / f"portfolio_{closing_day.isoformat()}.json"
        if not path.is_file():
            raise FileNotFoundError(
                f"Falta la cartera del {closing_day}: {path}"
            )

        raw = path.read_bytes()
        successor = json.loads(raw)
        if cutoff_date(successor) != closing_day:
            raise ValueError("Fecha incorrecta en la nueva cartera.")

        for field in ("initial_value_usdt", "base_level"):
            reconcile(successor[field], current[field], field)

        new_quantities = positions(successor)
        new_prices = {}
        old_pairs = {
            row["asset"]: row["pair"] for row in current["positions"]
        }

        for row in successor["positions"]:
            asset = row["asset"]
            price = number(row["rebalance_price_usdt"])
            if price <= 0:
                raise ValueError("Precio de rebalanceo inválido.")

            if asset in old_pairs:
                if row["pair"] != old_pairs[asset]:
                    raise ValueError(
                        f"Cambio de par pendiente de revisión: {asset}."
                    )
                reconcile(price, closing_prices[asset], f"precio de {asset}")

            new_prices[asset] = price
            reconcile(
                new_quantities[asset] * price,
                closing_value / 10,
                f"asignación del 10% para {asset}",
            )

        expected_cash = closing_value * (10 - len(new_quantities)) / 10
        reconcile(successor["cash_usdt"], expected_cash, "efectivo")

        new_value = portfolio_value(
            new_quantities, new_prices, successor["cash_usdt"]
        )
        reconcile(new_value, closing_value, "conservación del valor")

        for field in ("value_before_usdt", "value_after_usdt"):
            reconcile(successor[field], closing_value, field)
        reconcile(successor["index_level"], closing_level, "nivel conservado")

        return successor, hashlib.sha256(raw).hexdigest()
