/**
 * Telemetry link-health classification (pure, DOM-free).
 *
 * Single source of truth for the HUD staleness rule: frames arrive at 10 Hz,
 * so silence beyond STALE_AFTER_MS means the picture is frozen; silence beyond
 * OFFLINE_AFTER_MS (or no frame ever) means the link is down. Loaded by
 * index.html before app.js and executed directly by tests/test_hud_staleness.py
 * under Node.
 */
const LinkHealth = {
    STALE_AFTER_MS: 3000,
    OFFLINE_AFTER_MS: 10000,

    classify(lastFrameAtMs, nowMs) {
        if (!lastFrameAtMs || lastFrameAtMs <= 0) return "offline";
        if (nowMs < lastFrameAtMs) return "live";
        const silentForMs = nowMs - lastFrameAtMs;
        if (silentForMs > this.OFFLINE_AFTER_MS) return "offline";
        if (silentForMs > this.STALE_AFTER_MS) return "stale";
        return "live";
    }
};

if (typeof module !== "undefined") {
    module.exports = { LinkHealth };
}
