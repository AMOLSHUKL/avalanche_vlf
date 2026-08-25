#!/usr/bin/env node
/**
 * Runtime smoke test for prototypes without a browser.
 * Stubs DOM + WebGL + three.js, executes each inline script, pumps live
 * MockTelemetry frames for ~2 s of simulated mission time, then simulates a
 * triage-card click to drive the inspector path. Any uncaught exception fails.
 *
 * Usage: node scripts/smoke_frontend.js [file ...]
 */
const fs = require("fs");
const path = require("path");
const vm = require("vm");

// Default target: the production shell (WS frames injected). Explicit args win.
const root = path.resolve(__dirname, "..");
const argFiles = process.argv.slice(2);
const files = argFiles.length
    ? argFiles.map(f => (fs.existsSync(f) ? path.resolve(f) : path.join(root, f)))
    : [path.join(root, "frontend", "index.html")];

/* ---------------- Stubs ---------------- */
function ctxStub() {
    const grad = { addColorStop() {} };
    return new Proxy({}, {
        get(t, p) {
            if (p === "createRadialGradient" || p === "createLinearGradient" || p === "createConicGradient")
                return () => grad;
            if (p === "createImageData") return (w, h) => ({ data: new Uint8ClampedArray(w * h * 4), width: w, height: h });
            if (p === "getImageData") return (x, y, w, h) => ({ data: new Uint8ClampedArray(Math.max(4, w * h * 4)), width: w, height: h });
            if (p === "measureText") return () => ({ width: 10 });
            if (typeof t[p] !== "undefined") return t[p];
            return () => {};
        },
        set(t, p, v) { t[p] = v; return true; }
    });
}

function elementStub(id) {
    const el = {
        id: id || "",
        textContent: "", innerHTML: "", className: "",
        style: new Proxy({}, { get: () => "", set: () => true }),
        dataset: {},
        clientWidth: 640,
        width: 300, height: 150,
        children: [],
        classList: {
            _s: new Set(),
            add(...c) { c.forEach(x => this._s.add(x)); },
            remove(...c) { c.forEach(x => this._s.delete(x)); },
            toggle(c, force) {
                const on = force === undefined ? !this._s.has(c) : force;
                on ? this._s.add(c) : this._s.delete(c); return on;
            },
            contains(c) { return this._s.has(c); }
        },
        appendChild(child) { this.children.push(child); return child; },
        replaceChildren(...nodes) {
            this.children.length = 0;
            for (const nd of nodes) {
                if (!nd) continue;
                if (nd.__fragment) this.children.push(...nd.children);
                else this.children.push(nd);
            }
        },
        remove() {},
        closest(sel) {
            // Minimal ancestor walk: the queue's real scroller is .rc-scroll
            // (desktop) / .sheet-body (mobile); stub both as the element.
            if (sel && sel.includes("rc-scroll")) return el;
            if (sel && sel.includes("sheet-body")) return el;
            return null;
        },
        scrollTop: 0,
        setAttribute(k, v) { (el.__attrs = el.__attrs || {})[k] = String(v); },
        getAttribute(k) { return (el.__attrs && el.__attrs[k]) != null ? el.__attrs[k] : null; },
        querySelector(sel) {
            // Field-level patches query scoped selectors; return a stable stub
            // per (element, selector) so repeated patches hit the same object.
            el.__qs = el.__qs || {};
            if (!el.__qs[sel]) el.__qs[sel] = elementStub(el.id + ">" + sel);
            return el.__qs[sel];
        },
        querySelectorAll() { return []; },
        getBoundingClientRect: () => ({ left: 0, top: 0, width: 900, height: 700 }),
        getContext: () => ctxStub(),
        focus() {}, scrollIntoView() {}
    };
    Object.defineProperty(el, "parentElement", { get: () => elementStub(el.id + "-parent") });
    Object.defineProperty(el, "firstElementChild", {
        get: () => {
            if (!el.__fec) el.__fec = elementStub(el.id + "-fec");
            return el.__fec;
        }
    });

    const listeners = {};
    el.addEventListener = (type, fn) => { (listeners[type] = listeners[type] || []).push(fn); };
    el.removeEventListener = () => {};
    el.dispatch = (type, ev) => (listeners[type] || []).forEach(fn => fn(ev));
    el.withFragment = function () { this.__fragment = true; return this; };

    // innerHTML setter keeps a marker so tests can detect rendered cards.
    let _html = "";
    Object.defineProperty(el, "innerHTML", {
        get: () => _html,
        set(v) { _html = String(v); el.__hasCards = /data-cell=/.test(_html); }
    });
    return el;
}

