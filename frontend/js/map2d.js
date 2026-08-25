/**
 * AVLF.MapTopo — topographic 2D canvas renderer (primary working surface).
 *
 * Draws in meter-space through one affine transform, so zoom/focus is a pure
 * window change with no geometry rework. Layers bottom-up: paper plate, baked
 * hillshade, optional >30 deg hazard tint, contours, UTM grid, fused posterior
 * (shared AVLF.Fusion canvas), directive needles, UAV glyphs, reticle, labels.
 */
window.AVLF = window.AVLF || {};
(function (AVLF) {
    "use strict";
    const G = AVLF.GEO, DEM = AVLF.DEM;
    const S = G.SECTOR_M;
    let cv = null, ctx = null, dpr = 1;
    let shadeTile = null, hazardTile = null;
    let contourCache = { key: "", segs: [] };

    // View window in meters; winX east from west edge, winY south from north edge.
    const view = { zoom: 1, winX: 0, winY: 0 };
    let anim = null;
    let reticle = null;   // {cx, cy, zone, t0}
    const opts = { grid: true, contours: true, vectors: true, slope: false };

    const clampI = v => Math.max(0, Math.min(G.GRID - 1, v));
    function norm3(x, y, z) { const m = Math.hypot(x, y, z); return [x / m, y / m, z / m]; }
    function dot3(a, b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
    function hexA(hex, a) {
        if (!hex || hex[0] !== "#") return hex;
        const n = parseInt(hex.slice(1), 16);
        return "rgba(" + ((n >> 16) & 255) + "," + ((n >> 8) & 255) + "," + (n & 255) + "," + a + ")";
    }
    function css(name, fb) {
        const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
        return v || fb;
    }

    function mkTile(rgb, alphaFn) {
        const t = document.createElement("canvas");
        t.width = t.height = G.GRID;
        const c = t.getContext("2d");
        const img = c.createImageData(G.GRID, G.GRID);
        for (let y = 0; y < G.GRID; y++)
            for (let x = 0; x < G.GRID; x++) {
                const i = (y * G.GRID + x) * 4;
                img.data[i] = rgb[0]; img.data[i + 1] = rgb[1]; img.data[i + 2] = rgb[2];
                img.data[i + 3] = alphaFn(x, y);
            }
        c.putImageData(img, 0, 0);
        return t;
    }

    function bakeTiles() {
        const L = norm3(-0.62, 0.72, 0.55);
        // Neutral dark ink for hillshade — a red base here tinted the whole
        // map pink (the shade tile is drawn over every cell at 85% alpha).
        shadeTile = mkTile([15, 23, 42], (x, y) => {
            const g = DEM.gradient(clampI(x), clampI(y));
            const nl = norm3(-g.dzdx, -g.dzdy, 1);
            return Math.round(115 * Math.pow(Math.max(0, dot3(nl, L)), 1.6));
        });
        hazardTile = mkTile([220, 38, 38], (x, y) => {
            const sl = DEM.slopeDeg(clampI(x), clampI(y));
            if (sl <= 30) return 0;
            return sl >= 40 ? 70 : Math.round(36 * (sl - 30) / 10);
        });
    }

    function init(canvasEl) {
        cv = canvasEl;
        ctx = cv.getContext("2d");
        bakeTiles();
    }

    function fit() {
        const r = cv.parentElement.getBoundingClientRect();
        dpr = Math.min(window.devicePixelRatio || 1, 2);
        const w = Math.max(1, Math.round(r.width)), h = Math.max(1, Math.round(r.height));
        if (cv.width !== Math.round(w * dpr)) cv.width = Math.round(w * dpr);
        if (cv.height !== Math.round(h * dpr)) cv.height = Math.round(h * dpr);
        return { w, h };
    }

    function baseRect(w, h) {
        const sheetMode = w <= 1023;
        const padTop = 52, padX = sheetMode ? 12 : 22;
        const padBottom = sheetMode ? 108 : 24;
        const size = Math.max(80, Math.min(w - padX * 2, h - padTop - padBottom));
        return { size, x: (w - size) / 2, y: padTop + (h - padTop - padBottom - size) / 2 };
    }

    function clampWindow() {
        const span = S / view.zoom;
        view.winX = Math.max(0, Math.min(S - span, view.winX));
        view.winY = Math.max(0, Math.min(S - span, view.winY));
    }

    function advanceAnim(now) {
        if (!anim) return;
        const k = Math.min(1, (now - anim.t0) / anim.dur);
        const e = 1 - Math.pow(1 - k, 3);
        view.zoom = anim.from.zoom + (anim.to.zoom - anim.from.zoom) * e;
        view.winX = anim.from.x + (anim.to.x - anim.from.x) * e;
        view.winY = anim.from.y + (anim.to.y - anim.from.y) * e;
        if (k >= 1) anim = null;
    }

    function animateTo(toZoom, toX, toY, now, dur) {
        anim = { t0: now, dur: dur || 550, from: { zoom: view.zoom, x: view.winX, y: view.winY },
                 to: { zoom: toZoom, x: toX, y: toY } };
    }

    function focusCell(cx, cy, now) {
        const span = S / 4;
        animateTo(4,
            Math.max(0, Math.min(S - span, (cx + .5) * G.CELL_M - span / 2)),
            Math.max(0, Math.min(S - span, S - (cy + .5) * G.CELL_M - span / 2)),
            now);
    }
    function recenterExtents(now) {
        const pts = [];
        AVLF.state.cells.forEach(c => {
            if (c.zone === "P1" || c.zone === "P2" || c.zone === "P3")
                pts.push([(c.x + .5) * G.CELL_M, (c.y + .5) * G.CELL_M]);
        });
        if (!pts.length) { resetView(now); return; }
        let minX = 500, maxX = 0, minYn = 500, maxYn = 0;
        for (const [ex, ny] of pts) {
            minX = Math.min(minX, ex); maxX = Math.max(maxX, ex);
            minYn = Math.min(minYn, ny); maxYn = Math.max(maxYn, ny);
        }
        const pad = 60;
        const spanM = Math.max(maxX - minX, maxYn - minYn) + pad * 2;
        const zoom = Math.max(1, Math.min(4, S / spanM));
        const span = S / zoom;
        animateTo(zoom,
            Math.max(0, Math.min(S - span, (minX + maxX) / 2 - span / 2)),
            Math.max(0, Math.min(S - span, S - (minYn + maxYn) / 2 - span / 2)),
            now, 700);
    }
    function resetView(now) {
        animateTo(1, 0, 0, now, 650);
    }

    /* ============================ RENDER ============================ */
    function render(now) {
        if (!cv) return;
        const { w, h } = fit();
        advanceAnim(now);
        clampWindow();
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, w, h);

        const R = baseRect(w, h);
        const s = R.size * view.zoom / S;          // px per meter on screen
        const ox = R.x - view.winX * s;            // screen x of sector west edge
        const oy = R.y - view.winY * s;            // screen y of sector north edge
        // Draw in meter space: X=east, Ym=south-from-north (screen down).
        ctx.setTransform(dpr * s, 0, 0, dpr * s, dpr * ox, dpr * oy);

        // Paper plate
        ctx.fillStyle = css("--surface-2", "#eef2f7");
        ctx.fillRect(0, 0, S, S);

        ctx.save();
        ctx.beginPath(); ctx.rect(0, 0, S, S); ctx.clip();

        // Hillshade + hazard tint (baked GRID tiles, drawn per-cell block)
        ctx.globalAlpha = .85;
        ctx.imageSmoothingEnabled = true;
        ctx.drawImage(shadeTile, 0, 0, S, S);
        ctx.globalAlpha = 1;

        // Contours (cached segments in normalized coords)
        if (opts.contours) drawContours(s);

        // UTM grid every 100 m
        if (opts.grid) {
            ctx.strokeStyle = css("--border-strong", "#cbd5e1");
            ctx.lineWidth = 0.7 / s; ctx.globalAlpha = .45;
            for (let m = 0; m <= S; m += 100) {
                ctx.beginPath(); ctx.moveTo(m, 0); ctx.lineTo(m, S); ctx.stroke();
                ctx.beginPath(); ctx.moveTo(0, m); ctx.lineTo(S, m); ctx.stroke();
            }
            ctx.globalAlpha = 1;
        }

        // Slope hazard tint (>30 deg)
        if (opts.slope) {
            ctx.globalAlpha = .9;
            ctx.drawImage(hazardTile, 0, 0, S, S);
            ctx.globalAlpha = 1;
        }

        // Fused posterior (shared layer canvas)
        ctx.drawImage(AVLF.Fusion.canvas, 0, 0, S, S);

        // Directive needles (approach guidance — independent of drone toggle)
        drawNeedles(s);

        // UAV glyphs + scan wedges
        if (opts.vectors) drawUavs(s, now);
        ctx.restore();

        // Plate border (screen-space width)
        ctx.strokeStyle = css("--border-strong", "#cbd5e1");
        ctx.lineWidth = 1.4 / s;
        ctx.strokeRect(0, 0, S, S);

        // Selection reticle
        if (reticle) drawReticle(s, now);

        // Screen-space chrome: labels, north arrow
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        if (view.zoom <= 1.6 && opts.grid) drawLabels(R, s);
        drawNorth(R);
    }

    function drawContours(s) {
        const key = "c" + opts.slope; // cache once; slope flag irrelevant here
        if (contourCache.key !== key) {
            const segs = [];
            for (let level = 3800; level <= 4075; level += 25)
                for (let y = 0; y < G.GRID; y++) {
                    for (let x = 0; x < G.GRID; x++) {
                        const a = DEM.elevation(x, y),
                              bE = DEM.elevation(x + 1, y),
                              bN = DEM.elevation(x, y + 1);
                        if ((a - level) * (bE - level) < 0)
                            segs.push([x * 5, y * 5, (x + 1) * 5, y * 5]);
                        if ((a - level) * (bN - level) < 0)
                            segs.push([x * 5, y * 5, x * 5, (y + 1) * 5]);
                    }
                }
            contourCache = { key, segs };
        }
        ctx.strokeStyle = css("--border-strong", "#cbd5e1");
        ctx.lineWidth = 0.6 / s;
        ctx.globalAlpha = .5;
        ctx.beginPath();
        for (const [x1, y1, x2, y2] of contourCache.segs) {
            ctx.moveTo(x1, S - y1); ctx.lineTo(x2, S - y2);
        }
        ctx.stroke();
        ctx.globalAlpha = 1;
    }

    function cellCenter(c) {
        return [(c.x + .5) * G.CELL_M, S - (c.y + .5) * G.CELL_M];
    }

    function drawNeedles(s) {
        const col = hexA(css("--accent", "#4f46e5"), .85);
        AVLF.state.directives.forEach(d => {
            const c = AVLF.state.cells.get(d.target_zone_id.replace("cell_", ""));
            if (!c || c.zone === "P4") return;
            const [px, py] = cellCenter(c);
            const a = (-d.approach_azimuth_deg + 90) * Math.PI / 180;
            const len = 62;
            ctx.strokeStyle = col; ctx.fillStyle = col;
            ctx.lineWidth = 1.8 / s;
            ctx.setLineDash([4 / s, 3 / s]);
            ctx.beginPath(); ctx.moveTo(px, py);
            ctx.lineTo(px + Math.cos(a) * len, py + Math.sin(a) * len);
            ctx.stroke(); ctx.setLineDash([]);
            const tx = px + Math.cos(a) * len, ty = py + Math.sin(a) * len;
            ctx.beginPath();
            ctx.moveTo(tx, ty);
            ctx.lineTo(tx + Math.cos(a + 2.7) * 22, ty + Math.sin(a + 2.7) * 22);
            ctx.lineTo(tx + Math.cos(a - 2.7) * 22, ty + Math.sin(a - 2.7) * 22);
            ctx.closePath(); ctx.fill();
        });
    }

    function drawUavs(s, now) {
        AVLF.state.uavs.forEach(u => {
            const p = G.metersOfLatLon(u.current_lat, u.current_lon);
            const tx = p.eastM, ty = S - p.northM;
            const o = u._anim || (u._anim = {});
            if (o.x === undefined) { o.x = tx; o.y = ty; }
            o.x += (tx - o.x) * .14; o.y += (ty - o.y) * .14;
            const col = u.asset_id === "UAV_ALPHA"
                ? css("--uav-a", "#0891b2") : css("--uav-b", "#7c3aed");
            const hd = (-u.heading_deg + 90) * Math.PI / 180;
            ctx.fillStyle = hexA(col, .13);
            ctx.beginPath(); ctx.moveTo(o.x, o.y);
            ctx.arc(o.x, o.y, 42, hd - .55, hd + .55); ctx.closePath(); ctx.fill();
            ctx.fillStyle = col;
            ctx.shadowColor = col; ctx.shadowBlur = 8;
            ctx.beginPath(); ctx.arc(o.x, o.y, 6, 0, Math.PI * 2); ctx.fill();
            ctx.shadowBlur = 0;
            ctx.strokeStyle = css("--surface", "#fff"); ctx.lineWidth = 2 / s;
            ctx.stroke();
        });
    }

    function drawReticle(s, now) {
        const c = AVLF.state.cells.get(reticle.key);
        if (!c || c.zone === "P4") { reticle = null; return; }
        const [px, py] = cellCenter(c);
        const col = c.zone === "P1" ? css("--p1", "#dc2626") : css("--sig-cyan", "#0891b2");
        const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;
        const rot = REDUCED ? 0 : (now / 1600) % (Math.PI * 2);
        const k = REDUCED ? 1 : ((now / 1200) % 1);

        ctx.strokeStyle = col; ctx.lineWidth = 2.2 / s;
        // rotating dashed ring
        ctx.save();
        ctx.translate(px, py); ctx.rotate(rot);
        ctx.setLineDash([14 / s, 9 / s]);
        ctx.beginPath(); ctx.arc(0, 0, 34, 0, Math.PI * 2); ctx.stroke();
        ctx.restore();
        // pulsing outer ring
        ctx.globalAlpha = (1 - k) * .8;
        ctx.beginPath(); ctx.arc(px, py, 34 + k * 26, 0, Math.PI * 2); ctx.stroke();
        ctx.globalAlpha = 1;
        // corner brackets
        ctx.setLineDash([]);
        const r1 = 44, arm = 13;
        [[-1,-1],[1,-1],[1,1],[-1,1]].forEach(([sx, sy]) => {
            ctx.beginPath();
            ctx.moveTo(px + sx * r1, py + sy * (r1 - arm));
            ctx.lineTo(px + sx * r1, py + sy * r1);
            ctx.lineTo(px + sx * (r1 - arm), py + sy * r1);
            ctx.stroke();
        });
        // center dot
        ctx.fillStyle = col;
        ctx.beginPath(); ctx.arc(px, py, 2.5, 0, Math.PI * 2); ctx.fill();
    }

    function drawLabels(R, s) {
        ctx.fillStyle = css("--ink-3", "#94a3b8");
        ctx.font = "600 9px ui-monospace, monospace";
        ctx.textAlign = "center";
        const originX = R.x - view.winX * s;
        for (let m = 0; m <= S; m += 125) {
            const px = originX + m * s;
            if (px > R.x - 4 && px < R.x + R.size + 4)
                ctx.fillText(String(m), px, R.y + R.size + 14);
        }
    }

    function drawNorth(R) {
        ctx.save();
        ctx.translate(R.x + R.size - 18, R.y + 18);
        const acc = css("--accent", "#4f46e5");
        ctx.strokeStyle = acc; ctx.fillStyle = acc; ctx.lineWidth = 1.5;
        ctx.beginPath(); ctx.moveTo(0, 9); ctx.lineTo(0, -9); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(0, -13); ctx.lineTo(-3.6, -5.5); ctx.lineTo(3.6, -5.5);
        ctx.closePath(); ctx.fill();
        ctx.font = "800 9px sans-serif"; ctx.textAlign = "center";
        ctx.fillText("N", 0, -17);
        ctx.restore();
    }

    function pick(clientX, clientY) {
        const r = cv.getBoundingClientRect();
        const R = baseRect(r.width, r.height);
        const s = R.size * view.zoom / S;
        const mx = (clientX - r.left - (R.x - view.winX * s)) / s;
        const myN = S - (clientY - r.top - (R.y - view.winY * s)) / s;   // north meters
        const cx = Math.floor(mx / G.CELL_M), cy = Math.floor(myN / G.CELL_M);
        if (cx >= 0 && cx < G.GRID && cy >= 0 && cy < G.GRID &&
            clientX - r.left >= R.x - view.winX * s &&
            clientX - r.left <= R.x - view.winX * s + R.size) return { cx, cy };
        return null;
    }

    AVLF.MapTopo = {
        init, render, pick,
        focusCell(cx, cy) { focusCell(cx, cy, performance.now()); },
        recenterExtents() { recenterExtents(performance.now()); },
        resetView() { resetView(performance.now()); },
        setReticle(key, zone) { reticle = key ? { key, zone, t0: performance.now() } : null; },
        setOpts(patch) { Object.assign(opts, patch); },
        opts
    };
})(window.AVLF);
