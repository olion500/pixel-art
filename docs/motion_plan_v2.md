# Ninja motion plan v2 (aseprite-ai-artist director format)

Written from the rules of [aseprite-ai-artist](https://github.com/with-pebbly/aseprite-ai-artist) — `rules/40-timing-and-spacing`,
`43-jump-fall-land`, `44-attacks-and-impacts`, `45-secondary-motion` — plus the Sprite Fusion measurements (motion_plan.md §1).
Sprite: 33 px tall side view, facing right. Rig layers: `arm-near`, `leg-near`, `head`, `scarf`, `torso`, `arm-far`, `leg-far`.

## What v1 got wrong (by the rules)
- Cross total was 840 ms → rule table (Slynyrd PB53 cross): **450 ms** (wind-up 50+50, smear 50, hit 100, follow 100, recover 50, overshoot 50).
- Moved the whole arm at once → **power chain**: hips → torso → arm → fist, each one frame later (rule 44.11).
- Smear was a separate cyan stripe → **2 frames at 32 px, first biggest then shrinking, in the arm's own two brightest colors, opaque** (44.5).
- Spark ~13 px → **9–11 px at 32 px** (44 size table).
- Squash on launch → **squash on landing; at launch the back toe stays on the ground** (43.4, 43.5).
- **Rising = limbs trailing, falling = arms up / legs reaching / head level** (43.9); the air phase needs at least two sub-motions (43.8).

---

```
CROSS (rear-hand) — 9 frames, tag "cross", forward. Total 500 ms (+ stance hold).

 1 stance        100ms  original guard. Feet pixels never move after this (ground pivot fixed).
 2 wind-up A      50ms  hips drop 1px, rear shoulder back 1px, rear fist cocks at the chin (opposite direction, 2px)
 3 wind-up B      50ms  torso rotates forward: front shoulder turns away, rear elbow lifts; head +1px forward, upright
 4 smear 1        50ms  rear arm swept from chin to 3/4 reach as ONE opaque streak in the arm's two lightest navy tones,
                        widest at the fist end; front hand rises to guard the chin
 5 smear 2        50ms  arm at full reach, a thin 1px streak behind it (shrinking)
 6 HIT           100ms  rear arm straight & horizontal at visor height, +2px longer than natural, fist past the target line;
                        head +2px, back heel up 1px, front knee 1px more bent. Spark 9–11px at the fist (separate layer).
 7 follow        100ms  same pose, arm 1px shorter; spark ring breaking
 8 recover        50ms  fist pulled back to the chest (different, lower arc than the strike)
 9 overshoot      50ms  guard pose copied from frame 1, torso shifted 1px BACK
(loop to 1)

Secondary: scarf tip lags the head by 1 frame: lifts on 2–3, pulled straight back on 5–7,
drops on 8, swings through on 9, settles on 1 (decay 3→2→1px).
FX layer (code): spark on 6 (contact, 9px) → 7 (burst, 11px) → 8 (ring) → 9 (fragments); fist white flash on 6 only.
Risks: at 33px the rear arm passes behind the torso — the smear must stay readable over the dark suit (use the light navy + teal).
```

```
JUMP (standing broad jump, timed strip) — 10 frames, tag "jump", forward. Total 1000 ms.
Head dy relative to standing (+ = up), from the rule 43 32px table; ground pivot fixed on ground frames.

 1 stand, arms up        0   120ms  weight up, arms raised slightly
 2 dip                  −3    80ms  knees bend, arms swing back
 3 crouch               −9   100ms  torso 45° forward, thighs near horizontal, arms fully back (anticipation)
 4 push                 −4    60ms  legs extending, arms swinging forward, back toe on the ground
 5 take-off line        +2    60ms  one straight line from back toe to fingertips (toe still touching), STRETCH
 6 apex, knees tucking +10   100ms  rest shape, knees pulled up, arms forward-up, scarf trailing back/down (rising = trailing)
 7 descent, legs fwd    +6    60ms  arms UP for balance, legs reaching forward-down, head level, scarf trailing UP
 8 landing crouch       −9   140ms  = frame 3 pose (squash on landing), knees ~90°, arms forward-down
 9 rise                 −4   120ms  coming up, arms lowering
10 stand                 0   120ms  = frame 1, scarf settles 1 frame late
(loop)

Secondary: scarf lags 1 frame: up on dip/crouch, trailing back/down on take-off/apex, streaming UP on descent,
still up on landing, falls on rise, settles by frame 10.
FX layer (code): take-off dust on 5 (4 frames, 60ms), landing dust on 8.
Risks: the −9 crouch at 33px is a big redraw (thighs horizontal) — keep head and torso pixels identical to the stand,
only re-pose legs/arms; volume must not change.
```

## Execution with the tool
1. Storyboard: Gemini draws one panel per frame from the lines above (concept/storyboard step in their `animate` skill).
2. Rig + frames in Aseprite (headless build) through the aseprite-ai-artist MCP server: frames, durations, tags, panels as references.
3. Grid loop: read each frame back as text, keep head/torso identical to the source, fix by changing characters.
4. Critic: independent `pixel-critic` cold read and score; a fix is kept only if a blind A/B prefers it.
5. Export: spritesheet + JSON + GIF.

## Results (aseprite-ai-artist, headless Aseprite)

Setup: Aseprite v1.3.15.5 built from source with no UI or Skia (`LAF_BACKEND=none`; libjpeg-turbo pulled in via a local git clone because zip downloads are blocked).
The aseprite-ai-artist 0.8.2 MCP server runs as `serve --headless`. `tools/aai_call.mjs` calls its tools; `tools/aai_build.py` generates the call list.

Flow: storyboard (shot list → Gemini → re-generate only the cells that missed) → head lock → Aseprite: palette, rig layers
(`legs` linked to one cel across all frames / `hips` / `upper` / `fx`), per-frame `draw` grid, rule-based frames via `cel copy+move`,
per-frame `frame set_duration`, `tag`, `look filmstrip`, `validate`, `export` (.aseprite, sheet+JSON, GIF).
Review: an independent pixel-critic subagent does a cold read and scores against the rulebook → fix blockers → **a fix is kept only if a blind A/B prefers it**.

| Round | Cross | Jump | Main changes |
|---|---|---|---|
| v1 | 5/10 | 3/10 | Feet slide 5–7px, smear isn't a smear / hop in place, dust looks like shoes, one airborne frame |
| v2 (A/B: v2 wins) | partial | blockers 4/4 fixed | Front foot aligned, chin→reach smear / +12px travel, +10px apex, landing = crouch drawing, grey dust |
| v3 (A/B: v3 wins) | 5/10 | 5/10 | Leg cel linked, upper body forward, speed lines attached to the arm / dust behind the feet, landing arms forward |
| v4 (A/B: v4 wins) | **6/10** | **5/10** | `hips` layer split (removes the notch), hit frame = max reach / feet pinned after landing |

Remaining (latest critic): cross — head pulls back 2px at the hit, hips don't move forward. Jump — only 2 airborne frames (16px rise in one step from launch to apex), back heel slides 4px after landing.
These come from the storyboard drawings themselves, so the next step is adding one rising in-between frame and re-drawing the landing frames to match each other.
Comparison: `out/compare_aseprite.gif`.
