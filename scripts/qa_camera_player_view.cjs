#!/usr/bin/env node
"use strict";

/*
 * Finite, offline layout QA for the ACTUAL bundled player_view.js.
 *
 * Use an existing Playwright installation, or install the locked developer
 * dependency with npm ci --ignore-scripts --audit=false in
 * scripts/camera_layout_dependencies. Use an already installed browser:
 *   node scripts/qa_camera_player_view.cjs --output-dir /tmp/camera-player-layout
 * Optional: --browser /absolute/path/to/chromium
 *
 * This developer helper is deliberately outside pytest and the Windows build.
 * It uses small original fixtures with the observed provider DOM structure,
 * not provider pages, media streams, credentials, or generated iframe tokens.
 * Every browser request is fulfilled locally or aborted. Screenshots prove
 * synthetic layout only: they do not prove live playback or native embedding.
 */

const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "..");
const SCRIPT_PATH = path.join(ROOT, "packaging/camera/player_view.js");
const STYLE_ID = "global-pulse-camera-player-view";
const MARKER = "data-global-pulse-player-view";
const FRAME_URL = "https://offline-layout.invalid/provider-player?alias=bsyc1080&fixture=offline&state=provider-error&sentinel=a%2Bb";
const CAMERAS = [
    { id: "gpc-tannum-sands", kind: "coastalcoms", url: "https://widget.coastalcoms.com/video/005972b5-8290-420c-8527-9ce69bbcd2ec" },
    { id: "gpc-1770", kind: "coastalcoms", url: "https://widget.coastalcoms.com/video/e53407e0-915b-4964-b60a-638e1bd32d6d" },
    { id: "bsyc", kind: "ipcam_public", url: "https://www.ipcamlive.com/bsyc1080" },
];
const VIEWPORTS = [
    { name: "wide-short", width: 1436, height: 300 },
    { name: "normal", width: 960, height: 540 },
    { name: "narrow", width: 360, height: 280 },
];
const sha256 = value => crypto.createHash("sha256").update(value).digest("hex");

function options(argv) {
    const result = { outputDir: path.join(os.tmpdir(), "global-pulse-camera-player-layout") };
    for (let i = 0; i < argv.length; i++) {
        if (argv[i] === "--help") {
            console.log("Offline layout only. Usage: node scripts/qa_camera_player_view.cjs [--output-dir DIR] [--browser PATH]");
            process.exit(0);
        }
        const key = { "--output-dir": "outputDir", "--browser": "browser" }[argv[i]];
        if (!key || !argv[i + 1] || argv[i + 1].startsWith("--")) throw new Error(`Invalid option: ${argv[i]}`);
        result[key] = path.resolve(argv[++i]);
    }
    return result;
}

function documentHtml(body, css = "", script = "", bodyClass = "") {
    return `<!doctype html><html><head><meta charset="utf-8"><title>OFFLINE camera layout fixture</title>
    <style>*,*::before,*::after{box-sizing:border-box}body{font:16px/1.4 Arial,sans-serif}
    button{font:inherit;color:inherit;background:#293b4b;border:1px solid #91a8bb;border-radius:4px;padding:3px 10px}
    ${css}</style></head><body class="${bodyClass}">${body}<script>${script}</script></body></html>`;
}

