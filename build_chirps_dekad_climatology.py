"""
CHIRPS dekadal rainfall climatology files for the dekadal downscaling
(dowscale_dekade.py's forecast_files table):

  downscale_data/chirpsv3_dekads_<first year>_<last year>_<dekad>_<country>.nc

One file per dekad of the year: the rainfall total (mm, whole millimetres) of
that calendar dekad in every year, as tp(longitude, latitude, year) with year
running 0, 1, ... from the first year. Dekads are numbered 1-36 through the
year, three per month: days 1-10, 11-20 and 21 to the end of the month
(16 = June dekad 1, 32 = November dekad 2).

CHIRPS comes from the same public dynamical.org icechunk store
chirps_agro_climatology.py reads (CHIRPS v3 final, 0.05deg daily), so no
credentials are needed. Run by hand, not in CI:

    python build_chirps_dekad_climatology.py --dekad 32 33
    python build_chirps_dekad_climatology.py --dekad 1 --country Kenya --force
"""
import argparse
import calendar
import glob
import os
from concurrent.futures import ThreadPoolExecutor

import icechunk
import numpy as np
import pandas as pd
import xarray as xr

# same bboxes as dowscale_dekade.py's dekade_bboxes
dekade_bboxes = {
    "Kenya": {"lat1": 7, "lon1": 33, "lat2": -6, "lon2": 42},
    "Great_Horn": {"lat1": 25.5, "lon1": 19.5, "lat2": -8, "lon2": 57},
    "Ethiopia": {"lat1": 16, "lon1": 32, "lat2": 2, "lon2": 49},
    "Somalia": {"lat1": 13, "lon1": 40.5, "lat2": -2.5, "lon2": 52},
}

RES = 0.05  # CHIRPS grid spacing in degrees


def open_chirps():
    storage = icechunk.s3_storage(
        bucket="dynamical-ucsb-chc-chirps",
        prefix="ucsb-chc-chirps-analysis-final/v0.1.0.icechunk",
        region="us-west-2",
        anonymous=True,
    )
    session = icechunk.Repository.open(storage).readonly_session("main")
    return xr.open_zarr(session.store, chunks=None)


def dekad_dates(dekad, year):
    """First and last day of dekad 1-36 in the given year."""
    month, part = (dekad - 1) // 3 + 1, (dekad - 1) % 3
    first_day = 1 + 10 * part
    last_day = calendar.monthrange(year, month)[1] if part == 2 else first_day + 9
    return pd.Timestamp(year, month, first_day), pd.Timestamp(year, month, last_day)


def find_template(output_dir, country, skip):
    """An existing dekad file of this country to take the grid from, if any."""
    for path in sorted(glob.glob(f'{output_dir}/chirpsv3_dekads_*_{country}.nc')):
        if os.path.abspath(path) in skip:
            continue
        try:
            with xr.open_dataset(path) as ds:
                return path, ds.latitude.values, ds.longitude.values
        except Exception as e:
            print(f"  cannot read {path} as a grid template ({e}), trying the next one")
    return None, None, None


def build_dekad(da, dekad, years, n_workers):
    """tp(longitude, latitude, year): the dekad's rainfall total in each year."""
    record_start, record_end = pd.Timestamp(da.time.values[0]), pd.Timestamp(da.time.values[-1])

    def load(year):
        start, end = dekad_dates(dekad, year)
        if start < record_start or end > record_end:
            raise ValueError(f"CHIRPS ({record_start:%Y-%m-%d} to {record_end:%Y-%m-%d}) "
                             f"does not cover dekad {dekad} of {year}")
        sub = da.sel(time=slice(start, end)).load()
        ndays = (end - start).days + 1
        if sub.sizes['time'] != ndays:
            raise ValueError(f"CHIRPS {start:%Y-%m-%d} to {end:%Y-%m-%d} has {sub.sizes['time']} days, expected {ndays}")
        # kg m-2 s-1 (= mm/s, averaged over the day) -> mm over the dekad;
        # skipna=False keeps the ocean NaN instead of turning it into 0
        return (sub * 86400).sum('time', skipna=False)

    with ThreadPoolExecutor(n_workers) as pool:
        totals = list(pool.map(load, years))

    tp = xr.concat(totals, dim=pd.Index(np.arange(len(years)), name='year'))
    # the existing files hold whole millimetres, rounded down
    tp = np.floor(tp).astype('float32').drop_vars('spatial_ref', errors='ignore')
    return tp.transpose('longitude', 'latitude', 'year')


