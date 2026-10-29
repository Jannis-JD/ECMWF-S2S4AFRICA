#!/usr/bin/env python3
"""Download deterministic IFS medium-range products for the S2S Africa domain.

This downloader is intentionally parallel to ``download_s2s.py``.  It uses
ECMWF Open Data's operational stream only (``stream=oper``, ``type=fc``),
never the ensemble/probability stream.  Requests are split by field group
because ECMWF fields have different valid forecast-step frequencies and
levels.
"""

from __future__ import annotations

import datetime as dt
import os
import sys
from pathlib import Path

from ecmwf.opendata import Client

DATA_ROOT = Path("data")
RESOLUTION = "0p1"
# Same N/W/S/E box as .github/workflows/daily_download2.0.yml.
AFRICA_AREA = [22.5, -21.0, -34.5, 55.5]

# Product names and parameters mirror the S2S downloader's complete product
# set.  Products using another S2S auxiliary domain are retained as separate
# requests, with the same domain definitions used by download_s2s.py.
PRODUCTS = {
    "surface": {
        "param": ["2t", "d2m", "cape", "tcw", "10u", "10v", "tp"],
        "step": list(range(0, 361, 24)),
        "area": AFRICA_AREA,
    },
    "temperature_minmax": {
        "param": ["mx2t6", "mn2t6"],
        "step": list(range(6, 361, 12)),
        "area": AFRICA_AREA,
    },
    "wind_700": {
        "param": ["u", "v"],
        "levelist": [700],
        "step": list(range(0, 361, 24)),
        "area": AFRICA_AREA,
    },
    "vertical_velocity_500": {
        "param": ["w"],
        "levelist": [500],
        "step": list(range(0, 361, 24)),
        "area": AFRICA_AREA,
    },
    "humidity_wind_pressure": {
        "param": ["q", "u"],
        "levelist": [1000, 925, 850, 700, 500, 300],
        "step": list(range(0, 361, 24)),
        "area": AFRICA_AREA,
    },
    "sst": {
        "param": ["sst"],
        "step": list(range(0, 361, 24)),
        "area": [20.0, 45.0, -20.0, 120.0],
    },
    "sst_nino34": {
        "param": ["sst"],
        "step": list(range(0, 361, 24)),
        "area": [5.0, -180.0, -5.0, 179.5],
    },
    "wind_10m_aux": {
        "param": ["10u", "10v"],
        "step": list(range(0, 361, 24)),
        "area": [20.0, 45.0, -20.0, 120.0],
    },
    "precip_aux": {
        "param": ["tp"],
        "step": list(range(0, 361, 24)),
        "area": [20.0, 30.0, -20.0, 120.0],
    },
    "tcw_indian_ocean": {
        "param": ["tcw"],
        "step": list(range(0, 361, 24)),
        "area": [20.0, -30.0, -20.0, 120.0],
    },
    "humidity_wind_indian_ocean": {
        "param": ["q", "u"],
        "levelist": [1000, 925, 850, 700, 500, 300],
        "step": list(range(0, 361, 24)),
        "area": [20.0, -30.0, -20.0, 120.0],
    },
}


def get_current_date() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")


def _client() -> Client:
    return Client(
        source="ecmwf",
        model="ifs",
        resol=RESOLUTION,
        maximum_retries=3,
        retry_after=(5, 60, 2),
    )


def _request(date_str: str, product: dict) -> dict:
    """Build one deterministic Open Data request."""
    request = {
        "model": "ifs",
        "stream": "oper",
        "type": "fc",
        "date": date_str,
        "time": 0,
        "param": product["param"],
        "step": product["step"],
        "area": product["area"],
    }
    if "levelist" in product:
        request["levelist"] = product["levelist"]
    return request


def download_product(date_str: str, name: str, product: dict) -> bool:
    output = DATA_ROOT / date_str / f"ECMWF_medium_{name}.grib2"
    if output.exists() and output.stat().st_size > 0:
        print(f"Already exists: {output}")
        return True

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".part")
    temporary.unlink(missing_ok=True)
    try:
        _client().retrieve(target=str(temporary), **_request(date_str, product))
        temporary.replace(output)
        print(f"Downloaded: {output}")
        return True
    except Exception as exc:
        temporary.unlink(missing_ok=True)
        print(f"Download failed for {name}: {exc}")
        return False


def main() -> int:
    date_str = os.environ.get("ECMWF_FORECAST_DATE", get_current_date())
    print(f"Downloading deterministic IFS medium-range data for {date_str}")
    results = [download_product(date_str, name, product) for name, product in PRODUCTS.items()]
    if all(results):
        print("Medium-range download completed")
        return 0
    print("Medium-range download failed")
    return 1


if __name__ == "__main__":
    sys.exit(main())
