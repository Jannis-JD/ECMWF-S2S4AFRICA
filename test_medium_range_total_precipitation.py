#!/usr/bin/env python3
"""Download a two-week ECMWF medium-range total-precipitation test product.

This deliberately uses the same ECMWF Open Data client and request path as
``download_medium_range.py``, but writes to a separate test directory and
requests only deterministic total precipitation (``tp``).

ECMWF Open Data is provided under the ECMWF Open Data Terms of Use and the
Creative Commons Attribution 4.0 International (CC BY 4.0) licence.
"""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

from ecmwf.opendata import Client

ECMWF_OPEN_DATA_URL = "https://data.ecmwf.int/forecasts/"
TEST_ROOT = Path("data/medium_range_test")
RESOLUTION = "0p1"
# Deterministic IFS total precipitation is cumulative at forecast-hour steps.
# Requesting 24, 48, ..., 336 hours covers two weeks; step ranges are used
# for ensemble probability products, not deterministic ``tp``.
TWO_WEEK_STEPS = [24 * i for i in range(1, 15)]


def get_current_date() -> str:
    """Return today's UTC date in the format accepted by ECMWF Open Data."""
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")


def download_total_precipitation(date_str: str, output_file: Path) -> Path:
    """Download 14 daily total-precipitation accumulations for one forecast."""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    temporary_file = output_file.with_suffix(output_file.suffix + ".part")
    temporary_file.unlink(missing_ok=True)

    client = Client(
        source="ecmwf",
        model="ifs",
        resol=RESOLUTION,
        maximum_retries=3,
        retry_after=(5, 60, 2),
    )
    client.retrieve(
        model="ifs",
        stream="oper",
        type="fc",
        param=["tp"],
        date=date_str,
        time=0,
        step=TWO_WEEK_STEPS,
        target=str(temporary_file),
    )
    temporary_file.replace(output_file)
    return output_file


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--date",
        default=get_current_date(),
        help="Forecast initialization date in YYYY-MM-DD format (default: today UTC).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional output path (default: data/medium_range_test/<date>/tp_2weeks.grib2).",
    )
    args = parser.parse_args()

    output_file = args.output or TEST_ROOT / args.date / "tp_2weeks.grib2"
    print("ECMWF Open Data medium-range test")
    print(f"Portal: {ECMWF_OPEN_DATA_URL}")
    print(f"Date: {args.date}")
    print("Variable: total precipitation (tp)")
    print(f"Forecast-hour steps: {len(TWO_WEEK_STEPS)} ({TWO_WEEK_STEPS[0]} to {TWO_WEEK_STEPS[-1]})")
    print(f"Output: {output_file}")

    try:
        result = download_total_precipitation(args.date, output_file)
    except Exception as exc:
        output_file.with_suffix(output_file.suffix + ".part").unlink(missing_ok=True)
        print(f"Download failed: {exc}")
        return 1

    size = result.stat().st_size
    if size == 0:
        print("Download failed: the output file is empty")
        return 1
    print(f"Download succeeded: {result} ({size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
