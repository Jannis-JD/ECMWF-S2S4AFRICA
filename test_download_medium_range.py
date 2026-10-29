#!/usr/bin/env python3
"""Unit tests for deterministic medium-range request construction."""

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("download_medium_range.py")
spec = importlib.util.spec_from_file_location("download_medium_range", MODULE_PATH)
medium = importlib.util.module_from_spec(spec)
spec.loader.exec_module(medium)


def test_all_requests_are_deterministic_and_have_an_area():
    for name, product in medium.PRODUCTS.items():
        request = medium._request("2026-10-27", product)
        assert request["stream"] == "oper", name
        assert request["type"] == "fc", name
        assert request["area"] == product["area"], name
        assert "enfo" not in request.values(), name
        assert "ep" not in request.values(), name


def test_primary_products_use_the_s2s_africa_window():
    for name, product in medium.PRODUCTS.items():
        if name in {"sst", "sst_nino34", "wind_10m_aux", "precip_aux", "tcw_indian_ocean", "humidity_wind_indian_ocean"}:
            continue
        assert product["area"] == [22.5, -21.0, -34.5, 55.5]


def test_requested_variables_cover_the_s2s_product_set():
    parameters = {param for product in medium.PRODUCTS.values() for param in product["param"]}
    assert {"tp", "2t", "d2m", "cape", "tcw", "10u", "10v"} <= parameters
    assert {"mx2t6", "mn2t6", "u", "v", "w", "q", "sst"} <= parameters
