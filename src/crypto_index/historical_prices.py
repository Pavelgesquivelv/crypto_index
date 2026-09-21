"""Read verified Binance Spot monthly archives at daily CDMX cutoffs."""

import calendar
import csv
import hashlib
import io
import re
import zipfile
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo


def monthly_open_prices(archive_path, year, month):
    """
    Return {ISO date: Decimal price} at 07:00 America/Mexico_City.

    Requires the archive's adjacent .CHECKSUM file.
    Missing, duplicate or non-traded cutoff candles raise ValueError.
    """
    archive_path = Path(archive_path)
    checksum_path = archive_path.with_name(
        archive_path.name + ".CHECKSUM"
    )

    expected_suffix = f"-1m-{year:04d}-{month:02d}.zip"
    if not archive_path.name.endswith(expected_suffix):
        raise ValueError("Archive filename does not match requested month")

    days = calendar.monthrange(year, month)[1]
    targets = {}

    for day in range(1, days + 1):
        cutoff = datetime(
            year, month, day, 7,
            tzinfo=ZoneInfo("America/Mexico_City"),
        )
        targets[int(cutoff.timestamp() * 1000)] = (
            cutoff.date().isoformat()
        )

    checksum_parts = checksum_path.read_text(
        encoding="utf-8"
    ).split()

    if not checksum_parts:
        raise ValueError("Empty checksum file")

    expected_hash = checksum_parts[0].lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        raise ValueError("Malformed SHA-256 checksum")

    raw = archive_path.read_bytes()
    actual_hash = hashlib.sha256(raw).hexdigest()

    if actual_hash != expected_hash:
        raise ValueError("Archive checksum mismatch")

    prices = {}

    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        csv_names = [
            name for name in archive.namelist()
            if name.endswith(".csv")
        ]
        if len(csv_names) != 1:
            raise ValueError("Expected exactly one CSV in archive")

        with archive.open(csv_names[0]) as stream:
            reader = csv.reader(
                io.TextIOWrapper(stream, encoding="utf-8-sig")
            )

            for row in reader:
                if not row:
                    continue
                if row[0].lower() in ("open_time", "open time"):
                    continue

                stamp = int(row[0])

                # Binance archives may use milliseconds or microseconds.
                if stamp >= 100_000_000_000_000:
                    if stamp % 1000:
                        raise ValueError("Unsupported timestamp precision")
                    stamp //= 1000

                if stamp not in targets:
                    continue
                if len(row) < 9:
                    raise ValueError("Incomplete cutoff candle")

                date = targets[stamp]
                if date in prices:
                    raise ValueError(f"Duplicate cutoff: {date}")

                price = Decimal(row[1])
                volume = Decimal(row[5])
                trades = int(row[8])

                if (
                    not price.is_finite() or price <= 0
                    or not volume.is_finite() or volume <= 0
                    or trades <= 0
                ):
                    raise ValueError(f"Invalid cutoff candle: {date}")

                prices[date] = price

    missing = sorted(set(targets.values()) - set(prices))
    if missing:
        raise ValueError(f"Missing daily cutoffs: {', '.join(missing)}")

    return dict(sorted(prices.items()))
