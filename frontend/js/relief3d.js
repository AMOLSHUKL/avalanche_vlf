/**
 * AVLF.Relief3D — realistic alpine terrain relief engine (three.js).
 *
 * Terrain: PlaneGeometry displaced by the analytical DEM (avalanche slope with
 * sinusoidal gully runout), rendered with a custom ShaderMaterial providing:
 *   · directional hillshade lighting (ambient + sun uniforms)
 *   · elevation contour isolines (25 m, index 100 m) via fwidth AA
 *   · slope-steepness hazard tint (>30° avalanche zones)
 *   · UTM grid lines, night-ops tone in dark theme
 *   · fused posterior projection from the shared AVLF.Fusion canvas texture
 * Targets: surface beacon + burial shaft + error sphere + pulse ring per
 * P1/P2/P3 cell. Burial depths are exaggerated ×12 vertically for visibility
 * at sector scale (documented on the legend tooltip).
 */
window.AVLF = window.AVLF || {};
(function (AVLF) {
    "use strict";
    const G = AVLF.GEO, DEM = AVLF.DEM;
    const S = G.SECTOR_M;
    const VEX = 1.6;                 // vertical exaggeration for relief readability
    const SHAFT_K = 12;              // burial depth exaggeration (visual)
    const POLAR_MIN = 15 * Math.PI / 180;
    const POLAR_MAX = 80 * Math.PI / 180;

    let renderer, scene, camera, controls, terrain, worldGroup, skirtMat;
    let cv = null, active = false, lastPaint = 0;
    let reticle3d = null;
    const uavMarks = {};
    // Marker diff only runs when inputs actually change (fusion data version
    // or selection), not every frame — the full 10k-cell sweep is not free.
    let lastMarkerRev = -1, lastSelSync = null;
    const markers = new Map();       // cellKey -> marker group
    let themeIsDark = false;

    const heatCanvas = AVLF.Fusion.canvas;
    const fusionTex = (() => {
        const t = new THREE.CanvasTexture(heatCanvas);
        t.anisotropy = 4;
        return t;
    })();

    /* ------------------------- Theme calibration ------------------------- */
    const THEMES = {
        light: {
            snow: new THREE.Color(0xf7faff), rock: new THREE.Color(0x8e8b86),
            skyAmb: new THREE.Color(0xdfe9f5), groundAmb: new THREE.Color(0x7e8896),
            sun: new THREE.Color(0xfff2df), sunInt: .95, ambInt: .55,
            line: new THREE.Color(0x51637c), gridLine: new THREE.Color(0x6b8098),
            hazard: new THREE.Color(0xdc2626), fog: new THREE.Color(0xd7e2ef),
            sky: 0xd7e2ef
        },
        dark: {
            snow: new THREE.Color(0x9fb6d8), rock: new THREE.Color(0x232f45),
            skyAmb: new THREE.Color(0x1c2942), groundAmb: new THREE.Color(0x0d1524),
            sun: new THREE.Color(0xaecbff), sunInt: .5, ambInt: .5,
            line: new THREE.Color(0x4f9fd9), gridLine: new THREE.Color(0x2f6f9f),
            hazard: new THREE.Color(0xf87171), fog: new THREE.Color(0x0b1120),
            sky: 0x0b1120
        }
    };

    /* --------------------------- Shader material -------------------------- */
    const uniforms = {
        uSnowColor:      { value: null },
        uRockColor:      { value: null },
        uSkyAmb:         { value: null },
        uGroundAmb:      { value: null },
        uSunDir:         { value: new THREE.Vector3(-0.55, 0.72, 0.42).normalize() },
        uSunColor:       { value: null },
        uSunInt:         { value: .95 },
        uAmbInt:         { value: .55 },
        uFusion:         { value: fusionTex },
        uFusionOpacity:  { value: 1.0 },
        uContours:       { value: 1.0 },
        uContourMinor:   { value: 25.0 },
        uContourMajor:   { value: 100.0 },
        uLineColor:      { value: null },
        uSlopeOverlay:   { value: 0.0 },
        uHazardColor:    { value: null },
        uGrid:           { value: 1.0 },
        uGridColor:      { value: null },
        uVex:            { value: VEX },
        uFogColor:       { value: null },
        uFogNear:        { value: 650.0 },
        uFogFar:         { value: 1500.0 }
    };

    const vertexShader = [
        "attribute float aHeightM;",
        "varying vec3 vNormal;",
        "varying vec3 vWorldPos;",
        "varying vec2 vUv;",
        "varying float vHeightM;",
        "uniform float uVex;",
        "void main() {",
        "    vNormal = normalize(normalMatrix * normal);",
        "    vec3 p = position;",
        "    p.z = (aHeightM - 3800.0) * uVex;",   // plane-space up before rotation
        "    vHeightM = aHeightM;",
        "    vec4 wp = modelMatrix * vec4(p, 1.0);",
        "    vWorldPos = wp.xyz;",
        "    vUv = uv;",
        "    gl_Position = projectionMatrix * viewMatrix * wp;",
        "}"
    ].join("\n");

    // NOTE: normals are recomputed on the CPU after displacement; the fragment
    // stage consumes them directly (vNormal is view-space, sun dir is given in
    // view space too via uniform update per frame).
    const fragmentShader = [
        "precision highp float;",
        "uniform vec3 uSnowColor;",
        "uniform vec3 uRockColor;",
        "uniform vec3 uSkyAmb;",
        "uniform vec3 uGroundAmb;",
        "uniform vec3 uSunDir;",
        "uniform vec3 uSunColor;",
        "uniform float uSunInt;",
        "uniform float uAmbInt;",
        "uniform sampler2D uFusion;",
        "uniform float uFusionOpacity;",
        "uniform float uContours;",
        "uniform float uContourMinor;",
        "uniform float uContourMajor;",
        "uniform vec3 uLineColor;",
        "uniform float uSlopeOverlay;",
        "uniform vec3 uHazardColor;",
        "uniform float uGrid;",
        "uniform vec3 uGridColor;",
        "uniform float uVex;",
        "uniform vec3 uFogColor;",
        "uniform float uFogNear;",
        "uniform float uFogFar;",
        "varying vec3 vNormal;",
        "varying vec3 vWorldPos;",
        "varying vec2 vUv;",
        "varying float vHeightM;",

        "float isoLine(float meters, float interval, float thickness) {",
        "    float g = abs(fract(meters / interval + 0.5) - 0.5) * interval;", // dist to line (m)",
        // Screen-space AA via fwidth() when the derivatives extension exists
        // (WebGL2 always; WebGL1 only with OES_standard_derivatives). Without
        // it — old WebGL1-only devices, software GL — fall back to a fixed
        // world-space line width so isolines still render, just unrefined.
        "#ifdef GL_OES_standard_derivatives",
        "    float w = fwidth(meters) * thickness;",
        "#else",
        "    float w = interval * 0.004 * thickness;",
        "#endif",
        "    return 1.0 - smoothstep(w, w * 2.0, g);",
        "}",

        "void main() {",
        "    vec3 N = normalize(vNormal);",
        // The slab is double-sided; shade its underside with the same lit
        // model or backfaces read as dark metallic blades from behind.
        "    if (!gl_FrontFacing) N = -N;",
        "    float ndl = max(dot(N, uSunDir), 0.0);",
        // Alpine surface: snow on holdable ground, rock exposure on the steep
        // release walls.
        "    float slopeDeg = degrees(acos(clamp(N.y, 0.0, 1.0)));",
        "    float relH = clamp((vHeightM - 3830.0) / 280.0, 0.0, 1.0);",
        "    float snow = smoothstep(0.0, 0.10, relH) * (1.0 - smoothstep(38.0, 50.0, slopeDeg));",
        "    vec3 albedo = mix(uRockColor, uSnowColor, snow);",
        // Broad low-frequency variation so the face never reads as brushed
        // metal: two cheap trig octaves beat against each other.
        "    float shadeN = sin(vWorldPos.x * 0.021 + vWorldPos.z * 0.017)",
        "        * sin(vWorldPos.z * 0.023 - vWorldPos.x * 0.011)",
        "        + 0.6 * sin(vHeightM * 0.055 + vWorldPos.x * 0.007);",
        "    albedo *= 1.0 + 0.055 * shadeN;",
        // Hemisphere ambient (sky from above, rock bounce from below) + sun.
        "    vec3 hemi = mix(uGroundAmb, uSkyAmb, N.y * 0.5 + 0.5);",
        // Snow scatters: cut directional contrast on snow, keep it on rock.
        "    float dirK = uSunInt * mix(1.0, 0.55, snow);",
        "    vec3 lit = albedo * (hemi * uAmbInt + uSunColor * dirK * ndl);",
        // Snow shadows read blue, not grey.
        "    lit = mix(lit, lit * vec3(0.80, 0.87, 1.08), (1.0 - ndl) * snow * 0.55);",

        // Slope steepness hazard tint (>30 deg avalanche zones)
        "    float hazard = smoothstep(30.0, 38.0, slopeDeg) * uSlopeOverlay;",
        "    lit = mix(lit, uHazardColor, hazard * 0.42);",

        // Elevation contour isolines (minor 25 m, major 100 m)
        "    if (uContours > 0.5) {",
        "        float minor = isoLine(vHeightM, uContourMinor, 1.1);",
        "        float major = isoLine(vHeightM, uContourMajor, 1.4);",
        "        lit = mix(lit, uLineColor, minor * 0.16 + major * 0.28);",
        "    }",

        // UTM grid every 50 m in world XZ
        "    if (uGrid > 0.5) {",
        "        float gx = isoLine(vWorldPos.x, 100.0, 1.2);",
        "        float gz = isoLine(vWorldPos.z, 100.0, 1.2);",
        "        lit = mix(lit, uGridColor, max(gx, gz) * 0.17);",
        "    }",

        // Fused posterior projection
        "    vec4 fus = texture2D(uFusion, vUv);",
        "    lit = mix(lit, fus.rgb, fus.a * uFusionOpacity * 0.92);",

        // Depth cue
        "    float dist = length(cameraPosition - vWorldPos);",
        "    float fogK = smoothstep(uFogNear, uFogFar, dist);",
        "    lit = mix(lit, uFogColor, fogK * 0.85);",

        "    gl_FragColor = vec4(lit, 1.0);",
        "}"
    ].join("\n");

    /* ------------------------------ Build ------------------------------ */
    function init(canvasEl) {
        cv = canvasEl;
        renderer = new THREE.WebGLRenderer({ canvas: cv, antialias: true });
        renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
        scene = new THREE.Scene();
        camera = new THREE.PerspectiveCamera(52, 1, 1, 4000);

        controls = new THREE.OrbitControls(camera, cv);
        controls.enableDamping = true;
        controls.dampingFactor = .08;
        controls.minPolarAngle = POLAR_MIN;   // 15° — no flipping beneath terrain
        controls.maxPolarAngle = POLAR_MAX;   // 80° — near-horizon but above ground
        controls.minDistance = 70;
        controls.maxDistance = 850;

        // The orbit target must live ON the slab surface. A buried target made
        // the collision floor fight the damped controls every frame — camera
        // shoved around, zoom blocked, felt like diving under the map.
        worldGroup = new THREE.Group();
        scene.add(worldGroup);
        buildTerrain();

        const t0 = new THREE.Vector3(0, surfaceY(50, 50) + 6, 0);
        controls.target.copy(t0);
        camera.position.copy(sph(470, 52 * Math.PI / 180, 38 * Math.PI / 180)).add(t0);

        buildSkirt();
        buildAvalanche();
        buildLandscape();
        buildLights();
        buildUavMarkers();
        applyTheme(document.documentElement.getAttribute("data-theme") === "dark");
        initHud();
        resize();
        window.addEventListener("resize", resize);
        window.addEventListener("orientationchange", () => setTimeout(resize, 120));
    }

    /* Immediate, stutter-free modality updates: fusion repaints its canvas,
       we just flip needsUpdate so the next frame re-uploads the texture. */
    function flagFusionDirty() { fusionTex.needsUpdate = true; }

    function buildTerrain() {
        const geo = new THREE.PlaneGeometry(S, S, G.GRID - 1, G.GRID - 1);
        const count = geo.attributes.position.count;
        const heights = new Float32Array(count);
        const pos = geo.attributes.position;
        for (let i = 0; i < count; i++) {
            const cx = Math.round((pos.getX(i) + S / 2) / G.CELL_M - .5);
            const cy = Math.round((pos.getY(i) + S / 2) / G.CELL_M - .5);
            heights[i] = DEM.elevation(clampI(cx), clampI(cy));
        }
        geo.setAttribute("aHeightM", new THREE.BufferAttribute(heights, 1));
        // Displace CPU-side too so computeVertexNormals yields true normals
        // (the vertex shader re-displaces identically).
        for (let i = 0; i < count; i++)
            pos.setZ(i, (heights[i] - 3800) * VEX);
        geo.rotateX(-Math.PI / 2);
        geo.computeVertexNormals();

        const mat = new THREE.ShaderMaterial({
            uniforms, vertexShader, fragmentShader,
            // Contour isolines use fwidth(); under WebGL1 this needs the
            // derivatives extension declared or the fragment shader won't link.
            extensions: { derivatives: true },
            // Double-sided so the slab occludes from every side: looking at
            // the mountain from behind must show rock, not markers floating
            // in a see-through sheet.
            side: THREE.DoubleSide
        });
        terrain = new THREE.Mesh(geo, mat);
        worldGroup.add(terrain);
    }
    const clampI = v => Math.max(0, Math.min(G.GRID - 1, v));

    /* Solid terrain slab: extrude the DEM boundary down to y = -50 m so the
       relief reads as a physical block. Vertex-colored: snow tone at the rim
       fading into the sky/fog tone at the base, so a grazing view reads as a
       grounded mass instead of two floating grey lines (the old "long grey
       line" artifact was this wall's uniform color edge-on). */
    let skirtGeo = null;
    function buildSkirt() {
        const BASE_Y = -50;
        // Closed perimeter walk over boundary cell centers: north row →
        // east col → south row → west col, wrapping cleanly to start.
        const ring = [];
        for (let i = 0; i < G.GRID; i++) ring.push([i, G.GRID - 1]);
        for (let i = G.GRID - 2; i >= 0; i--) ring.push([G.GRID - 1, i]);
        for (let i = G.GRID - 2; i >= 0; i--) ring.push([i, 0]);
        for (let i = 1; i <= G.GRID - 2; i++) ring.push([0, i]);

        const pos = [], col = [], idx = [];
        const n = ring.length;
        ring.forEach(([cx, cy], i) => {
            const wx = (cx + .5) * 5 - S / 2;
            const wz = (cy + .5) * 5 - S / 2;
            const h = (DEM.elevation(clampI(cx), clampI(cy)) - 3800) * VEX;
            pos.push(wx, h, wz, wx, BASE_Y, wz);
            col.push(1, 1, 1, 0, 0, 0);   // rim→base mix factor; themed in applyTheme
            const a = i, b = (i + 1) % n;
            idx.push(a * 2, b * 2, a * 2 + 1,
                     b * 2, b * 2 + 1, a * 2 + 1);
        });

        skirtGeo = new THREE.BufferGeometry();
        skirtGeo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(pos), 3));
        skirtGeo.setAttribute("color", new THREE.BufferAttribute(new Float32Array(col), 3));
        skirtGeo.setIndex(idx);
        skirtMat = new THREE.MeshBasicMaterial({
            vertexColors: true, side: THREE.DoubleSide
        });
        worldGroup.add(new THREE.Mesh(skirtGeo, skirtMat));
    }

    /* --------------------------- Landscape assets ---------------------------
       Procedural, instanced, terrain-conforming: snow pines below the
       treeline, rock outcrops on steep faces and the gully flanks, and a
       small base camp on the southern flat. Deterministic PRNG so every
       reload places the same forest. */
    function mulberry32(a) {
        return function () {
            a |= 0; a = a + 0x6D2B79F5 | 0;
            let t = Math.imul(a ^ a >>> 15, 1 | a);
            t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
            return ((t ^ t >>> 14) >>> 0) / 4294967296;
        };
    }
    function gullyDistM(xm, ym) {
        const ax = 170, ay = 430, bx = 330, by = 100;
        const abx = bx - ax, aby = by - ay;
        const t = Math.max(0, Math.min(1, ((xm - ax) * abx + (ym - ay) * aby) / (abx * abx + aby * aby)));
        return Math.hypot(xm - (ax + t * abx), ym - (ay + t * aby));
    }
    const landscapeMats = {};
    function buildLandscape() {
        const rnd = mulberry32(20260825);
        const dummy = new THREE.Object3D();

        // Snow pines: two-tier merged cone canopy, instanced.
        const tiers = [{ r: 2.4, h: 5.2, y: 3.1 }, { r: 1.7, h: 4.0, y: 6.1 }];
        const geos = tiers.map(t => {
            const g = new THREE.ConeGeometry(t.r, t.h, 7);
            g.translate(0, t.y, 0);
            return g;
        });
        let vN = 0, iN = 0;
        geos.forEach(g => { vN += g.attributes.position.count; iN += g.index.count; });
        const pArr = new Float32Array(vN * 3), nArr = new Float32Array(vN * 3);
        const iArr = new Uint16Array(iN);
        let vo = 0, io = 0;
        geos.forEach(g => {
            pArr.set(g.attributes.position.array, vo * 3);
            nArr.set(g.attributes.normal.array, vo * 3);
            for (let i = 0; i < g.index.count; i++) iArr[io + i] = g.index.array[i] + vo;
            vo += g.attributes.position.count; io += g.index.count;
            g.dispose();
        });
        const pineGeo = new THREE.BufferGeometry();
        pineGeo.setAttribute("position", new THREE.BufferAttribute(pArr, 3));
        pineGeo.setAttribute("normal", new THREE.BufferAttribute(nArr, 3));
        pineGeo.setIndex(new THREE.BufferAttribute(iArr, 1));

        const spots = [];
        for (let tries = 0; tries < 2400 && spots.length < 130; tries++) {
            const cx = 2 + Math.floor(rnd() * 96), cy = 2 + Math.floor(rnd() * 96);
            const xm = cx * 5, ym = cy * 5;
            if (DEM.elevation(cx, cy) > 3950) continue;          // treeline
            if (DEM.slopeDeg(cx, cy) > 24) continue;             // holdable ground
            if (gullyDistM(xm, ym) < 46) continue;               // avalanche track
            if (Math.hypot(xm - 60, ym - 60) < 34) continue;     // base camp
            if (spots.some(sp => Math.hypot(sp[0] - cx, sp[1] - cy) < 3.4)) continue;
            spots.push([cx, cy]);
        }
        landscapeMats.pine = new THREE.MeshLambertMaterial({ color: 0x2a5a42 });
        const pines = new THREE.InstancedMesh(pineGeo, landscapeMats.pine, spots.length);
        spots.forEach(([cx, cy], i) => {
            dummy.position.set((cx + .5) * 5 - S / 2, surfaceY(cx, cy) - .3, (cy + .5) * 5 - S / 2);
            dummy.rotation.set(0, rnd() * Math.PI * 2, 0);
            dummy.scale.setScalar(.75 + rnd() * .75);
            dummy.updateMatrix();
            pines.setMatrixAt(i, dummy.matrix);
        });
        worldGroup.add(pines);

        // Rock outcrops: steep faces and the gully flanks.
        const rSpots = [];
        for (let tries = 0; tries < 1600 && rSpots.length < 64; tries++) {
            const cx = 2 + Math.floor(rnd() * 96), cy = 2 + Math.floor(rnd() * 96);
            const xm = cx * 5, ym = cy * 5;
            const steep = DEM.slopeDeg(cx, cy) > 30 || gullyDistM(xm, ym) < 34;
            if (!steep || Math.hypot(xm - 60, ym - 60) < 30) continue;
            rSpots.push([cx, cy]);
        }
        landscapeMats.rock = new THREE.MeshLambertMaterial({ color: 0x8d8a84 });
        const rockGeo = new THREE.IcosahedronGeometry(1.6, 0);
        const rocks = new THREE.InstancedMesh(rockGeo, landscapeMats.rock, rSpots.length);
        rSpots.forEach(([cx, cy], i) => {
            dummy.position.set((cx + .5) * 5 - S / 2, surfaceY(cx, cy) + .2, (cy + .5) * 5 - S / 2);
            dummy.rotation.set(rnd() * .6, rnd() * Math.PI * 2, rnd() * .6);
            dummy.scale.set(1 + rnd() * 1.6, .7 + rnd() * .9, 1 + rnd() * 1.6);
            dummy.updateMatrix();
            rocks.setMatrixAt(i, dummy.matrix);
        });
        worldGroup.add(rocks);

        // Base camp: two tents, antenna mast with beacon, supply crates.
        const camp = new THREE.Group();
        const tentMat = new THREE.MeshLambertMaterial({ color: 0xd97706 });
        const tent2Mat = new THREE.MeshLambertMaterial({ color: 0x0891b2 });
        const kitMat = new THREE.MeshLambertMaterial({ color: 0x6b7280 });
        const mkTent = (mat, r, len, dx, dz) => {
            const t = new THREE.Mesh(new THREE.CylinderGeometry(r, r, len, 3), mat);
            t.rotation.x = Math.PI / 2;
            t.rotation.z = Math.PI / 2;
            t.position.set(dx, r * .72, dz);
            return t;
        };
        const cy0 = surfaceY(12, 12);
        camp.add(mkTent(tentMat, 2.6, 6.5, -5, 0));
        camp.add(mkTent(tent2Mat, 2.0, 5.0, 4.5, 4));
        const mast = new THREE.Mesh(new THREE.CylinderGeometry(.14, .2, 11, 6), kitMat);
        mast.position.set(1, cy0 + 5.5, -5);
        const beacon = new THREE.Mesh(new THREE.SphereGeometry(.5, 8, 6),
            new THREE.MeshBasicMaterial({ color: 0xdc2626 }));
        beacon.position.set(1, cy0 + 11.2, -5);
        const crate = (dx, dz, s) => {
            const c = new THREE.Mesh(new THREE.BoxGeometry(s, s, s), kitMat);
            c.position.set(dx, cy0 + s / 2, dz);
            c.rotation.y = rnd() * 1.2;
            return c;
        };
        camp.add(mast, beacon, crate(-1.5, 6.5, 1.7), crate(.6, 7.6, 1.2));
        // Camp authored around its local origin; place at cell (12,12) and
        // lift every part onto the local ground height.
        camp.position.set((12.5) * 5 - S / 2, 0, (12.5) * 5 - S / 2);
        camp.children.forEach(o => { o.position.y += surfaceY(12, 12); });
        worldGroup.add(camp);
        landscapeMats.beacon = beacon;
    }

    function buildLights() {
        scene.add(new THREE.AmbientLight(0xffffff, .5));
        const sun = new THREE.DirectionalLight(0xffffff, .9);
        sun.position.set(-320, 300, 200);
        scene.add(sun);
    }

    /* Low-poly quadcopter: fuselage + X arms + four spinning rotor discs +
       nav lights, heading-oriented with a banking roll into turns. All
       Lambert so the scene sun reads across the hull. */
    function buildQuadcopter(col) {
        const g = new THREE.Group();
        const hull = new THREE.MeshLambertMaterial({ color: col });
        const dark = new THREE.MeshLambertMaterial({ color: 0x1c2431 });
        const body = new THREE.Mesh(new THREE.BoxGeometry(2.6, 1.0, 4.2), hull);
        const nose = new THREE.Mesh(new THREE.SphereGeometry(1.3, 10, 8), hull);
        nose.position.set(0, 0, 2.1);
        const gimbal = new THREE.Mesh(new THREE.SphereGeometry(.7, 8, 6), dark);
        gimbal.position.set(0, -.8, 1.6);
        g.add(body, nose, gimbal);
        const rotors = [];
        [[-2.6, -2.6], [2.6, -2.6], [-2.6, 2.6], [2.6, 2.6]].forEach(([ax, az], i) => {
            const arm = new THREE.Mesh(new THREE.BoxGeometry(.55, .4, 3.6), dark);
            arm.position.set(ax * .5, .1, az * .5);
            arm.rotation.y = Math.atan2(ax, az);
            g.add(arm);
            const pod = new THREE.Mesh(new THREE.CylinderGeometry(.55, .65, .7, 8), dark);
            pod.position.set(ax, .2, az);
            const disc = new THREE.Mesh(
                new THREE.CylinderGeometry(2.1, 2.1, .1, 14),
                new THREE.MeshBasicMaterial({
                    color: 0xdfe9f5, transparent: true, opacity: .34, depthWrite: false
                }));
            disc.position.set(ax, .75, az);
            g.add(pod, disc);
            rotors.push(disc);
            const lamp = new THREE.Mesh(
                new THREE.SphereGeometry(.32, 6, 5),
                new THREE.MeshBasicMaterial({ color: i < 2 ? 0xdc2626 : 0x22c55e }));
            lamp.position.set(ax, -.25, az);
            g.add(lamp);
        });
        const strobe = new THREE.Mesh(
            new THREE.SphereGeometry(.38, 6, 5),
            new THREE.MeshBasicMaterial({ color: 0xffffff }));
        strobe.position.set(0, .95, 0);
        g.add(strobe);
        return { grp: g, rotors, strobe };
    }

    function buildUavMarkers() {
        [["UAV_ALPHA", 0x0891b2], ["UAV_BRAVO", 0x7c3aed]].forEach(([id, col]) => {
            const quad = buildQuadcopter(col);
            const grp = quad.grp;
            const halo = new THREE.Mesh(
                new THREE.RingGeometry(6.5, 8, 36),
                new THREE.MeshBasicMaterial({ color: col, transparent: true, opacity: .55, side: THREE.DoubleSide }));
            halo.rotation.x = -Math.PI / 2;
            const beam = new THREE.Mesh(
                new THREE.ConeGeometry(9, 34, 18, 1, true),
                new THREE.MeshBasicMaterial({ color: col, transparent: true, opacity: .06, side: THREE.DoubleSide }));
            beam.position.y = -17; beam.rotation.x = Math.PI;
            const trailGeo = new THREE.BufferGeometry();
            trailGeo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(60 * 3), 3));
            trailGeo.setDrawRange(0, 0);
            const trail = new THREE.Line(trailGeo,
                new THREE.LineBasicMaterial({ color: col, transparent: true, opacity: .4 }));
            grp.add(halo, beam);
            worldGroup.add(grp, trail);
            uavMarks[id] = { grp, halo, beam, trail, rotors: quad.rotors, strobe: quad.strobe,
                             pts: [], phase: Math.random() * 6, lastHeading: null };
        });
    }

    function applyTheme(isDark) {
        themeIsDark = isDark;
        const T = THEMES[isDark ? "dark" : "light"];
        uniforms.uSnowColor.value = T.snow;
        uniforms.uRockColor.value = T.rock;
        uniforms.uSkyAmb.value = T.skyAmb;
        uniforms.uGroundAmb.value = T.groundAmb;
        uniforms.uSunColor.value = T.sun;
        uniforms.uSunInt.value = T.sunInt;
        uniforms.uAmbInt.value = T.ambInt;
        uniforms.uLineColor.value = T.line;
        uniforms.uHazardColor.value = T.hazard;
        uniforms.uGridColor.value = T.gridLine;
        uniforms.uFogColor.value = T.fog;
        // Skirt rim fades snow→fog down the wall; a uniform-colored wall read
        // as stark slivers wherever the boundary dipped below the silhouette.
        if (skirtGeo) {
            const c = skirtGeo.attributes.color;
            const rim = isDark ? T.snow : T.snow.clone().multiplyScalar(.96);
            for (let i = 0; i < c.count; i += 2) {
                c.setXYZ(i, rim.r, rim.g, rim.b);
                c.setXYZ(i + 1, T.fog.r, T.fog.g, T.fog.b);
            }
            c.needsUpdate = true;
        }
        if (landscapeMats.pine) {
            landscapeMats.pine.color.set(themeIsDark ? 0x1a3328 : 0x2a5a42);
            landscapeMats.rock.color.set(themeIsDark ? 0x39435a : 0x8d8a84);
            if (landscapeMats.beacon)
                landscapeMats.beacon.material.color.set(themeIsDark ? 0xf87171 : 0xdc2626);
        }
        if (aval) {
            aval.uni.uFlowColor.value.set(themeIsDark ? 0xcfe0f5 : 0xffffff);
            aval.uni.uDepositColor.value.set(themeIsDark ? 0x7e97b8 : 0xdfe8f2);
            aval.uni.uFogColor.value.copy(T.fog);
        }
        scene.background = new THREE.Color(T.sky);
        renderer.setClearColor(T.sky);
        if (terrain) terrain.material.needsUpdate = true;
    }

    /* --------------------- Target subsurface markers --------------------- */
    function surfaceY(cx, cy) { return (DEM.elevation(clampI(cx), clampI(cy)) - 3800) * VEX; }

    /* --------------------- Target markers with LOD --------------------- *
     * Triage LOD rules:
     *   FULL — P1 targets and the currently selected target: beacon, burial
     *          shaft, exact burial point, ±r error sphere, pulse ring.
     *   DOT  — secondary P2/P3 targets: low-profile surface disc colored by
     *          posterior confidence (same ramp as the legend), no shaft.
     * Selecting a card transitions its marker dot→full, shows the animated
     * reticle, and dims every unrelated marker by 40% opacity.
     */
    function confidenceColor(p) {
        return p >= 0.85 ? 0xdc2626 : p >= 0.45 ? 0xd97706 : 0x0284c7;
    }

    function syncMarkers() {
        const state = AVLF.state;
        const want = new Map();          // key -> {c, mode}
        state.cells.forEach(c => {
            if (c.zone !== "P1" && c.zone !== "P2" && c.zone !== "P3") return;
            const key = `${c.x}_${c.y}`;
            want.set(key, {
                c,
                mode: (c.zone === "P1" || key === state.selectedKey) ? "full" : "dot"
            });
        });

        markers.forEach((m, key) => {
            if (!want.has(key)) { worldGroup.remove(m.grp); disposeGroup(m.grp); markers.delete(key); }
        });
        want.forEach(({ c, mode }, key) => {
            let m = markers.get(key);
            if (m && m.mode !== mode) {           // dot ⇄ full transition
                worldGroup.remove(m.grp); disposeGroup(m.grp); markers.delete(key);
                m = null;
            }
            if (!m) { m = buildMarker(c, mode); markers.set(key, m); }
            applyDim(m, !!state.selectedKey && key !== state.selectedKey);
            if (mode === "dot") m.disc.material.color.setHex(confidenceColor(c.p));
        });

        // Reticle rides the selected marker's true surface position.
        const sel = state.selectedKey ? markers.get(state.selectedKey) : null;
        positionReticle(sel ? new THREE.Vector3(sel.grp.position.x, sel.surfaceY, sel.grp.position.z) : null,
                        sel ? sel.zone : null);
    }

    function trackMat(list, mat, baseOpacity) {
        mat.transparent = true;
        mat.userData.baseOpacity = baseOpacity;
        list.push(mat);
        return mat;
    }
    function applyDim(m, dimmed) {
        const k = dimmed ? 0.6 : 1;   // dim unrelated markers by 40%
        m.dimmed = dimmed;
        m.mats.forEach(mat => { if (mat !== m.pulse?.material) mat.opacity = mat.userData.baseOpacity * k; });
    }
    function disposeGroup(grp) {
        grp.traverse(o => {
            if (o.geometry && o.geometry.dispose) o.geometry.dispose();
            if (o.material && o.material.dispose) o.material.dispose();
        });
    }

    function buildMarker(c, mode) {
        const grp = new THREE.Group();
        const wx = (c.x + .5) * 5 - S / 2, wz = (c.y + .5) * 5 - S / 2;
        const gy = surfaceY(c.x, c.y);
        const colHex = c.zone === "P1" ? 0xdc2626 : c.zone === "P2" ? 0xd97706 : 0x0284c7;
        const mats = [];
        grp.position.set(wx, 0, wz);
        worldGroup.add(grp);

        // Low-profile dot: posterior-confidence colored surface disc.
        if (mode === "dot") {
            const disc = new THREE.Mesh(
                new THREE.CircleGeometry(3.2, 18),
                trackMat(mats, new THREE.MeshBasicMaterial({ color: confidenceColor(c.p) }), .92));
            disc.rotation.x = -Math.PI / 2;
            disc.position.y = gy + .6;
            grp.add(disc);
            return { grp, mats, disc, mode, zone: c.zone, surfaceY: gy };
        }

        // Full subsurface treatment
        const depthM = c.depth != null ? c.depth : 1.2;

        const cone = new THREE.Mesh(
            new THREE.ConeGeometry(2.6, 7, 10),
            trackMat(mats, new THREE.MeshBasicMaterial({ color: colHex }), 1));
        cone.position.y = gy + 4.5;
        const halo = new THREE.Mesh(
            new THREE.RingGeometry(5, 6.6, 30),
            trackMat(mats, new THREE.MeshBasicMaterial({
                color: colHex, side: THREE.DoubleSide
            }), .75));
        halo.rotation.x = -Math.PI / 2;
        halo.position.y = gy + .5;

        const pulse = new THREE.Mesh(
            new THREE.RingGeometry(6.5, 8.2, 32),
            trackMat(mats, new THREE.MeshBasicMaterial({
                color: colHex, side: THREE.DoubleSide
            }), .8));
        pulse.rotation.x = -Math.PI / 2;
        pulse.position.y = gy + .7;

        const shaftLen = Math.max(depthM * SHAFT_K, 5);
        const shaft = new THREE.Mesh(
            new THREE.CylinderGeometry(2.1, 2.1, shaftLen, 12, 1, true),
            trackMat(mats, new THREE.MeshBasicMaterial({
                color: colHex, side: THREE.DoubleSide, depthWrite: false
            }), .28));
        shaft.position.y = gy - shaftLen / 2;

        const point = new THREE.Mesh(
            new THREE.SphereGeometry(1.7, 12, 10),
            trackMat(mats, new THREE.MeshBasicMaterial({ color: colHex }), 1));
        point.position.y = gy - shaftLen;

        const rVis = Math.max((c.radius || 1.2) * 3.5, 3);
        const err = new THREE.Mesh(
            new THREE.SphereGeometry(rVis, 14, 10),
            trackMat(mats, new THREE.MeshBasicMaterial({
                color: colHex, wireframe: true, depthWrite: false
            }), .13));
        err.position.y = gy - shaftLen;

        grp.add(cone, halo, pulse, shaft, point, err);
        return { grp, mats, pulse, halo, mode, depth: depthM, zone: c.zone, surfaceY: gy };
    }

    /* --------------------------- Targeting reticle --------------------------- */
    function ensureReticle() {
        if (reticle3d) return reticle3d;
        const g = new THREE.Group();
        const arcs = [];
        for (let i = 0; i < 4; i++) {
            const arc = new THREE.Mesh(
                new THREE.RingGeometry(11, 13.4, 24, 1, i * Math.PI / 2, Math.PI / 2 * .58),
                new THREE.MeshBasicMaterial({ color: 0xdc2626, side: THREE.DoubleSide, transparent: true, opacity: .95 }));
            arcs.push(arc);
            g.add(arc);
        }
        g.visible = false;
        scene.add(g);
        reticle3d = { grp: g, arcs };
        return reticle3d;
    }
    function positionReticle(posOrNull, zone) {
        const r = ensureReticle();
        if (!posOrNull) { r.grp.visible = false; return; }
        const col = zone === "P1" ? 0xdc2626 : zone === "P2" ? 0xd97706 : 0x0284c7;
        r.arcs.forEach(a => a.material.color.setHex(col));
        r.grp.position.copy(posOrNull);
        r.grp.position.y += 2;
        r.grp.visible = true;
    }

    /* ---------------------- Orientation gizmo (corner compass) ----------------------
       Lightweight DOM compass synced to OrbitControls azimuth/polar. Clicking
       it smooth-interpolates back to North-Up. Zero GL cost, updated only when
       the heading moves. */
    let lastGizmoAz = 999, lastGizmoPol = 999;
    function syncGizmo() {
        const rose = document.getElementById("gizmoRose");
        if (!rose || !controls) return;
        const az = controls.getAzimuthalAngle ? controls.getAzimuthalAngle() : 0;
        const pol = controls.getPolarAngle ? controls.getPolarAngle() : 0;
        const azDeg = Math.round(-az * 180 / Math.PI * 10) / 10;
        const polDeg = Math.round(pol * 180 / Math.PI);
        if (Math.abs(azDeg - lastGizmoAz) < .2 && polDeg === lastGizmoPol) return;
        lastGizmoAz = azDeg; lastGizmoPol = polDeg;
        rose.style.transform = `rotate(${azDeg}deg)`;
        const tilt = document.getElementById("gizmoTilt");
        if (tilt) tilt.textContent = `${polDeg}°`;
    }

    /* ------------------------------ Camera ops ------------------------------ */
    let flyAnim = null;
    let preset = "orbit";
    function flyTo(pos, tgt, dur) {
        const p0 = camera.position.clone(), t0 = controls.target.clone();
        const start = performance.now(), d = dur == null ? 850 : dur;
        flyAnim = () => {
            const k = Math.min(1, (performance.now() - start) / d);
            const e = 1 - Math.pow(1 - k, 3);
            camera.position.lerpVectors(p0, pos, e);
            controls.target.lerpVectors(t0, tgt, e);
            if (k >= 1) flyAnim = null;
        };
    }
    // Spherical helper: polar from +Y, azimuth from +Z toward +X.
    function sph(radius, polar, azim) {
        return new THREE.Vector3(
            radius * Math.sin(polar) * Math.sin(azim),
            radius * Math.cos(polar),
            radius * Math.sin(polar) * Math.cos(azim));
    }

    function focusCell(cx, cy) {
        const tx = (cx + .5) * 5 - S / 2, tz = (cy + .5) * 5 - S / 2;
        const ty = surfaceY(cx, cy);
        flyTo(sph(190, 52 * Math.PI / 180, 35 * Math.PI / 180).add(new THREE.Vector3(tx, ty, tz)),
              new THREE.Vector3(tx, ty, tz));
        preset = "orbit";
    }

    function recenterExtents() {
        const pts = [];
        AVLF.state.cells.forEach(c => {
            if (c.zone === "P1" || c.zone === "P2" || c.zone === "P3")
                pts.push([(c.x + .5) * 5 - S / 2, (c.y + .5) * 5 - S / 2]);
        });
        if (!pts.length) { resetNorthUp(); return; }
        let minX = 1e9, maxX = -1e9, minZ = 1e9, maxZ = -1e9;
        for (const [x, z] of pts) {
            minX = Math.min(minX, x); maxX = Math.max(maxX, x);
            minZ = Math.min(minZ, z); maxZ = Math.max(maxZ, z);
        }
        const ctr = new THREE.Vector3((minX + maxX) / 2, 0, (minZ + maxZ) / 2);
        ctr.y = worldHeightAt(ctr.x, ctr.z) + 8;
        const spanR = Math.max(maxX - minX, maxZ - minZ, 80) * 1.35 + 90;
        flyTo(sph(spanR, 50 * Math.PI / 180, 32 * Math.PI / 180).add(ctr), ctr, 900);
        preset = "orbit";
    }

    function resetNorthUp() {
        // Top-down over the current pivot, target riding the local surface.
        const tgt = controls.target.clone();
        tgt.y = worldHeightAt(tgt.x, tgt.z) + 4;
        flyTo(tgt.clone().add(new THREE.Vector3(0.001, 520, 0.001)), tgt, 900);
        preset = "orbit";
    }

    function cyclePreset() {
        const order = ["orbit", "top", "chase"];
        preset = order[(order.indexOf(preset) + 1) % order.length];
        if (preset === "top") resetNorthUp();
        if (preset === "orbit") {
            const tgt = new THREE.Vector3(
                controls.target.x, worldHeightAt(controls.target.x, controls.target.z) + 6,
                controls.target.z);
            flyTo(tgt.clone().add(sph(470, 52 * Math.PI / 180, 38 * Math.PI / 180)), tgt);
        }
        return preset;
    }

    /* ------------------------------ Debug HUD ------------------------------
       ?debug=3d pins a live scene readout over the map (draw calls,
       triangles, avalanche state, UAV height above terrain). Exists so a
       screenshot from a real device doubles as a diagnostics report —
       headless GL cannot render this scene (see TERMUX_RUNBOOK.md). */
    let hudEl = null, hudLast = 0;
    function initHud() {
        if (!/[?&]debug=3d/.test(location.search)) return;
        hudEl = document.createElement("div");
        hudEl.id = "gl3dHud";
        hudEl.style.cssText =
            "position:absolute;top:10px;left:10px;z-index:30;pointer-events:none;" +
            "font:10px/1.5 var(--mono),monospace;color:#0f172a;background:rgba(255,255,255,.82);" +
            "padding:8px 10px;border-radius:8px;white-space:pre;box-shadow:0 2px 8px rgba(15,23,42,.25)";
        cv.parentElement.appendChild(hudEl);
    }
    function updateHud(now) {
        if (!hudEl || now - hudLast < 400) return;
        hudLast = now;
        const st = AVLF.state;
        const uavs = st.uavs.map(u => {
            const m = uavMarks[u.asset_id]; if (!m) return null;
            const p = G.metersOfLatLon(u.current_lat, u.current_lon);
            const cx = clampI(Math.floor((p.eastM - S / 2 + S / 2) / 5));
            const cy = clampI(Math.floor((p.northM - S / 2 + S / 2) / 5));
            const agl = Math.round(u.current_alt_m - DEM.elevation(cx, cy));
            return `${u.asset_id.replace("UAV_", "")} AGL ${agl}m`;
        }).filter(Boolean).join(" · ");
        hudEl.textContent =
            `draws ${renderer.info.render.calls} · tris ${renderer.info.render.triangles}\n` +
            `markers ${markers.size} · aval ${aval ? aval.state : "—"}\n${uavs}`;
    }

    /* --------------------------- Avalanche sequence ---------------------------
       Scripted snow release down the carved gully (the same line the DEM
       carves): idle → flow (~22 s) → settled deposit. Auto-triggers once per
       mission at incident+75 s; triggerAvalanche() forces it for demos.
       prefers-reduced-motion jumps straight to the settled deposit. */
    const AVALANCHE_T_S = 75, FLOW_S = 22;
    let aval = null;
    function buildAvalanche() {
        // Stations along the DEM track, world-space, terrain-conforming.
        const N = 64, stations = [];
        const ax = 170, ay = 430, bx = 330, by = 100;
        for (let i = 0; i <= N; i++) {
            const t = i / N;
            const xm = ax + (bx - ax) * t, ym = ay + (by - ay) * t;
            const cx = clampI(Math.round(xm / 5 - .5)), cy = clampI(Math.round(ym / 5 - .5));
            const wx = (cx + .5) * 5 - S / 2, wz = (cy + .5) * 5 - S / 2;
            const h = (DEM.elevation(cx, cy) - 3800) * VEX;
            stations.push({ wx, wz, h, t });
        }
        // Crown slab: 5 points across per station with a cos crown — real
        // volume (thick spine, tapered rims), not a flat sheet. Deposit
        // profile thickens toward the runout; deterministic roughness.
        const pos = [], ts = [], idx = [];
        const HALF_W = 24, CROWN = 5;
        for (let i = 0; i <= N; i++) {
            const s = stations[i], s2 = stations[Math.min(i + 1, N)], s0 = stations[Math.max(i - 1, 0)];
            let dx = s2.wx - s0.wx, dz = s2.wz - s0.wz;
            const len = Math.hypot(dx, dz) || 1;
            const nx = -dz / len, nz = dx / len;
            const w = HALF_W + Math.sin(s.t * 19) * 3.0;
            const rough = Math.sin(i * 12.9898) * .9;         // deterministic
            const lift = 2.2 + 6.5 * smooth01((s.t - .55) / .45) + rough;
            for (let c = 0; c < CROWN; c++) {
                const u = c / (CROWN - 1) * 2 - 1;            // -1..1 across
                const crown = Math.pow(Math.cos(u * Math.PI / 2), .65);
                pos.push(
                    s.wx + nx * u * w,
                    s.h + .4 + lift * crown,
                    s.wz + nz * u * w);
                ts.push(s.t);
            }
            if (i < N) {
                const a = i * CROWN, b = a + CROWN;
                for (let c = 0; c < CROWN - 1; c++) {
                    idx.push(a + c, b + c, a + c + 1,
                             b + c, b + c + 1, a + c + 1);
                }
            }
        }
        const geo = new THREE.BufferGeometry();
        geo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(pos), 3));
        geo.setAttribute("aT", new THREE.BufferAttribute(new Float32Array(ts), 1));
        geo.setIndex(idx);

        const uniforms = {
            uProgress: { value: 0 }, uTime: { value: 0 }, uSettle: { value: 0 },
            uFlowColor: { value: new THREE.Color(0xffffff) },
            uDepositColor: { value: new THREE.Color(0xdfe8f2) },
            uFogColor: { value: new THREE.Color(0xd7e2ef) },
            uFogNear: { value: 650 }, uFogFar: { value: 1500 }
        };
        const mat = new THREE.ShaderMaterial({
            uniforms, transparent: true, side: THREE.DoubleSide,
            vertexShader: [
                "attribute float aT;",
                "uniform float uProgress;",
                "varying float vT; varying vec3 vWP;",
                "void main() {",
                "    vT = aT;",
                "    vec3 p = position;",
                // Traveling bulge: the flow front piles up as it moves.
                "    float front = smoothstep(0.18, 0.0, abs(aT - uProgress));",
                "    p.y += front * 3.2;",
                "    vec4 wp = modelMatrix * vec4(p, 1.0);",
                "    vWP = wp.xyz;",
                "    gl_Position = projectionMatrix * viewMatrix * wp;",
                "}"
            ].join("\n"),
            fragmentShader: [
                "precision highp float;",
                "uniform float uProgress, uTime, uSettle, uFogNear, uFogFar;",
                "uniform vec3 uFlowColor, uDepositColor, uFogColor;",
                "varying float vT; varying vec3 vWP;",
                "void main() {",
                "    float edge = 1.0 - smoothstep(uProgress - 0.035, uProgress, vT);",
                "    if (edge <= 0.001) discard;",
                "    float streak = 0.5 + 0.5 * sin(vT * 140.0 - uTime * 7.0 + sin(vT * 43.0) * 2.0);",
                "    vec3 col = mix(uDepositColor, uFlowColor, 1.0 - uSettle);",
                "    col += (1.0 - uSettle) * streak * 0.10;",
                "    float front = smoothstep(0.05, 0.0, abs(vT - uProgress)) * (1.0 - uSettle);",
                "    col = mix(col, vec3(1.0), front * 0.65);",
                "    float dist = length(cameraPosition - vWP);",
                "    col = mix(col, uFogColor, smoothstep(uFogNear, uFogFar, dist) * 0.85);",
                "    gl_FragColor = vec4(col, edge * 0.96);",
                "}"
            ].join("\n")
        });
        const mesh = new THREE.Mesh(geo, mat);
        mesh.visible = false;
        worldGroup.add(mesh);

        // Powder spray riding the flow front.
        const PN = 220;
        const pp = new Float32Array(PN * 3), pt = new Float32Array(PN);
        for (let i = 0; i < PN; i++) pt[i] = Math.random();
        const pgeo = new THREE.BufferGeometry();
        pgeo.setAttribute("position", new THREE.BufferAttribute(pp, 3));
        const pmat = new THREE.PointsMaterial({
            color: 0xffffff, size: 2.4, transparent: true, opacity: 0, depthWrite: false
        });
        const points = new THREE.Points(pgeo, pmat);
        points.visible = false;
        worldGroup.add(points);

        aval = {
            state: "idle", t0: 0, settleAt: 0, stations, N,
            mesh, uni: uniforms, points, pt, pmat, ppos: pp
        };
    }
    function smooth01(x) {
        x = Math.max(0, Math.min(1, x));
        return x * x * (3 - 2 * x);
    }
    function avalPathPoint(t, out) {
        const s = aval.stations;
        const f = t * aval.N, i = Math.min(aval.N - 1, Math.floor(f)), k = f - i;
        const a = s[i], b = s[i + 1];
        out.x = a.wx + (b.wx - a.wx) * k;
        out.z = a.wz + (b.wz - a.wz) * k;
        out.h = a.h + (b.h - a.h) * k;
        return out;
    }
    function triggerAvalanche() {
        if (!aval || aval.state !== "idle") return;
        if (REDUCED()) {
            aval.uni.uProgress.value = 1;
            aval.uni.uSettle.value = 1;
            aval.mesh.visible = true;
            aval.state = "settled";
            return;
        }
        aval.state = "flowing";
        aval.t0 = performance.now();
        aval.mesh.visible = true;
        aval.points.visible = true;
        // One-time vantage move so the release is actually on screen.
        const mid = avalPathPoint(.45, { x: 0, z: 0, h: 0 });
        const midV = new THREE.Vector3(mid.x, mid.h, mid.z);
        flyTo(sph(330, 50 * Math.PI / 180, 28 * Math.PI / 180).add(midV), midV, 1100);
    }
    function resetAvalanche() {
        if (!aval) return;
        aval.state = "idle";
        aval.mesh.visible = false;
        aval.points.visible = false;
        aval.pmat.opacity = 0;
        aval.uni.uProgress.value = 0;
        aval.uni.uSettle.value = 0;
    }
    function updateAvalanche(now) {
        if (!aval) return;
        const st = AVLF.state;
        // Mission replay/restart: clock moved back before the trigger → reset.
        // The trigger check MUST run while idle — it is the only auto-start.
        if (st.incidentEpochS != null) {
            const elapsed = (Date.now() - st.serverOffsetMs) / 1000 - st.incidentEpochS;
            if (elapsed < AVALANCHE_T_S - 2) { resetAvalanche(); return; }
            if (aval.state === "idle" && elapsed >= AVALANCHE_T_S) triggerAvalanche();
        }
        if (aval.state === "idle") return;
        if (aval.state === "flowing") {
            const k = Math.min(1, (now - aval.t0) / (FLOW_S * 1000));
            aval.uni.uProgress.value = 1 - Math.pow(1 - k, 2.2);
            aval.uni.uTime.value = now / 1000;
            // Powder spray concentrated near the front.
            const front = aval.uni.uProgress.value;
            for (let i = 0; i < aval.pt.length; i++) {
                const seed = aval.pt[i];
                let t = front - .28 * seed;
                if (t < 0) t = 0;
                const p = avalPathPoint(t, { x: 0, z: 0, h: 0 });
                const wob = Math.sin(now / 260 + seed * 40) * 3;
                aval.ppos[i * 3] = p.x + wob;
                aval.ppos[i * 3 + 1] = p.h + 3 + Math.abs(Math.cos(now / 300 + seed * 25)) * 5;
                aval.ppos[i * 3 + 2] = p.z + wob;
            }
            aval.points.geometry.attributes.position.needsUpdate = true;
            aval.pmat.opacity = .8 * (1 - k * .3);
            if (k >= 1) { aval.state = "settling"; aval.settleAt = now; }
        } else if (aval.state === "settling") {
            const k = Math.min(1, (now - aval.settleAt) / 4000);
            aval.uni.uSettle.value = k;
            aval.pmat.opacity = .5 * (1 - k);
            if (k >= 1) { aval.state = "settled"; aval.points.visible = false; }
        }
    }

    /* ------------------------------ Frame ------------------------------ */
    function setActive(on) { active = on; if (on) resize(); }
    function setDirty() { /* fusion canvas repaints itself; texture refresh is timed */ }

    function resize() {
        if (!renderer || !cv.parentElement) return;
        const r = cv.parentElement.getBoundingClientRect();
        renderer.setSize(Math.max(1, r.width), Math.max(1, r.height), false);
        camera.aspect = Math.max(.2, r.width / Math.max(1, r.height));
        camera.updateProjectionMatrix();
    }

    const REDUCED = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

    /* ---- Terrain collision guard ----
       With the target riding the surface this is a safety net, not a fight:
       clamp the target to a column above the local DEM, and keep the camera
       above the highest terrain under it or between it and the target. */
    function worldHeightAt(wx, wz) {
        const cx = clampI(Math.floor((wx + S / 2) / 5));
        const cy = clampI(Math.floor((wz + S / 2) / 5));
        return (DEM.elevation(cx, cy) - 3800) * VEX;
    }
    const CLEARANCE = 7;
    function enforceAboveTerrain() {
        const t = controls.target;
        // Pan bounds: inside the slab neighbourhood, at/above local surface.
        t.x = Math.max(-S / 2 - 40, Math.min(S / 2 + 40, t.x));
        t.z = Math.max(-S / 2 - 40, Math.min(S / 2 + 40, t.z));
        const surfaceT = worldHeightAt(t.x, t.z);
        if (t.y < surfaceT + 1.5) t.y = surfaceT + 1.5;
        if (t.y > 520) t.y = 520;

        const midX = (camera.position.x + t.x) / 2;
        const midZ = (camera.position.z + t.z) / 2;
        const floorY = Math.max(
            worldHeightAt(camera.position.x, camera.position.z),
            worldHeightAt(midX, midZ),
            -38                                     // never below the skirt base
        ) + CLEARANCE;
        if (camera.position.y < floorY) camera.position.y = floorY;
    }

    function render(now) {
        if (!active || !renderer || document.hidden) return;
        controls.update();
        if (flyAnim) flyAnim();
        enforceAboveTerrain();

        // Sun direction into view space for the shader (view-space normals).
        const n = new THREE.Vector3(-0.55, 0.72, 0.42).normalize()
            .transformDirection(camera.matrixWorldInverse);
        uniforms.uSunDir.value.copy(n);

        const state = AVLF.state;
        state.uavs.forEach(u => {
            const m = uavMarks[u.asset_id]; if (!m) return;
            const p = G.metersOfLatLon(u.current_lat, u.current_lon);
            const wx = p.eastM - S / 2, wz = p.northM - S / 2;
            const cx = clampI(Math.floor((wx + S / 2) / 5)), cy = clampI(Math.floor((wz + S / 2) / 5));
            const gy = (DEM.elevation(cx, cy) - 3800) * VEX;
            // Backend flies terrain-following AGL; this clamp is the safety
            // net — a UAV must never render beneath the slope it crosses.
            const wy = Math.max((u.current_alt_m - 3800) * VEX, gy + 8);
            m.grp.position.set(wx, wy, wz);
            m.halo.scale.setScalar(1 + Math.sin(now / 320 + m.phase) * .13);
            // Fly the model: yaw to heading, roll into heading changes,
            // rotors blur, strobe blinks, gentle hover bob.
            const hdg = (u.heading_deg || 0) * Math.PI / 180;
            if (m.lastHeading == null) m.lastHeading = hdg;
            let dH = hdg - m.lastHeading;
            if (dH > Math.PI) dH -= 2 * Math.PI;
            if (dH < -Math.PI) dH += 2 * Math.PI;
            m.lastHeading = hdg;
            m.bank = (m.bank || 0) * .88 + Math.max(-.45, Math.min(.45, dH * 2.2)) * .12;
            m.grp.rotation.order = "YXZ";
            m.grp.rotation.y = hdg;
            m.grp.rotation.z = m.bank;
            m.grp.position.y += Math.sin(now / 480 + m.phase) * .7;
            m.rotors.forEach((r, i) => { r.rotation.y = now * .05 + i * 1.7; });
            m.strobe.visible = (now % 900) < 110;
            // Shaft reaches for the ground but never becomes a full-height
            // spotlight sail when the UAV reports high ASL altitude.
            m.beam.scale.y = Math.min(2.2, Math.max(.15, (wy - gy) / 34));
            // Trail: short recent-path ribbon only. Pushing every frame let
            // the buffer span altitude changes as tall vertical streaks.
            const last = m.pts[m.pts.length - 1];
            if (!last || last.distanceToSquared(m.grp.position) > .25) {
                m.pts.push(m.grp.position.clone());
                if (m.pts.length > 24) m.pts.shift();
                m.trail.geometry.setFromPoints(m.pts);
            }
        });

        markers.forEach(m => {
            if (!m.pulse) return;              // dot LOD has no pulse ring
            const k = REDUCED() ? .5 : .5 + .5 * Math.sin(now / 420);
            m.pulse.scale.setScalar(.85 + k * 1.9);
            m.pulse.material.opacity =
                m.pulse.material.userData.baseOpacity * (.85 - k * .55)
                * (m.dimmed ? .6 : 1);
            m.halo.scale.setScalar(1 + Math.sin(now / 500) * .1);
        });

        if (reticle3d && reticle3d.grp.visible && !REDUCED()) {
            reticle3d.grp.rotation.y = -(now / 1500) % (Math.PI * 2);
        }
        updateAvalanche(now);
        updateHud(now);
        if (landscapeMats.beacon)
            landscapeMats.beacon.visible = (now % 1400) < 220;
        syncGizmo();

        if (preset === "chase" && state.uavs.length && uavMarks.UAV_ALPHA) {
            const p = uavMarks.UAV_ALPHA.grp.position;
            camera.position.lerp(new THREE.Vector3(p.x - 38, p.y + 24, p.z + 44), .04);
            controls.target.lerp(p, .09);
        }

        // Marker diff runs only on data/selection change (see lastMarkerRev).
        const rev = AVLF.Fusion.layerState.version;
        if (rev !== lastMarkerRev || state.selectedKey !== lastSelSync) {
            lastMarkerRev = rev;
            lastSelSync = state.selectedKey;
            syncMarkers();
        }

        renderer.render(scene, camera);
    }

    function pick(clientX, clientY) {
        if (!active || !terrain) return null;
        const rect = cv.getBoundingClientRect();
        const ndc = new THREE.Vector2(
            ((clientX - rect.left) / rect.width) * 2 - 1,
            -((clientY - rect.top) / rect.height) * 2 + 1);
        const ray = new THREE.Raycaster();
        ray.setFromCamera(ndc, camera);
        const hit = ray.intersectObject(terrain)[0];
        if (!hit) return null;
        const cx = Math.floor((hit.point.x + S / 2) / 5);
        const cy = Math.floor((hit.point.z + S / 2) / 5);
        if (cx < 0 || cx > 99 || cy < 0 || cy > 99) return null;
        return { cx, cy };
    }

    /* ------------------------------ Public API ------------------------------ */
    AVLF.Relief3D = {
        init, render, pick, setActive,
        setDirty,
        flagFusionDirty,
        focusCell,
        recenterExtents,
        resetNorthUp,
        cyclePreset,
        applyTheme,
        triggerAvalanche,
        setContours(on) { uniforms.uContours.value = on ? 1 : 0; },
        setGrid(on) { uniforms.uGrid.value = on ? 1 : 0; },
        setSlopeOverlay(on) { uniforms.uSlopeOverlay.value = on ? 1 : 0; },
        setVectors(on) {
            Object.values(uavMarks).forEach(m => {
                m.grp.visible = !!on; m.trail.visible = !!on;
            });
        },
        setFusionOpacity(v) { uniforms.uFusionOpacity.value = v; }
    };
})(window.AVLF);
