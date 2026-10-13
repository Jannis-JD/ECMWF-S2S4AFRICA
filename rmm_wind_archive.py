"""
Builds, and keeps extending, a daily ERA5 archive of the 850 and 200 hPa zonal
wind averaged over 15S-15N: the observed winds the RMM index (Wheeler and
Hendon 2004, see mjo_rmm_index.py) needs next to the OLR of olr_obs_archive.py,
for its EOFs / climatology / reforecast bias and as the lead-in in front of
each forecast.

Two public, credential-free sources, picked per day:

  * up to 2023-01-10: WeatherBench2's daily ERA5 on the 1.5 degree grid,
    u_component_of_wind. 2006-2022 takes ~15 minutes.
  * after that: ARCO-ERA5's raw files, one per day and level of hourly 0.25
    degree analyses (gs://gcp-public-data-arco-era5/raw/date-variable-pressure_level/),
    which run up to ~5 days behind real time (ERA5T). ~90 MB a day for the
    two levels, so only the lead-in period and the daily top-up should
    come from here. (The ARCO zarr store olr_obs_archive.py reads keeps all 37
    levels of an hour in one 100 MB chunk, four times the download for a
    quarter of the hours.)

    python rmm_wind_archive.py --start 2006-01-01 --end 2023-01-10   # EOF / climatology period (WeatherBench2)
    python rmm_wind_archive.py --start 2026-05-01                    # lead-in period (ARCO)
    python rmm_wind_archive.py                                       # daily: extend to the latest ERA5T day

The years between the two periods are not needed and can stay empty.
mjo_rmm_index.py needs the LEADIN_DAYS (see download_rmm_winds.py) before
each forecast.

Writes one file per year, <OLR_OBS_DIR>/era5_u_15S15N_<YYYY>.nc (default
olr_obs/), holding `u850` and `u200` (time, longitude) in m s-1 on the S2S
longitudes (-180..178.5), plus a `source` (time) coordinate. The latitude mean
is the plain mean of the 21 rows 15N..15S of the 1.5 degree grid, as in WH04.
Days already in the archive are skipped.
"""

import argparse
import os
import shutil
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from urllib.error import HTTPError
from urllib.request import urlopen

import numpy as np
import xarray as xr

from olr_obs_archive import LONS, OUT_DIR, WB2, WB2_LAST_DAY, _OFFSETS, _WEIGHTS, _gcs_exists, _gcs_url, runs

LEVELS = (850, 200)
LAT_MAX = 15
WB2_VAR = ARCO_VAR = "u_component_of_wind"
ARCO_RAW = "gcp-public-data-arco-era5/raw/date-variable-pressure_level"

# ARCO rows (0.25 degree, 90N first) under the 1.5 degree cells centred on
# 15N..15S: summing each cell's 7-point box (edge points half weight) over the
# 21 cells is a trapezoid over 15.75N..15.75S
_ROWS = slice(int((90 - LAT_MAX) / 0.25) - 3, int((90 + LAT_MAX) / 0.25) + 4)
_ROW_W = np.ones(_ROWS.stop - _ROWS.start)
_ROW_W[[0, -1]] = 0.5
_ROW_W /= _ROW_W.sum()


# ============================================================
# WeatherBench2 (daily, 1.5 degree, up to 2023-01-10)
# ============================================================

def fetch_wb2(days):
    """Daily-mean 15S-15N winds, shape (len(days), len(LEVELS), 240), for consecutive days."""
    ds = xr.open_zarr(f"gs://{WB2}", storage_options={"token": "anon"}, chunks=None)
    da = ds[WB2_VAR].sel(time=slice(str(days[0]), str(days[-1])), level=list(LEVELS))
    if da.sizes["time"] != len(days):
        raise RuntimeError(f"WeatherBench2 has {da.sizes['time']} of the {len(days)} days {days[0]} .. {days[-1]}")
    da = da.sel(latitude=slice(-LAT_MAX - 0.1, LAT_MAX + 0.1))
    assert da.sizes["latitude"] == 2 * LAT_MAX / 1.5 + 1
    da = da.load().mean("latitude")
    da = da.assign_coords(longitude=((da.longitude + 180) % 360) - 180).sortby("longitude")
    np.testing.assert_allclose(da.longitude, LONS)
    return da.transpose("time", "level", "longitude").values.astype(np.float32)


# ============================================================
# ARCO-ERA5 raw files (hourly, 0.25 degree, up to ~5 days ago)
# ============================================================

def raw_url(day, level):
    return _gcs_url(f"{ARCO_RAW}/{day:%Y/%m/%d}/{ARCO_VAR}/{level}.nc")


def download(url, out, attempts=4):
    for attempt in range(1, attempts + 1):
        try:
            with urlopen(url, timeout=120) as r, open(out, "wb") as f:
                shutil.copyfileobj(r, f)
            return
        except HTTPError:
            raise
        except OSError as e:                    # stalled or dropped connection
            if attempt == attempts:
                raise
            print(f"  retrying {url.rsplit('/', 4)[1:]} ({e})", flush=True)


