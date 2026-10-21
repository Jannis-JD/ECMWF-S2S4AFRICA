"""
Gathers the 850 and 200 hPa zonal wind the RMM index (mjo_rmm_index.py) needs
for one ECMWF extended-range forecast, next to the OLR that
download_olr_waves.py already fetched -- all averaged over 15S-15N (plain mean
of the 1.5 degree rows, as in Wheeler and Hendon 2004), every longitude:

  data/<date>/rmm_u_forecast_<date>.nc
      the forecast: every member, days 1-46, from dynamical.org
      (ecmwf-ifs-ens-forecast-46-day-daily-1-5-degree, pressure_level group).
      dynamical runs ~48 h behind, so the daily run's init usually isn't
      there yet: then it comes from the ECDS s2s-forecasts u_component_of_wind
      instead (needs CDSAPI_KEY), the same 00 UTC instants on the same grid.
  data/<date>/rmm_u_reforecast_<date>.nc
      the reforecasts nearest this calendar day in each year 2006-2024
      (Planette, via gef.load_reforecast), ensemble mean, days 1-45 -- for the
      lead-dependent model bias.
  data/<date>/rmm_u_obs_leadin_<date>.nc
      the LEADIN_DAYS observed days before the forecast starts, from the ERA5
      archive built by rmm_wind_archive.py. The few days ERA5T hasn't reached
      are filled with each day's own day-1 forecast (ensemble mean); the
      `source` coordinate says which is which.

Each holds `u850` and `u200` in m s-1. Run rmm_wind_archive.py first so the
archive reaches as far as ERA5T allows.

Env vars:
    DATE_STR      forecast init date, defaults to today-2
    OLR_OBS_DIR   ERA5 archive folder (default olr_obs/), see rmm_wind_archive.py
    CDSAPI_KEY    ECDS key, only needed when dynamical doesn't have the init yet

Lead time convention: the model winds are instantaneous, at 00 UTC of
init + 0, 1, 2, ... days (checked against ERA5 for the reforecasts: lead 0 is
the 00 UTC analysis). Step N here is the mean of the two instants either side
of the N-th forecast day, so it lines up with the OLR's step N (the mean over
00-24 UTC on valid_date = init + N - 1 days) and with the observed daily means.
The reforecasts stop at init + 45 days, hence 45 days.
"""

import os
import sys
import tempfile
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import xarray as xr

import dynamical_catalog

import get_ECMWF_functions as gef
from olr_obs_archive import OUT_DIR as OBS_DIR
from rmm_wind_archive import LAT_MAX, LEVELS

# ============================================================
# CONFIG
# ============================================================

if "DATE_STR" in os.environ:
    date_str = os.environ["DATE_STR"]
else:
    today = datetime.today()
    two_days_earlier = today - timedelta(days=2)
    date_str = two_days_earlier.strftime("%Y-%m-%d")

print(f"Downloading 15S-15N zonal wind for the RMM index: {date_str}")

path = f'data/{date_str}/'
os.makedirs(path, exist_ok=True)

INIT = pd.Timestamp(date_str)
LEADIN_DAYS = 160      # the RMM's 120-day running mean in front of the 40 observed days it plots
DAY1_FALLBACK = 3      # a gap day with no forecast started on it may use day 2 .. this

DAILY_DATASET = "ecmwf-ifs-ens-forecast-46-day-daily-1-5-degree"


def open_forecast_u():
    """Lazy forecast zonal wind at LEVELS, 15S-15N."""
    ds = dynamical_catalog.open(DAILY_DATASET, group="pressure_level", chunks=None)
    return ds["wind_u"].sel(pressure_level=list(LEVELS), latitude=slice(LAT_MAX, -LAT_MAX))


def daily_means(u, dim):
    """Instants at 0, 1, 2, ... days along `dim` -> means over days 1, 2, ...
    (the average of the two instants either side), labelled step = 1, 2, ... days."""
    a, b = u.isel({dim: slice(None, -1)}), u.isel({dim: slice(1, None)})
    out = b.copy(data=0.5 * (a.values + b.values)).rename({dim: "step"})
    return out.assign_coords(step=pd.to_timedelta(np.arange(1, out.sizes["step"] + 1), unit="D"))


def by_level(u):
    """(.., pressure_level, ..) -> Dataset u850, u200."""
    ds = xr.Dataset({f"u{level}": u.sel(pressure_level=level, drop=True) for level in LEVELS})
    for c in ds.coords:
        ds[c].attrs = {}        # dynamical's coordinate attrs include dicts, which netCDF can't hold
    for v in ds.data_vars:
        ds[v].attrs = {"units": "m s-1", "long_name": f"{v[1:]} hPa zonal wind, 15S-15N mean"}
    return ds.astype("float32")