// Provider layout shape after video.js enhances #video; no video source exists.
function coastalFixture() {
    return documentHtml(`
      <div id="page-content"><div id="player-area"><div id="video" class="video-js">
        <video class="vjs-tech" controls aria-label="Offline video placeholder"></video>
        <div id="fixture-label">OFFLINE LAYOUT FIXTURE<br><small>No live camera playback</small></div>
        <div id="provider-branding" class="vjs-logo">Provider branding · fixture</div>
        <div id="provider-controls" class="vjs-control-bar"><button>Play</button><button>Mute</button><button>Fullscreen</button></div>
      </div></div><div class="alert alert-info"><strong>Offline fixture.</strong> We are experiencing some technical issues with this camera, so the vision may be unavailable.</div></div>`, `
      body{margin:0;padding:0}#page-content{width:100%;margin:auto}#player-area{width:100%;height:163.125px}
      #video{position:relative;width:100%;height:100%;background:linear-gradient(135deg,#102838,#050a0e);color:#fff}
      .vjs-tech{position:absolute;inset:0;width:100%;height:100%}#fixture-label{position:absolute;top:35%;left:0;width:100%;text-align:center;font-size:clamp(16px,2vw,24px)}
      #fixture-label small{font-size:13px;color:#b2c7d6}#provider-branding{position:absolute;right:12px;top:10px;font-size:13px;color:#cbdfed}
      #provider-controls{position:absolute;bottom:0;left:0;right:0;display:flex;gap:10px;padding:8px;background:#10212f}
      /* The actual direct player has an unstyled alert; do not supply Bootstrap colors here. */
      @media(min-width:320px){#player-area{width:320px;height:180px}}
      @media(min-width:480px){#player-area{width:100%;height:270px}}
      @media(min-width:640px){#player-area{height:360px}}
      @media(min-width:768px){#player-area{height:432px}}
      @media(min-width:1024px){#player-area{height:576px}}
      @media(min-width:1280px){#player-area{height:720px}}`, `
      window.qaOriginal={player:document.querySelector('#video'),parent:document.querySelector('#video').parentNode,
        media:document.querySelector('.vjs-tech'),html:document.querySelector('#video').innerHTML,
        notice:document.querySelector('.alert'),noticeText:document.querySelector('.alert').textContent};
    `);
}

// Only the original public-page ancestry is modeled. The iframe is synthetic,
// appears after the focus script runs, and retains its URL/query/error content.
function publicFixture() {
    return documentHtml(`
      <div id="fb-root"></div>
      <div class="wrap wrap--black"><header class="header header--guest">Offline site navigation fixture</header></div>
      <div class="section-content">
        <div class="wrap wrap--gray-lightest"><div id="cameraheaderdiv" class="section section--live">Offline camera heading fixture</div></div>
        <section class="section section--live"><div id="playerdiv"></div></section>
      </div>
      <div class="wrap wrap--gray-light wrap--footer"><footer class="footer">Offline footer fixture</footer><div class="wrap wrap--gray-lighter"></div></div>`, `
      body{margin:0;background:#eee}.wrap--black{background:#151a20;color:white;padding:30px}
      .wrap--gray-lightest{background:#e9edf0}.section{width:calc(100% - 32px);max-width:1024px;margin:auto}
      #cameraheaderdiv{padding:28px 0}#playerdiv{margin:24px 0}#playeriframe{display:block;border:0}
      .wrap--footer{padding:48px;background:#ddd}`, `
      window.qaOriginal={player:document.querySelector('#playerdiv'),parent:document.querySelector('#playerdiv').parentNode};
      window.qaFrameLoads=0;
      window.qaAddProviderIframe=()=>{
        if(document.querySelector('#playeriframe')) throw new Error('Fixture iframe already exists');
        const frame=document.createElement('iframe');frame.id='playeriframe';
        frame.setAttribute('title','Offline provider player fixture');
        frame.setAttribute('allowfullscreen','');frame.setAttribute('allow','autoplay; fullscreen');
        frame.src=${JSON.stringify(FRAME_URL)};
        window.qaProviderWidthAtCreate=Math.min(document.querySelector('#cameraheaderdiv').getBoundingClientRect().width,1024);
        frame.width=window.qaProviderWidthAtCreate;frame.height=Math.round(window.qaProviderWidthAtCreate/(4/3));
        frame.addEventListener('load',()=>window.qaFrameLoads++);
        document.querySelector('#playerdiv').appendChild(frame);
        window.qaOriginal.frame=frame;window.qaOriginal.frameParent=frame.parentNode;
        window.qaOriginal.frameAttrs=Array.from(frame.attributes,a=>[a.name,a.value]);
      };
      window.qaProviderResize=()=>{
        const frame=document.querySelector('#playeriframe');if(!frame)return;
        const width=Math.min(document.querySelector('#cameraheaderdiv').getBoundingClientRect().width,1024);
        frame.style.width=width+'px';frame.style.height=Math.round(width/(4/3))+'px';
      };
    `, "page page--player");
}

