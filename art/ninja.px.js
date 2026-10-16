// Ninja remade with pxl (https://github.com/crsolver/claude-pxl): base sprite + idle / punch / jump.
//
// The base is the Sprite Fusion ninja converted to a pxl grid (tools/to_pxl.py, 16 -> 11 keys).
// Animations are built from parts of that grid, posed per frame by a small skeleton written in
// plain JS (pxl has no free rotation, so leaning is a row shear, the way pixel artists do it),
// then fixed by hand with per-frame pixel patches after looking at the previews.

pal({ k: "#030104", n: "#171b3f", m: "#232c4c", N: "#273961", P: "#a12a70", p: "#e03e8e",
      t: "#3b8dac", c: "#06e7db", h: "#74fdf4", s: "#8cbbcb", w: "#cfeef2" })

const BASE = `
..................kkkkkk.........
.................knNNNNNk........
................knnnNNNNNk.......
...............kNnnnnNNNNk.......
...............knnkkkkkkkkk......
..........kkk..kntktccccchk......
..kkk...kkpppk.kntktcccchhk......
..kppkkkppppppkknnnktccccck......
..kppppppPkkkPPmknnNkkkkkkk......
...kppppPk...kkkpknnNNNNNk.......
....kkkkk...kmcnP.kknNNNk........
...........kNmcNnPpPkkkkk........
..........kccmmkNnPpppPpk........
.........kNNmkknNNnPPPPkk........
........kNNnk.knNNNnnnmkk........
........kNNk..knnNNNnNknnk.......
........kNNk..knnnnnnkknNNk......
.......kmNnk..knNNNNnk.knNmkk....
.......kNNNnkknNNNNNnkk.knnNnk...
.......kNNnnkkNNNNNNNNNk.knnNk...
.......knnnkknNNNNNNNNNNk.knnk...
........kkk.kNNNNnknnNNNNkkkk....
............kNNNmk.kkmNNNNk......
...........kNNNnk....knnNNk......
..........knNNmk......knNNk......
.........knnnnk.......knNk.......
........kkknnk........knkkk......
.......kkwwkk........kkkkwk......
.......kswwwk........ksswwk......
......kksssk........kkswwswkk....
......kswwwkk.......kstwwwwwwk...
......kwwwwwk.......ksstsssssk...
......kkkkkkk.......kkkkkkkkkk...`.split("\n").filter((r) => r.trim()).map((r) => r.trim())

sprite("ninja", BASE.join("\n"))

// ---------------------------------------------------------------- parts
// A part is a list of [x, y, key] in base coordinates. Rects are inclusive; earlier parts win.
const taken = new Set()
function part(rects) {
  const out = []
  for (const [x0, y0, x1, y1] of rects)
    for (let y = y0; y <= y1; y++)
      for (let x = x0; x <= x1; x++) {
        const k = BASE[y]?.[x]
        if (!k || k === "." || taken.has(x + "," + y)) continue
        taken.add(x + "," + y)
        out.push([x, y, k])
      }
  return out
}
const P = {
  scarf: part([[2, 5, 14, 8], [2, 9, 11, 10]]),
  head: part([[15, 0, 27, 8], [17, 9, 26, 10]]),
  armF: part([[23, 14, 29, 18], [25, 19, 29, 19], [26, 20, 29, 22]]),
  armB: part([[7, 12, 12, 21]]),
  shoeB: part([[6, 27, 12, 32]]),
  shoeF: part([[20, 27, 29, 32]]),
  legs: part([[5, 22, 30, 26]]),
  torso: part([[0, 0, 32, 32]]),      // everything left: torso + neck wrap
}
const FIST = P.armF.filter(([x, y]) => x >= 25 && y >= 16)   // front fist incl. outline
const FIST_C = [27, 18]
const HIP = { b: [14, 22], f: [21, 22] }
const SHOULDER = { f: [22, 15], b: [12, 13] }
const ANKLE = { b: [10, 27], f: [24, 27] }   // where the shoe part attaches
const NECK = [17, 9]

// Draw a part with an offset, an optional lean (row shear around pivotY) and per-column wave.
function blit(c, pts, dx, dy, o = {}) {
  for (const [x, y, k] of pts) {
    const lean = o.shear ? Math.round(o.shear * (o.pivotY - y)) : 0
    const wave = o.wave ? o.wave(x, y) : 0
    c.px(x + dx + lean + (o.wx ? o.wx(x, y) : 0), y + dy + wave, k)
  }
}

