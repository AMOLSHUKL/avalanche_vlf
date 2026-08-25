#!/usr/bin/env node
/**
 * Static verifier for prototype HTML files.
 * 1. Syntax-checks every inline <script> block.
 * 2. Cross-checks getElementById / addEventListener targets against markup ids.
 * 3. Verifies referenced local assets exist on disk.
 * Usage: node scripts/verify_frontend.js [file ...]
 */
const fs = require("fs");
const path = require("path");

// Default target: the production shell. Explicit args still win.
const root = path.resolve(__dirname, "..");
const argFiles = process.argv.slice(2);
const files = argFiles.length
    ? argFiles.map(f => (fs.existsSync(f) ? path.resolve(f) : path.join(root, f)))
    : [path.join(root, "frontend", "index.html")];

let failures = 0;
for (const file of files) {
    const full = path.isAbsolute(file) ? file : path.join(dir, file);
    if (!fs.existsSync(full)) { console.log(`FAIL ${file}: missing`); failures++; continue; }
    const html = fs.readFileSync(full, "utf8");
    const problems = [];

    // 1. Inline script syntax + local JS asset collection
    const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
    const localJs = [];
    scripts.forEach((s, i) => {
        try { new Function(s); }
        catch (e) { problems.push(`inline script #${i} syntax error: ${e.message}`); }
    });

    // 1b. External local <script src> files: existence (checked below) + id scan
    const externalRefs = [...html.matchAll(/<script src="([^"]+)"><\/script>/g)].map(m => m[1]);

    // 2. id references vs markup (markup ids + ids assigned in any scanned JS)
    const declaredIds = new Set([...html.matchAll(/id="([^"]+)"/g)].map(m => m[1]));
    externalRefs.forEach(ref => {
        if (/^(https?:)?\/\//.test(ref)) return;
        const p = path.resolve(path.dirname(full), ref);
        if (!fs.existsSync(p)) return;   // reported by the asset check
        const js = fs.readFileSync(p, "utf8");
        try { new Function(js); }
        catch (e) { problems.push(`${ref} syntax error: ${e.message}`); }
        localJs.push({ ref, js });
    });
    scripts.forEach(js => localJs.push({ ref: "(inline)", js }));
    localJs.forEach(({ ref, js }) => {
        [...js.matchAll(/\.id\s*=\s*"([^"]+)"/g)].forEach(m => declaredIds.add(m[1]));
        [...js.matchAll(/getElementById\(\s*"([^"]+)"\s*\)/g)].forEach(m => {
            if (!declaredIds.has(m[1])) problems.push(`[${ref}] getElementById("${m[1]}") has no matching id`);
        });
    });

    // 3. Local asset references (relative to the HTML file's own directory)
    [...html.matchAll(/(?:src|href)="([^"#][^":]*)"/g)].forEach(m => {
        const ref = m[1];
        if (/^(https?:)?\/\//.test(ref)) return;
        const target = path.resolve(path.dirname(full), ref.split("?")[0]);
        if (!fs.existsSync(target)) problems.push(`missing asset: ${ref}`);
    });

    // 4. Viewport meta present
    if (!/name="viewport"/.test(html)) problems.push("no viewport meta tag");

    if (problems.length) {
        failures += problems.length;
        console.log(`FAIL ${file}`);
        problems.forEach(p => console.log(`   - ${p}`));
    } else {
        const kb = (fs.statSync(full).size / 1024).toFixed(0);
        console.log(`PASS ${file} (${scripts.length} script block(s), ${kb} KB)`);
    }
}
process.exit(failures ? 1 : 0);