function frameFixture() {
    return documentHtml(`
      <main id="fixture-player"><div id="provider-branding">Provider branding · fixture</div>
      <div id="provider-error"><strong>OFFLINE LAYOUT FIXTURE</strong><br>Synthetic provider error: camera unavailable.</div>
      <div id="provider-controls"><button>Play</button><button>Mute</button><button>Fullscreen</button></div></main>`, `
      html,body{margin:0;height:100%;overflow:hidden;background:#081824;color:#fff}
      #fixture-player{position:relative;width:100%;height:100%}
      #provider-branding{position:absolute;top:12px;right:12px;font-size:13px;color:#cbdfed}
      #provider-error{position:absolute;inset:32% 14px auto;text-align:center;padding:12px;background:#49321d;color:#ffdcac;font-size:14px}
      #provider-controls{position:absolute;bottom:0;left:0;right:0;display:flex;gap:10px;padding:8px;background:#10212f}`, `
      window.qaFrameOriginalHtml=document.documentElement.outerHTML;
      window.qaErrorNode=document.querySelector('#provider-error');
    `);
}

async function settle(page) {
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
}

async function dimensions(frame, selectors) {
    return frame.evaluate(selectors => {
        function noticeContrast(element) {
            const rgba = color => {
                const values = color.match(/[\d.]+/g).map(Number);
                return [values[0], values[1], values[2], values.length > 3 ? values[3] : 1];
            };
            const over = (foreground, background) => background.map((value, i) => foreground[i] * foreground[3] + value * (1 - foreground[3]));
            const ancestors = [];
            for (let node = element; node instanceof Element; node = node.parentElement) ancestors.unshift(node);
            let background = [255, 255, 255];
            for (const node of ancestors) background = over(rgba(getComputedStyle(node).backgroundColor), background);
            const foreground = over(rgba(getComputedStyle(element).color), background);
            const luminance = rgb => rgb.map(value => {
                value /= 255;
                return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
            }).reduce((total, value, i) => total + value * [0.2126, 0.7152, 0.0722][i], 0);
            const levels = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
            return { foreground, background, ratio: (levels[0] + 0.05) / (levels[1] + 0.05) };
        }
        const viewport = { width: innerWidth, height: innerHeight };
        const boxes = {};
        for (const selector of selectors) {
            const element = document.querySelector(selector);
            if (!element) { boxes[selector] = { missing: true }; continue; }
            const rect = element.getBoundingClientRect(), style = getComputedStyle(element);
            const hit = document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2);
            let visible = true;
            for (let node = element; node instanceof Element; node = node.parentElement) {
                const css = getComputedStyle(node);
                if (css.display === "none" || css.visibility !== "visible" || Number(css.opacity) === 0) visible = false;
            }
            boxes[selector] = { x: rect.x, y: rect.y, width: rect.width, height: rect.height,
                visible, display: style.display, centerUncovered: !!hit && (element === hit || element.contains(hit)) };
            if (selector === ".alert") boxes[selector].contrast = noticeContrast(element);
        }
        const documentSize = { width: document.documentElement.scrollWidth, height: document.documentElement.scrollHeight };
        return { viewport, documentSize, boxes };
    }, selectors);
}

function assertFits(measurement, label) {
    const { viewport, documentSize, boxes } = measurement;
    assert.ok(documentSize.width <= viewport.width + 1, `${label}: horizontal document overflow (${documentSize.width})`);
    assert.ok(documentSize.height <= viewport.height + 1, `${label}: vertical document overflow (${documentSize.height})`);
    for (const [selector, rect] of Object.entries(boxes)) {
        assert.ok(!rect.missing && rect.visible, `${label}: ${selector} is missing/hidden`);
        assert.ok(rect.width > 0 && rect.height > 0, `${label}: ${selector} is collapsed`);
        assert.ok(rect.x >= -1 && rect.y >= -1 && rect.x + rect.width <= viewport.width + 1 && rect.y + rect.height <= viewport.height + 1,
            `${label}: ${selector} falls outside viewport: ${JSON.stringify(rect)}`);
        assert.ok(rect.centerUncovered, `${label}: ${selector} is covered`);
        if (selector === ".alert") assert.ok(rect.contrast.ratio >= 4.5,
            `${label}: availability notice contrast is below 4.5:1 (${rect.contrast.ratio})`);
    }
}

