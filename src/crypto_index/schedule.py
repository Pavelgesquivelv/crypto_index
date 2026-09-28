"""Monthly selection and rebalance dates, Monday-Friday without holiday exclusions."""
import calendar
from datetime import date, timedelta
from zoneinfo import ZoneInfo

ZONE = ZoneInfo('America/Mexico_City')


def month_end(day):
    return date(day.year, day.month, calendar.monthrange(day.year, day.month)[1])


def selection_day(cutoff):
    if cutoff != month_end(cutoff):
        raise ValueError('El rebalanceo debe ser el último día del mes.')
    candidate = cutoff - timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def selection_due(now):
    local = now.astimezone(ZONE)
    return (local.date() == selection_day(month_end(local.date()))
            and local.hour == 7 and local.minute < 15)
