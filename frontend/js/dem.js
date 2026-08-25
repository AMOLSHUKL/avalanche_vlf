/**
 * AVLF.DEM / AVLF.GEO — shared terrain + geodesy primitives.
 *
 * Terrain mirrors backend TerrainEngine._generate_dem analytically:
 *   base ramp + cross-slope undulation, a start-zone peak, an east ridge,
 *   and a carved avalanche track (release → runout). Keep the formula
 *   mathematically identical to backend/engine/terrain.py.
 * The full 10k-cell DEM is not streamed over WS; when a /api/dem endpoint
 * lands, replace DEM.elevation and every consumer keeps working.
 */
window.AVLF = window.AVLF || {};
(function (AVLF) {
    "use strict";
    const GRID = 100, CELL_M = 5, SECTOR_M = GRID * CELL_M;
    const ORIGIN_LAT = 34.183900, ORIGIN_LON = 77.562100;
    const DEG_M_LAT = 1.0 / 111111.0;
    const DEG_M_LON = 1.0 / (111111.0 * Math.cos(ORIGIN_LAT * Math.PI / 180));

    // Avalanche track: release (170,430) → runout (330,100), meters.
    const GULLY_AX = 170, GULLY_AY = 430, GULLY_BX = 330, GULLY_BY = 100;
    const ABX = GULLY_BX - GULLY_AX, ABY = GULLY_BY - GULLY_AY;
    const AB2 = ABX * ABX + ABY * ABY;

    function elevation(x, y) {
        // Cell-center coordinates, matching the backend meshgrid exactly:
        // xx = (cx + 0.5) * cell_size — a corner-vs-center offset is sub-1 m
        // on the old ramp but 6 m across the peak/gully Gaussians.
        const xm = (x + 0.5) * CELL_M, ym = (y + 0.5) * CELL_M;
        let e = 3800.0 + ym * 0.42 + 25.0 * Math.sin(xm / 70.0);
        // Start-zone peak (release bowl).
        let dx = (xm - 110.0) / 90.0, dy = (ym - 430.0) / 60.0;
        e += 110.0 * Math.exp(-(dx * dx + dy * dy));
        // Eastern ridge wall.
        dx = (xm - 465.0) / 55.0; dy = (ym - 300.0) / 170.0;
        e += 70.0 * Math.exp(-(dx * dx + dy * dy));
        // Carved track.
        const t = Math.max(0, Math.min(1, ((xm - GULLY_AX) * ABX + (ym - GULLY_AY) * ABY) / AB2));
        const px = xm - (GULLY_AX + t * ABX), py = ym - (GULLY_AY + t * ABY);
        e -= 16.0 * Math.exp(-((px * px + py * py) / 784.0));
        return e;
    }
    function gradient(x, y) {
        const dzdx = (elevation(x + 1, y) - elevation(x - 1, y)) / (2 * CELL_M);
        const dzdy = (elevation(x, y + 1) - elevation(x, y - 1)) / (2 * CELL_M);
        return { dzdx, dzdy };
    }
    function slopeDeg(x, y) {
        const g = gradient(x, y);
        return Math.atan(Math.hypot(g.dzdx, g.dzdy)) * 180 / Math.PI;
    }
    function contourAzimuth(x, y) {
        const g = gradient(x, y);
        const upSlope = Math.atan2(g.dzdx, g.dzdy) * 180 / Math.PI;
        return ((upSlope + 90) % 360 + 360) % 360;
    }

    AVLF.GEO = {
        GRID, CELL_M, SECTOR_M,
        ORIGIN_LAT, ORIGIN_LON, DEG_M_LAT, DEG_M_LON,
        metersOfLatLon(lat, lon) {
            return {
                northM: (lat - ORIGIN_LAT) / DEG_M_LAT,
                eastM: (lon - ORIGIN_LON) / DEG_M_LON
            };
        },
        latLonOfMeters(northM, eastM) {
            return {
                lat: ORIGIN_LAT + northM * DEG_M_LAT,
                lon: ORIGIN_LON + eastM * DEG_M_LON
            };
        }
    };
    AVLF.DEM = { elevation, gradient, slopeDeg, contourAzimuth };
})(window.AVLF);
