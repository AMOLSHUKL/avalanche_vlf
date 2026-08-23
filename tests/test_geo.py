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
    mgrs_100km_square_letters,
    mission_grid_frame_from_latlon,
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


# --- Regression anchors for the 100 km square lettering subsystem ---
# Expected sequences per NGA TM 8358.1 "AA scheme": each zone set owns an
# exact 8-letter column block (A-H / J-R / S-Z, no wraparound); row letters
# cycle A-V minus I,O every 2000 km, even zones offset by 'F'.
# Known-answer strings cross-checked against reference libmgrs output.
_LIBMGRS_ANCHORS = [
    ((34.1839, 77.5621), "43S GT 36122 85514"),
    ((40.7128, -74.0060), "18T WL 83959 07350"),
    ((-33.8688, 151.2093), "56H LH 34368 50948"),
    ((30.0, 89.3), "45R YP 21859 21012"),
    ((64.84, -147.72), "06W VS 65844 90817"),
    ((51.5074, -0.1278), "30U XC 99316 10163"),
    ((-18.92, 47.52), "38K QE 65424 06130"),
]


@pytest.mark.parametrize("point,want", _LIBMGRS_ANCHORS)
def test_mgrs_known_answer_vectors(point, want):
    assert geodetic_to_mgrs(*point) == want


def test_mgrs_zone_is_zero_padded_for_single_digit_zones():
    assert geodetic_to_mgrs(64.84, -147.72).startswith("06W VS")
    assert geodetic_to_mgrs(0.0, 0.0).startswith("31N AA")


@pytest.mark.parametrize("zone", range(1, 61))
@pytest.mark.parametrize("northing", [50_000.0, 1_950_000.0, 3_000_050.0, 6_100_000.0])
def test_mgrs_square_letters_exhaustive_no_crash_and_known_sequence(zone, northing):
    letters_by_col = [
        mgrs_100km_square_letters(zone, col * 100000.0 + 50000.0, northing)[0]
        for col in range(1, 9)
    ]
    zone_set = (zone - 1) % 3
    expected_block = {0: "ABCDEFGH", 1: "JKLMNPQR", 2: "STUVWXYZ"}[zone_set]
    assert "".join(letters_by_col) == expected_block


@pytest.mark.parametrize("zone,expected_offset", [(43, 0), (44, 5)])
@pytest.mark.parametrize("row_index", range(0, 20))
def test_mgrs_row_letters_exhaustive_cycle(zone, expected_offset, row_index):
    """Every row index must resolve without crashing and follow the A-V minus
    I,O alphabet with the even-zone 'F' offset; the cycle repeats after 20
    blocks of northing."""
    alphabet = "ABCDEFGHJKLMNPQRSTUV"
    northing = row_index * 100000.0 + 50000.0
    letter = mgrs_100km_square_letters(zone=zone, easting_m=450000.0, northing_m=northing)[1]
    assert letter == alphabet[(row_index + expected_offset) % 20]
    wrapped = mgrs_100km_square_letters(
        zone=zone, easting_m=450000.0, northing_m=(row_index + 20) * 100000.0 + 50000.0
    )[1]
    assert wrapped == letter


@pytest.mark.parametrize("easting", [99_999.0, 0.0, 1_000_001.0])
def test_mgrs_square_letters_reject_invalid_easting(easting):
    with pytest.raises(ValueError):
        mgrs_100km_square_letters(zone=43, easting_m=easting, northing_m=50_000.0)


@pytest.mark.parametrize("northing", [9_400_000.0, 12_000_000.0])
def test_utm_to_geodetic_rejects_out_of_band_output(northing):
    with pytest.raises(ValueError):
        utm_to_geodetic(zone=43, is_north=True, easting_m=500_000.0, northing_m=northing)


def test_mission_grid_frame_matches_origin_conversion():
    frame = mission_grid_frame_from_latlon(34.1839, 77.5621)
    assert frame.zone == 43
    assert frame.band == "S"
    assert frame.square == "GT"
    utm = geodetic_to_utm(34.1839, 77.5621)
    assert frame.origin_easting_m == utm.easting_m
    assert frame.origin_northing_m == utm.northing_m
