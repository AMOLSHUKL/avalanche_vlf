"""
Verification suite for WGS84 <-> UTM <-> MGRS conversion (backend/engine/geo.py).

Anchors:
    - Null island resolves to the published reference "31N AA 66021 00000".
    - Points on a zone central meridian project to easting exactly 500000.
    - Mirror longitudes about a central meridian produce symmetric eastings.
    - Forward/inverse round trips close to sub-millimeter globally.
"""
import math

import pytest

from backend.engine.geo import (
    geodetic_to_utm,
    geodetic_to_mgrs,
    utm_to_geodetic,
    lon_to_utm_zone,
    utm_central_meridian_deg,
    mgrs_latitude_band,
    normalize_lon_deg,
)


def test_null_island_anchor():
    """Published MGRS reference for (0, 0) must be reproduced exactly."""
    assert geodetic_to_mgrs(0.0, 0.0) == "31N AA 66021 00000"


def test_longitude_normalization():
    assert normalize_lon_deg(180.0) == -180.0
    assert normalize_lon_deg(-181.0) == 179.0
    assert normalize_lon_deg(540.0) == 180.0 - 360.0 or normalize_lon_deg(540.0) == -180.0
    assert lon_to_utm_zone(77.5621) == 43
    assert lon_to_utm_zone(-77.0365) == 18
    assert lon_to_utm_zone(-180.0) == 1
    assert lon_to_utm_zone(179.9999) == 60


def test_central_meridian_easting_exact():
    for lon_cm in (3.0, 75.0, -177.0):
        zone = lon_to_utm_zone(lon_cm)
        assert abs(lon_cm - utm_central_meridian_deg(zone)) < 1e-9
        utm = geodetic_to_utm(34.1839, lon_cm)
        assert abs(utm.easting_m - 500000.0) < 1e-6


def test_mirror_symmetry_about_central_meridian():
    u_east = geodetic_to_utm(34.1839, 75.0 + 2.5)
    u_west = geodetic_to_utm(34.1839, 75.0 - 2.5)
    assert abs(u_east.easting_m + u_west.easting_m - 1000000.0) < 1e-3


def test_round_trip_closure_global_grid():
    worst = 0.0
    lat = -79.5
    while lat <= 83.5:
        lon = -179.7
        while lon <= 179.7:
            utm = geodetic_to_utm(lat, lon)
            lat2, lon2 = utm_to_geodetic(utm.zone, utm.is_north, utm.easting_m, utm.northing_m)
            cos_lat = max(0.01, math.cos(math.radians(lat)))
            dlat_m = abs(lat2 - lat) * 111320.0
            dlon_m = abs(((lon2 - lon + 180.0) % 360.0) - 180.0) * 111320.0 * cos_lat
            worst = max(worst, dlat_m, dlon_m)
            lon += 6.9
        lat += 8.7
    assert worst < 0.001


def test_latitude_bands_and_polar_rejection():
    assert mgrs_latitude_band(34.1839) == "S"
    assert mgrs_latitude_band(0.0) == "N"
    assert mgrs_latitude_band(-23.9) == "K"
    assert mgrs_latitude_band(84.0) == "X"
    with pytest.raises(ValueError):
        geodetic_to_utm(85.0, 0.0)
    with pytest.raises(ValueError):
        geodetic_to_mgrs(-81.0, 0.0)


def test_operational_origin_resolves_to_expected_square():
    """Origin (34.1839 N, 77.5621 E) lies in zone 43 S; column set for zone 43
    starts at 'A', and an easting near 736 km falls in the 7th column ('G')."""
    utm = geodetic_to_utm(34.183900, 77.562100)
    assert utm.zone == 43
    assert utm.is_north is True
    assert 700000 < utm.easting_m < 800000
    assert 3700000 < utm.northing_m < 3800000
    ref = geodetic_to_mgrs(34.183900, 77.562100)
    assert ref.startswith("43S G")


def test_precision_digits_control_resolution():
    coarse = geodetic_to_mgrs(34.183900, 77.562100, precision_digits=3)
    fine = geodetic_to_mgrs(34.183900, 77.562100, precision_digits=5)
    # Zone, band, and 100 km square are identical; only suffix length differs.
    assert coarse.split()[:2] == fine.split()[:2] == ["43S", "GT"]
    assert len(coarse.split()[2]) == 3
    with pytest.raises(ValueError):
        geodetic_to_mgrs(34.0, 77.0, precision_digits=0)