def write(ds, out):
    ds.to_netcdf(out)
    print(f"Wrote {out}")


# ============================================================
# 1. Forecast
# ============================================================

def forecast_from_dynamical(u):
    """The INIT run from dynamical, 15S-15N mean daily means as (number, step,
    pressure_level, longitude), or None when dynamical doesn't have it (yet)
    or has it only partly."""
    if INIT not in u.get_index("init_time"):
        print(f"dynamical has no {DAILY_DATASET} run started {date_str}")
        return None
    fc = u.sel(init_time=INIT).compute().mean("latitude")
    if fc.isnull().all(("ensemble_member", "longitude")).any():
        print(f"the {date_str} run is incomplete on dynamical (some lead days are all missing)")
        return None
    fc = daily_means(fc.sortby("lead_time"), "lead_time").rename({"ensemble_member": "number"})
    fc = fc.drop_vars([c for c in fc.coords if c not in fc.dims and c != "init_time"])
    fc.attrs = {"comment": "dynamical wind_u; step N = mean of the 00 UTC instants at init + N - 1 and init + N days"}
    return fc


def forecast_from_ecds():
    """The INIT run from the ECDS s2s-forecasts dataset (as download_s2s_legacy.py
    fetches it), shaped like forecast_from_dynamical's: the 00 UTC instants at
    init + 0 .. 46 days, 15S-15N mean, then daily means."""
    import cdsapi

    client = cdsapi.Client(url="https://ecds.ecmwf.int/api", key=os.environ["CDSAPI_KEY"])
    request = {
        "origin": "ecmwf",
        "year": date_str[:4],
        "month": date_str[5:7],
        "day": date_str[8:],
        "time": "00:00",
        "data_format": "grib",
        "level_type": "pressure",
        "level_value": [f"{level}_hpa" for level in LEVELS],
        "variable": ["u_component_of_wind"],
        "leadtime_hour": ["0/to/1104/by/24"],
        "area": [LAT_MAX, -180, -LAT_MAX, 178.5],
    }
    with tempfile.TemporaryDirectory(dir=path) as tmp:
        members = []
        for ftype in ("control_forecast", "perturbed_forecast"):
            grib = os.path.join(tmp, f"{ftype}.grib")
            print(f"Requesting the {ftype} winds from ECDS")
            client.retrieve("s2s-forecasts", request | {"forecast_type": ftype}).download(grib)
            u = xr.open_dataset(grib, engine="cfgrib", indexpath="").u.load()
            members.append(u if "number" in u.dims else u.expand_dims("number"))
    u = xr.concat(members, dim="number").sortby("number").rename({"isobaricInhPa": "pressure_level"})
    u = u.assign_coords(pressure_level=u.pressure_level.astype(int),
                        longitude=((u.longitude + 180) % 360) - 180).sortby("longitude")

    fc = daily_means(u.mean("latitude").sortby("step"), "step")
    fc = fc.drop_vars([c for c in fc.coords if c not in fc.dims])
    fc = fc.assign_coords(init_time=INIT).transpose("number", "step", "pressure_level", "longitude")
    expected = {"number": 101, "step": 46, "pressure_level": len(LEVELS), "longitude": 240}
    if dict(fc.sizes) != expected or fc.isnull().any():
        raise RuntimeError(f"unexpected ECDS winds for {date_str}: sizes {dict(fc.sizes)}, expected {expected}")
    fc.attrs = {"comment": "ECDS s2s-forecasts u_component_of_wind; step N = mean of the 00 UTC instants "
                           "at init + N - 1 and init + N days"}
    return fc


def get_forecast(u):
    out = f"{path}rmm_u_forecast_{date_str}.nc"
    if os.path.exists(out):
        print(f"Forecast already there: {out}")
        return
    fc = forecast_from_dynamical(u)
    if fc is None:
        print("Falling back to ECDS for the forecast")
        fc = forecast_from_ecds()
    comment = fc.attrs["comment"]
    fc = fc.assign_coords(valid_date=("step", (INIT + fc.step.to_index() - pd.Timedelta(days=1)).values))
    fc = by_level(fc.transpose("number", "step", "pressure_level", "longitude"))
    fc.attrs = {"comment": comment}
    write(fc, out)


# ============================================================
# 2. Reforecasts
# ============================================================

