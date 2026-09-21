"""Value a full month of unchanged theoretical holdings."""

import calendar
from datetime import date
from pathlib import Path

from crypto_index.calculation import (
    index_level,
    number,
    portfolio_value,
    return_pct,
)
from crypto_index.historical_prices import monthly_open_prices


def value_month(
    quantities,
    pairs,
    cash,
    archive_directory,
    year,
    month,
    previous_value,
    initial_value="100",
    base_level="100",
):
    """
    Value daily 07:00 CDMX cutoffs without applying any rebalance.

    Holdings must already be effective before the first cutoff.
    previous_value is the preceding daily valuation, not the index level.
    """
    if set(quantities) != set(pairs):
        raise ValueError("Holdings and pair mappings must match")
    if len(set(pairs.values())) != len(pairs):
        raise ValueError("Duplicate pair mappings")

    previous = number(previous_value)
    if previous <= 0:
        raise ValueError("Previous value must be positive")

    archive_directory = Path(archive_directory)
    prices_by_asset = {}

    for asset, pair in pairs.items():
        if (
            not isinstance(pair, str)
            or not pair.isascii()
            or not pair.isalnum()
            or not pair.endswith("USDT")
        ):
            raise ValueError(f"Invalid USDT pair: {asset}")

        path = archive_directory / (
            f"{pair}-1m-{year:04d}-{month:02d}.zip"
        )
        prices_by_asset[asset] = monthly_open_prices(
            path, year, month
        )

    results = []
    days = calendar.monthrange(year, month)[1]

    for day in range(1, days + 1):
        current_date = date(year, month, day).isoformat()
        prices = {
            asset: series[current_date]
            for asset, series in prices_by_asset.items()
        }

        value = portfolio_value(quantities, prices, cash)
        results.append({
            "date": current_date,
            "value_usdt": value,
            "index_level": index_level(
                value, initial_value, base_level
            ),
            "daily_return_pct": return_pct(value, previous),
            "cumulative_return_pct": return_pct(
                value, initial_value
            ),
        })
        previous = value

    return results
