#!/usr/bin/env node
/**
 * UI capture lever — drives the tactical HUD in headless chromium (proot)
 * and screenshots every review state into .ui_review/.
 *
 * Prereqs:
 *   - backend live at 127.0.0.1:8000 (Termux-native uvicorn)
 *   - run INSIDE the Ubuntu proot distro with the repo bound at /work and
 *     NODE_PATH=/usr/local/lib/node_modules (global playwright install):
 *
 *   proot-distro login ubuntu --bind <repo>:/work -- env \
 *     NODE_PATH=/usr/local/lib/node_modules node /work/scripts/capture_ui.js
 *
 * Optional args: --viewport=1440x900 --out=.ui_review --base=http://127.0.0.1:8000
 */
const path = require("path");
const fs = require("fs");
const { chromium } = require("playwright");

function arg(name, dflt) {
    const hit = process.argv.find(a => a.startsWith(`--${name}=`));
    return hit ? hit.split("=").slice(1).join("=") : dflt;
}

const [W, H] = arg("viewport", "1440x900").split("x").map(Number);
const OUT = path.resolve("/work", arg("out", ".ui_review"));
const BASE = arg("base", "http://127.0.0.1:8000");
const URL = `${BASE}/frontend/index.html`;

fs.mkdirSync(OUT, { recursive: true });

const sleep = ms => new Promise(r => setTimeout(r, ms));

(async () => {
    const browser = await chromium.launch({
        args: ["--no-sandbox", "--disable-gpu", "--use-gl=angle", "--use-angle=swiftshader"]
    });
    const page = await (await browser.newContext({ viewport: { width: W, height: H } })).newPage();
    const errors = [];
    page.on("pageerror", e => errors.push(`pageerror: ${e.message}`));
    page.on("console", m => { if (m.type() === "error") errors.push(`console: ${m.text()}`); });

    async function shot(name) {
        const file = path.join(OUT, `${name}_${W}x${H}.png`);
        await page.screenshot({ path: file });
        console.log(`captured ${file}`);
    }

    await page.goto(URL, { waitUntil: "domcontentloaded" });
    await page.waitForFunction(() => window.AVLF && AVLF.state.linkState === "live",
        { timeout: 30000 });
    // Let the simulator build heat until triage cards exist (or give up quietly;
    // early-phase shots are still useful).
    try {
        await page.waitForFunction(() => document.querySelectorAll("#queueDesk .tcard").length > 0,
            { timeout: 90000 });
        await sleep(4000); // settle animations + a few telemetry ticks
    } catch { console.log("note: no triage cards within 90s; capturing survey phase"); }

    const tag = W >= 1200 ? "" : "_tablet";

    /* ---- TOPO map, light then dark ---- */
    await shot(`01_topo_light${tag}`);
    await page.click("#themeBtn");
    await sleep(600);
    await shot(`02_topo_dark${tag}`);

    /* ---- RELIEF 3D, dark then light ---- */
    await page.click("#chipRelief");
    await sleep(2500); // WebGL terrain + fusion texture upload
    await shot(`03_relief_dark${tag}`);
    await page.click("#themeBtn");
    await sleep(600);
    await shot(`04_relief_light${tag}`);
    await page.click("#chipPlan");
    await sleep(800);

    /* ---- Layers popover ---- */
    await page.click("#tbLayers");
    await sleep(400);
    await shot(`05_layers_light${tag}`);
    if (await page.locator("#layersPop").isVisible().catch(() => false))
        await page.click("#popClose");

    /* ---- DSP inspector drawer on first target ----
       A card's cell can decay below reporting threshold between locating and
       clicking, so verify the drawer actually opened and retry once. */
    const drawerOpen = () => document.getElementById("dspDrawer").classList.contains("open");
    let opened = await page.locator("#queueDesk .tcard .tc-btn").first().isVisible()
        .catch(() => false);
    if (opened) {
        await page.locator("#queueDesk .tcard .tc-btn").first().click();
        try {
            await page.waitForFunction(drawerOpen, { timeout: 4000 });
        } catch {
            const second = page.locator("#queueDesk .tcard .tc-btn").nth(1);
            if (await second.isVisible().catch(() => false)) {
                await second.click();
                await page.waitForFunction(drawerOpen, { timeout: 4000 })
                    .catch(() => { opened = false; });
            } else opened = false;
        }
    }
    if (opened) {
        await sleep(2500); // let DSP canvases accumulate waveform
        await shot(`06_drawer_light${tag}`);
        await page.click("#mClose");
        await page.waitForFunction(
            s => !document.getElementById("dspDrawer").classList.contains(s),
            "open", { timeout: 4000 }).catch(() => {});
    } else {
        console.log("note: no stable triage card to open the DSP drawer");
    }

    /* ---- Fault injection: GPR disabled via REST, sensor grid reflects it ---- */
    await page.evaluate(async base => {
        await fetch(`${base}/api/inject-failure`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ sensor_type: "GPR", is_disabled: true })
        });
    }, BASE);
    await sleep(1500);
    await shot(`07_fault_gpr_disabled${tag}`);
    await page.evaluate(async base => {
        await fetch(`${base}/api/inject-failure`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ sensor_type: "GPR", is_disabled: false })
        });
    }, BASE);

    if (errors.length) {
        console.log("\nBROWSER ERRORS:");
        errors.forEach(e => console.log(`  - ${e}`));
        process.exitCode = 2;
    }
    await browser.close();
})().catch(e => { console.error("CAPTURE FAILED:", e.message); process.exit(1); });