// Scarf: the tail flutters (more toward its free end); `lift` raises the tip, `trail` stretches it.
// Sampled per destination column so a stretched scarf never tears into pieces.
const SCARF = new Map()
for (const [x, y, k] of P.scarf) { if (!SCARF.has(x)) SCARF.set(x, []); SCARF.get(x).push([y, k]) }
const SCARF_X0 = Math.min(...SCARF.keys())
function scarf(c, t, dx, dy, o = {}) {
  const amp = o.amp ?? 1, lift = o.lift ?? 0, trail = o.trail ?? 0
  const dOf = (x) => Math.max(0, (15 - x) / 13)
  for (let nx = SCARF_X0 - trail - 1; nx <= 15; nx++) {
    const sx = nx + Math.round(trail * dOf(nx))
    const col = SCARF.get(Math.max(SCARF_X0, sx))
    if (!col || sx < SCARF_X0 - 0) continue
    const d = dOf(sx)
    const wy = Math.round(amp * d * Math.sin(t * 2 * Math.PI - d * 3) - lift * d * d)
    for (const [y, k] of col) c.px(nx + dx, y + dy + wy, k)
  }
}

// Limb: outlined capsule chain (k outline, fill, 1px shadow side) - pxl's round-brush line.
function limb(c, pts, fill = "N", shadow = "n", w = 3) {
  for (let i = 0; i < pts.length - 1; i++) c.line(...pts[i], ...pts[i + 1], "k", w + 2)
  for (let i = 0; i < pts.length - 1; i++) c.line(...pts[i], ...pts[i + 1], fill, w)
  for (let i = 0; i < pts.length - 1; i++) {
    const [x0, y0] = pts[i], [x1, y1] = pts[i + 1]
    c.line(x0, y0 + 1, x1, y1 + 1, shadow, 1)
  }
}

// ---------------------------------------------------------------- idle
// Breathing: the upper body sinks 1px on the exhale, feet stay planted, scarf flutters.
const IDLE = [0, 0, 1, 1, 1, 1, 0, 0]
anim("ninja_idle", { w: 33, h: 33, frames: 8, fps: 8 }, (c) => {
  const d = IDLE[c.frame], t = c.phase
  blit(c, P.armB, 0, d)
  blit(c, P.legs, 0, 0)
  blit(c, P.shoeB, 0, 0)
  blit(c, P.shoeF, 0, 0)
  blit(c, P.torso, 0, d)
  blit(c, P.head, 0, d)
  scarf(c, t, 0, d, { amp: 1.4 })
  blit(c, P.armF, 0, d)
})

// ---------------------------------------------------------------- poses
// A pose moves the upper body (dx, dy, lean) and redraws limbs relative to the hips/shoulders.
// legs.b / legs.f: [knee, ankle] relative to the hip, ankle "g" = on the floor; tilt points the toe down.
// arms.f / arms.b: [elbow, hand] relative to the shoulder, or absolute with `at`.
const FLOOR = 27   // ankle y (base coords) when standing
const PIVOT_Y = 22 // lean pivots around the hips

function stampAt(c, pts, anchor, x, y, tilt = 0) {
  blit(c, pts, x - anchor[0], y - anchor[1], { wx: tilt ? (px, py) => -Math.round(tilt * (py - anchor[1]) / 5) : null })
}

