"""
Which date the 0.4 degree products of a run are for, and keeping them from being
overwritten by the next run's 1.5 degree ones.

CHC posts the 0.4 degree forecast initialized on day X at about 21:05 UTC on day X,
so a run at 02:33 UTC already has the init of the day before. The 1.5 degree ECMWF
forecast the rest of the pipeline uses lags two days. So a run has two forecast
dates: the 1.5 degree one (ECMWF date, run - 2) and the 0.4 degree one (normally
run - 1). The 0.4 degree products -- plot_s2s_04deg_.py's plots and
downscale_04deg_.py's Kenya weekly downscaling, with everything that reads it --
go under their own date's folders (plots/<country>/<date>/, data/<date>/).

The next day's run has that date as its ECMWF date, and dowscale_dekade.py then
writes the 1.5 degree Kenya weekly downscaled outputs under the same names into
the same folders. keep-published stops those from replacing the published 0.4
degree ones in the buckets.

    python forecast_04deg_dates.py resolve --run-date 2026-10-15 --ecmwf-date 2026-10-13
        The newest 0.4 degree init on CHC's server from the ECMWF date up to the day
        before the run date; the ECMWF date when there is none, FORECAST_04DEG_URL is
        not set or the server can't be reached. Printed (alone on stdout), and written
        as date=... to $GITHUB_OUTPUT when that is set.

    python forecast_04deg_dates.py keep-published --date 2026-10-13 --date-04deg 2026-10-14
        If gs://kenya-forecasting-data/<date>/ already holds the 0.4 degree Kenya
        weekly product, removes the local 1.5 degree outputs of the same names for
        <date> so the uploads leave the published ones alone; when there is no local
        0.4 degree product for --date-04deg (its downscaling failed), downloads the
        published ones for <date> instead, so the run's downscaled products are still
        the 0.4 degree ones. Run from the repo root (MAIN_PATH). Nothing to do when the
        two dates are the same.

    python forecast_04deg_dates.py archive [--date 2026-10-14 ...]
        Copies the global CHC files (pr_IFS-SUBS-0.4_<YYYYMMDD>.daily.nc, ~1.6 GB each)
        to FORECAST_04DEG_ARCHIVE/<YYYY>/ under their own names: every one on CHC's
        server (this month's and last month's folders) that isn't there yet, or only
        the given inits. CHC keeps a file for only a couple of weeks, so the daily
        workflow runs this to keep them. The archive is the private Sheerwater data
        lake: the forecast is licensed ECMWF data, never copy it anywhere public.
        Needs Google credentials that can write there.

resolve and plot_s2s_04deg_.py look in the archive too, so a date CHC no longer has
can still be (re)run.

Env vars: FORECAST_04DEG_URL (resolve, archive; not public, never printed), MAIN_PATH
(keep-published), FORECAST_04DEG_ARCHIVE (default gs://sheerwater-datalake/ecmwf-0_4/forecast)
"""
import argparse
import glob
import os
import re
import shutil
import sys
from datetime import datetime, timedelta, timezone

KENYA_BUCKET = "kenya-forecasting-data"
ARCHIVE = os.environ.get("FORECAST_04DEG_ARCHIVE", "gs://sheerwater-datalake/ecmwf-0_4/forecast").rstrip('/')

# what downscale_04deg_.py writes, relative to plots/Kenya/<date>/ and data/<date>/.
# The Kenya bucket holds the plots under <date>/ and the data under <date>/data/.
KENYA_WEEKLY_04DEG_PLOTS = [
    'weekly/weekly_precip_downscaled.png',
    'weekly/weekly_precip_downscaled_clipped.png',
    'weekly/weekly_precip_downscaled_anomaly.png',
    'weekly/weekly_precip_downscaled_anomaly_clipped.png',
    'weekly/prob_*spell_*days_downscaled.png',
    'weekly/median_*spell_length_downscaled.png',
    'weekly/weekly_chance_higherthan_*mm_downscaled.png',
    'weekly/counties',
    'monthly/monthly_precip_downscaled.png',
    'monthly/monthly_precip_downscaled_anomaly.png',
]
KENYA_WEEKLY_04DEG_DATA = [
    'data_weekly_Kenya_downscaled.nc',
    'data_weekly_Kenya_downscaled.zarr',
    'data_weekly_Kenya_downscaled_onset.nc',
    'data_weekly_Kenya_downscaled_onset.zarr',
    'daily_downscaled_kenya.tif',
    'daily_downscaled_kenya.zarr',
    'daily_downscaled_kenya_members.zarr',
    'daily_downscaled_kenya_members_onset.zarr',
    'CE_Kenya_dwnscaled_timeseries_daily.zarr',
]


