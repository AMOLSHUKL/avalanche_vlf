/**
 * AVALANCHE-VLF Tactical Command Dashboard Logic
 * Inverted Canvas Y-Axis for North-Up Alignment, 5-Phase Mission Tracking,
 * 15-Minute Asphyxiation Countdown, and Micro-Doppler / GPR DSP Inspector.
 */

const canvas = document.getElementById("radarCanvas");
const ctx = canvas.getContext("2d");
const queueEl = document.getElementById("triageQueue");
const triageCountEl = document.getElementById("triageCount");
const countdownEl = document.getElementById("goldenCountdown");
const survivalEl = document.getElementById("survivalProb");

const state = {
    gridSize: 100,
    cellSizePx: canvas.width / 100,
    cells: new Map(),
    uavs: [],
    directives: [],
    missionPhase: "ALERT_PREFLIGHT",
    // Server-anchored survival clock: offset between browser time and
    // backend wall-clock, refreshed on every telemetry frame.
    serverClockOffsetMs: 0,
    incidentEpochS: null,
    lastSurvivalProbability: 0.92,
    selectedTarget: null,
    // Telemetry link health: a frozen stream must never read as current.
    lastFrameAtMs: 0,
    linkState: "offline",  // offline | live | stale
    faults: {
        TRANSCEIVER_457: false,
        MOBILE_RF: false,
        GPR: false,
        THERMAL_IR: false,
        SEISMIC_ACOUSTIC: false,
        RECCO: false,
        RGB_VISUAL: false
    }
};

const linkPill = document.getElementById("linkStatus");
const linkText = document.getElementById("linkStatusText");

function setLinkState(newState, label) {
    if (state.linkState === newState) return;
    state.linkState = newState;
    linkPill.className = `link-pill ${newState}`;
    linkText.innerText = label;
}

function setLinkOffline() {
    state.lastFrameAtMs = 0;
    setLinkState("offline", "LINK OFFLINE");
}

// Initialize Grid Data Model (Ladakh Sector: UTM Zone 43S, square GT)
for (let y = 0; y < state.gridSize; y++) {
    for (let x = 0; x < state.gridSize; x++) {
        state.cells.set(`${x}_${y}`, {
            x, y,
            p: 0.01,
            zone: "P4",
            depth: null,
            radius: 1.0,
            // Populated with true 10-digit MGRS from the server on first update.
            mgrs: "",
            azimuth: 0.0,
            markerDeployed: false,
            permittivity: 3.2,
            groups: []
        });
    }
}

// WebSocket Connection with Resilient Auto-Reconnect
const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
const wsEndpoint = `${proto}//${window.location.host}/ws/telemetry`;
let ws;

function initWebSocket() {
    ws = new WebSocket(wsEndpoint);
    
    ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        if (msg.type === "telemetry_frame") {
            state.lastFrameAtMs = Date.now();
            setLinkState("live", "LINK LIVE");
            state.uavs = msg.uav_telemetry || [];
            state.directives = msg.directives || [];

            if (msg.mission_clock) {
                state.serverClockOffsetMs = Date.now() - (msg.mission_clock.server_epoch_s * 1000.0);
                state.incidentEpochS = msg.mission_clock.incident_epoch_s;
                state.lastSurvivalProbability = msg.mission_clock.survival_probability;
            }

            if (msg.mission_phase) {
                state.missionPhase = msg.mission_phase;
                updatePhaseRibbon(msg.mission_phase);
            }
            
            if (msg.updated_zones) {
                msg.updated_zones.forEach(z => {
                    const key = `${z.cell_x}_${z.cell_y}`;
                    const current = state.cells.get(key) || {};
                    state.cells.set(key, {
                        ...current,
                        x: z.cell_x,
                        y: z.cell_y,
                        p: z.probability,
                        zone: z.priority_zone,
                        depth: z.burial_depth_estimate_m,
                        radius: z.confidence_radius_m,
                        mgrs: z.mgrs_coord || current.mgrs,
                        groups: z.contributing_evidence_groups || []
                    });
                });
            }

            // Sync directives into target cells
            state.directives.forEach(d => {
                const zoneKey = d.target_zone_id.replace("cell_", "");
                const zone = state.cells.get(zoneKey);
                if (zone) {
                    zone.azimuth = d.approach_azimuth_deg;
                    zone.markerDeployed = d.marker_deployed;
                }
            });

            renderTriageQueue();
        }
    };

    ws.onclose = () => {
        setLinkOffline();
        setTimeout(initWebSocket, 1500);
    };

    ws.onerror = () => {
        ws.close();
    };
}

