"""
WGS84 geodetic <-> UTM <-> MGRS coordinate conversion.

Implements the standard Transverse Mercator projection for the Universal
Transverse Mercator (UTM) system using the equations in Snyder, "Map
Projections: A Working Manual", USGS Professional Paper 1395 (1987),
and the Military Grid Reference System 100 km square lettering rules from
NGA TM 8358.1 / DMA TM 8358.1 (the "AA scheme").

Dependency-free (math only) so the fusion engine stays air-gap deployable.

Conventions:
    - Latitude is geodetic degrees in [-80.0, 84.0]. Polar regions (UPS)
      are out of scope and raise ValueError.
    - Longitude is geodetic degrees, normalized to [-180.0, 180.0).
    - UTM easting is meters in [100000, 1000000). Northing is meters in
      [0, 10000000) north of the equator offset; southern hemisphere
      northing carries the standard 10,000,000 m false offset.
    - MGRS strings are "ZZB FFF EEEEE NNNNN" style: zone, latitude band,
      100 km square (column letter + row letter), then easting/northing
      numeric suffixes at the requested precision (default 5 digits = 1 m,
      i.e. a 10-digit grid reference).

Verification anchors used by tests/test_geo.py:
    - geodetic_to_mgrs(0.0, 0.0) == "31N AA 66021 00000"
    - Known-answer vectors cross-checked against the reference libmgrs /
      NGA TM 8358.1 implementation (e.g. New York "18T WL", London
      "30U XC", Fairbanks "06W VS").
    - Points on a zone central meridian project to easting exactly 500000.
    - Forward/inverse round trips close to sub-millimeter across all bands.

Known limitation: the MGRS Norway (32V) and Svalbard (31X/33X/35X/37X)
zone-override exceptions are not implemented; longitudes inside those
override windows north of 56N resolve via their regular UTM zone instead.
Outside the override regions this module matches libmgrs on an exhaustive
60-zone sweep (see tests/test_geo.py).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# --- WGS84 ellipsoid constants ---
_WGS84_A = 6378137.0                      # semi-major axis (m)
_WGS84_F = 1.0 / 298.257223563            # flattening
_WGS84_E2 = _WGS84_F * (2.0 - _WGS84_F)   # first eccentricity squared
_WGS84_EP2 = _WGS84_E2 / (1.0 - _WGS84_E2)  # second eccentricity squared

_UTM_K0 = 0.9996                          # central scale factor
_UTM_FALSE_EASTING_M = 500000.0
_SOUTH_FALSE_NORTHING_M = 10000000.0

# Latitude limits of the UTM band system (outside is UPS territory).
_LAT_MIN_DEG = -80.0
_LAT_MAX_DEG = 84.0

# MGRS 100 km square lettering per NGA TM 8358.1 (letters I and O are never
# used). Column letters come from three zone-set-specific 8-letter blocks
# covering easting columns 1..8 exactly; there is no cyclic wraparound.
_MGRS_COLUMN_BLOCKS = {0: "ABCDEFGH", 1: "JKLMNPQR", 2: "STUVWXYZ"}

# Row letters cycle every 2000 km through A-V minus I and O (20 letters).
_MGRS_ROW_ALPHABET = "ABCDEFGHJKLMNPQRSTUV"

# Latitude bands, 8 deg each from -80 (C) to 84 (X).
_MGRS_BAND_ALPHABET = "CDEFGHJKLMNPQRSTUVWX"


@dataclass(frozen=True)
class UTMCoordinate:
    """UTM position with its defining zone and hemisphere."""
    zone: int
    is_north: bool
    easting_m: float
    northing_m: float


def normalize_lon_deg(lon_deg: float) -> float:
    """Wrap longitude into [-180, 180)."""
    wrapped = math.fmod(lon_deg + 180.0, 360.0)
    if wrapped < 0.0:
        wrapped += 360.0
    return wrapped - 180.0


def lon_to_utm_zone(lon_deg: float) -> int:
    """Return the UTM zone (1..60) covering the given longitude."""
    return int((normalize_lon_deg(lon_deg) + 180.0) // 6.0) + 1


def utm_central_meridian_deg(zone: int) -> float:
    """Return the central meridian longitude (degrees) of a UTM zone."""
    if not 1 <= zone <= 60:
        raise ValueError(f"UTM zone out of range [1, 60]: {zone}")
    return (zone - 1) * 6.0 - 180.0 + 3.0


def _meridional_arc_m(lat_rad: float) -> float:
    """Meridional arc length from the equator (Snyder eq. 3-21 series)."""
    e2 = _WGS84_E2
    e4 = e2 * e2
    e6 = e4 * e2
    m1 = (
        1.0
        - e2 / 4.0
        - 3.0 * e4 / 64.0
        - 5.0 * e6 / 256.0
    )
    return _WGS84_A * (
        m1 * lat_rad
        - (3.0 * e2 / 8.0 + 3.0 * e4 / 32.0 + 45.0 * e6 / 1024.0)
        * math.sin(2.0 * lat_rad)
        + (15.0 * e4 / 256.0 + 45.0 * e6 / 1024.0)
        * math.sin(4.0 * lat_rad)
        - (35.0 * e6 / 3072.0)
        * math.sin(6.0 * lat_rad)
    )


def geodetic_to_utm(lat_deg: float, lon_deg: float) -> UTMCoordinate:
    """Project WGS84 geodetic coordinates to UTM (Snyder eqs. 8-9 .. 8-13)."""
    if not _LAT_MIN_DEG <= lat_deg <= _LAT_MAX_DEG:
        raise ValueError(
            f"Latitude {lat_deg} outside UTM coverage [{_LAT_MIN_DEG}, {_LAT_MAX_DEG}]; "
            "polar UPS conversion is not supported."
        )

    zone = lon_to_utm_zone(lon_deg)
    lon0 = utm_central_meridian_deg(zone)

    phi = math.radians(lat_deg)
    dlam = math.radians(normalize_lon_deg(lon_deg) - lon0)

    sin_phi = math.sin(phi)
    cos_phi = math.cos(phi)
    tan_phi = math.tan(phi)

    n = _WGS84_A / math.sqrt(1.0 - _WGS84_E2 * sin_phi * sin_phi)
    t = tan_phi * tan_phi
    c = _WGS84_EP2 * cos_phi * cos_phi
    a_prime = cos_phi * dlam

    ep2 = _WGS84_EP2
    m = _meridional_arc_m(phi)

    easting = _UTM_K0 * n * (
        a_prime
        + (1.0 - t + c) * a_prime**3 / 6.0
        + (5.0 - 18.0 * t + t * t + 72.0 * c - 58.0 * ep2)
        * a_prime**5 / 120.0
    ) + _UTM_FALSE_EASTING_M

    northing = _UTM_K0 * (
        m
        + n * tan_phi * (
            a_prime**2 / 2.0
            + (5.0 - t + 9.0 * c + 4.0 * c * c) * a_prime**4 / 24.0
            + (61.0 - 58.0 * t + t * t + 600.0 * c - 330.0 * ep2)
            * a_prime**6 / 720.0
        )
    )

    is_north = lat_deg >= 0.0
    if not is_north:
        northing += _SOUTH_FALSE_NORTHING_M

    return UTMCoordinate(zone=zone, is_north=is_north, easting_m=easting, northing_m=northing)


def utm_to_geodetic(zone: int, is_north: bool, easting_m: float, northing_m: float) -> tuple[float, float]:
    """Inverse UTM -> WGS84 geodetic (Snyder eqs. 8-14 .. 8-25). Returns (lat_deg, lon_deg)."""
    if not 1 <= zone <= 60:
        raise ValueError(f"UTM zone out of range [1, 60]: {zone}")

    x = easting_m - _UTM_FALSE_EASTING_M
    y = northing_m - (0.0 if is_north else _SOUTH_FALSE_NORTHING_M)

    e2 = _WGS84_E2
    ep2 = _WGS84_EP2
    e4 = e2 * e2
    e6 = e4 * e2

    m1 = 1.0 - e2 / 4.0 - 3.0 * e4 / 64.0 - 5.0 * e6 / 256.0
    mu = y / (_UTM_K0 * _WGS84_A * m1)

    e1 = (1.0 - math.sqrt(1.0 - e2)) / (1.0 + math.sqrt(1.0 - e2))

    phi1 = mu + (
        (3.0 * e1 / 2.0 - 27.0 * e1**3 / 32.0) * math.sin(2.0 * mu)
        + (21.0 * e1**2 / 16.0 - 55.0 * e1**4 / 32.0) * math.sin(4.0 * mu)
        + (151.0 * e1**3 / 96.0) * math.sin(6.0 * mu)
        + (1097.0 * e1**4 / 512.0) * math.sin(8.0 * mu)
    )

    sin_phi1 = math.sin(phi1)
    cos_phi1 = math.cos(phi1)
    tan_phi1 = math.tan(phi1)

    c1 = ep2 * cos_phi1 * cos_phi1
    t1 = tan_phi1 * tan_phi1
    n1 = _WGS84_A / math.sqrt(1.0 - e2 * sin_phi1 * sin_phi1)
    r1 = _WGS84_A * (1.0 - e2) / (1.0 - e2 * sin_phi1 * sin_phi1) ** 1.5
    d = x / (n1 * _UTM_K0)

    lat_rad = phi1 - (n1 * tan_phi1 / r1) * (
        d**2 / 2.0
        - (5.0 + 3.0 * t1 + 10.0 * c1 - 4.0 * c1 * c1 - 9.0 * ep2) * d**4 / 24.0
        + (61.0 + 90.0 * t1 + 298.0 * c1 + 45.0 * t1 * t1 - 252.0 * ep2 - 3.0 * c1 * c1)
        * d**6 / 720.0
    )

    lon_rad = (d - (1.0 + 2.0 * t1 + c1) * d**3 / 6.0
               + (5.0 - 2.0 * c1 + 28.0 * t1 - 3.0 * c1 * c1 + 8.0 * ep2 + 24.0 * t1 * t1)
               * d**5 / 120.0) / cos_phi1

    lat_deg = math.degrees(lat_rad)
    if not _LAT_MIN_DEG <= lat_deg <= _LAT_MAX_DEG:
        raise ValueError(
            f"Derived latitude {lat_deg} outside UTM coverage "
            f"[{_LAT_MIN_DEG}, {_LAT_MAX_DEG}] - corrupt or invalid input."
        )
    lon_deg = normalize_lon_deg(utm_central_meridian_deg(zone) + math.degrees(lon_rad))
    return lat_deg, lon_deg


def mgrs_latitude_band(lat_deg: float) -> str:
    """Return the MGRS latitude band letter for a latitude."""
    if not _LAT_MIN_DEG <= lat_deg <= _LAT_MAX_DEG:
        raise ValueError(f"Latitude {lat_deg} outside MGRS band coverage.")
    idx = int((lat_deg - _LAT_MIN_DEG) // 8.0)
    idx = min(idx, len(_MGRS_BAND_ALPHABET) - 1)  # clamp band X top edge (84.0 inclusive)
    return _MGRS_BAND_ALPHABET[idx]


def mgrs_100km_square_letters(zone: int, easting_m: float, northing_m: float) -> tuple[str, str]:
    """Return the (column, row) 100 km square letters for a UTM position."""
    col_index = int(easting_m // 100000.0)          # 1..8 within a valid UTM easting
    if not 1 <= col_index <= 8:
        raise ValueError(f"Easting {easting_m} outside valid UTM range.")
    col_block = _MGRS_COLUMN_BLOCKS[(zone - 1) % 3]
    col_letter = col_block[col_index - 1]

    row_offset = 5 if zone % 2 == 0 else 0          # even zones start at 'F'
    row_index = int(northing_m // 100000.0) % len(_MGRS_ROW_ALPHABET)
    row_letter = _MGRS_ROW_ALPHABET[(row_index + row_offset) % len(_MGRS_ROW_ALPHABET)]

    return col_letter, row_letter


@dataclass(frozen=True)
class MissionGridFrame:
    """Shared georeference for one incident: origin + MGRS square identity."""
    zone: int
    band: str
    square: str          # two-letter 100 km square, e.g. "GT"
    origin_easting_m: float
    origin_northing_m: float


def mission_grid_frame_from_latlon(lat: float, lon: float) -> MissionGridFrame:
    """Build the mission georeference from the grid origin lat/lon."""
    utm = geodetic_to_utm(lat, lon)
    col_letter, row_letter = mgrs_100km_square_letters(utm.zone, utm.easting_m, utm.northing_m)
    return MissionGridFrame(
        zone=utm.zone,
        band=mgrs_latitude_band(lat),
        square=f"{col_letter}{row_letter}",
        origin_easting_m=utm.easting_m,
        origin_northing_m=utm.northing_m,
    )


def geodetic_to_mgrs(lat_deg: float, lon_deg: float, precision_digits: int = 5) -> str:
    """
    Convert WGS84 geodetic coordinates to an MGRS grid reference string.

    precision_digits controls the numeric suffix length per axis (1..5):
    5 digits resolve 1 m ("10-digit" grid reference), 4 digits 10 m, etc.
    """
    if not 1 <= precision_digits <= 5:
        raise ValueError("precision_digits must be in [1, 5].")

    utm = geodetic_to_utm(lat_deg, lon_deg)
    band = mgrs_latitude_band(lat_deg)
    col_letter, row_letter = mgrs_100km_square_letters(utm.zone, utm.easting_m, utm.northing_m)

    divisor = 10.0 ** (5 - precision_digits)
    east_suffix = math.floor(utm.easting_m % 100000.0 / divisor)
    north_suffix = math.floor(utm.northing_m % 100000.0 / divisor)

    return (
        f"{utm.zone:02d}{band} {col_letter}{row_letter} "
        f"{east_suffix:0{precision_digits}d} {north_suffix:0{precision_digits}d}"
    )