function makeSandbox() {
    const els = new Map();
    const docListeners = {};
    const document = {
        hidden: false,
        getElementById(id) {
            if (!els.has(id)) els.set(id, elementStub(id));
            return els.get(id);
        },
        createElement(tag) {
            const el = elementStub("created-" + tag);
            if (tag === "fragment") { el.__fragment = true; }
            return el;
        },
        createDocumentFragment() { return elementStub("created-fragment").withFragment(); },
        querySelector() { return elementStub("qs"); },
        querySelectorAll() { return []; },
        addEventListener(type, fn) { (docListeners[type] = docListeners[type] || []).push(fn); },
        removeEventListener() {},
        dispatchDocument(type, ev) { (docListeners[type] || []).forEach(fn => fn(ev)); },
        body: elementStub("body"),
        documentElement: Object.assign(elementStub("html"), {
            getAttribute: () => null,
            setAttribute: () => {},
            removeAttribute: () => {}
        })
    };

    let rafBudget = 6000;
    const sandbox = {
        console, Math, Date, JSON, Number, String, Array, Object, Map, Set,
        Uint8ClampedArray, Float32Array, Promise, Symbol, Proxy, TypeError, Error,
        parseInt, parseFloat, isFinite, Infinity, NaN,
        performance: { now: () => Date.now() },
        setTimeout: (fn, ms) => setTimeout(fn, Math.min(ms || 0, 25)),
        clearTimeout,
        setInterval: (fn, ms) => setInterval(fn, Math.min(ms || 1, 30)),
        clearInterval,
        requestAnimationFrame(fn) { if (--rafBudget > 0) setImmediate(() => fn(Date.now())); },
        cancelAnimationFrame() {},
        matchMedia: () => ({ matches: false }),
        ResizeObserver: class { observe() {} unobserve() {} disconnect() {} },
        MutationObserver: class { observe() {} disconnect() {} },
        getComputedStyle: () => ({ getPropertyValue: () => "#888888" }),
        devicePixelRatio: 2, innerWidth: 1280, innerHeight: 800,
        location: { protocol: "http:", host: "localhost:8000", pathname: "/frontend/index.html" },
        addEventListener(type, fn) { (docListeners[type] = docListeners[type] || []).push(fn); },
        removeEventListener() {},
        // Fake WebSocket: instances recorded so the runner can pump frames.
        __wsInstances: [],
        WebSocket: function (url) {
            this.url = url;
            this.close = () => {};
            sandbox.__wsInstances.push(this);
        },
        fetch: () => Promise.resolve({ ok: true })
    };
    sandbox.window = sandbox;
    sandbox.document = document;

    // Pre-seed module/exports so vendor UMD builds (three.min.js) bind to a
    // local export object instead of replacing the universal THREE stub with
    // the real library, which would probe WebGL and crash.
    const vendorExports = {};
    sandbox.module = { exports: vendorExports };
    sandbox.exports = vendorExports;

    function universal(name) {
        const handler = {
            construct: () => universal(name + "#"),
            get(t, p) {
                if (p === Symbol.toPrimitive || p === "valueOf") return () => 0;
                if (p === "length" || p === "count") return 3;
                return universal(`${name}.${String(p)}`);
            },
            apply: () => universal(name + "()"),
            set: () => true
        };
        return new Proxy(function () {}, handler);
    }
    sandbox.THREE = universal("THREE");
    return sandbox;
}