function pose(c, p, t, ox = 0, oy = 0) {
  const dx = (p.dx ?? 0) + ox, dy = (p.dy ?? 0) + oy, lean = p.lean ?? 0
  const up = (pt) => [pt[0] + dx + Math.round(lean * (PIVOT_Y - pt[1])), pt[1] + dy]
  const upper = { shear: lean, pivotY: PIVOT_Y }
  const legPts = (side) => {
    const [k, a] = p.legs[side]
    const hip = [HIP[side][0] + dx, HIP[side][1] + dy]
    const knee = [hip[0] + k[0], hip[1] + k[1]]
    const ank = [hip[0] + a[0], a[1] === "g" ? FLOOR + oy : hip[1] + a[1]]
    return [hip, knee, ank]
  }
  const armPts = (side) => {
    const a = p.arms[side]
    const sh = a.at ? [a.at[0] + dx, a.at[1] + dy] : up(SHOULDER[side])
    return [sh, [sh[0] + a.e[0], sh[1] + a.e[1]], [sh[0] + a.h[0], sh[1] + a.h[1]]]
  }
  const drawLeg = (side) => {
    const pts = legPts(side)
    limb(c, pts)
    const ank = pts[2]
    stampAt(c, side === "b" ? P.shoeB : P.shoeF, ANKLE[side], ank[0], ank[1], p.legs[side][2] ?? 0)
  }
  const drawArm = (side) => {
    const pts = armPts(side)
    limb(c, pts, "N", "n", 3)
    stampAt(c, FIST, FIST_C, pts[2][0], pts[2][1])
  }

  // back to front: far arm, legs, torso, head, scarf, near arm
  if (p.arms?.b) drawArm("b"); else blit(c, P.armB, dx, dy, upper)
  if (p.legs) { drawLeg("b"); drawLeg("f") }
  else { blit(c, P.legs, ox, oy); blit(c, P.shoeB, ox, oy); blit(c, P.shoeF, ox, oy) }
  blit(c, P.torso, dx, dy, upper)
  const headLean = Math.round(lean * (PIVOT_Y - 7))
  blit(c, P.head, dx + headLean + (p.head?.[0] ?? 0), dy + (p.head?.[1] ?? 0))
  scarf(c, t + (p.scarf?.t ?? 0), dx + headLean, dy, p.scarf)
  if (p.arms?.f) drawArm("f"); else blit(c, P.armF, dx, dy, upper)
  for (const fix of p.fix ?? []) fix(c, ox, oy)   // hand-made pixel patches for this frame
}

// ---------------------------------------------------------------- punch: rear-hand cross
// Frame 0 is the untouched base. The far (back) arm punches; it is drawn behind the torso, so only
// the part past the chest shows. The near hand pulls back to guard the chin.
const GUARD = { e: [0, 3], h: [3, 3] }   // near hand tucked at the chest, clear of the punch
const stanceLegs = (bx, tilt, fx) => ({ b: [[-3, 3], [bx, "g", tilt]], f: [[2, 3], [fx, "g"]] })
const PUNCH = [
  {},
  { dx: -1, lean: -0.08, scarf: { amp: 1 } },
  { dx: 1, lean: 0.12, legs: stanceLegs(-5, 1, 4), arms: { f: GUARD, b: { at: [15, 13], e: [4, 2], h: [8, 0] } }, scarf: { trail: 1 } },
  { dx: 2, lean: 0.2, legs: stanceLegs(-7, 3, 5), arms: { f: GUARD, b: { at: [16, 13], e: [8, 0], h: [15, 0] } }, scarf: { trail: 2, lift: 1 } },
  { dx: 2, lean: 0.22, legs: stanceLegs(-7, 3, 5), arms: { f: GUARD, b: { at: [16, 13], e: [9, -1], h: [17, -1] } }, scarf: { trail: 3, lift: 2 } },
  { dx: 2, lean: 0.22, legs: stanceLegs(-7, 3, 5), arms: { f: GUARD, b: { at: [16, 13], e: [9, -1], h: [16, -1] } }, scarf: { trail: 3, lift: 1 } },
  { dx: 1, lean: 0.12, legs: stanceLegs(-5, 1, 4), arms: { f: GUARD, b: { at: [15, 13], e: [4, 3], h: [7, 1] } }, scarf: { trail: 2 } },
  { lean: 0.04, scarf: { trail: 1 } },
]
anim("ninja_punch", { w: 38, h: 33, frames: PUNCH.length, fps: 10 }, (c) => pose(c, PUNCH[c.frame], c.phase))