def fetch_arco(day):
    """Daily-mean 15S-15N winds on the S2S longitudes, shape (len(LEVELS), 240),
    from the day's 24 hourly analyses (00..23 UTC, as WeatherBench2)."""
    out = []
    for level in LEVELS:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "u.nc")
            download(raw_url(day, level), path)
            with xr.open_dataset(path) as ds:
                u = ds["u"].squeeze(drop=True)          # the newer files carry a one-level dimension
                assert u.shape == (24, 721, 1440) and u.latitude[0] == 90 and u.longitude[0] == 0
                x = u.isel(latitude=_ROWS).values       # (hour, row, 1440)
        if np.isnan(x).any():
            raise RuntimeError(f"ARCO's {level} hPa winds for {day} are incomplete")
        out.append(_ROW_W @ x.mean(axis=0))
    lon_idx = (np.round((LONS % 360) / 0.25).astype(int)[:, None] + _OFFSETS) % 1440
    return (np.array(out)[:, lon_idx] @ (_WEIGHTS / _WEIGHTS.sum())).astype(np.float32)


def latest_arco_day():
    """Last day ARCO has released both levels for."""
    day = date.today()
    while not all(_gcs_exists(raw_url(day, level).split("googleapis.com/")[1]) for level in LEVELS):
        day -= timedelta(days=1)
    return day


# ============================================================
# Archive files
# ============================================================

def year_path(year):
    return os.path.join(OUT_DIR, f"era5_u_15S15N_{year}.nc")


def archived_days():
    days = set()
    if not os.path.isdir(OUT_DIR):
        return days
    for fname in sorted(os.listdir(OUT_DIR)):
        if fname.startswith("era5_u_15S15N_") and fname.endswith(".nc"):
            with xr.open_dataset(os.path.join(OUT_DIR, fname)) as ds:
                days.update(t.astype("datetime64[D]").astype(date) for t in ds.time.values)
    return days


def write_days(days, u, sources):
    """Merge days (all in one year) into that year's file, atomically."""
    new = xr.Dataset(
        {f"u{level}": (("time", "longitude"), u[:, i]) for i, level in enumerate(LEVELS)},
        coords={"time": np.array(days, dtype="datetime64[ns]"), "longitude": LONS,
                "source": ("time", np.array(sources, dtype=object))},
    )
    path = year_path(days[0].year)
    if os.path.exists(path):
        with xr.open_dataset(path) as old:
            old = old.load()
        new = xr.concat([old, new], dim="time").sortby("time")
        new = new.isel(time=~new.get_index("time").duplicated(keep="last"))
    for level in LEVELS:
        new[f"u{level}"].attrs = {
            "units": "m s-1",
            "long_name": f"{level} hPa zonal wind, 15S-15N mean, daily mean",
            "comment": "source=wb2: WeatherBench2 era5_daily (conservative regrid); "
                       "source=arco: ARCO-ERA5 raw hourly analyses, box-averaged from 0.25 degree",
        }
    new.attrs = {"sources": f"gs://{WB2} ; gs://{ARCO_RAW}",
                 "updated": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    os.makedirs(OUT_DIR, exist_ok=True)
    tmp = path + ".tmp"
    new.to_netcdf(tmp)
    os.replace(tmp, path)
    print(f"  wrote {days[0]} .. {days[-1]} ({len(days)} days) to {path}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", help="first day YYYY-MM-DD (default: day after the archive's last day)")
    parser.add_argument("--end", help="last day YYYY-MM-DD (default: latest complete ERA5T day)")
    parser.add_argument("--workers", type=int, default=4, help="ARCO days downloaded at once")
    parser.add_argument("--batch-days", type=int, default=8, help="ARCO: write to disk this often")
    args = parser.parse_args()

    have = archived_days()
    end = date.fromisoformat(args.end) if args.end else latest_arco_day()
    if args.start:
        start = date.fromisoformat(args.start)
    elif have:
        start = max(have) + timedelta(days=1)
    else:
        sys.exit(f"{OUT_DIR}/ has no wind files: give --start for the first build (see --help)")

    todo = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    todo = [d for d in todo if d not in have]
    wb2_days = [d for d in todo if d <= WB2_LAST_DAY]
    arco_days = [d for d in todo if d > WB2_LAST_DAY]
    print(f"ERA5 15S-15N wind archive {OUT_DIR}/: {len(have)} days present; fetching {len(wb2_days)} days "
          f"from WeatherBench2 and {len(arco_days)} from ARCO ({start} .. {end})")

    # WeatherBench2: one request per year
    for run in runs(wb2_days):
        write_days(run, fetch_wb2(run), ["wb2"] * len(run))

    if not arco_days:
        return
    t0, done = time.time(), 0
    with ThreadPoolExecutor(args.workers) as pool:
        for run in runs(arco_days):
            for i in range(0, len(run), args.batch_days):
                batch = run[i:i + args.batch_days]
                write_days(batch, np.array(list(pool.map(fetch_arco, batch))), ["arco"] * len(batch))
                done += len(batch)
                rate = done / (time.time() - t0)
                print(f"  {done}/{len(arco_days)} ARCO days, {rate * 60:.1f} days/min "
                      f"(~{(len(arco_days) - done) / rate / 60:.0f} min left)", flush=True)


if __name__ == "__main__":
    main()