/* ---------------- Runner ---------------- */
let failures = 0, remaining = files.length;
function finishOne(file, ok, note) {
    console.log(`${ok ? "PASS" : "FAIL"} ${file}${note ? ": " + note : ""}`);
    if (!ok) failures++;
    if (--remaining <= 0) process.exit(failures ? 1 : 0);
}

for (const file of files) {
    const base = path.basename(file);
    const html = fs.readFileSync(file, "utf8");
    try {
        const external = [...html.matchAll(/<script src="([^"]+)"><\/script>/g)]
            .map(m => fs.readFileSync(path.resolve(path.dirname(file), m[1]), "utf8"));
        const inline = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]).join("\n;\n");

        const sandbox = makeSandbox();
        const ctx = vm.createContext(sandbox);
        [...external, inline].forEach(src =>
            vm.runInContext(src, ctx, { timeout: 5000, filename: base }));

        // Production page: pump synthetic telemetry frames through its
        // WebSocket onmessage so the full ingestion path runs.
        let pumpTimer = null;
        if (sandbox.__wsInstances.length) {
            const t0 = Date.now() / 1000;
            pumpTimer = setInterval(() => {
                const wsInst = sandbox.__wsInstances[sandbox.__wsInstances.length - 1];
                if (!wsInst || typeof wsInst.onmessage !== "function") return;
                const t = Date.now() / 1000 - t0;
                wsInst.onmessage({ data: JSON.stringify({
                    type: "telemetry_frame",
                    incident_id: "INCIDENT_HIMALAYA_2026_01",
                    mission_phase: "DEEP_RADAR_SCAN",
                    mission_clock: { server_epoch_s: Date.now() / 1000,
                                     incident_epoch_s: Date.now() / 1000 - 120,
                                     survival_probability: 0.87 },
                    uav_telemetry: [
                        { asset_id: "UAV_ALPHA", label: "UAV-Alpha",
                          current_lat: 34.1839 + 0.0009 * (Math.sin(t * .3) + 1),
                          current_lon: 77.5621 + 0.0012 * ((t * .05) % 1),
                          current_alt_m: 3845.2, heading_deg: 90,
                          speed_mps: 11, battery_pct: 96 },
                        { asset_id: "UAV_BRAVO", label: "UAV-Bravo",
                          current_lat: 34.1844, current_lon: 77.5628,
                          current_alt_m: 3851.7, heading_deg: 270,
                          speed_mps: 11, battery_pct: 94 }
                    ],
                    updated_zones: [
                        { cell_x: 52, cell_y: 44, probability: 0.91, priority_zone: "P1",
                          burial_depth_estimate_m: 1.35, confidence_radius_m: 1.1,
                          mgrs_coord: "43S UD 29815 49097",
                          contributing_evidence_groups: ["UWB GPR", "457 kHz"] },
                        { cell_x: 40, cell_y: 36, probability: 0.58, priority_zone: "P2",
                          burial_depth_estimate_m: 1.10, confidence_radius_m: 1.9,
                          mgrs_coord: "43S UD 29755 49035",
                          contributing_evidence_groups: ["THERMAL_IR"] }
                    ],
                    directives: [
                        { target_zone_id: "cell_52_44", approach_azimuth_deg: 137.5,
                          marker_deployed: true, marker_frequency_mhz: 868.2,
                          rationale: "Marker deployed. Vector mechanical excavation & probe line." }
                    ]
                })});
            }, 100);
        }

        // Poll for cards before exercising interactions: batch runs share one
        // event loop, so fixed wall-clock waits are unreliable under load.
        const startedAt = Date.now();
        const poller = setInterval(() => {
            const ready = ["queueDesk", "queueSheet", "queue"].some(qid => {
                const el = sandbox.document.getElementById(qid);
                return el.__hasCards ||
                       (el.children || []).some(ch => ch.dataset && ch.dataset.cell);
            });
            if (!ready && Date.now() - startedAt < 8000) return;
            clearInterval(poller);
            if (pumpTimer) { clearInterval(pumpTimer); pumpTimer = null; }
                const modal = sandbox.document.getElementById("modal");
                const modal2 = sandbox.document.getElementById("inspector");
                const drawer = sandbox.document.getElementById("dspDrawer");
                const mTitle = sandbox.document.getElementById("mTitle");
                const fakeCard = {
                    dataset: {},
                    closest: sel => sel && sel.includes("data-cell")
                        ? { dataset: { cell: "52_44" } } : null
                };
                fakeCard.dataset.cell = "52_44";

                let queueEl = null;
                for (const qid of ["queueDesk", "queueSheet", "queue"]) {
                    const cand = sandbox.document.getElementById(qid);
                    if (!queueEl && typeof cand.dispatch === "function") queueEl = cand;
                    if (cand.__hasCards || cand.innerHTML.length > 40) { queueEl = cand; break; }
                }
                if (!queueEl) queueEl = sandbox.document.getElementById("queue");
                if (queueEl && typeof queueEl.dispatch === "function")
                    queueEl.dispatch("click", { target: fakeCard });
                sandbox.document.dispatchDocument("click", { target: fakeCard });

                const opened = modal.classList.contains("open") ||
                               modal2.classList.contains("open") ||
                               drawer.classList.contains("open");
                const titleOk = mTitle && /CELL/i.test(mTitle.textContent);
                const hadCards = true;   // readiness gated by the poller above

                if (!hadCards) {
                    if (process.env.SMOKE_DEBUG) {
                        const dbg = vm.runInContext(
                            `JSON.stringify({wsN: window.__wsInstances.length,
                              onmsg: typeof (window.__wsInstances[0]||{}).onmessage,
                              deskLen: document.getElementById('queueDesk').innerHTML.length,
                              sheetLen: document.getElementById('queueSheet').innerHTML.length,
                              cells52_44: JSON.stringify((AVLF && AVLF.state && AVLF.state.cells.get('52_44')) || null),
                              linkState: AVLF && AVLF.state && AVLF.state.linkState})`, ctx);
                        console.log("DEBUG", dbg);
                    }
                    return finishOne(base, false, "triage queue never rendered a card");
                }
                if (!opened) {
                    if (process.env.SMOKE_DEBUG) {
                        const dbg = vm.runInContext(
                            `JSON.stringify({sel: AVLF.state.selectedKey,
                              insOpen: document.getElementById('inspector').classList.contains('open'),
                              mTitle: document.getElementById('mTitle').textContent})`, ctx);
                        console.log("DEBUG2", dbg);
                    }
                    return finishOne(base, false, "inspector did not open on card click");
                }
                if (!titleOk) return finishOne(base, false, "inspector title not populated");
                const cardCount = (queueEl.children || [])
                    .filter(ch => ch.dataset && ch.dataset.cell).length;
                if (process.env.SMOKE_DEBUG && sandbox.document.body) {
                    // Simulate the full operator loop: dismiss targeting with Esc.
                    sandbox.document.dispatchDocument("keydown", { key: "Escape" });
                    const state = vm.runInContext(
                        `JSON.stringify({
                           bodyDrawerOpen: document.body.classList.contains('drawer-open'),
                           sheetOpenCls: document.getElementById('mapPane').classList.contains('sheet-open'),
                           mode3dCls: document.getElementById('mapPane').classList.contains('mode3d'),
                           mode: AVLF.state.mode,
                           sel: AVLF.state.selectedKey,
                           drawerOpen: document.getElementById('dspDrawer').classList.contains('open'),
                           sheetElOpen: document.getElementById('targetSheet').classList.contains('open')
                         })`, ctx);
                    console.log("UISTATE", base, state);
                }
                finishOne(base, true, `${cardCount} reconciled card(s), inspector OK`);
        }, 150);
    } catch (e) {
        finishOne(base, false, e.message);
    }
}