// ---------------------------------------------------------------- jump
// Starts and ends crouched (like Sprite Fusion's, which was animated from an edited crouch pose).
const L = (bk, ba, fk, fa) => ({ b: [bk, ba], f: [fk, fa] })
const A = (fe, fh, be, bh) => ({ f: { e: fe, h: fh }, b: { e: be, h: bh } })
const CROUCH = { dy: 3, lean: 0.15, legs: L([-4, 1], [-5, "g"], [4, 0], [3, "g"]), arms: A([2, 3], [5, 2], [-2, 3], [-3, 6]) }
const JUMP = [
  CROUCH,
  { dy: 4, lean: 0.3, legs: L([-5, 0], [-6, "g"], [5, -1], [3, "g"]), arms: A([-2, 4], [-4, 6], [-3, 3], [-6, 4]), scarf: { lift: 1 } },
  { dx: 2, dy: 1, lean: 0.4, legs: { b: [[-3, 3], [-6, "g", 2]], f: [[5, -1], [4, 3]] }, arms: A([3, 0], [7, -2], [3, 1], [6, -1]), scarf: { trail: 1 } },
  { dx: 3, dy: -3, lean: 0.45, legs: { b: [[-4, 3], [-8, 4, 3]], f: [[4, 0], [2, 4, 1]] }, arms: A([4, -1], [8, -3], [3, 0], [7, -2]), scarf: { trail: 2, lift: 1 } },
  { dx: 3, dy: -5, lean: 0.35, legs: { b: [[-4, 2], [-8, 4, 3]], f: [[-1, 3], [-4, 6, 3]] }, arms: A([4, -1], [8, -2], [4, 0], [7, -1]), scarf: { trail: 3, lift: -1 } },
  { dx: 3, dy: -6, lean: 0.3, legs: L([3, -1], [0, 3], [5, -2], [3, 3]), arms: A([4, 1], [7, 0], [3, 2], [6, 1]), scarf: { trail: 2, lift: -2 } },
  { dx: 3, dy: -5, lean: 0.15, legs: L([3, -2], [1, 3], [5, -3], [4, 2]), arms: A([3, 2], [6, 1], [2, 3], [5, 2]), scarf: { trail: 1, lift: -2 } },
  { dx: 3, dy: -3, lean: 0.05, legs: L([0, 3], [-1, 6], [3, 2], [4, 6]), arms: A([3, 2], [6, 2], [-2, 3], [-2, 6]), scarf: { lift: -1 } },
  { dx: 2, dy: 0, lean: 0.15, legs: L([-2, 2], [-4, "g"], [3, 2], [4, "g"]), arms: A([3, 2], [6, 3], [-2, 3], [-3, 6]) },
  { dx: 1, dy: 4, lean: 0.3, legs: L([-5, 0], [-6, "g"], [5, -1], [3, "g"]), arms: A([3, 3], [6, 4], [-3, 3], [-5, 5]), scarf: { lift: 1 } },
  { dy: 4, lean: 0.2, legs: L([-5, 0], [-6, "g"], [5, -1], [3, "g"]), arms: A([2, 3], [5, 2], [-3, 3], [-4, 6]) },
  CROUCH,
]
anim("ninja_jump", { w: 46, h: 40, frames: JUMP.length, fps: 10 }, (c) => pose(c, JUMP[c.frame], c.phase, 4, 7))

// ================================================================ v2: motion principles + FX
// Applied from research (docs section 11): uneven timing (holds on anticipation, impact and apex),
// one fast smear frame, exaggerated reach at full extension, hit flash + spark + speed lines,
// overshoot on recovery, squash/stretch on crouch/launch/land, scarf as overlapping action,
// dust on take-off and landing. Each frame carries its own duration via frame({ ms }).

function seq(name, opts, list, ox = 0, oy = 0) {
  const n = list.length
  anim(name, opts, ...list.map(([ms, p], i) => frame({ ms }, (c) => pose(c, p, i / n, ox, oy))))
}