initWebSocket();

// Link-health watchdog: frames arriving at 10 Hz must never silently stop.
// Classification lives in frontend/link_state.js (shared with the test suite).
setInterval(() => {
    if (state.linkState === "offline") return;
    const verdict = LinkHealth.classify(state.lastFrameAtMs, Date.now());
    if (verdict === "offline") {
        setLinkState("offline", "LINK OFFLINE");
    } else if (verdict === "stale") {
        const silentForMs = Date.now() - state.lastFrameAtMs;
        setLinkState("stale", `STALE +${Math.round(silentForMs / 100) / 10}s`);
    }
}, 500);

// Phase Ribbon Updater
const PHASES = [
    "ALERT_PREFLIGHT",
    "LAWNMOWER_SURFACE_SCAN",
    "DEEP_RADAR_SCAN",
    "TARGET_VERIFICATION_MARKER_DROP",
    "SAR_VECTORING"
];

function updatePhaseRibbon(activePhase) {
    const activeIdx = PHASES.indexOf(activePhase);
    PHASES.forEach((p, idx) => {
        const el = document.getElementById(`phase-${p}`);
        if (!el) return;
        el.className = "phase-step";
        if (idx < activeIdx) el.classList.add("complete");
        else if (idx === activeIdx) el.classList.add("active");
    });
}