def list_chc_inits(url, months):
    """
    {init datetime: file url} of the 0.4 degree forecasts on CHC's server in the
    given month folders ('01'..'12'; the server keeps one folder per month).
    A month that can't be listed is left out.
    """
    import requests
    available = {}
    for month in sorted(set(months)):
        link = f'{url}/{month}/'
        try:
            html = requests.get(link, timeout=30).text
        except requests.RequestException as e:
            print(f"Could not list month {month} on CHC's server ({type(e).__name__})", file=sys.stderr)
            continue
        for f in re.findall(r'href="(pr_IFS-SUBS-0\.4_(\d{8})\.daily\.nc)"', html):
            available[datetime.strptime(f[1], '%Y%m%d')] = link + f[0]
    return available


def archive_path(init):
    """Where the CHC file of init (a datetime) is kept in the archive."""
    return f"{ARCHIVE}/{init:%Y}/pr_IFS-SUBS-0.4_{init:%Y%m%d}.daily.nc"


def archive_fs():
    """gcsfs with Google credentials (the archive is private): the default ones (CI), else the gcloud CLI's login."""
    import gcsfs
    import google.auth
    try:
        google.auth.default()
        return gcsfs.GCSFileSystem()
    except google.auth.exceptions.DefaultCredentialsError:
        import subprocess
        import google.oauth2.credentials
        token = subprocess.run('gcloud auth print-access-token', shell=True, capture_output=True,
                               text=True, check=True).stdout.strip()
        return gcsfs.GCSFileSystem(token=google.oauth2.credentials.Credentials(token))


def list_archived_inits(years):
    """
    {init datetime: gs:// path} of the archived 0.4 degree forecasts of the given years;
    empty when the archive can't be read (no credentials, no access, no network).
    """
    archived = {}
    try:
        fs = archive_fs()
        for year in sorted(set(years)):
            for path in fs.glob(f"{ARCHIVE}/{year}/pr_IFS-SUBS-0.4_*.daily.nc"):
                match = re.search(r'pr_IFS-SUBS-0\.4_(\d{8})\.daily\.nc$', path)
                if match:
                    archived[datetime.strptime(match.group(1), '%Y%m%d')] = 'gs://' + path.removeprefix('gs://')
    except Exception as e:
        print(f"Could not list the 0.4 degree archive {ARCHIVE} ({type(e).__name__})", file=sys.stderr)
    return archived


def available_inits(first, last):
    """
    {init datetime: url or gs:// path} of the 0.4 degree forecasts from first to last
    (datetimes): CHC's file when it still has it, else the archived one.
    """
    days = [first + timedelta(days=i) for i in range((last - first).days + 1)]
    found = list_archived_inits({d.year for d in days})
    url = os.environ.get("FORECAST_04DEG_URL", "").strip().rstrip('/')
    if url:
        found.update(list_chc_inits(url, {d.strftime('%m') for d in days}))
    else:
        print("FORECAST_04DEG_URL is not set: only the archive is looked in", file=sys.stderr)
    return {d: where for d, where in found.items() if first <= d <= last}


def resolve(run_date, ecmwf_date):
    """The newest 0.4 degree init in [ecmwf_date, run_date - 1 day], else ecmwf_date."""
    first = datetime.strptime(ecmwf_date, '%Y-%m-%d')
    last = datetime.strptime(run_date, '%Y-%m-%d') - timedelta(days=1)
    usable = available_inits(first, last)
    if not usable:
        print(f"No 0.4 degree init from {ecmwf_date} to {last:%Y-%m-%d} on CHC's server or in the "
              f"archive: the 0.4 degree date is the ECMWF date", file=sys.stderr)
        return ecmwf_date
    return max(usable).strftime('%Y-%m-%d')


def archive(dates=None):
    """
    Copy CHC files to the archive (see the module docstring), streaming: the file goes
    to a temporary object that only replaces the final name once its size matches
    CHC's, so an interrupted copy never looks archived. Returns the number of failures.
    """
    import requests
    url = os.environ.get("FORECAST_04DEG_URL", "").strip().rstrip('/')
    if not url:
        raise SystemExit("FORECAST_04DEG_URL is not set")
    today = datetime.now(timezone.utc)
    months = {today.strftime('%m'), (today - timedelta(days=35)).strftime('%m')}
    if dates:
        wanted = [datetime.strptime(d, '%Y-%m-%d') for d in dates]
        months |= {d.strftime('%m') for d in wanted}
    on_chc = list_chc_inits(url, months)
    if dates:
        for d in wanted:
            if d not in on_chc:
                print(f"{d:%Y-%m-%d}: not on CHC's server (any more)", file=sys.stderr)
        on_chc = {d: on_chc[d] for d in wanted if d in on_chc}
    fs = archive_fs()
    failures = 0
    for init, src in sorted(on_chc.items()):
        dest = archive_path(init)
        tmp = dest + '.partial'
        try:
            with requests.get(src, stream=True, timeout=60) as r:
                r.raise_for_status()
                size = int(r.headers['Content-Length'])
                if fs.exists(dest) and fs.size(dest) == size:
                    print(f"{init:%Y-%m-%d}: already archived")
                    continue
                print(f"{init:%Y-%m-%d}: copying {size / 1e9:.2f} GB to {dest}")
                f = fs.open(tmp, 'wb', block_size=64 * 2**20)
                try:
                    for chunk in r.iter_content(chunk_size=16 * 2**20):
                        f.write(chunk)
                except BaseException:
                    f.discard()  # abort the upload instead of committing a truncated object
                    raise
                f.close()
            if fs.size(tmp) != size:
                raise IOError(f"archived {fs.size(tmp)} bytes, CHC has {size}")
            fs.mv(tmp, dest)
        except Exception as e:
            failures += 1
            # the exception text could hold CHC's (private) address, so only its type is shown
            print(f"{init:%Y-%m-%d}: copy failed ({type(e).__name__})", file=sys.stderr)
            try:
                if fs.exists(tmp):
                    fs.rm(tmp)
            except Exception:
                pass
    return failures