// ---- FX helpers (canvas coords). Effects use the light keys only: w white, h pale cyan, c cyan.
function flashFist(c, x, y) {
  for (const [fx, fy, k] of FIST) c.px(x + fx - FIST_C[0], y + fy - FIST_C[1], k === "k" ? "k" : "w")
}
function spark(c, x, y, stage) {
  const ray = (dx, dy, n, inner, outer, from = 1) => {
    for (let i = from; i <= n; i++) c.px(x + dx * i, y + dy * i, i <= inner ? "w" : outer)
  }
  if (stage === 0) {                      // contact: small bright cross
    c.px(x, y, "w"); for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) ray(dx, dy, 2, 1, "h")
    for (const [dx, dy] of [[1, 1], [1, -1], [-1, 1], [-1, -1]]) ray(dx, dy, 1, 0, "h")
  } else if (stage === 1) {               // burst: long orthogonal rays, short diagonals, hot core
    c.circ(x, y, 1, "w")
    for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) ray(dx, dy, 5, 3, "h", 2)
    for (const [dx, dy] of [[1, 1], [1, -1], [-1, 1], [-1, -1]]) ray(dx, dy, 3, 1, "h", 2)
  } else if (stage === 2) {               // ring breaking up, rays detached
    for (let a = 0; a < 16; a++) if (a % 2 === 0)
      c.px(x + Math.round(4 * Math.cos(a * Math.PI / 8)), y + Math.round(4 * Math.sin(a * Math.PI / 8)), "h")
    for (const [dx, dy] of [[1, 0], [0, 1], [0, -1], [-1, 0]]) { c.px(x + dx * 6, y + dy * 6, "c"); c.px(x + dx * 7, y + dy * 7, "c") }
  } else if (stage === 3) {               // last particles drifting out
    for (const [dx, dy] of [[8, -2], [6, 4], [-2, -7], [1, 7], [9, 1], [-5, 3]]) c.px(x + dx, y + dy, dx % 2 ? "h" : "c")
  }
}
function speedLines(c, x0, x1, ys, gap = 0) {
  for (const y of ys) for (let x = x0; x <= x1; x++) if (!gap || (x - x0) % (gap + 3) < 3) c.px(x, y, (x - x0) < (x1 - x0) / 2 ? "h" : "w")
}
function smearArm(c, x0, x1, y) {          // tapered two-tone streak along the punch path
  c.poly([x0, y + 1, x1, y - 1, x1, y + 3, x0, y + 2], "h")
  c.line(x0 + 3, y + 1, x1, y + 1, "w", 1)
}
function dust(c, x, y, stage, dir = 0) {   // dir: -1 left only, 1 right only, 0 both
  const sides = dir ? [dir] : [-1, 1]
  for (const s of sides) {
    if (stage === 0) { c.circ(x + s * 2, y - 1, 1, "w"); c.px(x + s * 3, y, "s") }
    if (stage === 1) { c.circ(x + s * 5, y - 2, 2, "w"); c.hline(x + s * 5 - 2, y, 5, "s"); c.px(x + s * 2, y - 1, "s") }
    if (stage === 2) { c.px(x + s * 8, y - 3, "s"); c.px(x + s * 7, y - 1, "w"); c.px(x + s * 9, y - 1, "s") }
  }
}

// ---- punch v2: rear-hand cross with smear, hitstop hold, spark, overshoot
const ARM_AT = [16, 13]
const reach = (dx, e, h) => ({ f: GUARD, b: { at: ARM_AT, e, h } })
const fistAt = (p) => [ARM_AT[0] + p.dx + p.arms.b.h[0], ARM_AT[1] + p.arms.b.h[1]]
const IMPACT = { dx: 3, lean: 0.1, legs: stanceLegs(-8, 3, 6), arms: reach(3, [10, -1], [20, -1]), scarf: { trail: 3, lift: 2, amp: 0.5 } }
const PUNCH2 = [
  [120, {}],
  [150, { dx: -1, dy: 1, lean: -0.06, scarf: { lift: 1, amp: 0.6 } }],                       // anticipation (held)
  [50, { dx: 1, lean: 0.06, legs: stanceLegs(-6, 2, 4), arms: reach(1, [5, 0], [10, -1]), scarf: { trail: 2, lift: 1 },
         fix: [(c) => { smearArm(c, 21, 30, 12) }] }],                                         // smear
  [130, { ...IMPACT, fix: [(c) => { const [x, y] = fistAt(IMPACT); flashFist(c, x, y); spark(c, x + 3, y, 0); speedLines(c, 27, 34, [9, 15]) }] }],
  [90, { ...IMPACT, fix: [(c) => { const [x, y] = fistAt(IMPACT); spark(c, x + 3, y, 1); speedLines(c, 30, 35, [9, 15], 1) }] }],
  [70, { ...IMPACT, arms: reach(3, [9, -1], [19, -1]), fix: [(c) => { const [x, y] = fistAt(IMPACT); spark(c, x + 2, y, 2) }] }],
  [80, { dx: 1, lean: 0.05, legs: stanceLegs(-6, 2, 4), arms: reach(1, [5, 2], [9, 0]), scarf: { trail: 1, lift: -1 },
         fix: [(c) => spark(c, 38, 12, 3)] }],                                                 // recovery
  [80, { dx: -1, scarf: { trail: 0, lift: -1, amp: 0.8 } }],                                    // overshoot 1px back
  [130, { scarf: { amp: 0.6 } }],
]
seq("ninja_punch_v2", { w: 48, h: 33 }, PUNCH2)