async function originalIdentity(page, camera) {
    const result = await page.evaluate(kind => {
        const original = window.qaOriginal;
        const player = document.querySelector(kind === "coastalcoms" ? "#video" : "#playerdiv");
        const result = { samePlayer: player === original.player, sameParent: player.parentNode === original.parent };
        if (kind === "coastalcoms") {
            Object.assign(result, { sameMedia: document.querySelector(".vjs-tech") === original.media,
                sameContent: player.innerHTML === original.html, sameNotice: document.querySelector(".alert") === original.notice,
                sameNoticeText: original.notice.textContent === original.noticeText });
        } else {
            const frame = document.querySelector("#playeriframe");
            Object.assign(result, { sameFrame: frame === original.frame, sameFrameParent: frame.parentNode === original.frameParent,
                sameFrameAttributes: original.frameAttrs.every(([name, value]) => frame.getAttribute(name) === value),
                src: frame.getAttribute("src"), loads: window.qaFrameLoads, providerMeasuredWidth: window.qaProviderWidthAtCreate });
        }
        return result;
    }, camera.kind);
    for (const [key, value] of Object.entries(result)) if (key.startsWith("same")) assert.equal(value, true, `${camera.id}: ${key}`);
    if (camera.kind === "ipcam_public") {
        assert.equal(result.src, FRAME_URL, "Original iframe URL and parameters changed");
        assert.equal(result.loads, 1, "Original iframe was reloaded/replaced");
        assert.ok(result.providerMeasuredWidth > 0, "Provider header width measurement collapsed");
    }
    return result;
}

async function makePage(browser, fixtures, script, network, init = true) {
    const context = await browser.newContext({ viewport: { width: VIEWPORTS[0].width, height: VIEWPORTS[0].height }, serviceWorkers: "block" });
    context.setDefaultTimeout(5000);
    await context.route("**/*", async route => {
        const request = route.request(), url = request.url();
        if (fixtures.has(url)) {
            network.fulfilled++;
            await route.fulfill({ status: 200, contentType: "text/html; charset=utf-8", body: fixtures.get(url) });
        } else {
            network.aborted++;
            if (network.unexpected.length < 20) network.unexpected.push(url);
            await route.abort("blockedbyclient");
        }
    });
    const page = await context.newPage();
    if (init) await page.addInitScript({ content: script });
    return { context, page };
}

