"""
ECMWF reforecast files for the dekadal downscaling (dowscale_dekade.py's
forecast_files table):

  downscale_data/ECMWF_tp_forecasts_<MM>-<DD>-<year>_day2_to_day11_Kenya.nc

One file per dekad start date: the 10-day precipitation total (mm) from the
init up to lead day 10 (tp accumulated at 240 h) on the 1.5 degree S2S grid,
as tp(year, latitude, longitude) with one entry per year:

  * <start-year> to <year>-1: the ensemble mean of the 10 perturbed members of
    the ECMWF reforecasts that belong to the <year>-MM-DD real-time forecast
  * <year>: the control member of that real-time forecast

This reproduces the existing files exactly (checked against
ECMWF_tp_forecasts_11-11-2025_day2_to_day11_Kenya.nc). Despite "day2_to_day11"
in the name the total runs from the init to 240 h.

Data comes from the ECMWF Data Stores (ECDS) s2s-reforecasts and s2s-forecasts
datasets, with the CDSAPI_KEY environment variable as the key (or, if unset,
the key in ~/.cdsapirc: ECMWF accounts share one key across the data stores).
Run by hand, not in CI:

    python build_dekad_reforecast.py --date 11-21
    python build_dekad_reforecast.py --date 12-01 12-11 --force
"""
import argparse
import os
import re
import tempfile

import cdsapi
import numpy as np
import xarray as xr

# the grid of the existing files
AREA = [37.5, -18, -37.5, 57]  # N, W, S, E
LEADTIME_HOUR = "240"


def ecds_client():
    key = os.environ.get("CDSAPI_KEY")
    if key is None:
        with open(os.path.expanduser("~/.cdsapirc")) as f:
            key = re.search(r"key:\s*(\S+)", f.read()).group(1)
    return cdsapi.Client(url="https://ecds.ecmwf.int/api", key=key, quiet=True)


def retrieve_tp(client, dataset, request, tmp):
    """tp at 240 h from one ECDS request, without the GRIB bookkeeping coords."""
    grib = os.path.join(tmp, f"{dataset}_{request['forecast_type']}.grib")
    base = {"origin": "ecmwf", "time": "00:00", "data_format": "grib", "level_type": "single_level",
            "variable": ["total_precipitation"], "leadtime_hour": [LEADTIME_HOUR], "area": AREA}
    client.retrieve(dataset, base | request).download(grib)
    return xr.open_dataset(grib, engine="cfgrib", indexpath="").tp.load()


def build_file(client, month, day, year, start_year):
    with tempfile.TemporaryDirectory() as tmp:
        hindcast = retrieve_tp(client, "s2s-reforecasts", {
            "year": str(year), "month": month, "day": day,
            "hyear": [str(y) for y in range(start_year, year)], "hmonth": month, "hday": day,
            "forecast_type": "perturbed_forecast"}, tmp)
        control = retrieve_tp(client, "s2s-forecasts", {
            "year": str(year), "month": month, "day": day,
            "forecast_type": "control_forecast"}, tmp)

    hindcast = hindcast.mean("number")
    hindcast = hindcast.assign_coords(year=("time", hindcast.time.dt.year.values)).swap_dims(time="year")
    expected = list(range(start_year, year))
    if hindcast.year.values.tolist() != expected:
        raise ValueError(f"ECDS returned reforecast years {hindcast.year.values.tolist()}, expected {expected}")
    control = control.expand_dims(year=[year])

    tp = xr.concat([da.drop_vars([c for c in da.coords if c not in da.dims]) for da in (hindcast, control)],
                   dim="year")
    tp = tp.astype("float32").transpose("year", "latitude", "longitude")
    tp.attrs = {}
    return tp.to_dataset(name="tp")


def main():
    parser = argparse.ArgumentParser(description="Build ECMWF dekadal reforecast files for dowscale_dekade.py")
    parser.add_argument('--date', nargs='+', required=True, help="init month and day(s), MM-DD")
    parser.add_argument('--year', type=int, default=2025,
                        help="year of the real-time forecast the reforecasts belong to")
    parser.add_argument('--start-year', type=int, default=2005, help="first reforecast year")
    parser.add_argument('--output-dir', default='downscale_data')
    parser.add_argument('--force', action='store_true', help="overwrite files that already exist")
    args = parser.parse_args()

    for date in args.date:
        if not re.fullmatch(r'\d{2}-\d{2}', date):
            parser.error(f"--date {date}: expected MM-DD")

    client = ecds_client()
    os.makedirs(args.output_dir, exist_ok=True)
    for date in args.date:
        path = f'{args.output_dir}/ECMWF_tp_forecasts_{date}-{args.year}_day2_to_day11_Kenya.nc'
        if os.path.exists(path) and not args.force:
            print(f"{path} exists, skipping (use --force to overwrite)")
            continue
        month, day = date.split('-')
        print(f"{args.year}-{date}: reforecasts {args.start_year}-{args.year - 1} + control forecast {args.year}")
        ds = build_file(client, month, day, args.year, args.start_year)
        if np.isnan(ds.tp.values).any():
            raise ValueError(f"{path}: the ECDS data has missing values")
        ds.to_netcdf(path)
        print(f"  -> {path}")


if __name__ == "__main__":
    main()