// ---- jump v2: squash -> stretch -> hang -> fall -> squash, scarf lagging the body
const G = "g"
const legs2 = (b, f) => ({ b, f })
const JUMP2 = [
  [120, {}],
  [130, { dy: 3, lean: 0.12, head: [0, 1], legs: legs2([[-4, 1], [-6, G]], [[4, 0], [4, G]]),
          arms: A([1, 3], [3, 5], [-2, 3], [-5, 4]), scarf: { lift: 1, amp: 0.6 } }],           // anticipation squash
  [60, { dy: 4, lean: 0.2, head: [0, 1], legs: legs2([[-5, 0], [-7, G]], [[5, -1], [4, G]]),
         arms: A([-2, 3], [-5, 4], [-3, 2], [-7, 2]), scarf: { lift: 2, amp: 0.6 } }],
  [60, { dy: -2, lean: 0.08, head: [0, -1], legs: legs2([[-1, 4], [-3, 8, 4]], [[1, 4], [0, 8, 3]]),
         arms: A([2, -3], [4, -7], [1, -3], [2, -7]), scarf: { lift: -2, trail: 1 },
         fix: [(c, ox, oy) => dust(c, 17 + ox, 32 + oy, 0)] }],                                // launch stretch
  [70, { dy: -5, lean: 0.12, legs: legs2([[-2, 4], [-4, 7, 3]], [[3, 2], [2, 6, 2]]),
         arms: A([3, -2], [6, -5], [2, -2], [5, -4]), scarf: { lift: -2, trail: 2 },
         fix: [(c, ox, oy) => dust(c, 17 + ox, 32 + oy, 1)] }],
  [80, { dy: -7, lean: 0.15, legs: legs2([[1, 3], [-1, 6, 2]], [[4, 1], [3, 5, 1]]),
         arms: A([4, 0], [7, -1], [3, 0], [6, 0]), scarf: { lift: -1, trail: 2 },
         fix: [(c, ox, oy) => dust(c, 17 + ox, 32 + oy, 2)] }],
  [140, { dy: -8, lean: 0.18, legs: legs2([[3, -1], [0, 3]], [[5, -2], [3, 3]]),
          arms: A([4, 1], [7, 1], [3, 2], [6, 2]), scarf: { lift: 0, trail: 1, amp: 1.5 } }],    // apex tuck (hang)
  [100, { dy: -8, lean: 0.12, legs: legs2([[2, 1], [0, 5]], [[4, 0], [4, 5]]),
          arms: A([3, -1], [6, -3], [-2, -2], [-4, -5]), scarf: { lift: 2, amp: 1 } }],
  [70, { dy: -5, lean: 0.05, legs: legs2([[0, 3], [-2, 7, 1]], [[3, 3], [4, 7]]),
         arms: A([3, -2], [5, -5], [-3, -2], [-5, -5]), scarf: { lift: 3, amp: 0.8 } }],          // fall: scarf rides up
  [60, { dy: -2, legs: legs2([[-1, 3], [-3, 7]], [[3, 3], [4, 7]]),
         arms: A([3, -2], [5, -5], [-3, -2], [-5, -5]), scarf: { lift: 3, amp: 0.8 } }],
  [110, { dy: 4, lean: 0.2, head: [0, 1], legs: legs2([[-5, 0], [-7, G]], [[5, -1], [4, G]]),
          arms: A([3, 3], [6, 5], [-3, 3], [-6, 5]), scarf: { lift: 1, amp: 0.5 },
          fix: [(c, ox, oy) => dust(c, 17 + ox, 32 + oy, 0)] }],                               // landing squash
  [90, { dy: 2, lean: 0.1, legs: legs2([[-4, 1], [-6, G]], [[4, 1], [4, G]]),
         arms: A([2, 3], [4, 4], [-2, 3], [-4, 6]), scarf: { lift: -1, amp: 0.8 },
         fix: [(c, ox, oy) => dust(c, 17 + ox, 32 + oy, 1)] }],
  [130, { scarf: { lift: -1, amp: 1 }, fix: [(c, ox, oy) => dust(c, 17 + ox, 32 + oy, 2)] }],    // settle, scarf follows through
]
seq("ninja_jump_v2", { w: 46, h: 44 }, JUMP2, 4, 10)
