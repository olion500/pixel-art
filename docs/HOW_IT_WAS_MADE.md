# How the final ninja punch and jump were made

Final output: `out/aai/ninja_cross_v4.*`, `out/aai/ninja_jump_v4.*` (`.aseprite`, sprite sheet + JSON, GIF).
Comparison: `out/compare_aseprite.gif` (Sprite Fusion vs ours, real timing).

## In one line
**Design the motion first → have an image AI draw a storyboard following the design → assemble it frame by frame in Aseprite according to rules (aseprite-ai-artist) → an independent critic scores it → keep only the fixes that win a blind comparison.**

```
 ① Analysis           ② Design              ③ Storyboard            ④ Cleanup             ⑤ Aseprite assembly         ⑥ Review loop
 Measure Sprite  →  Frame-by-frame    →  Gemini draws 1 cell  →  Grid restore,    →  Layers, cel copy/move,  →  Critic cold read
 Fusion frames      shot list            per frame;             shared palette,      per-frame timing, FX,      → fix blockers
 + rulebook         (pose, ms, scarf,    redraw only the        head lock            validate, export           → blind A/B
                    FX)                  wrong cells                                                            (3 rounds)
```

---

## ① Analysis: why Sprite Fusion looks good (measured)
Each Sprite Fusion frame was measured by color: visor position, shoe position, silhouette size, scarf tip (`docs/motion_plan.md` §1).
- **Punch**: the feet stay fixed for all 8 frames, the head height stays fixed, and the head moves forward only 2px on impact. The motion comes from the arm and the torso twist.
- **Jump**: the head moves only 4px up/down. The jump is expressed through **pose**, not position (the engine handles the height).
- **Scarf**: always lags one beat behind the body.

## ② Design: aseprite-ai-artist rulebook + frame-by-frame shot list
`docs/motion_plan_v2.md`, `samples/ninja/plans/{cross_v2,jump_v2}.json`
The design was written from the timing tables and rules in aseprite-ai-artist's `rules/` (40 timing, 43 jump, 44 attacks, 45 secondary motion).
- **Cross (rear-hand), 9 frames**: stance 100 → wind-up 50·50 → smear 50·50 → **hit 100** → follow 100 → recover 80 → overshoot (1px back) 70 ms.
  Power chain (hips → torso → arm → fist, one frame apart each); at max reach the arm is 1–2px longer than real.
- **Jump (standing broad jump), 10 frames**: stand → dip → crouch (head −9) → push → take-off (back toe on the floor) → apex (+10, tuck)
  → descent (arms up, legs reaching) → landing crouch → rise → stand. **The squash goes on the landing**.
- Each frame specifies the pose, duration, scarf direction, and FX.

## ③ Storyboard: Gemini draws one cell per frame
`tools/plan_animate.py`, `tools/fix_cells.py`
- Put the source sprite (8× upscale) in the first cell of a grid and send the design table to Gemini 3 Pro Image as **per-cell instructions** ("Cell 3: …").
  Earlier, a vague prompt like "make it jump" let the model invent its own motion; per-cell instructions fixed that.
- **Fix only the cells that come out wrong**: a whole-sheet edit makes the model redraw the good frames too. So send just a
  "previous frame | empty | next frame" strip, draw only the middle, and paste it back (jump take-off frame, cross wind-up frame).

## ④ Cleanup: back to pixel art
`tools/gen_animate.py` (postprocess), `tools/head_lock.py`
- Remove the magenta background → remove the grid lines the model drew (full-width, boundary bands, cell edges) → drop the neighboring cell's scarf when it spills over.
- **Scale calibration**: models redraw the whole sheet at a different size, so the pixel size is computed as "the model's frame-1 height ÷ source height".
- Downsample each cell to native resolution by block majority vote → snap the whole animation to one shared 16-color palette.
- **Head lock**: in every frame where the head is upright, re-stamp the source head (helmet, visor) pixels. Removes the per-frame face flicker.

## ⑤ Aseprite assembly: running aseprite-ai-artist headless
`tools/aai_build.py` (generates the call list), `tools/aai_call.mjs` (MCP client)
- Layers: `legs` (one cel linked across all frames = **the feet never move by even 1px**) / `hips` / `upper` / `fx`.
- Each frame is drawn per layer as a text grid (`draw` kind `grid`).
- Rule-based frames are **cel copy + move, not redraws** (their animate skill principle):
  wind-up B = wind-up A's upper body +1px, overshoot = stance upper body −1px, strike frames push the upper body forward 1–2px.
