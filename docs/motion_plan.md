# Ninja motion design (punch, jump)

Plan first, then make. This document defines the composition of each motion **frame by frame** and sets the movement budget. The basis is the Sprite Fusion measurements (§1) and the research findings (doc §11).

## 1. What we learned from Sprite Fusion (measured)

| | punch (8f) | jump (12f) | idle (8f) |
|---|---|---|---|
| Foot position | **Fixed every frame** (shoe x 7.1 / 22.4, unchanged) | Feet lift only **4px** max | Fixed |
| Head (visor center) | y fixed at 7.0; x **+2px only on impact**, then 20.5 → 20.1 → 18.9 back | y 6.5–10.5 (**only a 4px range**), x drift ≤2px | Bobs 1px |
| Silhouette | Width 30 → 27 (wind-up) → **30 (extend)** → 25 → 28 | Height 24–27 throughout (vs 33 standing); width **21 → 26** only on the leap | Height 33 ↔ 32 |
| Scarf tip y | 8 → 9 → 8 → 7 (rises) → 8 → **10 (drops)** → 8 → 9 | 7 → **5 (rises in crouch)** → 6 → 8 → **10 (trails on leap)** → 9 → 7 → **4 (rises on fall)** → 5 → 7 → 9 → 10 | 7 → 9 → 8 |

Rules:
1. **Pose, not position**: actions read through pose changes. Translation is kept to a minimum (the engine moves the character).
2. **The silhouette must change clearly**: gather (shrink) → release (stretch) → gather back.
3. **The scarf lags the body** (rises when the body drops, falls when the body rises, trails back on fast motion).
4. Proportions, palette, and pixel size stay fixed.

## 2. punch: rear-hand cross (10 frames)
Translation budget: **feet fixed** (only the back heel lifts 1px), head x ≤ +2px, head y fixed.

| # | ms | Pose | Arms | Body/legs | Scarf | FX (separate layer) |
|---|---|---|---|---|---|---|
| 0 | 100 | Guard (= original) | Original | Original | Original | – |
| 1 | 120 | **Load** (hold) | Rear fist pulled to the chin | Hips 1px lower, rear shoulder 1px back | Tip 1px up | – |
| 2 | 60 | Twist start | Rear fist passes the chin, front hand moves to guard the chin | Torso turns slightly forward, head +1 | Starts to trail back | – |
| 3 | 40 | **Smear** | Rear arm 3/4 extended, stretched into a 2-tone streak from chin to fist | Head +1 | Trails back | Smear |
| 4 | 120 | **Impact** (hold) | Rear arm fully extended horizontally at visor height, **+2px longer than real** | Head +2, back heel up 1px, front knee slightly bent | Pulled straight back | Fist white flash + small spark + speed lines |
| 5 | 80 | Hitstop | Same pose | Same | Same | Big spark |
| 6 | 70 | Retract 1 | Fist back to half way | Head +1 | **Drops** | Spark ring breaks up |
| 7 | 70 | Retract 2 | Fist near the chin | Head 0 | Ripples | Fragments |
| 8 | 80 | **Overshoot** | Guard | Torso 1px behind guard position | Swings forward | – |
| 9 | 100 | Settle | Guard | Guard | Original | – |

## 3. jump: in-place long jump, crouch start/end (12 frames)
The starting pose is not the original standing pose but a **ready crouch** (same as Sprite Fusion: change the pose with Edit first, then animate).
Translation budget: head y range ≤ 5px, feet lift ≤ 5px, head x drift ≤ 2px.

