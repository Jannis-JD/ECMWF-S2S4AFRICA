#!/usr/bin/env python3
"""
Check a medium-range 0.1 degree store written by download_medium_range.py.

Usage:
    python check_medium_range.py <path/to/medium_range_precip_01.zarr>

Exits 0 when every check passes, 1 otherwise. Each failed check is printed.
"""

import os
import sys

import numpy as np
import xarray as xr

BOUNDING_BOX = list(map(float, os.environ.get("BOUNDING_BOX", "22.5,-21,-34.5,55.5").split(",")))
MAX_STEP_HOURS = int(os.environ.get("MAX_STEP", "144"))
STEP_INTERVAL_HOURS = int(os.environ.get("STEP_INTERVAL", "6"))

# Upper bound on one interval's precipitation in mm. Generous: the largest
# 6-hourly values seen in tropical storms are well under this.
MAX_INTERVAL_MM = 400.0


def main(zarr_path):
    failures = []

    def check(ok, message):
        print(("PASS " if ok else "FAIL ") + message)
        if not ok:
            failures.append(message)

    check(os.path.isdir(zarr_path), f"store exists: {zarr_path}")
    if failures:
        return failures
    check(os.path.exists(os.path.join(zarr_path, ".download_complete")),
          "store is marked complete (.download_complete present)")

    ds = xr.open_zarr(zarr_path, consolidated=True).compute()
    check("tp" in ds.data_vars, "variable tp present")
    for dim in ("number", "step", "latitude", "longitude"):
        check(dim in ds.dims, f"dimension {dim} present")

    tp = ds["tp"]

    # Grid: the box, and a 0.1 degree spacing.
    north, west, south, east = BOUNDING_BOX
    lat, lon = ds["latitude"].values, ds["longitude"].values
    check(np.isclose(lat.min(), south) and np.isclose(lat.max(), north),
          f"latitude spans {south}..{north} (got {lat.min():.2f}..{lat.max():.2f})")
    check(np.isclose(lon.min(), west) and np.isclose(lon.max(), east),
          f"longitude spans {west}..{east} (got {lon.min():.2f}..{lon.max():.2f})")
    if lat.size > 1 and lon.size > 1:
        check(np.allclose(np.diff(lat), 0.1, atol=1e-4) and np.allclose(np.diff(lon), 0.1, atol=1e-4),
              "grid spacing is 0.1 degrees")

    # Steps: 0 to MAX_STEP in STEP_INTERVAL hour increments.
    steps_h = (ds["step"].values / np.timedelta64(1, "h")).astype(int)
    expected = np.arange(0, MAX_STEP_HOURS + 1, STEP_INTERVAL_HOURS)
    check(np.array_equal(steps_h, expected),
          f"steps are 0..{MAX_STEP_HOURS}h every {STEP_INTERVAL_HOURS}h (got {steps_h.min()}..{steps_h.max()}h, {steps_h.size} steps)")

    # Values.
    values = tp.values
    check(not np.isnan(values).any(), "no NaN values in tp")
    check(np.nanmin(values) >= 0, f"tp is non-negative (min {np.nanmin(values):.3f} mm)")
    check(np.nanmax(values) <= MAX_INTERVAL_MM,
          f"tp is below {MAX_INTERVAL_MM} mm per interval (max {np.nanmax(values):.2f} mm)")
    check(np.nanmax(values) > 0, "tp is not all zero")
    check(tp.attrs.get("units") == "mm", f"tp units are mm (got {tp.attrs.get('units')!r})")

    # Per-interval amounts should not depend on the 0 step (it is the baseline).
    if values.shape[1] > 1:
        check(np.all(values[:, 0] == 0), "step 0 is the zero baseline")

    # Time axis: time is the init, and valid_time = time + step.
    init = np.datetime64(ds["time"].values, "ns")
    valid = ds["valid_time"].values.astype("datetime64[ns]")
    check(np.array_equal(valid, init + ds["step"].values.astype("timedelta64[ns]")),
          "valid_time equals time + step")

    print(f"{len(failures)} failure(s)" if failures else "all checks passed")
    return failures


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(1 if main(sys.argv[1]) else 0)
