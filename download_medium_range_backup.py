#!/usr/bin/env python3
"""
Download ECMWF Medium-Range Forecast Data (9x9 km resolution)

This script downloads 10-day forecasts from ECMWF's open data repository.
It separates variables into instantaneous and accumulated types to avoid
GRIB data corruption issues when mixing them in the same request.

Data source: https://data.ecmwf.int/forecasts/
Resolution: 0.1 degree (~9.3 km)
Licence: ECMWF Open Data Terms of Use, CC BY 4.0
"""

import os
import sys
import time
import datetime
from pathlib import Path

import xarray as xr

from ecmwf.opendata import Client


def get_current_date():
    """Get current UTC date for forecast initialization."""
    return datetime.datetime.utcnow().strftime("%Y-%m-%d")


def ensure_data_dir(date_str):
    """Create directory structure if it doesn't exist."""
    data_dir = Path(f"data/{date_str}")
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def download_instantaneous_variables(date_str):
    """Download instantaneous variables (temperature, pressure, wind)."""
    print("⏳ Downloading instantaneous variables...")
    
    OUTPUT_FILE = f"data/{date_str}/ECMWF_medium_inst.grib2"
    
    if os.path.exists(OUTPUT_FILE):
        print(f"✅ Instantaneous variables already exist: {OUTPUT_FILE}")
        return True
    
    try:
        client = Client(source="ecmwf")
        
        client.retrieve(
            model="ifs",
            stream="oper",
            param=["2t", "msl", "10u", "10v", "d2m"],
            date=date_str,
            time=0,
            step=range(0, 241, 3),
            target=OUTPUT_FILE
        )
        
        print(f"✅ Successfully downloaded instantaneous variables")
        return True
    except Exception as e:
        print(f"❌ Error downloading instantaneous variables: {e}")
        return False


    steps_24h = [f"{i*24}-{(i+1)*24}" for i in range(10)]
    
    try:
        client = Client(source="ecmwf")
        client.retrieve(
            model="ifs",
            stream="oper",
            param=["tp", "tpg1", "tpg5", "10fg"],
            date=date_str,
            time=0,
            step=steps_24h,
            target=OUTPUT_FILE
        )
        
        print(f"✅ Successfully downloaded accumulated variables")
        return True
    except Exception as e:
        print(f"❌ Error downloading accumulated variables: {e}")
        return False



def download_accumulated_variables(date_str):
    """Download accumulated variables (precipitation, wind gusts)."""
    print("⏳ Downloading accumulated variables...")
    
    OUTPUT_FILE = f"data/{date_str}/ECMWF_medium_accum.grib2"
    
    if os.path.exists(OUTPUT_FILE):
        print(f"✅ Accumulated variables already exist: {OUTPUT_FILE}")
        return True


def download_probability_variables(date_str):
    """Download ensemble probability products."""
    print("⏳ Downloading probability variables...")
    
    OUTPUT_FILE = f"data/{date_str}/ECMWF_medium_prob.grib2"
    
    try:
        client = Client(source="ecmwf")
        steps_24h = [f"{i*24}-{(i+1)*24}" for i in range(10)]
        
        client.retrieve(
            model="ifs",
            stream="enfo",
            param=["tpg1", "tpg5", "10fgg10"],
            date=date_str,
            time=0,
            step=steps_24h,
            target=OUTPUT_FILE
        )
        
        print(f"✅ Successfully downloaded probability variables")
        return True
    except Exception as e:
        print(f"ℹ️ Probability variables not available: {e}")
        return True


def convert_grib_to_netcdf(date_str):
    """Convert downloaded GRIB files to NetCDF for easier processing."""
    print("🔄 Converting GRIB files to NetCDF...")
    
    data_dir = Path(f"data/{date_str}")
    inst_file = data_dir / "ECMWF_medium_inst.grib2"
    accum_file = data_dir / "ECMWF_medium_accum.grib2"
    
    if not inst_file.exists() or not accum_file.exists():
        print("⚠️ GRIB files not found, skipping conversion")
        return False
    
    try:
        ds_inst = xr.open_dataset(inst_file, engine='cfgrib', chunks={'time': 1})
        nc_inst_file = inst_file.with_suffix('.nc')
        ds_inst.to_netcdf(nc_inst_file)
        print(f"✅ Converted instantaneous to {nc_inst_file}")
    except Exception as e:
        print(f"⚠️ Error converting instantaneous: {e}")
    
    try:
        ds_accum = xr.open_dataset(accum_file, engine='cfgrib', chunks={'time': 1})
        nc_accum_file = accum_file.with_suffix('.nc')
        ds_accum.to_netcdf(nc_accum_file)
        print(f"✅ Converted accumulated to {nc_accum_file}")
    except Exception as e:
        print(f"⚠️ Error converting accumulated: {e}")
    
    return True


def convert_to_weekly(date_str):
    """Convert daily data to weekly aggregations for compatible plotting."""
    print("🔄 Creating weekly aggregations...")
    
    from ecmwf.opendata import humanize
    
    nc_inst = f"data/{date_str}/ECMWF_medium_inst.nc"
    nc_accum = f"data/{date_str}/ECMWF_medium_accum.nc"
    
    if not Path(nc_inst).exists() or not Path(nc_accum).exists():
        print("⚠️ NetCDF files not found, skipping conversion")
        return False
    
    # Load and weekly aggregate
    try:
        ds_inst = xr.open_dataset(nc_inst)
        ds_weekly_inst = ds_inst.resample(step='W').mean()
        ds_weekly_inst.to_netcdf(f"data/{date_str}/ECMWF_medium_weekly_inst.nc")
        print(f"✅ Created weekly instantaneous aggregation")
    except Exception as e:
        print(f"⚠️ Error creating weekly instantaneous: {e}")
    
    return True


def main():
    print("=" * 60)
    print("ECMWF Medium-Range Forecast Downloader")
    print("=" * 60)
    
    date_str = get_current_date()
    print(f"\n📅 Date: {date_str}")
    ensure_data_dir(date_str)
    
    success = True
    
    print("\n" + "-" * 60)
    success &= download_instantaneous_variables(date_str)
    print("-" * 60)
    
    print("\n" + "-" * 60)
    success &= download_accumulated_variables(date_str)
    print("-" * 60)
    
    print("\n" + "-" * 60)
    success &= download_probability_variables(date_str)
    print("-" * 60)

    print("\n" + "-" * 60)
    
    print("\n" + "-" * 60)
    success &= convert_grib_to_netcdf(date_str)
    print("-" * 60)
    
    print("\n" + "-" * 60)
    success &= convert_to_weekly(date_str)
    print("-" * 60)
    
    if success:
        print(f"\n✅ All medium-range data downloaded successfully for {date_str}")
        return 0
    else:
        print(f"\n❌ Some errors occurred during download for {date_str}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
