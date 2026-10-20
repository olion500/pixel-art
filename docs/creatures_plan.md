# Concept image only → animated sprite (humanoid + non-humanoid monster)

No answer key (reference animation). The input is **one concept illustration**. The motion design comes only from the aseprite-ai-artist rule tables.
Test concepts were generated with Gemini because no user concept was available (`samples/concepts/`). The same flow works with your own concept.

## Pipeline
1. **Concept → base pixel sprite** (`tools/concept_to_sprite.py`): the image model redraws the concept as pixel art at the specified size.
   Then the grid is restored (art pixel size detected from edge-peak spacing), the palette quantized, the alpha binarized, and specks removed.
   Rule (concept skill): the concept is a reference for proportions, silhouette, and color masses; it is never used as the pixels.
2. **PixelSpec + motion design** (this document): frame count, poses, and ms from the rule tables. Shot lists in `samples/<char>/plans/`.
3. **Storyboard** (`plan_animate.py`) → per-cell fixes (`fix_cells.py`)
4. **Aseprite assembly** (`aai_build.py` + `aai_call.mjs`, headless aseprite-ai-artist)
5. **Critic cold read → fixes → blind A/B**

---

## A. Fox swordswoman (humanoid, about 32 px tall)
PixelSpec: side view, facing right, 32 px tall, 16 colors, dark outline. Signature traits: fox ears, a big tail, a teal cloak, a curved sword at the hip.

```
IDLE — 4 frames, tag "idle", pingpong-like loop. Rule 41: at ≥32px always breathe; extremes held ~2× the transitions; tail/ears lag.
 1 rest            300ms  base pose
 2 exhale          150ms  torso + arms 1px down (feet fixed), tail tip still up (lag)
 3 exhale hold     300ms  same body, tail tip 1px down, one ear tip flicks 1px
 4 inhale          150ms  body back up, tail tip still down (lag)
Face pixels identical in every frame (41.14).
```

```
SLASH (iaido draw-cut) — 7 frames, tag "slash". Rule 44 sword side-view table: wind-up 100, smear 50, hit 100, follow 50, recover 50, overshoot 50.
 1 stance          100ms  hand on the hilt at the hip
 2 wind-up         100ms  knees bend 2px lower, torso twists back, hand grips, sword starts leaving the sheath (opposite direction)
 3 smear            50ms  sword swept from the hip up and forward: one crescent fan 4–6px wide (FX layer, steel's 2 brightest colors)
 4 HIT             100ms  front foot lunges 3px forward, sword fully extended forward, slightly above horizontal, blade +1–2px longer
 5 follow           50ms  blade continues down-forward past the target, thin crescent remnant
 6 recover         100ms  return to stance, sword back toward the sheath (different arc than the strike)
 7 overshoot        50ms  stance with the upper body 1px back
Secondary: cloak and tail lag 1 frame, pulled back on 3–4, swing forward on 6–7.
```

## B. Stone boar (non-humanoid quadruped, heavy, about 28 px tall × 44 px long)
Rule 54: answer the five questions → beast / territory guardian / strength: charging tusks / weakness: soft belly + slow wind-up / proud / conqueror.
Dominant shape: **square (brute) + triangular tusks**. Identifying element: stone shell. Heavy-brute formula: weight up front.

```
IDLE — 4 frames, tag "idle". Rule 41 (heavy = slow, 300–400ms) + 51.14 (heavy animals: small bounce, big head swing).
 1 rest            400ms  base pose
 2 exhale          200ms  belly/back 1px down (hooves fixed), head still up (head lags 1 frame)
 3 exhale hold     400ms  head 1px down, snout breath, stubby tail flicks 1px
 4 inhale          200ms  body back up, head still down
Shell plates are rigid (no deformation).
```

```
WALK — 8 frames, tag "walk", forward loop. Rule 51: lateral four-beat walk (near hind → near fore → far hind → far fore),
2–3 feet always on the ground, planted feet slide back at ground speed, swing feet lift 1–2px on an arc, heavy = 1px bob.
 1 near-hind contact     120ms  near hind leg planted forward, far fore leg lifting
 2 near-fore contact     120ms  near fore planted forward, near hind dragging back, body 1px low
 3 far-hind contact      120ms  far hind planted forward
 4 far-fore contact      120ms  far fore planted forward, body 1px low
 5–8  repeat with the leg pairs swapped (the second half of each leg's cycle)
Head 1 frame behind the chest; tusks follow the head; tail on a different period.
```

```
CHARGE (gore) — 8 frames, tag "charge", enemy attack. Rule 44.3 (enemies telegraph 150–400ms), 54.14 (heavy = slow wind-up).
 1 stance          120ms  base pose
 2 wind-up A       150ms  head drops low, weight shifts back onto the hind legs, front hooves dig in
 3 wind-up B (hold)250ms  head lowest, tusks pointing forward, back shell raised (readable telegraph)
 4 lunge smear      50ms  whole body thrown forward 6px, tusks lead, front legs reaching
 5 GORE HIT        120ms  tusks thrust forward-up at full reach, front legs braced, spark at the tusk tip
 6 follow           80ms  head tossed up past the hit, spark breaking up
 7 recover         150ms  pulls back to stance, heavy (long)
 8 overshoot        80ms  body 1px back, shell settles
```
