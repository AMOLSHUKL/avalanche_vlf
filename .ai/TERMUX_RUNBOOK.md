# Termux Environment Runbook

**Device:** OnePlus Pad 2 (12 GB / 256 GB) · **OS:** Android, Termux native · **Last verified:** 2026-08-24

Runbook for the AVALANCHE-VLF development environment on this device, covering the bionic/Linux split, agent tooling, captures, and recovery. Written for a fresh session to understand the machine before touching it.

## Current architecture (validated 2026-08-24)

```
Android kernel (bionic)
└── Termux host
    ├── FastAPI backend          — Termux-native (bionic-linked numpy/pydantic-core)
    ├── git / tmux / nvim+clangd / node / gh / ripgrep
    └── Ubuntu 26.04 proot-distro
        ├── opencode 1.18.21     — official upstream build, /usr/local/bin
        ├── agy 1.1.19           — official Antigravity CLI, ~/.local/bin
        └── playwright chromium  — headless UI captures
```

Agent tooling lives inside the Ubuntu session; bionic-native workloads stay in Termux. There is no compatibility layer: the former 386 MB Termux glibc stack, the Hope2333 opencode build, and its 175 MB bun shim cache were removed on 2026-08-24 after the official upstream build was verified in Ubuntu (see "Why the glibc layer existed" below).

## Why the split exists

PyPI `manylinux` wheels do not load under Termux's Android linker, and compiling C/Rust extensions on-device requires toolchains that bloat Termux (this caused an 818 MB `~/.cargo` and the original glibc experiment). The contract:

1. **Termux host** — the interpreter, Android-built C extensions (`python-numpy`), and tools with native Termux builds. No compile-heavy work.
2. **Project venv** (`./venv/`, `include-system-site-packages = false`) — pip-managed app deps bounded by `requirements.txt`. numpy reaches the venv through a `.pth` bridge (see recovery).
3. **Ubuntu proot** — everything wanting a conventional Linux userspace: agent CLIs, chromium, any future native toolchain. When the device is rooted, this rootfs moves to chroot unchanged, eliminating proot's ~2× syscall tax.

### What is global and why

| Item | Consumer | Notes |
|---|---|---|
| python 3.14 + python-numpy 2.4.4 | backend, venv bridge | numpy only via `pkg`; pip sdist cannot build here |
| nodejs 26, git, ripgrep, tmux | project + shell | |
| clang/llvm 21 | nvim clangd LSP | |
| neovim, gh, ffmpeg | editor, GitHub, media | |
| proot-distro + Ubuntu 26.04 | agent CLIs + captures | future chroot rootfs |
| ~~glibc layer, rust, cmake, qemu~~ | ~~opencode~~ | **removed** 2026-08-24, ~1.5 GB reclaimed total |

## Agent environment (opencode / agy)

Enter the persistent session from Termux:

```bash
ubuntu-dev    # function in ~/.bashrc; equivalent to:
# proot-distro login ubuntu \
#   --bind /data/data/com.termux/files/home:/termux-home \
#   --bind ~/development/projects/SIH_2026/avalanche_vlf:/work \
#   --work-dir /work
```

