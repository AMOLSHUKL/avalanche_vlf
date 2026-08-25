/**
 * AVLF.Fusion — single source of truth for the fused posterior heat layer.
 *
 * Renders probability blobs into an offscreen 1024² canvas that both the 2D
 * topo map (composited over hillshade) and the 3D relief engine (CanvasTexture
 * projection) consume, so modality filtering and opacity behave identically
 * across views.
 *
 * Modality checkboxes filter by each target's contributing evidence groups.
 * A cell with no checkboxable evidence is treated as core posterior and stays
 * faintly visible — the map must never hide a locked target entirely.
 */
window.AVLF = window.AVLF || {};
(function (AVLF) {
    "use strict";
    const SIZE = 1024, PX = SIZE / AVLF.GEO.GRID;

    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = SIZE;
    const ctx = canvas.getContext("2d");

    const MODALITY_PATTERNS = {
        VLF: /457|VLF/i,
        GPR: /GPR/i,
        THERMAL: /THERMAL/i,
        RECCO: /RECCO/i,
        RGB: /RGB|OPTICAL/i
    };

    const layerState = {
        modalities: { VLF: true, GPR: true, THERMAL: true, RECCO: true, RGB: true },
        opacity: 1.0,
        version: 0
    };

    function zoneColor(zone) {
        const s = getComputedStyle(document.documentElement);
        return zone === "P1" ? s.getPropertyValue("--p1").trim() || "#dc2626"
             : zone === "P2" ? s.getPropertyValue("--p2").trim() || "#d97706"
             : s.getPropertyValue("--p3").trim() || "#0284c7";
    }
    function hexA(hex, a) {
        if (!hex.startsWith("#")) return hex;
        const n = parseInt(hex.slice(1), 16);
        return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
    }

    // How much of a cell's evidence survives the active-modality filter?
    function matchRatio(groups) {
        const list = groups && groups.length ? groups : [];
        let matched = 0, checkable = 0;
        for (const g of list) {
            let isCheckable = false;
            for (const key in MODALITY_PATTERNS) {
                if (MODALITY_PATTERNS[key].test(g)) {
                    isCheckable = true;
                    if (layerState.modalities[key]) { matched++; break; }
                }
            }
            if (isCheckable) checkable++;
        }
        if (!checkable) return { visible: true, intensity: 0.5 };   // core posterior
        if (!matched) return { visible: false, intensity: 0 };
        return { visible: true, intensity: 0.4 + 0.6 * (matched / checkable) };
    }

    function render() {
        const state = AVLF.state;
        ctx.clearRect(0, 0, SIZE, SIZE);
        ctx.globalAlpha = layerState.opacity;
        state.cells.forEach(c => {
            if (c.zone === "P4" || c.p < 0.02) return;
            const m = matchRatio(c.groups);
            if (!m.visible) return;
            const col = zoneColor(c.zone);
            const px = c.x * PX + PX / 2, py = (AVLF.GEO.GRID - 1 - c.y) * PX + PX / 2;
            // Wide soft halos (P1 ≈ 90 m, P2 ≈ 60 m, P3 ≈ 40 m radius) — the
            // legible victim-signature glow; tight dots read as map noise.
            const rad = (c.zone === "P1" ? 95 : c.zone === "P2" ? 64 : 44) *
                        (0.8 + 0.2 * m.intensity);
            const grad = ctx.createRadialGradient(px, py, rad * .08, px, py, rad);
            grad.addColorStop(0, hexA(col, Math.min(.95, (.26 + .7 * c.p) * m.intensity)));
            grad.addColorStop(1, hexA(col, 0));
            ctx.fillStyle = grad;
            ctx.beginPath(); ctx.arc(px, py, rad, 0, Math.PI * 2); ctx.fill();
        });
        ctx.globalAlpha = 1;
        layerState.version++;
        // Immediate GPU upload on the terrain shader (late-bound: fusion.js
        // loads before relief3d.js).
        if (AVLF.Relief3D && AVLF.Relief3D.flagFusionDirty) AVLF.Relief3D.flagFusionDirty();
    }

    function setModality(key, on) {
        layerState.modalities[key] = on;
        render();
    }
    function setOpacity(v) {
        layerState.opacity = v;
        render();
    }

    AVLF.Fusion = { canvas, render, setModality, setOpacity, layerState };
})(window.AVLF);