def _matches(root, patterns):
    return [p for pattern in patterns for p in sorted(glob.glob(os.path.join(root, pattern)))]


def _remove(path):
    if os.path.isdir(path):
        shutil.rmtree(path)
    else:
        os.remove(path)


def published_is_04deg(fs, date):
    """True if the Kenya bucket's weekly downscaled forecast for date is downscale_04deg_.py's."""
    import xarray as xr
    remote = f'{KENYA_BUCKET}/{date}/data/data_weekly_Kenya_downscaled.nc'
    if not fs.exists(remote):
        return False
    # the bucket is public: "#mode=bytes" has netCDF read just the header over HTTP
    url = f'https://storage.googleapis.com/{remote}#mode=bytes'
    with xr.open_dataset(url, engine='netcdf4') as ds:
        return str(ds.attrs.get('forecast_resolution', '')).startswith('0.4deg')


def keep_published(date, date_04deg, prefix):
    if date == date_04deg:
        print(f"0.4 degree and ECMWF date are both {date}: nothing to keep")
        return
    import gcsfs
    fs = gcsfs.GCSFileSystem(token='anon')
    if not published_is_04deg(fs, date):
        print(f"No published 0.4 degree Kenya weekly product for {date}: the 1.5 degree one stays")
        return

    plots_dir = os.path.join(prefix, 'plots', 'Kenya', date)
    data_dir = os.path.join(prefix, 'data', date)
    for path in _matches(plots_dir, KENYA_WEEKLY_04DEG_PLOTS) + _matches(data_dir, KENYA_WEEKLY_04DEG_DATA):
        _remove(path)
    print(f"Removed the 1.5 degree Kenya weekly downscaled outputs for {date}: "
          f"gs://{KENYA_BUCKET}/{date}/ already holds the 0.4 degree ones")

    if os.path.exists(os.path.join(prefix, 'data', date_04deg, 'data_weekly_Kenya_downscaled.nc')):
        return
    # today's 0.4 degree downscaling didn't run: use the published one for date
    print(f"No 0.4 degree Kenya weekly product for {date_04deg}: downloading the published one for {date}")
    for local_root, remote_root, patterns in ((plots_dir, f'{KENYA_BUCKET}/{date}', KENYA_WEEKLY_04DEG_PLOTS),
                                              (data_dir, f'{KENYA_BUCKET}/{date}/data', KENYA_WEEKLY_04DEG_DATA)):
        for pattern in patterns:
            for remote in fs.glob(f'{remote_root}/{pattern}'):
                local = os.path.join(local_root, remote[len(remote_root) + 1:])
                os.makedirs(os.path.dirname(local), exist_ok=True)
                fs.get(remote, local, recursive=True)
                print(f"  gs://{remote} -> {local}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('resolve')
    p.add_argument('--run-date', required=True)
    p.add_argument('--ecmwf-date', required=True)
    p = sub.add_parser('archive')
    p.add_argument('--date', action='append', help="init YYYY-MM-DD to archive (repeatable); default every one "
                                                   "on CHC's server that isn't archived yet")
    p = sub.add_parser('keep-published')
    p.add_argument('--date', required=True)
    p.add_argument('--date-04deg', required=True)
    args = parser.parse_args()

    if args.command == 'resolve':
        date = resolve(args.run_date, args.ecmwf_date)
        print(f"0.4 degree date {date} (ECMWF date {args.ecmwf_date})", file=sys.stderr)
        print(date)
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
                fh.write(f"date={date}\n")
    elif args.command == 'archive':
        sys.exit(1 if archive(args.date) else 0)
    else:
        keep_published(args.date, args.date_04deg, os.environ.get("MAIN_PATH", os.getcwd()))


if __name__ == '__main__':
    main()