async function cameraCase(browser, camera, mode, script, report, outputDir) {
    const fixtures = new Map([[camera.url, camera.kind === "coastalcoms" ? coastalFixture() : publicFixture()], [FRAME_URL, frameFixture()]]);
    const { context, page } = await makePage(browser, fixtures, script, report.network, mode === "document-created");
    try {
        await page.goto(camera.url, { waitUntil: "load" });
        if (mode === "document-created") {
            assert.equal(await page.locator(`#${STYLE_ID}`).count(), 1, "Document-created hook did not apply at DOMContentLoaded");
        }
        const applied = await page.evaluate(script); // Native also re-executes at navigation completion.
        assert.deepEqual(applied, { applied: true, view: camera.kind });
        assert.equal(await page.locator(`#${STYLE_ID}`).count(), 1, "Style injection must be idempotent");
        if (camera.kind === "ipcam_public") {
            assert.equal(await page.locator("#playeriframe").count(), 0, "Iframe should arrive after focus CSS");
            await page.evaluate(() => window.qaAddProviderIframe());
            await page.waitForFunction(() => window.qaFrameLoads === 1);
        }
        const frame = camera.kind === "ipcam_public" ? page.frames().find(frame => frame.url() === FRAME_URL) : null;
        const frameBefore = frame ? await frame.content() : null;
        const observations = [];
        // Return to the original dimensions too: all resizes must retain identity.
        for (const viewport of [...VIEWPORTS, VIEWPORTS[0]]) {
            await page.setViewportSize({ width: viewport.width, height: viewport.height });
            if (frame) await page.evaluate(() => window.qaProviderResize());
            await settle(page);
            const parent = await dimensions(page, camera.kind === "coastalcoms"
                ? ["#player-area", "#video", "#provider-controls", "#provider-branding", ".alert"] : ["#playerdiv", "#playeriframe"]);
            assertFits(parent, `${camera.id}/${mode}/${viewport.name}`);
            const identity = await originalIdentity(page, camera);
            let child = null;
            if (frame) {
                child = await dimensions(frame, ["#provider-branding", "#provider-controls", "#provider-error"]);
                assertFits(child, `${camera.id}/${mode}/${viewport.name}/iframe`);
                assert.equal(await frame.content(), frameBefore, "Provider iframe document/error content changed");
                assert.equal(await frame.evaluate(() => document.querySelector("#provider-error") === window.qaErrorNode), true);
                assert.equal(await frame.locator(`#${STYLE_ID}`).count(), 0, "Child frame was styled");
            }
            observations.push({ viewport: viewport.name, parent, child, identity });
            if (mode === "document-created" && observations.length <= VIEWPORTS.length) {
                const filename = `${camera.id}-${viewport.name}-OFFLINE.png`;
                await page.screenshot({ path: path.join(outputDir, filename) });
                report.screenshots.push(filename);
            }
        }
        // An unrelated provider gate must remain present and above the player.
        await page.evaluate(() => {
            const gate = document.createElement("dialog"); gate.id = "qa-provider-dialog";
            gate.textContent = "Synthetic provider gate (offline fixture)";
            document.body.appendChild(gate); gate.showModal();
        });
        const gate = await dimensions(page, ["#qa-provider-dialog"]);
        assertFits(gate, `${camera.id}/provider-dialog`);
        assert.equal((await page.evaluate(script)).applied, true);
        assertFits(await dimensions(page, ["#qa-provider-dialog"]), `${camera.id}/provider-dialog-after-reapply`);
        report.cases.push({ camera: camera.id, mode, status: "PASS", observations, providerDialogPreserved: true });
    } finally { await context.close(); }
}

async function guardCases(browser, script, report) {
    for (const camera of CAMERAS) {
        const html = camera.kind === "coastalcoms" ? coastalFixture() : publicFixture();
        for (const [name, url, expected] of [
            ["query", `${camera.url}?fixture=unexpected`, false],
            ["path", `${camera.url}/unrelated`, false],
            ["host", camera.url.replace(new URL(camera.url).hostname, "unrelated.invalid"), false],
            ["fragment", `${camera.url}#player`, true],
        ]) {
            const fixtures = new Map([[url.split("#")[0], html]]);
            const { context, page } = await makePage(browser, fixtures, script, report.network);
            try {
                await page.goto(url, { waitUntil: "load" });
                const result = await page.evaluate(script);
                assert.equal(result.applied, expected, `${camera.id}: ${name} URL guard`);
                assert.equal(await page.locator(`#${STYLE_ID}`).count(), expected ? 1 : 0);
                assert.equal(await page.locator(`[${MARKER}]`).count(), expected ? 1 : 0);
                report.guards.push({ camera: camera.id, case: name, result, status: "PASS" });
            } finally { await context.close(); }
        }
        const host = "https://offline-layout.invalid/frame-host";
        const fixtures = new Map([[host, documentHtml(`<iframe src="${camera.url}" title="Child-frame guard fixture"></iframe>`)], [camera.url, html]]);
        const { context, page } = await makePage(browser, fixtures, script, report.network);
        try {
            await page.goto(host, { waitUntil: "load" });
            const child = page.frames().find(frame => frame.url() === camera.url);
            assert.ok(child, "Fixture child frame did not load");
            assert.deepEqual(await child.evaluate(script), { applied: false, reason: "child_frame" });
            assert.equal(await child.locator(`#${STYLE_ID}`).count(), 0);
            assert.equal(await child.locator(`[${MARKER}]`).count(), 0);
            report.guards.push({ camera: camera.id, case: "child-frame", status: "PASS" });
        } finally { await context.close(); }
    }
    const camera = CAMERAS[0];
    const { context, page } = await makePage(browser, new Map([[camera.url, documentHtml("<main>Changed provider DOM fixture</main>")]]), script, report.network);
    try {
        await page.goto(camera.url, { waitUntil: "load" });
        assert.deepEqual(await page.evaluate(script), { applied: false, reason: "player_missing" });
        assert.equal(await page.locator(`#${STYLE_ID}`).count(), 0);
        report.guards.push({ camera: camera.id, case: "missing-player", status: "PASS" });
    } finally { await context.close(); }
}