| # | ms | Pose | Torso angle | Legs | Arms | Scarf | FX |
|---|---|---|---|---|---|---|---|
| 0 | 100 | Ready crouch | 20° forward | Knees bent ~90°, feet planted | Forward-down guard | Tip up | – |
| 1 | 120 | **Deeper crouch** (anticipation hold) | 35° | Knees deeper, 1px lower | Swung back behind the hips | **Flips up** | – |
| 2 | 60 | Push-off | 45° | Back leg extending (toe on ground), front knee driving up | Swinging forward | Starts to trail back | – |
| 3 | 60 | **Take-off stretch** | 45° diagonal | Back leg straight trailing down-back (toe pointed), front knee up, feet 2px off the ground | Reaching forward past the head | Trails back | Dust at the ground |
| 4 | 70 | Rising stretch | ~70° (nearly horizontal) | Both legs trailing back | Forward (superman) | Lowest, trailing back | Dust spreads |
| 5 | 120 | **Apex, tuck begins** (hang) | Back up to 45° | Knees pulling forward under the body | Forward | Trailing | – |
| 6 | 100 | Apex tuck | Nearly upright | Knees at the chest | Forward | Starts to rise | – |
| 7 | 70 | Descent | Upright | Legs extending down toward the ground | Up/out for balance | **Rises** | – |
| 8 | 60 | Touch-down | Upright | Feet touch, knees slightly bent | Forward | Highest | – |
| 9 | 110 | **Landing squash** | 25° | Deepest crouch (1px lower than frame 0, stance wider) | Forward-down | Still up | Landing dust |
| 10 | 90 | Recover | 20° | Ready crouch | Guard | Dropping | Dust breaks up |
| 11 | 100 | Ready crouch (= frame 0) | 20° | Same | Same | Back to original | – |

## 4. How to make it
1. **Character frames**: Gemini (the method that worked for idle).
   - Unlike before, give it **the table above as a per-cell shot list**, not a vague motion description.
   - Spell out the constraints: in place, translation budget, same size, feet fixed (punch).
   - jump goes in two steps: ① create the ready-crouch pose with Gemini edit → ② lock that image as frame 0 and generate the rest.
2. **Effects are a separate layer**: drawn in code (pxl), not left to the generative model. They're placed precisely at the fist position and ground line, and exported separately.
3. **Post-processing**: same as before (grid restore, scale calibration, shared palette, frame 0 lock).
4. **Review**: check each frame against the table (pose, translation budget, scarf direction) and re-generate any frame that's off.

## 5. Results and process (`out/plan/`, comparison: `out/compare_plan.gif`)

Tools: `tools/plan_animate.py` (shot list → Gemini → cleanup), `tools/fix_cells.py` (re-generate single cells),
`tools/fx_overlay.py` (FX layer), plans: `samples/ninja/plans/{punch,jump}.json`.

- **punch**: generated once, matches the design (feet fixed, rear arm horizontal at full extension, retract, overshoot).
  The FX are drawn in code on the frames tagged with `fx` in the plan: arm smear (3) → fist flash + spark + speed lines (4) → big spark (5) → ring (6) → fragments (7).
  The FX-only layer is saved separately as `ninja_punch_fx_layer.png`.
- **jump**: first generation (`ninja_jump_raw_v1.png`) matched the design for 7 of 13 cells (deep crouch, diagonal take-off, horizontal stretch, apex tuck, descent, landing squash).
  The rest drifted: ready crouch → standing, push-off/apex → running stride, touch-down/recover → standing.
  - **A whole-sheet edit failed**: the model also redrew good frames (the horizontal stretch turned into standing). Prompt kept in `ninja_jump_revise_prompt.txt`.
  - **Per-cell re-generation worked**: send only a [previous | empty | next] strip, take the middle, paste it back. The ready crouch (2, 13 = copy of 2), apex (7), touch-down (10), and recover (12) now match the design. Push-off (4) was too large, so it was re-generated with "same size as the neighboring panels" stated explicitly.
  - Final sheet: `ninja_jump_raw_fixed2.png`.
- Cleanup issues found and fixed: grid-line remnants on pasted cells (check cell edges and boundary bands), the next cell's scarf spilling into the crop (drop pieces touching the edge), the 4:1 aspect ratio not being supported.

Remaining issues: the push-off frame (jump f2) is still slightly larger than the others.
Each jump frame is drawn a little differently, so it doesn't look as uniform as Sprite Fusion.