Inside, `/root/.bashrc` (guarded by the bind's existence) exports `XDG_CONFIG_HOME=/termux-home/.config` and `XDG_DATA_HOME=/termux-home/.local/share`, so opencode reads the same auth, sessions, skills, and config as anything Termux-side — zero-migration sharing. `agy` is on PATH via `~/.local/bin`.

- Updates: `opencode upgrade` inside Ubuntu (upstream-first, no fork dependency).
- OAuth flows (agy, first-run opencode providers) use the headless paste-the-URL pattern.
- proot tax: ~2× on syscall-heavy operations and ~285 ms per `proot-distro login` entry. Gone when the rootfs moves to chroot after rooting.

## Known-good state (2026-08-24, post-relocation)

```
Termux pkgs : python 3.14.6, python-numpy 2.4.4 (global site), nodejs 26.4.0,
              git 2.55.0, proot 5.1.107, proot-distro 5.8.0 (+ Ubuntu 26.04),
              clang 21.1.8 (nvim LSP), neovim, gh, ffmpeg, tmux
              — NO glibc layer, NO rust/cmake/qemu (removed)
Project venv: fastapi 0.141.1, pydantic 2.13.4 (pydantic_core 2.46.4),
              uvicorn 0.52.4, httpx 0.28.1, websockets 17.0.1, pytest 8.4.2,
              pytest-asyncio 0.26.0, PyYAML 6.0.3, numpy 2.4.4 via .pth bridge
Ubuntu proot: opencode 1.18.21 (/usr/local/bin), agy 1.1.19 (~/.local/bin),
              playwright + chromium headless (captures)
Removed     : ~/.cargo registry (~818 MB), pip/npm caches, rust/cmake/qemu,
              49-52 pkg glibc layer (~386 MB), Hope2333 opencode + shim cache
              (~175 MB) — 2026-08-24; stale ~/tmp Bun bytecode + bare
              development/venv (~86 MB) and the retired Termux-side "ag"
              Gemini helper + its venv (~76 MB) — 2026-08-24
Dependency upgrade paths: pip for pure-python/wheel packages inside the venv
bounds; `pkg upgrade python-numpy` for numpy; sdist wheels needing rust/cmake
will FAIL by design — move that consumer to Ubuntu or wait for upstream wheels.
```

Historical note: the venv cannot pip-install numpy (the 2.5.x sdist fails against Bionic libc: `cpow`/`cexpl` undeclared in `npy_math_complex.c.src`). The working fix is a `.pth` bridge exposing the Android-built global numpy to the venv:

```bash
# venv/lib/python3.14/site-packages/_termux_system_numpy.pth
/data/data/com.termux/files/usr/lib/python3.14/site-packages
```

Only `pip` overlaps between the two site-packages trees; nothing shadows. If the Termux python minor version changes, recreate the file under the new path and re-verify with `comm -12` on both listings.

## Recovery procedures

### Broken or missing project venv

```bash
cd ~/development/projects/SIH_2026/avalanche_vlf
rm -rf venv && python -m venv venv
venv/bin/pip install -r requirements.txt
printf '/data/data/com.termux/files/usr/lib/python3.14/site-packages\n' \
  > venv/lib/python3.14/site-packages/_termux_system_numpy.pth
venv/bin/python -m pytest tests/ -q     # expect 367 passed
```

### Broken opencode / agy in Ubuntu

The distro is disposable; the config/auth live on the Termux side (`~/.config/opencode`, `~/.local/share/opencode`) and survive any distro rebuild.

```bash
proot-distro remove ubuntu && proot-distro install ubuntu
proot-distro login ubuntu -- bash -c "
  apt update && apt install -y curl nodejs npm fonts-dejavu-core
  npm install -g playwright && npx playwright install chromium
  curl -fsSL https://antigravity.google/cli/install.sh | bash
"
# opencode: download the opencode-linux-arm64.tar.gz asset from the latest
# github.com/sst/opencode release, extract, place binary at /usr/local/bin/opencode
# restore the shared-config lines from this runbook into /root/.bashrc
```

The Hope2333 Termux build is gone by design; if it is ever needed again, its bashrc wrapper is preserved at `~/.config/opencode/termux-launcher-rollback.sh`, but it would require reinstalling the glibc layer (`glibc-repo` + `glibc-runner`) — the official Ubuntu build is the supported path.

### Backend (FastAPI) operations

```bash
tmux new-session -d -s avlf \
  "venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000"
curl -s http://127.0.0.1:8000/api/healthz
tmux kill-session -t avlf
```

Networking is shared with proot: chromium and agent tools inside Ubuntu reach the backend at `127.0.0.1:8000` directly.

## UI capture workflow

```bash
# 1. backend (Termux, tmux)
tmux new-session -d -s avlf \
  "venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000"

# 2. captures (Ubuntu, repo bound at /work)
proot-distro login ubuntu --bind ~/development/projects/SIH_2026/avalanche_vlf:/work -- \
  env NODE_PATH=/usr/local/lib/node_modules node /work/scripts/capture_ui.js
# tablet pass: append --viewport=1024x768
```

Output lands in `.ui_review/` (untracked; delete when the review round is done). Captures every review state: TOPO/RELIEF, both themes, layers popover, DSP drawer, GPR fault injection. Restart the tmux session first for a fresh-mission shot (golden window ~15:00, survival ~92%).

proot notes for captures: Ubuntu 26.04's `chromium-browser` apt package is a snap stub — use Playwright's bundled chromium. SwiftShader loses WebGL2 contexts under proot on this device, so the three.js RELIEF 3D view cannot be pixel-rendered here (2D captures fine); the shader carries a derivatives fallback for real WebGL1-only devices. Global npm modules live in `/usr/local/lib/node_modules`.

## Termux/Android issues hit during setup (2026-08-24)

Android — not the project — caused every one of these. Recorded so the next session recognizes the symptoms instead of rediscovering them.

| Symptom | Root cause | Fix / mitigation |
|---|---|---|
| Background servers died minutes after launch (`nohup`/`setsid` uvicorn gone) | **Android phantom process kill** | Use tmux for anything long-running. Device-side mitigations already applied: phantom-process restriction disabled + Termux set to unrestricted background usage in Developer Options. Re-check both after OS updates. |
| `pip install numpy` fails (`cpow`/`cexpl` undeclared) | manylinux wheels incompatible with the Android linker; sdist hits Bionic libc gaps | Never pip-build C-extension sdists on-device. numpy comes from `pkg`; venv reads it via the `.pth` bridge. |
| `chromium-browser` in Ubuntu: "requires the chromium snap" | Ubuntu 26.04 ships a snap stub; snapd cannot run under proot | Playwright's bundled chromium (already provisioned). |
| RELIEF 3D blank in headless captures; `CONTEXT_LOST_WEBGL` repeatedly | **SwiftShader is a silent no-op under proot** (verified 2026-08-25: contexts create, shaders compile/link, `getError()`=0, but framebuffer reads and page screenshots are always empty — headless `--enable-unsafe-swiftshader` AND headed Xvfb+Mesa both). Mesa llvmpipe is unreachable through chromium's ANGLE here. | Env limit, not an app bug. Pixel-audit 3D on real hardware; open the dashboard with `?debug=3d` for an on-screen scene report (draw calls, triangles, avalanche state, UAV AGL) so screenshots double as diagnostics. Structural 3D verification runs via `scripts/smoke_frontend.js` + the DEM parity check (frontend `dem.js` vs backend `TerrainEngine`, must be exact). |
| opencode (Hope2333 build) died with `open ld.so failed` when the glibc layer was removed | That build was a Bun single-file binary with a Termux shim redirecting libc into the glibc layer | Resolved by relocating opencode to the official Ubuntu build (2026-08-24). Lesson: `readelf -l <bin> | grep -i interp` before assuming what a binary needs. |
| FastAPI cannot be started from inside the Ubuntu session (`ImportError: dlopen failed ... not accessible for the namespace`) | Under proot, CPython resolves the venv prefix to the guest path `/work`, and the Android linker namespace rejects dlopen of `/work`-prefixed paths (permitted paths only cover real `/data` locations) | Start the backend from a Termux prompt only (tmux procedure above). The bionic venv is unreachable from Ubuntu — by architecture, not misconfiguration. |
| `pip list --outdated` flags numpy/pydantic_core as sdist upgrades | Same wheel-boundary cause | numpy upgrades via `pkg upgrade python-numpy` only; leave pydantic_core to upstream wheels. |
