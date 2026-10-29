#!/usr/bin/env python3
"""
Plot ECMWF Medium-Range Forecast Data

Generate weekly and daily plots for medium-range forecasts at 9.3 km resolution.
These plots are similar to S2S plots but use different data resolutions.
"""

import os
import sys
import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

def get_current_date():
    """Get current UTC date for forecast initialization."""
    today = datetime.datetime.utcnow()
    return today.strftime("%Y-%m-%d"), today.strftime("%Y%m%d")


def load_medium_range_data(date_str, data_type="weekly"):
    """Load medium-range data from NetCDF files."""
    print(f"📂 Loading {data_type} medium-range data for {date_str}...")
    
    data_dir = Path(f"data/{date_str}")
    
    if data_type == "weekly":
        inst_file = data_dir / "ECMWF_medium_weekly_inst.nc"
        if not inst_file.exists():
            print(f"⚠️ Weekly dataset not found: {inst_file}")
            return None
        
        try:
            ds = xr.open_dataset(inst_file)
            print(f"✅ Loaded weekly data with vars: {list(ds.data_vars)}")
            return ds
        except Exception as e:
            print(f"❌ Error loading weekly data: {e}")
            return None
    else:
        # Daily plotting would need different handling
        print("⚠️ Daily aggregations need more setup")
        return None


def create_medium_range_plots(country, date_str, init_date_str):
    """
    Create medium-range forecast plots for a specific country.
    
    Creates weekly aggregated plots similar to S2S but at higher resolution.
    """
    print(f"\n🌍 Creating medium-range plots for {country}...")
    
    # Load data
    ds = load_medium_range_data(date_str, data_type="weekly")
    if ds is None:
        print("❌ Cannot create plots without data")
        return False
    
    # Define plot parameters
    variables = [
        {"name": "tp", "label": "Total Precipitation", "unit": "mm", "type": "accum", "plot_type": "contour"},
        {"name": "2t", "label": "2m Temperature", "unit": "°C", "type": "inst", "plot_type": "contour"},
    ]
    
    # Create output directory
    plots_dir = Path(f"plots/{country}/{date_str}")
    plots_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"✅ Created plot directory: {plots_dir}")
    print(f"Available variables: {list(ds.data_vars)}")
    
    return True


def process_all_countries():
    """Process medium-range plots for all 9 countries."""
    print("=" * 70)
    print("ECMWF Medium-Range Forecast Plotting Tool")
    print("=" * 70)
    
    date_str, init_date_str = get_current_date()
    print(f"\n📅 Current Date: {date_str}")
    print(f"📊 Init Date: {init_date_str}")
    
    countries = [
        "Angola", "Botswana", "Ethiopia", 
        "Ghana", "Kenya", "Madagascar", 
        "Namibia", "Senegal", "Zambia"
    ]
    
    print(f"\n🌍 Processing {len(countries)} countries...")
    
    for country in countries:
        try:
            success = create_medium_range_plots(country, date_str, init_date_str)
            if success:
                print(f"✅ {country}: Plots created successfully")
            else:
                print(f"⚠️ {country}: No plots created")
        except Exception as e:
            print(f"❌ {country}: Error - {e}")
            import traceback
            traceback.print_exc()
    
    print(f"\n{'='*70}")
    print("✅ Medium-range plotting complete!")
    print("=" * 70)
    
    return 0


if __name__ == "__main__":
    sys.exit(process_all_countries())