async function main() {
    const args = options(process.argv.slice(2));
    fs.mkdirSync(args.outputDir, { recursive: true });
    const script = fs.readFileSync(SCRIPT_PATH, "utf8");
    const report = {
        schema: 1, kind: "OFFLINE_SYNTHETIC_LAYOUT_ONLY", status: "RUNNING", startedAt: new Date().toISOString(),
        script: path.relative(ROOT, SCRIPT_PATH), scriptSha256: sha256(script),
        sourceCommit: process.env.GITHUB_SHA || null, chromiumSandboxEnabled: true,
        liveCameraPlaybackVerified: false, windowsNativeEmbeddingVerified: false,
        fixtureLimitations: "Original minimal DOM/CSS fixtures and synthetic controls/branding/error content; no provider scripts or media.",
        network: { strategy: "Every request is fulfilled from in-memory fixtures or aborted; no route continues to network.", fulfilled: 0, aborted: 0, unexpected: [] },
        cases: [], guards: [], screenshots: [],
    };
    let browser;
    try {
        let chromium;
        try {
            try {
                ({ chromium } = require("playwright"));
                report.playwright = { package: "playwright", version: require("playwright/package.json").version };
            } catch (error) {
                if (error.code !== "MODULE_NOT_FOUND") throw error;
                const core = path.join(__dirname, "camera_layout_dependencies/node_modules/playwright-core");
                ({ chromium } = require(core));
                report.playwright = { package: "playwright-core", version: require(path.join(core, "package.json")).version };
            }
            browser = await chromium.launch({ headless: true, chromiumSandbox: true, ...(args.browser ? { executablePath: args.browser } : {}) });
        } catch (error) {
            report.status = "BLOCKED";
            report.error = `Browser unavailable; no layout acceptance result. ${String(error.message).slice(0, 6000)}`;
            process.exitCode = 2;
            return;
        }
        report.browserVersion = browser.version();
        report.browserExecutable = args.browser || "Playwright-managed Chromium";
        for (const camera of CAMERAS) for (const mode of ["document-created", "after-load"]) {
            await cameraCase(browser, camera, mode, script, report, args.outputDir);
        }
        await guardCases(browser, script, report);
        assert.equal(report.network.aborted, 0, "An unexpected request was attempted (and aborted)");
        assert.equal(sha256(fs.readFileSync(SCRIPT_PATH, "utf8")), report.scriptSha256, "Bundled script changed during QA");
        report.status = "PASS";
    } catch (error) {
        report.status = "FAIL";
        report.error = String(error.stack || error);
        process.exitCode = 1;
    } finally {
        if (browser) await browser.close();
        report.finishedAt = new Date().toISOString();
        const filename = path.join(args.outputDir, "CAMERA_PLAYER_LAYOUT.json");
        fs.writeFileSync(filename, `${JSON.stringify(report, null, 2)}\n`);
        console.log(JSON.stringify({ status: report.status, kind: report.kind, cases: report.cases.length,
            guards: report.guards.length, screenshots: report.screenshots.length, report: filename }));
    }
}

main().catch(error => { console.error(String(error.stack || error)); process.exitCode = 1; });