def get_reforecast():
    out = f"{path}rmm_u_reforecast_{date_str}.nc"
    if os.path.exists(out):
        print(f"Reforecast already there: {out}")
        return
    rf = gef.load_reforecast(date_str, "pressure", "u", levels=list(LEVELS),
                             bbox={"lat1": LAT_MAX, "lon1": -180, "lat2": -LAT_MAX, "lon2": 178.5},
                             time_range=slice(0, 46), all_years=True, size_warning_mb=2000)
    n_members = rf.sizes["number"]
    rf = daily_means(rf.mean(("number", "latitude")), "step")
    rf = by_level(rf.transpose("init_time", "step", "pressure_level", "longitude"))
    rf = rf.assign_coords(centre_day=gef.reforecast_center_day(rf, date_str))
    rf.attrs = {"comment": f"Planette ECMWF IFS reforecasts, mean of {n_members} members; "
                           "step N = mean of the 00 UTC instants at init + N - 1 and init + N days"}
    write(rf, out)


# ============================================================
# 3. Observed lead-in
# ============================================================

def read_obs_archive(days):
    """ERA5 winds for whichever of `days` the archive has."""
    files = [os.path.join(OBS_DIR, f"era5_u_15S15N_{y}.nc") for y in sorted({d.year for d in days})]
    files = [f for f in files if os.path.exists(f)]
    if not files:
        return None
    obs = xr.open_mfdataset(files, combine="by_coords")
    return obs.sel(time=obs.time.isin(days.values)).load()


def day1_forecast(u, day):
    """Ensemble-mean forecast winds for `day` from the run started that day
    (day 1), or else from up to DAY1_FALLBACK - 1 days before it."""
    inits = u.get_index("init_time")
    for lead in range(1, DAY1_FALLBACK + 1):
        init = day - pd.Timedelta(days=lead - 1)
        if init not in inits:
            continue
        fc = u.sel(init_time=init, lead_time=[pd.Timedelta(days=lead - 1), pd.Timedelta(days=lead)])
        fc = fc.compute().mean(("lead_time", "ensemble_member", "latitude"))
        if not fc.isnull().any():
            return fc.drop_vars([c for c in fc.coords if c not in fc.dims]), f"ecmwf_lead{lead}"
    raise RuntimeError(f"no ECMWF run on dynamical covers {day:%Y-%m-%d} at days 1-{DAY1_FALLBACK}")


def get_obs_leadin(u):
    out = f"{path}rmm_u_obs_leadin_{date_str}.nc"
    days = pd.date_range(INIT - pd.Timedelta(days=LEADIN_DAYS), INIT - pd.Timedelta(days=1), freq="D")
    obs = read_obs_archive(days)
    have = obs.get_index("time") if obs is not None else pd.DatetimeIndex([])
    last_obs = have.max() if len(have) else days[0] - pd.Timedelta(days=1)

    holes = days[(days <= last_obs) & ~days.isin(have)]
    if len(holes):
        sys.exit(f"The ERA5 wind archive in {OBS_DIR}/ is missing {len(holes)} lead-in days "
                 f"({holes[0]:%Y-%m-%d} .. {holes[-1]:%Y-%m-%d}): run "
                 f"python rmm_wind_archive.py --start {holes[0]:%Y-%m-%d}")
    gap = days[days > last_obs]
    if len(gap) > 15:
        sys.exit(f"The ERA5 wind archive in {OBS_DIR}/ ends {last_obs:%Y-%m-%d}, {len(gap)} days before "
                 f"this forecast: run python rmm_wind_archive.py "
                 f"--start {max(last_obs + pd.Timedelta(days=1), days[0]):%Y-%m-%d} first")

    parts = []
    if obs is not None and len(have):
        parts.append(obs.assign_coords(source=("time", obs.source.values.astype("U12"))))
    for day in gap:
        fc, source = day1_forecast(u, day)
        parts.append(by_level(fc).expand_dims(time=[day])
                     .assign_coords(source=("time", np.array([source], dtype="U12"))))
        print(f"  {day:%Y-%m-%d}: not in ERA5 yet, using the ECMWF forecast ({source})")

    leadin = xr.concat(parts, dim="time").sortby("time")
    assert leadin.sizes["time"] == LEADIN_DAYS and not leadin.to_array().isnull().any()
    leadin.attrs = {"comment": "ERA5 (source wb2/arco, see rmm_wind_archive.py), then ECMWF "
                               "ensemble-mean forecasts for the days ERA5T hasn't reached"}
    sources = pd.Series(leadin.source.values).value_counts().to_dict()
    print(f"Observed lead-in {days[0]:%Y-%m-%d} .. {days[-1]:%Y-%m-%d}: {sources}")
    write(leadin.astype("float32"), out)


if __name__ == "__main__":
    u = open_forecast_u()
    get_forecast(u)
    get_reforecast()
    get_obs_leadin(u)
