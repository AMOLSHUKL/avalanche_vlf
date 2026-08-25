/**
 * AVALANCHE-VLF tactical command app — orchestrator.
 *
 * Owns: WebSocket ingestion (/ws/telemetry), link watchdog (LinkHealth),
 * golden-window clock, phase UI, triage surfaces (column + mobile sheet),
 * sensor fault injection, GIS toolbar + layers popover, bi-directional
 * map<->card targeting with the non-blocking DSP telemetry drawer.
 */
(function (AVLF) {
    "use strict";
    const $ = id => document.getElementById(id);

    AVLF.state = {
        gridSize: 100,
        cells: new Map(),
        uavs: [],
        directives: [],
        missionPhase: null,
        serverOffsetMs: 0,
        incidentEpochS: null,
        survival: 0,
        lastFrameAtMs: 0,
        linkState: "offline",
        selectedKey: null,
        mode: "2d"
    };
    for (let y = 0; y < 100; y++)
        for (let x = 0; x < 100; x++)
            AVLF.state.cells.set(`${x}_${y}`, {
                x, y, p: 0.01, zone: "P4",
                depth: null, radius: 2.6, mgrs: "", groups: []
            });

    /* ========================= WebSocket ========================= */
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    let ws = null;

    function connect() {
        ws = new WebSocket(`${proto}//${location.host}/ws/telemetry`);
        ws.onmessage = e => handleFrame(JSON.parse(e.data));
        ws.onclose = () => { setLink("offline", "LINK OFFLINE"); setTimeout(connect, 1500); };
        ws.onerror = () => ws.close();
    }

    function setLink(s, label) {
        const st = AVLF.state;
        if (st.linkState === s) return;
        st.linkState = s;
        const btn = $("linkBtn");
        btn.className = `link-dot-btn ${s}`;
        btn.title = label;
    }

    function handleFrame(msg) {
        if (msg.type !== "telemetry_frame") return;
        const st = AVLF.state;
        st.lastFrameAtMs = Date.now();
        setLink("live", "LINK LIVE · 10 Hz");
        st.uavs = msg.uav_telemetry || [];
        st.directives = msg.directives || [];
        if (msg.mission_clock) {
            st.serverOffsetMs = Date.now() - msg.mission_clock.server_epoch_s * 1000;
            st.incidentEpochS = msg.mission_clock.incident_epoch_s;
            st.survival = msg.mission_clock.survival_probability;
        }
        if (msg.mission_phase && msg.mission_phase !== st.missionPhase) {
            st.missionPhase = msg.mission_phase;
            updatePhases(msg.mission_phase);
        }
        let heatChanged = false;
        (msg.updated_zones || []).forEach(z => {
            const c = st.cells.get(`${z.cell_x}_${z.cell_y}`);
            if (!c) return;
            c.p = z.probability;
            c.zone = z.priority_zone;
            c.depth = z.burial_depth_estimate_m;
            c.radius = z.confidence_radius_m;
            c.mgrs = z.mgrs_coord || c.mgrs;
            c.groups = z.contributing_evidence_groups || [];
            if (c.zone !== "P4") heatChanged = true;
        });
        if (heatChanged) { AVLF.Fusion.render(); renderTargets(); }
    }

    setInterval(() => {
        if (AVLF.state.linkState === "offline") return;
        const v = LinkHealth.classify(AVLF.state.lastFrameAtMs, Date.now());
        if (v === "offline") setLink("offline", "LINK OFFLINE");
        else if (v === "stale")
            setLink("stale", `STALE +${((Date.now() - AVLF.state.lastFrameAtMs) / 1000).toFixed(1)}s`);
    }, 500);

    /* ==================== Phases + golden window ==================== */
    const PHASE_LABELS = ["PRE-FLIGHT", "SURFACE SCAN", "DEEP RADAR", "MARKER DROP", "SAR VECTOR"];
    // Sidebar list casing; acronyms stay uppercase.
    const PHASE_LIST_LABELS = ["Pre-flight", "Surface scan", "Deep radar", "Marker drop", "SAR vector"];
    const RING_C = 282.74;

    function buildPhaseUI() {
        PHASE_LABELS.forEach((label, i) => {
            const d = document.createElement("span");
            d.className = "pdot"; $("phaseDots").appendChild(d);
            const item = document.createElement("div");
            item.className = "ph-item";
            item.innerHTML = `<span class="n">${i + 1}</span>${PHASE_LIST_LABELS[i]}`;
            $("phaseList").appendChild(item);
        });
    }

    function updatePhases(phaseId) {
        const idx = AVLF.PHASE_ORDER.indexOf(phaseId);
        [...$("phaseDots").children].forEach((el, i) =>
            el.className = "pdot" + (i < idx ? " done" : i === idx ? " now" : ""));
        [...$("phaseList").children].forEach((el, i) =>
            el.className = "ph-item" + (i < idx ? " done" : i === idx ? " now" : ""));
        $("phaseChip").textContent =
            idx >= 0 ? `PHASE ${idx + 1}/5 · ${PHASE_LABELS[idx]}` : "PHASE —";
    }

    setInterval(() => {
        const st = AVLF.state;
        if (st.incidentEpochS === null) return;
        const elapsed = Math.max(0, (Date.now() - st.serverOffsetMs) / 1000 - st.incidentEpochS);
        const remain = Math.max(0, 900 - elapsed);
        const tier = elapsed <= 900 ? "" : elapsed <= 2100 ? "warn" : "crit";
        const t = `${String(Math.floor(remain / 60)).padStart(2, "0")}:${String(Math.floor(remain % 60)).padStart(2, "0")}`;
        const s = `${(st.survival * 100).toFixed(0)}%`;
        $("goldenPill").className = `golden-pill ${tier}`;
        $("ringCard").className = `ring-card ${tier}`;
        $("gTime").textContent = t;
        $("gTimeRing").textContent = t;
        $("gSurv").textContent = s;
        $("gSurvRing").textContent = s;
        $("ringFg").style.strokeDashoffset = (RING_C * (1 - remain / 900)).toFixed(1);
    }, 500);

    /* ======================= Triage rendering ======================= */
    function targetsSorted() {
        // Rank by posterior quantized to 0.5%: raw probabilities jitter at
        // telemetry rate, and two near-equal targets flipping rank every tick
        // thrashed the reconcile path into a continuous re-order loop.
        return [...AVLF.state.cells.values()]
            .filter(c => c.zone === "P1" || c.zone === "P2" || c.zone === "P3")
            .sort((a, b) => Math.round(b.p * 200) - Math.round(a.p * 200));
    }

    /* ---- Keyed card reconciliation ----
       Cards are DOM-persistent: created once per target, then patched field-
       by-field at telemetry rate. A full innerHTML swap at 10 Hz replayed the
       entry animation and destroyed hover/selection state — the panel glitch.
       `fresh` marks only genuinely new targets and is stripped on
       animationend: CSS animations restart whenever a node is re-inserted,
       so a surviving .fresh class would replay the rise on every reorder
       (the continuous flashing). */
    const seenCards = { desk: new Set(), sheet: new Set() };

    function buildCard(c, fresh) {
        const el = document.createElement("article");
        el.className = `tcard ${c.zone}${fresh ? " fresh" : ""}`;
        if (fresh)
            el.addEventListener("animationend", () => el.classList.remove("fresh"), { once: true });
        el.dataset.cell = `${c.x}_${c.y}`;
        el.innerHTML = `
            <div class="tc-strip"></div>
            <div class="tc-body">
                <div class="tc-row1">
                    <span class="tc-id">
                        <span class="zbadge"></span>
                        <span class="tc-coord">${c.x},${c.y}</span>
                        <span class="mgrs-tag"></span>
                    </span>
                    <span class="tc-prob"></span>
                </div>
                <div class="tc-meta">
                    <div>BURIAL Z <b data-f="depth"></b></div>
                    <div>RADIUS <b data-f="radius"></b></div>
                    <div>APPROACH <b data-f="az"></b></div>
                    <div>EVIDENCE <b style="font-family:var(--mono);font-size:10px" data-f="evi"></b></div>
                </div>
                <div class="tc-evi" data-f="mkrow" style="display:none"><b>DIRECTIVE ACTIVE</b><span class="mk-chip">MARKER 868 MHz</span></div>
                <div class="tc-dir" data-f="dir"></div>
                <button class="tc-btn" data-cell="${c.x}_${c.y}">INSPECT DSP TELEMETRY</button>
            </div>`;
        patchCard(el, c);
        return el;
    }

    function patchCard(el, c) {
        const dir = AVLF.state.directives.find(d => d.target_zone_id === `cell_${c.x}_${c.y}`);
        const q = sel => el.querySelector(sel);
        // Guarded writes: setting textContent to the same value still
        // invalidates layout — visible as churn at 10 Hz on a tablet.
        const set = (sel, v) => { const n = q(sel); if (n.textContent !== v) n.textContent = v; };
        set(".zbadge", c.zone);
        set(".mgrs-tag", c.mgrs || "MGRS…");
        set(".tc-prob", `${(c.p * 100).toFixed(1)}%`);
        set('[data-f="depth"]', c.depth != null ? c.depth.toFixed(2) + " m" : "—");
        set('[data-f="radius"]', `±${c.radius.toFixed(1)} m`);
        set('[data-f="az"]', dir ? dir.approach_azimuth_deg.toFixed(0) + "°" : "—");
        set('[data-f="evi"]',
            (c.groups && c.groups.length ? c.groups[0] : "—").toUpperCase());
        const mkRow = q('[data-f="mkrow"]');
        const mkShow = !!(dir && dir.marker_deployed);
        if (mkRow.style.display !== (mkShow ? "" : "none"))
            mkRow.style.display = mkShow ? "" : "none";
        set('[data-f="dir"]',
            dir ? dir.rationale : "Vector secondary orthogonal radar pass.");
        el.classList.toggle("selected", AVLF.state.selectedKey === el.dataset.cell);
        // Zone may upgrade/downgrade as fusion sharpens.
        ["P1", "P2", "P3"].forEach(z => el.classList.toggle(z, c.zone === z));
    }

    function reconcileQueue(container, targets, seen) {
        if (!container) return;
        const kids = [...container.children].filter(el => el.dataset && el.dataset.cell);
        // The queue column itself never scrolls — the surrounding .rc-scroll
        // (desktop) / .sheet-body (mobile) does. Anchor against the real
        // scroller or the correction is a no-op.
        const scroller = container.closest(".rc-scroll, .sheet-body") || container;

        // Scroll anchor: when order changes (a new target inserting at the
        // top is the common case), pin whatever card the reader is looking at
        // so the sensor toggles below the queue don't scroll out of reach.
        let anchorKey = null, anchorOff = 0;
        if (kids.length) {
            const sTop = scroller.getBoundingClientRect().top;
            const anchor = kids.find(el =>
                el.getBoundingClientRect().bottom >= sTop - 4) || kids[0];
            anchorKey = anchor.dataset.cell;
            anchorOff = anchor.getBoundingClientRect().top - sTop;
        }

        // Fast path: identical key order → patch fields in place. Never touch
        // the DOM structure here: re-inserting nodes at telemetry rate killed
        // hover state and jittered the scrollbar (the lingering panel glitch).
        const sameOrder = kids.length === targets.length &&
            kids.every((el, i) => el.dataset.cell === `${targets[i].x}_${targets[i].y}`);
        if (sameOrder) {
            targets.forEach((c, i) => patchCard(kids[i], c));
            return;
        }

        const byKey = new Map(kids.map(el => [el.dataset.cell, el]));
        const frag = document.createDocumentFragment();
        const keep = new Set();
        targets.forEach(c => {
            const key = `${c.x}_${c.y}`;
            keep.add(key);
            let el = byKey.get(key);
            const isNew = !seen.has(key);
            seen.add(key);
            if (!el) el = buildCard(c, isNew);
            else patchCard(el, c);
            frag.appendChild(el);          // moves existing nodes → stable order
        });
        container.replaceChildren(frag);
        byKey.forEach((el, key) => {
            if (!keep.has(key)) { el.remove(); seen.delete(key); }
        });
        // Restore the reader's place: shift the scroller so the anchored card
        // sits exactly where it did before the reorder.
        if (anchorKey) {
            const el = [...container.children].find(ch => ch.dataset.cell === anchorKey);
            if (el) {
                const d = el.getBoundingClientRect().top -
                    scroller.getBoundingClientRect().top - anchorOff;
                if (Math.abs(d) > 1) scroller.scrollTop += d;
            }
        }
    }

    let emptyShown = false;
    let lastScrolledKey = null;
    function renderTargets() {
        const targets = targetsSorted();
        reconcileQueue($("queueDesk"), targets, seenCards.desk);
        reconcileQueue($("queueSheet"), targets, seenCards.sheet);

        const emptyHtml =
            `<div class="empty-state">Autonomous lawn-mower survey running.<br>The fused posterior builds as UAVs sweep the sector.</div>`;
        if (!targets.length) {
            if (!emptyShown) {
                emptyShown = true;
                seenCards.desk.clear(); seenCards.sheet.clear();
                $("queueDesk").innerHTML = emptyHtml;
                $("queueSheet").innerHTML = emptyHtml;
            }
        } else emptyShown = false;
        $("qCount").textContent = `${targets.length} TARGET${targets.length === 1 ? "" : "S"}`;
        $("qCountSheet").textContent = String(targets.length);

        // Scroll to selection once per target change — never per telemetry tick.
        if (AVLF.state.selectedKey !== lastScrolledKey) {
            lastScrolledKey = AVLF.state.selectedKey;
            if (AVLF.state.selectedKey) {
                const scope = window.innerWidth >= 1024 ? $("queueDesk") : $("queueSheet");
                const el = [...scope.children].find(
                    ch => ch.dataset && ch.dataset.cell === AVLF.state.selectedKey);
                if (el && !isFullyVisible(el))
                    el.scrollIntoView({ block: "nearest", behavior: "smooth" });
            }
        }
        updatePeek(targets);
    }

    function isFullyVisible(el) {
        const r = el.getBoundingClientRect();
        const p = el.parentElement.getBoundingClientRect();
        return r.top >= p.top - 4 && r.bottom <= p.bottom + 4;
    }

    let lastPeekSig = "";
    function updatePeek(targets) {
        const el = $("peekTarget");
        const top = targets[0];
        const sig = top ? `${top.x}_${top.y}:${top.zone}` : "empty";
        if (!top) {
            if (sig !== lastPeekSig) {
                lastPeekSig = sig;
                delete el.dataset.built;   // spans are gone with the empty state
                el.innerHTML = `<span class="peek-empty">Survey running — posterior building…</span>`;
            }
            return;
        }
        // Persistent nodes: identity/zone changes patch in place; the live
        // probability updates every tick as a bare text write (no innerHTML
        // swap — rebuilding this row at 10 Hz read as panel flashing).
        if (sig !== lastPeekSig) {
            lastPeekSig = sig;
            if (!el.dataset.built) {
                el.innerHTML =
                    `<span class="peek-zone"></span><span class="peek-name"></span><span class="peek-prob"></span>`;
                el.dataset.built = "1";
            }
            const z = el.querySelector(".peek-zone");
            z.textContent = top.zone;
            z.className = `peek-zone ${top.zone.toLowerCase()}`;
            el.querySelector(".peek-name").textContent = `CELL ${top.x},${top.y}`;
        }
        const prob = el.querySelector(".peek-prob");
        const txt = `${(top.p * 100).toFixed(0)}%`;
        if (prob.textContent !== txt) prob.textContent = txt;
        prob.style.color =
            `var(${top.zone === "P1" ? "--p1" : top.zone === "P2" ? "--p2" : "--p3"})`;
    }

    /* ============ Bi-directional targeting + DSP drawer ============ */
    let dspRaf = null;
    const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;

    function openTarget(key, opts) {
        const c = AVLF.state.cells.get(key);
        if (!c || c.zone === "P4") return;
        const focus = !opts || opts.focus !== false;
        AVLF.state.selectedKey = key;

        // Focus + reticle on whichever view is live (both stay consistent).
        if (focus) {
            if (AVLF.state.mode === "3d") AVLF.Relief3D.focusCell(c.x, c.y);
            else AVLF.MapTopo.focusCell(c.x, c.y);
        }
        AVLF.MapTopo.setReticle(key);

        populateDrawer(c);
        setDrawer(true);
        renderTargets();                 // selection ring + marker LOD refresh
    }

    function populateDrawer(c) {
        const locked = c.p >= 0.85;
        $("mTitle").textContent = `TARGET ANALYTICS · CELL_${c.x}_${c.y}`;
        $("mSub").textContent =
            `MGRS ${c.mgrs || "PENDING"} · BURIAL Z ${c.depth != null ? c.depth.toFixed(2) : "—"} m · POSTERIOR ${(c.p * 100).toFixed(1)}%`;
        $("dStat").textContent = locked ? "RESPIRATION LOCKED" : "SCANNING";
        $("dFreq").textContent = locked ? "0.28 Hz · 17 bpm" : "no periodicity";
        $("mDepth").textContent = `${c.depth != null ? c.depth.toFixed(2) : "—"} m`;
        $("dTwt").textContent = c.depth != null ? `${(c.depth * 3.8).toFixed(1)} ns` : "—";
        const perm = locked ? 52.5 : c.p >= .45 ? 34 : 12;
        $("permFill").style.width = `${(perm / 55) * 100}%`;
        $("permNote").innerHTML =
            `Signature ε<sub>r</sub> ≈ <b>${perm}</b>` +
            (locked ? " — high water-content anomaly consistent with a living subject."
                    : " — below tissue-confidence threshold.");
        const dir = AVLF.state.directives.find(d => d.target_zone_id === `cell_${c.x}_${c.y}`);
        $("mAz").textContent = dir
            ? `${dir.approach_azimuth_deg.toFixed(1)}° contour traverse`
            : locked ? "computing…" : "awaiting P1 lock";
        const mk = $("mMk");
        mk.textContent = dir && dir.marker_deployed ? "DEPLOYED [868.2 MHz]" : "STANDBY";
        mk.className = dir && dir.marker_deployed ? "go" : "";
        runDsp(locked);
    }

    function setDrawer(open) {
        $("dspDrawer").classList.toggle("open", open);
        // Desktop: shift the GIS bar clear of the drawer (CSS transition).
        document.body.classList.toggle("drawer-open", open && window.innerWidth >= 1024);
        $("drawerBackdrop").classList.toggle("show",
            open && window.innerWidth <= 1023);
    }
    function closeDrawer() { setDrawer(false); if (dspRaf) cancelAnimationFrame(dspRaf); }

    /* Graceful dismissal: close the drawer AND reset targeting highlights
       (selection, reticle, marker dimming) so no state is left dangling. */
    function dismissTargeting() {
        AVLF.state.selectedKey = null;
        AVLF.MapTopo.setReticle(null);
        renderTargets();
        closeDrawer();
    }

    $("mClose").addEventListener("click", dismissTargeting);
    $("drawerBackdrop").addEventListener("click", dismissTargeting);
    // Orbit drags on the map end with a click event too — a pointer that
    // travelled is NOT an outside-dismiss click.
    let pressOrigin = null;
    addEventListener("pointerdown", e => { pressOrigin = [e.clientX, e.clientY]; }, true);
    function wasDrag(e) {
        return pressOrigin &&
            Math.hypot(e.clientX - pressOrigin[0], e.clientY - pressOrigin[1]) > 7;
    }

    document.addEventListener("click", e => {
        // Outside-click dismissal on desktop (mobile uses the backdrop).
        const drawer = $("dspDrawer");
        if (!drawer.classList.contains("open") || window.innerWidth < 1024) return;
        if (wasDrag(e)) return;
        if (e.target.closest("#dspDrawer")) return;
        if (e.target.closest("[data-cell]")) return;      // retargeting click
        if (e.target.closest(".sen-chip") || e.target.closest("#gisBar") ||
            e.target.closest("#layersPop")) return;
        dismissTargeting();
    });
    $("focusTargetBtn").addEventListener("click", () => {
        const k = AVLF.state.selectedKey;
        if (!k) return;
        const c = AVLF.state.cells.get(k);
        if (AVLF.state.mode === "3d") AVLF.Relief3D.focusCell(c.x, c.y);
        else AVLF.MapTopo.focusCell(c.x, c.y);
    });

    document.addEventListener("click", e => {
        const cellEl = e.target.closest("[data-cell]");
        if (cellEl) openTarget(cellEl.dataset.cell);
        const chip = e.target.closest(".sen-chip");
        if (chip) toggleSensor(chip.dataset.sensor, chip);
    });

    addEventListener("keydown", e => {
        if (e.key === "Escape") {
            dismissTargeting();
            setSheet(false);
            closePopover();
        }
    });

    /* Orientation gizmo (corner compass) — same reset as the toolbar button. */
    $("orientGizmo").addEventListener("click", () => {
        AVLF.MapTopo.resetView();
        AVLF.Relief3D.resetNorthUp();
    });

    /* ====================== Sensor fault injection ====================== */
    const SENSORS = [
        ["TRANSCEIVER_457", "457 kHz"], ["MOBILE_RF", "IMSI"], ["GPR", "UWB GPR"],
        ["THERMAL_IR", "THERMAL"], ["SEISMIC_ACOUSTIC", "SEISMIC"], ["RECCO", "RECCO"],
        ["RGB_VISUAL", "RGB"]
    ];

    function buildSensors() {
        const chip = ([id, name]) =>
            `<button class="sen-chip" data-sensor="${id}" aria-pressed="false">${name}</button>`;
        $("sensorsDesk").innerHTML = SENSORS.map(chip).join("");
        $("sensorsSheet").innerHTML = SENSORS.map(chip).join("");
    }

    async function toggleSensor(sensorId, btn) {
        const faulted = !btn.classList.contains("fault");
        document.querySelectorAll(`.sen-chip[data-sensor="${sensorId}"]`).forEach(b => {
            b.classList.toggle("fault", faulted);
            b.setAttribute("aria-pressed", String(faulted));
        });
        updateFaultCounts();
        try {
            const res = await fetch("/api/inject-failure", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ sensor_type: sensorId, is_disabled: faulted })
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
        } catch (err) {
            // Revert optimistic state so the UI never lies about sensor health.
            document.querySelectorAll(`.sen-chip[data-sensor="${sensorId}"]`).forEach(b => {
                b.classList.toggle("fault", !faulted);
                b.setAttribute("aria-pressed", String(!faulted));
            });
            updateFaultCounts();
            console.error("Fault injection failed:", err);
        }
    }

    function updateFaultCounts() {
        const faults = document.querySelectorAll(".sen-chip.fault").length / 2;
        const nominal = SENSORS.length - faults;
        $("sCount").textContent = `${nominal}/7`;
        $("sCountSheet").textContent = `${nominal}/7 ${nominal === 7 ? "NOMINAL" : "DEGRADED"}`;
        // The incident card's fusion line must track reality: a faulted
        // sensor stream is no longer part of the fusion input.
        const fc = $("fusionCount");
        fc.textContent = `${nominal} MODALITIES`;
        fc.classList.toggle("warn", nominal < SENSORS.length);
    }

    /* ===================== Bottom sheet mechanics ===================== */
    const sheet = $("targetSheet"), backdrop = $("sheetBackdrop");

    function setSheet(open) {
        sheet.classList.toggle("open", open);
        $("mapPane").classList.toggle("sheet-open", open);
        backdrop.classList.toggle("show", open && window.innerWidth <= 640);
    }
    $("sheetGrip").addEventListener("click", () => setSheet(!sheet.classList.contains("open")));
    $("sheetPeekRow").addEventListener("click", () => setSheet(!sheet.classList.contains("open")));
    backdrop.addEventListener("click", () => setSheet(false));

    /* ===================== GIS toolbar + layers ===================== */
    const pop = $("layersPop");

    function closePopover() {
        pop.classList.remove("open");
        $("tbLayers").classList.remove("on");
        $("tbLayers").setAttribute("aria-expanded", "false");
    }
    $("tbLayers").addEventListener("click", e => {
        e.stopPropagation();
        const opening = !pop.classList.contains("open");
        pop.classList.toggle("open", opening);
        $("tbLayers").classList.toggle("on", opening);
        $("tbLayers").setAttribute("aria-expanded", String(opening));
    });
    $("popClose").addEventListener("click", closePopover);
    document.addEventListener("click", e => {
        if (pop.classList.contains("open") &&
            !e.target.closest("#layersPop") && !e.target.closest("#tbLayers"))
            closePopover();
    });

    const MODALITY_KEYS = [
        ["lyVlf", "VLF"], ["lyGpr", "GPR"], ["lyThermal", "THERMAL"],
        ["lyRecco", "RECCO"], ["lyRgb", "RGB"]
    ];
    MODALITY_KEYS.forEach(([id, key]) => {
        $(id).addEventListener("change", e => AVLF.Fusion.setModality(key, e.target.checked));
    });
    $("fusionOpacity").addEventListener("input", e => {
        const v = e.target.value / 100;
        $("fusionOpacityVal").textContent = `${e.target.value}%`;
        AVLF.Fusion.setOpacity(v);
        AVLF.Relief3D.setFusionOpacity(v);
    });
    $("swGrid").addEventListener("change", e => {
        AVLF.MapTopo.setOpts({ grid: e.target.checked });
        AVLF.Relief3D.setGrid(e.target.checked);
    });
    $("swContours").addEventListener("change", e => {
        AVLF.MapTopo.setOpts({ contours: e.target.checked });
        AVLF.Relief3D.setContours(e.target.checked);
    });
    $("swVectors").addEventListener("change", e => {
        AVLF.MapTopo.setOpts({ vectors: e.target.checked });
        AVLF.Relief3D.setVectors(e.target.checked);
    });

    $("tbRecenter").addEventListener("click", () => {
        AVLF.MapTopo.recenterExtents();
        AVLF.Relief3D.recenterExtents();
        flashBtn($("tbRecenter"));
    });
    $("tbNorth").addEventListener("click", () => {
        AVLF.MapTopo.resetView();
        AVLF.Relief3D.resetNorthUp();
        flashBtn($("tbNorth"));
    });
    $("tbSlope").addEventListener("click", () => {
        const on = !$("tbSlope").classList.contains("on");
        $("tbSlope").classList.toggle("on", on);
        $("tbSlope").setAttribute("aria-pressed", String(on));
        AVLF.MapTopo.setOpts({ slope: on });
        AVLF.Relief3D.setSlopeOverlay(on);
    });
    function flashBtn(btn) {
        btn.classList.add("on");
        setTimeout(() => { if (btn.id !== "tbLayers") btn.classList.remove("on"); }, 700);
    }

    /* ===================== Map modes ===================== */
    function setMode(mode) {
        AVLF.state.mode = mode;
        $("mapPane").classList.toggle("mode3d", mode === "3d");
        $("chipPlan").classList.toggle("on", mode === "2d");
        $("chipRelief").classList.toggle("on", mode === "3d");
        AVLF.Relief3D.setActive(mode === "3d");
        if (mode === "2d") {
            // The 2D view is fixed north-up; drop any tilt the 3D camera left
            // on the gizmo so the indicator always matches the live view.
            const tilt = $("gizmoTilt"), rose = $("gizmoRose");
            if (tilt) tilt.textContent = "0°";
            if (rose) rose.style.transform = "rotate(0deg)";
        }
    }
    $("chipPlan").addEventListener("click", () => setMode("2d"));
    $("chipRelief").addEventListener("click", () => setMode("3d"));

    function bindPick(canvasEl, pickFn) {
        let down = null;
        canvasEl.addEventListener("pointerdown", e => { down = [e.clientX, e.clientY]; });
        canvasEl.addEventListener("pointerup", e => {
            if (!down) return;
            const moved = Math.hypot(e.clientX - down[0], e.clientY - down[1]);
            down = null;
            if (moved > 7) return;
            const hit = pickFn(e.clientX, e.clientY);
            if (hit) openTarget(`${hit.cx}_${hit.cy}`, { focus: false });
        });
    }

    /* ========================= Theme ========================= */
    function applyTheme(pref) {
        const root = document.documentElement;
        if (pref === "dark") root.setAttribute("data-theme", "dark");
        else root.removeAttribute("data-theme");
        $("thMoon").style.display = pref === "dark" ? "none" : "";
        $("thSun").style.display = pref === "dark" ? "" : "none";
        AVLF.Relief3D.applyTheme(pref === "dark");
        AVLF.Fusion.render();   // blob colors come from tokens
        try { localStorage.setItem("avlf-theme", pref); } catch (_) {}
    }
    $("themeBtn").addEventListener("click", () => {
        applyTheme(document.documentElement.getAttribute("data-theme") === "dark"
            ? "light" : "dark");
    });

    /* ========================= DSP canvases ========================= */
    function setupCv(cv) {
        const dpr = Math.min(devicePixelRatio, 2);
        const w = Math.max(120, cv.clientWidth || 300);
        cv.width = w * dpr; cv.height = 112 * dpr;
        const ctx = cv.getContext("2d");
        ctx.scale(dpr, dpr);
        return { ctx, w };
    }

    function runDsp(locked) {
        const dop = $("dopCv"), gpr = $("gprCv");
        const { ctx: dc, w: dw } = setupCv(dop);
        const { ctx: gc, w: gw } = setupCv(gpr);
        gc.fillStyle = "#0b1220"; gc.fillRect(0, 0, gw, 112);
        gc.strokeStyle = "rgba(140,170,210,.22)"; gc.lineWidth = 1;
        for (let y = 12; y < 112; y += 15) { gc.beginPath(); gc.moveTo(0, y); gc.lineTo(gw, y); gc.stroke(); }
        gc.strokeStyle = "#67c3ff"; gc.lineWidth = 2.2;
        gc.shadowColor = "#67c3ff"; gc.shadowBlur = 6;
        gc.beginPath();
        for (let x = -gw * .26; x <= gw * .26; x += 2) {
            const y = 54 + Math.sqrt(x * x * .42);
            x === -gw * .26 ? gc.moveTo(gw / 2 + x, y) : gc.lineTo(gw / 2 + x, y);
        }
        gc.stroke(); gc.shadowBlur = 0;

        function wave(t) {
            dc.fillStyle = "#0b1220"; dc.fillRect(0, 0, dw, 112);
            dc.strokeStyle = "rgba(140,170,210,.18)";
            dc.beginPath(); dc.moveTo(0, 56); dc.lineTo(dw, 56); dc.stroke();
            dc.strokeStyle = locked ? "#34d399" : "#5f7389"; dc.lineWidth = 2;
            dc.beginPath();
            const amp = locked ? 27 : 4.5, sp = locked ? 2.8 : 1.1;
            for (let px = 0; px <= dw; px++) {
                const ph = px * .042 - t * sp;
                const py = 56 + Math.sin(ph) * amp + Math.sin(ph * 3) * amp * .12;
                px === 0 ? dc.moveTo(px, py) : dc.lineTo(px, py);
            }
            dc.stroke();
            dspRaf = requestAnimationFrame(wave);
        }
        if (dspRaf) cancelAnimationFrame(dspRaf);
        REDUCED ? wave(0) : requestAnimationFrame(wave);
    }

    /* ========================= Boot + loop ========================= */
    AVLF.PHASE_ORDER = [
        "ALERT_PREFLIGHT", "LAWNMOWER_SURFACE_SCAN", "DEEP_RADAR_SCAN",
        "TARGET_VERIFICATION_MARKER_DROP", "SAR_VECTORING"
    ];
    AVLF.openTarget = openTarget;

    AVLF.boot = function () {
        let stored = null;
        try { stored = localStorage.getItem("avlf-theme"); } catch (_) {}
        const dark = stored ||
            (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");

        AVLF.MapTopo.init($("cv2d"));
        AVLF.Fusion.render();
        AVLF.Relief3D.init($("cv3d"));
        applyTheme(dark);
        bindPick($("cv2d"), (x, y) => AVLF.MapTopo.pick(x, y));
        bindPick($("cv3d"), (x, y) => AVLF.Relief3D.pick(x, y));
        buildPhaseUI();
        buildSensors();
        renderTargets();
        connect();

        function loop(now) {
            requestAnimationFrame(loop);
            if (document.hidden) return;
            if (AVLF.state.mode === "2d") AVLF.MapTopo.render(now);
            else AVLF.Relief3D.render(now);
        }
        requestAnimationFrame(loop);
    };

    if (document.readyState === "loading")
        document.addEventListener("DOMContentLoaded", AVLF.boot);
    else AVLF.boot();
})(window.AVLF);
