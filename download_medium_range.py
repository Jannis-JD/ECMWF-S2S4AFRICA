#!/usr/bin/env python3
"""Download ECMWF IFS medium-range open data from AWS."""

from __future__ import annotations

import datetime as dt
import os
import sys
from pathlib import Path

import xarray as xr
from ecmwf.opendata import Client

DATA_ROOT = Path("data")
RESOLUTION = "0p1"
INSTANTANEOUS_PARAMS = ["2t", "msl", "10u", "10v", "d2m"]
ACCUMULATED_PARAMS = ["tp", "tpg1", "tpg5", "10fg"]
PROBABILITY_PARAMS = ["tpg1", "tpg5", "10fgg10"]


def get_current_date():
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")


def ensure_data_dir(date_str):
    data_dir = DATA_ROOT / date_str
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def _client():
    return Client(
        source="aws",
        model="ifs",
        resol=RESOLUTION,
        maximum_retries=3,
        retry_after=(5, 60, 2),
    )


def _retrieve(request, output_file):
    if output_file.exists() and output_file.stat().st_size > 0:
        print(f"✅ Already exists: {output_file}")
        return True

    output_file.parent.mkdir(parents=True, exist_ok=True)
    temporary_file = output_file.with_suffix(output_file.suffix + ".part")
    temporary_file.unlink(missing_ok=True)
    try:
        _client().retrieve(target=str(temporary_file), **request)
        temporary_file.replace(output_file)
        print(f"✅ Downloaded: {output_file}")
        return True
    except Exception as exc:
        temporary_file.unlink(missing_ok=True)
        print(f"❌ Download failed for {output_file}: {exc}")
        return False


def download_instantaneous_variables(date_str):
    """Download deterministic instantaneous fields every three hours."""
    output_file = ensure_data_dir(date_str) / "ECMWF_medium_inst.grib2"
    return _retrieve({
        "model": "ifs", "stream": "oper", "type": "fc",
        "param": INSTANTANEOUS_PARAMS, "date": date_str, "time": 0,
        "step": list(range(0, 241, 3)),
    }, output_file)


def download_accumulated_variables(date_str):
    """Download deterministic 24-hour accumulations for the ten-day forecast."""
    output_file = ensure_data_dir(date_str) / "ECMWF_medium_accum.grib2"
    steps = [f"{24 * i}-{24 * (i + 1)}" for i in range(10)]
    return _retrieve({
        "model": "ifs", "stream": "oper", "type": "fc",
        "param": ACCUMULATED_PARAMS, "date": date_str, "time": 0,
        "step": steps,
    }, output_file)


def download_probability_variables(date_str):
    """Download ECMWF's documented 24-hour ensemble probabilities."""
    output_file = ensure_data_dir(date_str) / "ECMWF_medium_prob.grib2"
    steps = [f"{12 * i}-{12 * i + 24}" for i in range(29)]
    return _retrieve({
        "model": "ifs", "stream": "enfo", "type": "ep",
        "param": PROBABILITY_PARAMS, "date": date_str, "time": 0,
        "step": steps,
    }, output_file)


def _convert_grib(input_file):
    output_file = input_file.with_suffix(".nc")
    if output_file.exists() and output_file.stat().st_size > 0:
        print(f"✅ Already exists: {output_file}")
        return True
    try:
        with xr.open_dataset(input_file, engine="cfgrib") as dataset:
            dataset.to_netcdf(output_file)
        print(f"✅ Converted: {output_file}")
        return True
    except Exception as exc:
        output_file.unlink(missing_ok=True)
        print(f"❌ Conversion failed for {input_file}: {exc}")
        return False


def convert_to_netcdf(date_str):
    data_dir = ensure_data_dir(date_str)
    files = [data_dir / "ECMWF_medium_inst.grib2", data_dir / "ECMWF_medium_accum.grib2"]
    if not all(path.exists() and path.stat().st_size > 0 for path in files):
        print("⚠️ Required GRIB files are missing; skipping conversion")
        return False
    return all(_convert_grib(path) for path in files)


def main():
    date_str = os.environ.get("ECMWF_FORECAST_DATE", get_current_date())
    print("=" * 70)
    print("ECMWF IFS Medium-Range Download (AWS, 0.1 degree)")
    print("=" * 70)
    print(f"Date: {date_str}\n")
    ensure_data_dir(date_str)

    results = [
        download_instantaneous_variables(date_str),
        download_accumulated_variables(date_str),
        download_probability_variables(date_str),
    ]
    if all(results):
        results.append(convert_to_netcdf(date_str))

    if all(results):
        print(f"\n✅ Medium-range workflow completed for {date_str}")
        return 0
    print(f"\n❌ Medium-range workflow failed for {date_str}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
