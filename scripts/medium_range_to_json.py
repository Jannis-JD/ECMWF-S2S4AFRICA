#!/usr/bin/env python3
"""Publish medium-range NetCDF data as website JSON and figures."""
from __future__ import annotations
import argparse, json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import xarray as xr

VARS = {
 "temp": (("t2m","2t","2m_temperature"), "2 m Temperature", "°C"),
 "precip": (("tp","total_precipitation"), "Total Precipitation", "mm"),
 "mslp": (("msl","mean_sea_level_pressure"), "Mean Sea-Level Pressure", "hPa"),
 "u10": (("u10","10u"), "10 m U-Wind", "m/s"),
 "v10": (("v10","10v"), "10 m V-Wind", "m/s"),
}

def find_var(ds, names):
    return next((ds[n] for n in names if n in ds.data_vars), None)

def convert_units(name, values):
    values = np.asarray(values, dtype=float)
    if name == "temp" and np.nanmean(values) > 100: return values - 273.15
    if name == "precip" and np.nanmax(values) < 10: return values * 1000
    if name == "mslp" and np.nanmean(values) > 10000: return values / 100
    return values

def valid_dates(init, week):
    start = datetime.strptime(init, "%Y%m%d") + timedelta(days=(week - 1) * 7)
    return f"{start:%d %b} - {(start + timedelta(days=6)):%d %b %Y}"

def payload(name, init, week, values, lat, lon):
    return {"metadata": {"variable": name, "label": VARS[name][1], "unit": VARS[name][2],
        "init_date": init, "week": week, "week_label": f"Week {week}",
        "valid_dates": valid_dates(init, week), "forecast_type": "medium"},
        "grid": {"lat": [float(lat[0]), float(lat[-1]), float(abs(lat[1]-lat[0]))],
                 "lon": [float(lon[0]), float(lon[-1]), float(abs(lon[1]-lon[0]))],
                 "nlat": len(lat), "nlon": len(lon)},
        "values": np.where(np.isfinite(values), values, None).tolist()}

def weekly_values(da, variable):
    values = da.values
    if values.ndim < 3: raise ValueError(f"Expected time/lat/lon data, got {values.shape}")
    reducer = np.nansum if variable == "precip" else np.nanmean
    return [reducer(values[i:i+7], axis=0) for i in range(0, min(values.shape[0], 42), 7)]

def publish(date_str, source_dir, website_dir):
    init = date_str.replace("-", "")
    source = Path(source_dir) / date_str
    target = Path(website_dir) / "data" / "medium" / "weekly" / init
    figures = Path(website_dir) / "plots" / "medium" / date_str
    target.mkdir(parents=True, exist_ok=True); figures.mkdir(parents=True, exist_ok=True)
    datasets = [xr.open_dataset(source / n) for n in ("ECMWF_medium_inst.nc", "ECMWF_medium_accum.nc") if (source / n).exists()]
    if not datasets: raise FileNotFoundError(f"No medium-range NetCDF files found in {source}")
    catalog = {"last_updated": datetime.now(timezone.utc).isoformat(), "dates": [init], "data": {init: {}}, "type": "medium", "weeks": list(range(1,7))}
    try:
        for name, (names, label, unit) in VARS.items():
            da = next((find_var(ds, names) for ds in datasets if find_var(ds, names) is not None), None)
            if da is None: continue
            lat = np.asarray(da["latitude" if "latitude" in da.coords else "lat"].values)
            lon = np.asarray(da["longitude" if "longitude" in da.coords else "lon"].values)
            weeks = weekly_values(da, name); catalog["data"][init][name] = {"weeks": list(range(1, len(weeks)+1))}
            folder = target / name; folder.mkdir(exist_ok=True)
            for week, values in enumerate(weeks, 1):
                values = convert_units(name, values)
                (folder / f"{name}_{init}_w{week:02d}.json").write_text(json.dumps(payload(name, init, week, values, lat, lon), separators=(",", ":")))
                if week == 1:
                    plt.figure(figsize=(9,5)); plt.imshow(values, origin="upper", extent=[lon.min(),lon.max(),lat.min(),lat.max()]); plt.colorbar(label=unit); plt.title(f"ECMWF medium-range {label} — {date_str}"); plt.tight_layout(); plt.savefig(figures / f"{name}_week01.png", dpi=140); plt.close()
        (Path(website_dir) / "data" / "medium" / "weekly" / "catalog.json").write_text(json.dumps(catalog, indent=2) + "\n")
    finally:
        for ds in datasets: ds.close()



def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--source-dir", default="data")
    parser.add_argument("--website-dir", required=True)
    args = parser.parse_args()
    publish(args.date, args.source_dir, args.website_dir)


if __name__ == "__main__":
    main()