- Jump: forward travel (+12px), apex height (+10), landing = the crouch drawing, landing feet pinned, tuck shins recolored navy.
- FX layer (drawn in code): smear along the arm path (rule 44.5: the arm's two brightest colors, chin → reach),
  fist white flash, spark 4 stages (small cross → burst → ring → fragments), speed lines on the arm outline, grey dust on the ground line.
- `frame set_duration` → `tag` → `look filmstrip` → `validate` → `export` (.aseprite, sheet+JSON, GIF).

## ⑥ Review loop: independent critic + blind A/B
The role is defined by aseprite-ai-artist's `agents/pixel-critic.md`.
- A separate agent that knows nothing about the process first writes a **cold read** (what does this look like?) and only then scores against the rulebook (blocking / worth fixing / note, with coordinates).
- After fixing blockers, the two versions are shown **without saying which is newer**; a fix is kept only if it wins (comparison mode).

| Round | Cross | Jump | Fixes |
|---|---|---|---|
| v1 | 5/10 | 3/10 | (first review) feet slide 5–7px, no smear / hop in place, dust looks like shoes, one airborne frame |
| v2 | blind A/B win | blind A/B win (4/4 blockers fixed) | front-foot alignment, chin→reach smear / travel, apex, landing = crouch, grey dust |
| v3 | 5/10 | 5/10 | leg cel linked, upper body forward, speed lines on the arm / dust behind the feet, landing arms forward |
| v4 | **6/10** | **5/10** | `hips` layer split (removes the thigh notch), hit = max reach / feet pinned after landing |

Remaining issues: cross — head pulls back 2px on the hit. Jump — only 2 airborne frames, heel slides 4px after landing (both come from the storyboard drawings).

---

## What didn't work (and why it was dropped)
| Approach | Result | Reason |
|---|---|---|
| Procedural animation / rig (no AI) | Idle OK, jump stiff | Limbs drawn as simple lines can't change pose |
| Gemini with a vague prompt | Good drawing, motion invented by the model | Needed design → per-cell instructions |
| Gemini whole-sheet edit | Good frames broke too | → per-cell regeneration |
| Veo video model | Jump natural, punch broken (turns to face camera, punches several times) | Camera angle and action count can't be controlled |
| claude-pxl (pixel art as code) | Clean but stiff | Precise placement, but no drawing quality |

## How to reproduce

### Setup (once)
```sh
# Aseprite without UI (no Skia) – X11 dev headers needed
apt-get install -y libx11-dev libxcursor-dev libxi-dev libxrandr-dev libgl1-mesa-dev libfontconfig1-dev
git clone --depth 1 --branch v1.3.15.5 --recurse-submodules --shallow-submodules https://github.com/aseprite/aseprite.git
#   if the proxy blocks GitHub zip downloads: git clone libjpeg-turbo 3.0.2 and put SOURCE_DIR in cmake/FindJpegTurbo.cmake
cmake -G Ninja -DCMAKE_BUILD_TYPE=Release -DLAF_BACKEND=none -DENABLE_UPDATER=OFF -DENABLE_NEWS=OFF -DENABLE_CCACHE=OFF ..
ninja aseprite                      # -> build/bin/aseprite

# aseprite-ai-artist (MCP server)
git clone https://github.com/with-pebbly/aseprite-ai-artist && cd aseprite-ai-artist && npm ci && npm run build

# Gemini key (never inside the repo)
echo 'GEMINI_API_KEY=...' > ~/.config/pixel-art/gemini.env && chmod 600 ~/.config/pixel-art/gemini.env
```

### Running (cross example; jump options in brackets)
```sh
# ③ storyboard
python3 tools/plan_animate.py samples/ninja/ninja-base.png samples/ninja/plans/cross_v2.json -o out/plan2/ninja_cross
#   regenerate only the wrong cells, then re-run cleanup
python3 tools/fix_cells.py out/plan2/ninja_cross_raw_v1.png --cols 5 --rows 2 \
        --fixes samples/ninja/plans/cross_v2_fixes.json -o out/plan2/ninja_cross_raw_fixed.png
python3 tools/plan_animate.py samples/ninja/ninja-base.png samples/ninja/plans/cross_v2.json \
        --reuse out/plan2/ninja_cross_raw_fixed.png -o out/plan2/ninja_cross

# ⑤ Aseprite call list  [jump: --head-err 40 --pad 16 --top-pad 8, no waist/hips/align]
python3 tools/aai_build.py cross samples/ninja/plans/cross_v2.json out/plan2/ninja_cross \
        --waist 36 --hips 3 --pad 12 --align-front-shoe --save out/aai/ninja_cross_v4 -o out/aai/cross_calls_v4.json

# run it (headless Aseprite + aseprite-ai-artist)
export AAI_HOME=/path/to/aseprite-ai-artist ASEPRITE_PATH=/path/to/aseprite/build/bin/aseprite
ln -sfn $AAI_HOME/node_modules tools/node_modules       # so the MCP SDK resolves
node tools/aai_call.mjs out/aai/cross_calls_v4.json --out out/aai/cross_look_v4
```

### ⑥ Review
Give a subagent `agents/pixel-critic.md` and `rules/` (07, 40, 43, 44, 45, 81, 92) and have it review the per-frame zoomed PNGs:
cold read → score → fix blockers → keep only fixes that win a blind A/B (filmstrips named a/b).

## File map
| Path | Role |
|---|---|
| `docs/motion_plan.md`, `docs/motion_plan_v2.md` | Sprite Fusion analysis, frame-by-frame design, per-round results |
| `samples/ninja/plans/*_v2*.json` | Shot lists (pose, ms, FX, cel moves) and per-cell fixes |
| `tools/plan_animate.py`, `tools/gen_animate.py` | Storyboard generation and cleanup |
| `tools/fix_cells.py` | Per-cell regeneration |
| `tools/head_lock.py`, `tools/fx_overlay.py` | Head lock, FX drawing |
| `tools/aai_build.py`, `tools/aai_call.mjs` | Aseprite call list generation and execution |
| `out/plan2/` | Storyboards (raw model output, prompts, cleaned sheets) |
| `out/aai/` | Aseprite outputs per round, critic review images, A/B strips |