def main():
    parser = argparse.ArgumentParser(description="Build CHIRPS dekadal climatology files for dowscale_dekade.py")
    parser.add_argument('--dekad', type=int, nargs='+', required=True, help="dekad(s) of the year, 1-36")
    parser.add_argument('--country', default='Great_Horn', choices=list(dekade_bboxes))
    parser.add_argument('--start-year', type=int, default=2005)
    parser.add_argument('--end-year', type=int, default=2025)
    parser.add_argument('--output-dir', default='downscale_data')
    parser.add_argument('--workers', type=int, default=8, help="parallel per-year reads from the icechunk store")
    parser.add_argument('--force', action='store_true', help="overwrite files that already exist")
    args = parser.parse_args()

    for dekad in args.dekad:
        if not 1 <= dekad <= 36:
            parser.error(f"--dekad {dekad}: must be between 1 and 36")
    years = list(range(args.start_year, args.end_year + 1))
    bbox = dekade_bboxes[args.country]

    def out_path(dekad):
        return f'{args.output_dir}/chirpsv3_dekads_{args.start_year}_{args.end_year}_{dekad:02d}_{args.country}.nc'

    # The existing files label each cell by its western edge in longitude and
    # by its centre in latitude, so the cells picked here are the ones whose
    # western edge lies in the bbox.
    da = open_chirps().precipitation_surface.sel(
        latitude=slice(bbox['lat1'], bbox['lat2']),
        longitude=slice(bbox['lon1'], bbox['lon2'] + RES))
    latitude = da.latitude.values
    longitude = np.round(da.longitude.values - RES / 2, 3)

    # dowscale_dekade.py concatenates these files along 'step', which only
    # lines up if their coordinates are identical to the last bit -- so reuse
    # the coordinates of a file that is already there.
    template, t_lat, t_lon = find_template(args.output_dir, args.country,
                                           skip={os.path.abspath(out_path(d)) for d in args.dekad})
    if template is not None:
        if (t_lat.shape != latitude.shape or t_lon.shape != longitude.shape
                or not np.allclose(t_lat, latitude, atol=RES / 10)
                or not np.allclose(t_lon, longitude, atol=RES / 10)):
            raise ValueError(f"The grid of {template} does not match the {args.country} bbox cut-out of CHIRPS")
        latitude, longitude = t_lat, t_lon
        print(f"grid taken from {template}")
    else:
        print(f"no existing {args.country} dekad file in {args.output_dir}, using the CHIRPS grid")

    os.makedirs(args.output_dir, exist_ok=True)
    for dekad in args.dekad:
        path = out_path(dekad)
        if os.path.exists(path) and not args.force:
            print(f"{path} exists, skipping (use --force to overwrite)")
            continue
        start, end = dekad_dates(dekad, years[-1])
        print(f"dekad {dekad} ({start:%b %d} to {end:%b %d}), {years[0]}-{years[-1]}, {args.country}: reading CHIRPS")
        tp = build_dekad(da, dekad, years, args.workers)
        tp = tp.assign_coords(latitude=latitude, longitude=longitude)
        # dynamical.org coord attrs include dict-valued 'statistics_approximate',
        # which netCDF can't serialize
        for c in tp.coords:
            tp.coords[c].attrs = {}
        tp.attrs = {}
        tp.to_dataset(name='tp').to_netcdf(path)
        print(f"  -> {path}")


if __name__ == "__main__":
    main()