// 15-Minute Survival Countdown, anchored to the server incident clock.
// survival_probability arrives inside every telemetry frame (10 Hz) computed
// by the backend tri-phase model; the browser never re-implements it.
setInterval(() => {
    if (state.incidentEpochS === null) return;
    const elapsedSec = Math.max(0.0, serverNowSec() - state.incidentEpochS);
    const remainingSec = Math.max(0, (15 * 60) - elapsedSec);
    const mins = Math.floor(remainingSec / 60);
    const secs = Math.floor(remainingSec % 60);
    countdownEl.innerText = `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;

    const elapsedMin = elapsedSec / 60;
    let color;
    if (elapsedMin <= 15.0) {
        color = "var(--golden-green)";
    } else if (elapsedMin <= 35.0) {
        color = "var(--golden-amber)";
    } else {
        color = "var(--golden-red)";
    }
    countdownEl.style.color = color;
    survivalEl.style.color = color;
    survivalEl.innerText = `${(state.lastSurvivalProbability * 100).toFixed(1)}%`;
}, 500);

function serverNowSec() {
    return (Date.now() - state.serverClockOffsetMs) / 1000.0;
}

// Topographic Map Drawing Loop (North-Up)
function draw() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // Topographic Grid Lines
    ctx.strokeStyle = "#131b26";
    ctx.lineWidth = 0.5;
    for (let i = 0; i <= canvas.width; i += state.cellSizePx * 10) {
        ctx.beginPath();
        ctx.moveTo(i, 0); ctx.lineTo(i, canvas.height);
        ctx.moveTo(0, i); ctx.lineTo(canvas.width, i);
        ctx.stroke();
    }

    // Grid coordinate labels every 50 m along both edges
    ctx.fillStyle = "#3d4c5e";
    ctx.font = "9px monospace";
    for (let g = 0; g <= state.gridSize; g += 10) {
        const label = `${g * 5}`;
        const px = Math.min(g * state.cellSizePx + 3, canvas.width - 26);
        ctx.fillText(label, px, canvas.height - 4);          // east axis
        const py = Math.min(canvas.height - g * state.cellSizePx - 3, canvas.height - 8);
        ctx.fillText(label, 3, Math.max(py, 10));            // north axis
    }

    // Rotating radar sweep (decorative scan cue, skipped if unsupported)
    if (typeof ctx.createConicGradient === "function") {
        const now = performance.now() / 1000;
        const sweepAngle = (now * 0.9) % (Math.PI * 2);
        const gradient = ctx.createConicGradient(sweepAngle, canvas.width / 2, canvas.height / 2);
        gradient.addColorStop(0.0, "rgba(57, 197, 207, 0.10)");
        gradient.addColorStop(0.08, "rgba(57, 197, 207, 0.0)");
        gradient.addColorStop(1.0, "rgba(57, 197, 207, 0.0)");
        ctx.fillStyle = gradient;
        ctx.fillRect(0, 0, canvas.width, canvas.height);
    }

    // Heatmaps with North-Up Coordinate Transformation: py = height - (y+1)*size
    const tSec = Date.now() / 1000;
    state.cells.forEach(c => {
        if (c.p >= 0.15) {
            const px = c.x * state.cellSizePx;
            const py = canvas.height - ((c.y + 1) * state.cellSizePx);

            if (c.zone === "P1") {
                // Pulsing containment ring: breathes at ~1 Hz around target
                const pulseR = (c.radius || 0.7) * 9 + Math.sin(tSec * Math.PI * 2) * 4;
                ctx.fillStyle = `rgba(248, 81, 73, ${Math.min(0.95, c.p)})`;
                ctx.fillRect(px - state.cellSizePx * 0.5, py - state.cellSizePx * 0.5, state.cellSizePx * 2, state.cellSizePx * 2);
                ctx.strokeStyle = `rgba(248, 81, 73, ${0.55 + 0.35 * Math.sin(tSec * Math.PI * 2)})`;
                ctx.lineWidth = 2;
                ctx.beginPath();
                ctx.arc(px + state.cellSizePx * 0.5, py + state.cellSizePx * 0.5, pulseR, 0, Math.PI * 2);
                ctx.stroke();
            } else if (c.zone === "P2") {
                ctx.fillStyle = `rgba(210, 153, 34, ${Math.min(0.75, c.p)})`;
                ctx.fillRect(px, py, state.cellSizePx * 1.5, state.cellSizePx * 1.5);
            } else if (c.zone === "P3") {
                ctx.fillStyle = `rgba(88, 166, 255, ${c.p * 0.4})`;
                ctx.fillRect(px, py, state.cellSizePx, state.cellSizePx);
            }
        }
    });

    // Multi-UAV Asset Overlays
    state.uavs.forEach(uav => {
        const originLat = 34.183900;
        const originLon = 77.562100;
        const latSpan = 500.0 / 111111.0;
        const lonSpan = 500.0 / (111111.0 * Math.cos(originLat * Math.PI / 180));

        const px = ((uav.current_lon - originLon) / lonSpan) * canvas.width;
        const py = canvas.height - (((uav.current_lat - originLat) / latSpan) * canvas.height);

        const isAlpha = uav.asset_id === "UAV_ALPHA";
        ctx.fillStyle = isAlpha ? "#39c5cf" : "#bc8cff";
        ctx.beginPath();
        ctx.arc(px, py, 6, 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = "#ffffff";
        ctx.lineWidth = 1.5;
        ctx.stroke();

        ctx.fillStyle = "#ffffff";
        ctx.font = "10px monospace";
        ctx.fillText(uav.label.split(" ")[0], px + 9, py + 3);
    });
}

// Triage Queue Rendering
function renderTriageQueue() {
    const targets = [];
    state.cells.forEach(c => {
        if (c.zone === "P1" || c.zone === "P2") targets.push(c);
    });
    targets.sort((a, b) => b.p - a.p);
    
    triageCountEl.innerText = `${targets.length} TARGETS`;
    if (targets.length === 0) {
        queueEl.innerHTML = `<div style="color:var(--muted); font-size:0.78rem; text-align:center; padding-top:40px;">Executing autonomous lawn-mower grid search. No targets locked...</div>`;
        return;
    }

    queueEl.innerHTML = targets.map(c => `
        <div class="triage-card ${c.zone}">
            <div class="card-header">
                <span class="card-title" style="color: ${c.zone === 'P1' ? 'var(--p1)' : 'var(--p2)'}">[${c.zone}] TARGET LOCK (${c.x}, ${c.y})</span>
                <span class="card-prob" style="color: ${c.zone === 'P1' ? 'var(--p1)' : 'var(--p2)'}">${(c.p * 100).toFixed(1)}%</span>
            </div>
            <div class="card-meta-grid">
                <div>BURIAL DEPTH (Z): <strong>${c.depth ? c.depth.toFixed(2) + 'm' : '1.30m'}</strong></div>
                <div>RADIUS: <strong>±${(c.radius || 0.7).toFixed(1)}m</strong></div>
                <div>APPROACH: <strong>${c.azimuth ? c.azimuth.toFixed(0) + '°' : '135° (Contour)'}</strong></div>
                <div>MGRS: <span class="badge-mgrs">${c.mgrs || 'PENDING'}</span></div>
            </div>
            <div style="display:flex; justify-content:space-between; align-items:center; margin-top:4px;">
                <span style="font-size:0.7rem; color:var(--muted);">EVIDENCE: <strong>${c.groups.join(', ') || 'UWB GPR'}</strong></span>
                ${c.zone === 'P1' ? `<span class="marker-badge">MARKER RELEASED [868 MHz]</span>` : ''}
            </div>
            <div class="directive-box ${c.zone}">
                DIRECTIVE: ${c.zone === 'P1' ? 'DEPLOY MECHANICAL EXCAVATION & PROBE TEAM' : 'VECTOR SECONDARY ORTHOGONAL RADAR PASS'}
            </div>
            <button class="btn-inspect" onclick="openInspector('${c.x}_${c.y}')">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></svg>
                INSPECT MICRO-DOPPLER & GPR DSP
            </button>
        </div>
    `).join("");
}

// Canvas Click Target Selection
canvas.addEventListener("click", (e) => {
    const rect = canvas.getBoundingClientRect();
    const clickX = e.clientX - rect.left;
    const clickY = e.clientY - rect.top;
    const cx = Math.floor(clickX / state.cellSizePx);
    const cy = Math.floor((canvas.height - clickY) / state.cellSizePx);
    const key = `${cx}_${cy}`;
    if (state.cells.has(key)) {
        openInspector(key);
    }
});

// Target Analytics Inspector Modal
const modal = document.getElementById("inspectorModal");
let dspAnimFrame;

function openInspector(cellKey) {
    const cell = state.cells.get(cellKey);
    if (!cell) return;
    
    state.selectedTarget = cell;
    document.getElementById("modalTargetTitle").innerText = `TARGET ANALYTICS: CELL_${cell.x}_${cell.y}`;
    document.getElementById("modalTargetSubtitle").innerText = `MGRS: ${cell.mgrs || 'PENDING'} | BURIAL DEPTH (Z): ${cell.depth ? cell.depth.toFixed(2) : '1.30'}m`;
    document.getElementById("modalDepthText").innerText = `${cell.depth ? cell.depth.toFixed(2) : '1.30'} m`;
    document.getElementById("modalApproachAzimuth").innerText = `${cell.azimuth ? cell.azimuth.toFixed(1) : '135.0'}° (Contour Traverse)`;
    document.getElementById("modalMarkerStatus").innerText = cell.zone === 'P1' ? "DEPLOYED [868.2 MHz]" : "STANDBY";
    
    modal.style.display = "flex";
    renderDspCanvases();
}

function closeInspector() {
    modal.style.display = "none";
    if (dspAnimFrame) cancelAnimationFrame(dspAnimFrame);
}

// Draw Animated Micro-Doppler Sine Wave & Synthetic GPR B-Scan
function renderDspCanvases() {
    const dopplerCanvas = document.getElementById("dopplerCanvas");
    const dCtx = dopplerCanvas.getContext("2d");
    const gprCanvas = document.getElementById("gprBscanCanvas");
    const gCtx = gprCanvas.getContext("2d");

    // Static GPR B-Scan Synthesis
    gCtx.fillStyle = "#05080f";
    gCtx.fillRect(0, 0, gprCanvas.width, gprCanvas.height);

    // Draw snow stratification layers
    gCtx.strokeStyle = "#1a2538";
    gCtx.lineWidth = 1;
    for (let y = 15; y < gprCanvas.height; y += 18) {
        gCtx.beginPath();
        gCtx.moveTo(0, y);
        gCtx.lineTo(gprCanvas.width, y);
        gCtx.stroke();
    }

    // Draw target hyperbola
    const apexX = gprCanvas.width / 2;
    const apexY = 65;
    gCtx.strokeStyle = "#38bdf8";
    gCtx.lineWidth = 2.5;
    gCtx.beginPath();
    for (let x = -80; x <= 80; x += 2) {
        const y = apexY + Math.sqrt(x * x * 0.45);
        if (x === -80) gCtx.moveTo(apexX + x, y);
        else gCtx.lineTo(apexX + x, y);
    }
    gCtx.stroke();

    // Draw Micro-Doppler Respiration Wave (0.28 Hz)
    function animWave() {
        dCtx.fillStyle = "#04060a";
        dCtx.fillRect(0, 0, dopplerCanvas.width, dopplerCanvas.height);

        // Center line
        dCtx.strokeStyle = "#16202c";
        dCtx.lineWidth = 1;
        dCtx.beginPath();
        dCtx.moveTo(0, dopplerCanvas.height / 2);
        dCtx.lineTo(dopplerCanvas.width, dopplerCanvas.height / 2);
        dCtx.stroke();

        // Respiration Waveform
        const t = Date.now() / 1000;
        dCtx.strokeStyle = "#3fb950";
        dCtx.lineWidth = 2;
        dCtx.beginPath();
        for (let px = 0; px < dopplerCanvas.width; px++) {
            const phase = (px * 0.04) - (t * 2.8);
            const py = (dopplerCanvas.height / 2) + Math.sin(phase) * 32.0 + Math.sin(phase * 3.0) * 4.0;
            if (px === 0) dCtx.moveTo(px, py);
            else dCtx.lineTo(px, py);
        }
        dCtx.stroke();

        dspAnimFrame = requestAnimationFrame(animWave);
    }
    
    animWave();
}

// Hardware Fault Injection Controller
async function toggleFault(sensorType, btnId) {
    state.faults[sensorType] = !state.faults[sensorType];
    const isFaulted = state.faults[sensorType];
    const btn = document.getElementById(btnId);
    btn.className = isFaulted ? "btn-toggle fault" : "btn-toggle";
    btn.innerText = isFaulted ? "FAULT ACTIVE" : "NORMAL";

    try {
        await fetch("/api/inject-failure", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ sensor_type: sensorType, is_disabled: isFaulted })
        });
    } catch (err) {
        console.error("Fault injection request failed:", err);
    }
}

// Continuous render loop: sweep and pulse animation run even when the
// telemetry link stalls, while the link pill reports data freshness.
function renderLoop() {
    draw();
    requestAnimationFrame(renderLoop);
}
renderLoop();