"""Download and verify Binance Spot monthly 1-minute archives."""

import calendar
import hashlib
import re
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


BASE_URL = "https://data.binance.vision/data/spot/monthly/klines"


def download_bytes(url):
    for attempt in range(3):
        try:
            with urlopen(url, timeout=60) as response:
                return response.read()
        except HTTPError as error:
            if error.code == 404:
                raise FileNotFoundError(
                    "Archive resource not found; historical trading "
                    "availability remains unresolved"
                ) from None
            if error.code not in (429, 500, 502, 503, 504):
                raise
            if attempt == 2:
                raise
        except (URLError, TimeoutError):
            if attempt == 2:
                raise

        time.sleep(2 ** attempt)


def verify_checksum(raw, checksum):
    parts = checksum.decode("utf-8").split()
    if not parts or not re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
        raise ValueError("Malformed SHA-256 checksum")

    actual = hashlib.sha256(raw).hexdigest()
    if actual != parts[0].lower():
        raise ValueError("Archive checksum mismatch")
    return actual


def ensure_monthly_archive(pair, year, month, directory):
    """
    Return a verified local archive path.

    Reuse a valid archive/checksum pair without network requests.
    Reject a damaged cache rather than silently overwriting it.
    A missing remote archive is not proof of historical ineligibility.
    """
    if (
        not isinstance(pair, str)
        or not re.fullmatch(r"[A-Z0-9]+USDT", pair)
    ):
        raise ValueError("Expected an uppercase USDT pair")

    calendar.monthrange(year, month)

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)

    filename = f"{pair}-1m-{year:04d}-{month:02d}.zip"
    archive_path = directory / filename
    checksum_path = directory / (filename + ".CHECKSUM")

    if archive_path.exists() != checksum_path.exists():
        raise ValueError(
            "Incomplete cache: preserve or move the existing file "
            "before retrying"
        )

    if archive_path.exists():
        verify_checksum(
            archive_path.read_bytes(),
            checksum_path.read_bytes(),
        )
        return archive_path

    url = f"{BASE_URL}/{pair}/1m/{filename}"
    checksum = download_bytes(url + ".CHECKSUM")
    raw = download_bytes(url)
    verify_checksum(raw, checksum)

    # Exclusive creation prevents overwriting existing evidence.
    # Interrupted writes will be rejected on the next invocation.
    with archive_path.open("xb") as file:
        file.write(raw)
    with checksum_path.open("xb") as file:
        file.write(checksum)

    return archive_path
