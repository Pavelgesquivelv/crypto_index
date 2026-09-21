"""Theoretical portfolio valuation and equal-weight rebalancing."""

from decimal import Decimal, localcontext


ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")


def number(value):
    """Convert a value to a finite Decimal."""
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("Values must be finite")
    return result


def portfolio_value(quantities, prices, cash="0"):
    """Value unchanged holdings using prices from one valuation cutoff."""
    with localcontext() as context:
        context.prec = 40

        total = number(cash)
        if total < ZERO:
            raise ValueError("Cash cannot be negative")

        for asset, raw_quantity in quantities.items():
            if asset == "USDT":
                raise ValueError("Represent USDT through cash")

            quantity = number(raw_quantity)
            if quantity < ZERO:
                raise ValueError(f"Negative quantity: {asset}")
            if quantity == ZERO:
                continue
            if asset not in prices:
                raise ValueError(f"Missing price: {asset}")

            price = number(prices[asset])
            if price <= ZERO:
                raise ValueError(f"Price must be positive: {asset}")

            total += quantity * price

        return total


def index_level(value, initial_value="100", base_level="100"):
    """Convert portfolio value into an index level."""
    with localcontext() as context:
        context.prec = 40

        value = number(value)
        initial = number(initial_value)
        base = number(base_level)

        if value < ZERO or initial <= ZERO or base <= ZERO:
            raise ValueError("Invalid index inputs")

        return base * value / initial


def return_pct(current_value, previous_value):
    """Percentage return between two valuations without external flows."""
    with localcontext() as context:
        context.prec = 40

        current = number(current_value)
        previous = number(previous_value)

        if current < ZERO or previous <= ZERO:
            raise ValueError("Invalid return inputs")

        return (current / previous - ONE) * HUNDRED


def rebalance(value, selected_assets, prices):
    """
    Allocate 10% to each selected asset, with at most ten assets.

    Unfilled slots remain in USDT cash. Selection and historical
    availability must be validated before calling this function.
    No fees, slippage or exchange quantity rounding are modeled.
    """
    with localcontext() as context:
        context.prec = 40

        value = number(value)
        assets = list(selected_assets)

        if value <= ZERO:
            raise ValueError("Portfolio value must be positive")
        if len(assets) > 10:
            raise ValueError("At most ten assets can be selected")
        if len(set(assets)) != len(assets):
            raise ValueError("Duplicate selected assets")
        if "USDT" in assets:
            raise ValueError("USDT is reserved for cash")

        allocation = value / Decimal("10")
        quantities = {}

        for asset in assets:
            if asset not in prices:
                raise ValueError(f"Missing price: {asset}")

            price = number(prices[asset])
            if price <= ZERO:
                raise ValueError(f"Price must be positive: {asset}")

            quantities[asset] = allocation / price

        cash = allocation * Decimal(10 - len(assets))
        after = portfolio_value(quantities, prices, cash)
        tolerance = max(ONE, value) * Decimal("1e-30")

        if abs(after - value) > tolerance:
            raise ValueError("Rebalance failed value conservation")

        return {
            "quantities": quantities,
            "cash": cash,
            "value_before": value,
            "value_after": after,
        }
