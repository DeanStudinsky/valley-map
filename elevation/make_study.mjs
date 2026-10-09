// make_study.mjs — the sight-line study area: one 0.5 m LiDAR grid covering
// every stop-controlled intersection osm.json knows about, with the vertical
// return profile in each cell rather than just its highest return.
//
// Why the profile: the question at a stop sign is whether something occupies
// the band 3.5 ft above the road between a driver and an approaching car. A
// DSM keeps only the top surface, which is right for a roof or a block wall
// and badly wrong for a palm (40 ft of bare trunk under a crown) or a shade
// tree pruned up to 8 ft. The point cloud still knows the difference — pulses
// that slip through a crown return from the trunk and the ground, and nothing
// returns from the empty air in between — so each cell keeps a histogram of
// its non-ground returns by height above the DTM.
//
// Box: E 548000..549300, N 3743600..3744900 (1.3 km square, 2600 x 2600 cells).
// Sources, all USGS 3DEP CA_SaltonSea_EarthMRI_2021_D21:
//   raw/USGS_LPC_..._11SNT480430.laz      E 548000..549000  N 3743000..3744000
//   raw/LPC_SaltonSea_2021_11SNT480440.laz E 548000..549000  N 3744000..3745000
//   raw/ept_east.bin (fetch_ept.mjs)      E 549000..549300, same flight via EPT
// The EPT points are only taken east of E 549000 so no ground is counted twice;
// the 50 m strip they overlap the local tile is used to check registration.
//
// Outputs
//   study/dsm.f32  study/dtm.f32   Float32 ft NAVD88, 0.5 m, row0=SOUTH col0=WEST
//   study/vox.u8   [cell][NB]      non-ground returns per 1-ft bin above DTM,
//                                  bin NB-1 = everything >= NB-1 ft (saturating)
//   study/cnt.u8   [cell][3]       ground, non-ground, multi-return non-ground
//   study/meta.json
//   terrain_study.bin + _meta.json 1 m [DSM][DTM] ft for the scene (committed)
//
// Grid convention matches every other tile: sample (row, col) is the value at
// UTM (X0 + col*cell, Y0 + row*cell), points binned by floor().
//
// Run from elevation/:  node make_study.mjs
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'fs';
import lp from 'laz-perf';
const createLazPerf = lp.createLazPerf || lp.create;

const FT = 3.280839895;
const BASE_FT = 399.57349381574863;
const ADDR_E = 548660.3, ADDR_N = 3744180.9;
const X0 = 548000, Y0 = 3743600, CELL = 0.5, NC = 2600, NR = 2600, N = NC * NR;
const NB = 33;                       // 0..31 ft in 1 ft bins + one overflow bin
const EPT_E = 549000;                // EPT points are used east of this only

const LAZ = [
  'raw/USGS_LPC_CA_SaltonSea_EarthMRI_2021_D21_11SNT480430.laz',
  'raw/LPC_SaltonSea_2021_11SNT480440.laz',
];
const EPT = 'raw/ept_east.bin', EPT_META = 'raw/ept_east.json';

const mod = await createLazPerf();

// Stream every point in the box as (e, n, zMetres, class, nret) from both kinds
// of source. `ept` says which source a point came from.
function eachPoint(fn) {
  for (const path of LAZ) {
    const buf = readFileSync(path);
    const dv = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
    const xs = dv.getFloat64(131, true), ys = dv.getFloat64(139, true), zs = dv.getFloat64(147, true);
    const xo = dv.getFloat64(155, true), yo = dv.getFloat64(163, true), zo = dv.getFloat64(171, true);
    const z = new mod.LASZip();
    const fptr = mod._malloc(buf.length); mod.HEAPU8.set(buf, fptr); z.open(fptr, buf.length);
    const count = z.getCount(), ptLen = z.getPointLength();
    const fmt = z.getPointFormat() & 0x3f;
    const classOff = fmt >= 6 ? 16 : 15, classMask = fmt >= 6 ? 0xff : 0x1f;
    const dest = mod._malloc(ptLen); const di = dest >> 2;
    for (let i = 0; i < count; i++) {
      z.getPoint(dest);
      const i32 = mod.HEAP32, u8 = mod.HEAPU8;
      const e = i32[di] * xs + xo, n = i32[di + 1] * ys + yo;
      if (e < X0 || e >= X0 + NC * CELL || n < Y0 || n >= Y0 + NR * CELL) continue;
      const rb = u8[dest + 14];
      const nret = fmt >= 6 ? (rb >> 4) & 0x0f : (rb >> 3) & 0x07;
      fn(e, n, i32[di + 2] * zs + zo, u8[dest + classOff] & classMask, nret, false);
    }
    z.delete(); mod._free(fptr); mod._free(dest);
  }
  if (existsSync(EPT)) {
    const m = JSON.parse(readFileSync(EPT_META, 'utf8'));
    const b = readFileSync(EPT);
    const dv = new DataView(b.buffer, b.byteOffset, b.byteLength);
    for (let o = 0; o + 14 <= b.length; o += 14) {
      const e = m.box.E0 + dv.getFloat32(o, true), n = m.box.N0 + dv.getFloat32(o + 4, true);
      if (e < X0 || e >= X0 + NC * CELL || n < Y0 || n >= Y0 + NR * CELL) continue;
      fn(e, n, dv.getFloat32(o + 8, true), b[o + 12], b[o + 13] >> 4, true);
    }
  } else console.warn(`!! ${EPT} missing — east of E ${EPT_E} will be empty`);
}

const noise = cls => cls === 7 || cls === 18 || cls === 20;

/* ── pass 1: DSM, DTM, return counts ── */
const dsm = new Float32Array(N).fill(NaN);
const dtm = new Float32Array(N).fill(NaN);
const cnt = new Uint8Array(N * 3);
// Registration check: the EPT and local ground surfaces where both exist.
const OV0 = Math.floor((548950 - X0) / CELL), OV1 = Math.floor((EPT_E - X0) / CELL);
const ovW = OV1 - OV0;
const ovLocal = new Float32Array(ovW * NR).fill(NaN), ovEpt = new Float32Array(ovW * NR).fill(NaN);
const ovLocalTop = new Float32Array(ovW * NR).fill(NaN), ovEptTop = new Float32Array(ovW * NR).fill(NaN);
let nLocal = 0, nEpt = 0;
console.time('pass1');
eachPoint((e, n, zm, cls, nret, ept) => {
  if (noise(cls)) return;
  const col = (e - X0) / CELL | 0, row = (n - Y0) / CELL | 0;
  if (col >= OV0 && col < OV1) {               // overlap strip: keep both, separately
    const k = row * ovW + (col - OV0);
    const G = ept ? ovEpt : ovLocal, T = ept ? ovEptTop : ovLocalTop;
    if (cls === 2 && !(G[k] <= zm)) G[k] = zm;
    if (!(T[k] >= zm)) T[k] = zm;
  }
  if (ept ? e < EPT_E : e >= EPT_E) return;     // one source per cell
  ept ? nEpt++ : nLocal++;
  const i = row * NC + col, z = zm * FT;
  if (!(dsm[i] >= z)) dsm[i] = z;
  if (cls === 2) {
    if (!(dtm[i] <= z)) dtm[i] = z;
    if (cnt[i * 3] < 255) cnt[i * 3]++;
  } else {
    if (cnt[i * 3 + 1] < 255) cnt[i * 3 + 1]++;
    if (nret > 1 && cnt[i * 3 + 2] < 255) cnt[i * 3 + 2]++;
  }
});
console.timeEnd('pass1');
console.log(`points kept: local ${nLocal.toLocaleString()}, EPT ${nEpt.toLocaleString()}`);

// Registration: median ground and top-surface differences in the overlap, plus
// the best 1-cell shift of the top surface (buildings and walls give it edges).
{
  const med = a => { a.sort((x, y) => x - y); return a.length ? a[a.length >> 1] : NaN; };
  const dz = [];
  for (let k = 0; k < ovW * NR; k++)
    if (ovLocal[k] === ovLocal[k] && ovEpt[k] === ovEpt[k]) dz.push((ovEpt[k] - ovLocal[k]) * FT);
  let best = null;
  for (let sr = -2; sr <= 2; sr++) for (let sc = -2; sc <= 2; sc++) {
    let s = 0, k = 0;
    for (let r = 2; r < NR - 2; r++) for (let c = 2; c < ovW - 2; c++) {
      const a = ovLocalTop[r * ovW + c], b = ovEptTop[(r + sr) * ovW + c + sc];
      if (a === a && b === b) { s += Math.abs(a - b); k++; }
    }
    const mad = s / k;
    if (!best || mad < best.mad) best = { sr, sc, mad };
  }
  console.log(`EPT vs local overlap: ground dZ median ${med(dz).toFixed(3)} ft over ${dz.length} cells; ` +
              `top-surface best shift dRow ${best.sr} dCol ${best.sc} (cells of 0.5 m), mean |dZ| ${(best.mad * FT).toFixed(2)} ft`);
  globalThis.REG = { groundDzMedianFt: med(dz), groundCells: dz.length, bestShiftCells: [best.sr, best.sc], topMadFt: best.mad * FT };
}

// Fill: DTM under buildings needs many passes (a 30 m roof is 60 cells across).
function fill(g, passes) {
  let cp = new Float32Array(N);
  for (let p = 0; p < passes; p++) {
    cp.set(g);
    let filled = 0;
    for (let r = 0; r < NR; r++) for (let c = 0; c < NC; c++) {
      const i = r * NC + c; if (cp[i] === cp[i]) continue;
      let s = 0, k = 0;
      for (let dr = -1; dr <= 1; dr++) { const rr = r + dr; if (rr < 0 || rr >= NR) continue;
        for (let dc = -1; dc <= 1; dc++) { const cc = c + dc; if (cc < 0 || cc >= NC) continue;
          const v = cp[rr * NC + cc]; if (v === v) { s += v; k++; } } }
      if (k >= 2) { g[i] = s / k; filled++; }
    }
    if (!filled) break;
  }
  let left = 0; for (let i = 0; i < N; i++) if (g[i] !== g[i]) { g[i] = BASE_FT; left++; }
  return left;
}
console.time('fill');
const dtmMissing = (() => { let k = 0; for (let i = 0; i < N; i++) if (dtm[i] !== dtm[i]) k++; return k; })();
const leftT = fill(dtm, 200);
for (let i = 0; i < N; i++) if (dsm[i] !== dsm[i]) dsm[i] = NaN;
const leftS = fill(dsm, 12);
for (let i = 0; i < N; i++) if (dsm[i] < dtm[i]) dsm[i] = dtm[i];
console.timeEnd('fill');
console.log(`DTM cells interpolated (no ground return): ${dtmMissing.toLocaleString()} (${(100 * dtmMissing / N).toFixed(1)}%), unfillable ${leftT}; DSM unfillable ${leftS}`);

/* ── pass 2: vertical profile of non-ground returns above the filled DTM ── */
const vox = new Uint8Array(N * NB);
console.time('pass2');
eachPoint((e, n, zm, cls, nret, ept) => {
  if (noise(cls) || cls === 2) return;
  if (ept ? e < EPT_E : e >= EPT_E) return;
  const col = (e - X0) / CELL | 0, row = (n - Y0) / CELL | 0;
  const i = row * NC + col;
  const h = zm * FT - dtm[i];
  if (h < 0) return;
  const b = Math.min(NB - 1, h | 0);
  if (vox[i * NB + b] < 255) vox[i * NB + b]++;
});
console.timeEnd('pass2');

mkdirSync('study', { recursive: true });
writeFileSync('study/dsm.f32', Buffer.from(dsm.buffer));
writeFileSync('study/dtm.f32', Buffer.from(dtm.buffer));
writeFileSync('study/vox.u8', vox);
writeFileSync('study/cnt.u8', cnt);
writeFileSync('study/meta.json', JSON.stringify({
  note: 'Sight-line study grid. Float32 ft NAVD88. row0=SOUTH col0=WEST; sample (r,c) at UTM (x0+c*cellM, y0+r*cellM).',
  source: 'USGS 3DEP CA_SaltonSea_EarthMRI_2021_D21 (flown 2021): tiles 11SNT480430, 11SNT480440 (LAZ) + EPT east of E 549000',
  nc: NC, nr: NR, cellM: CELL, cellFt: CELL * FT, utm: { x0: X0, y0: Y0, addrE: ADDR_E, addrN: ADDR_N },
  baseFt: BASE_FT, vox: { bins: NB, binFt: 1, overflowBin: NB - 1, layout: 'uint8 [cell][bin] non-ground returns, saturating' },
  cnt: { layout: 'uint8 [cell][ground, nonGround, multiReturnNonGround]' },
  dtmInterpolatedCells: dtmMissing, registration: globalThis.REG,
}, null, 2));

/* ── scene product: 1 m [DSM][DTM], 2x2 blocks (DSM max, DTM mean) ── */
const nc1 = NC / 2, nr1 = NR / 2, n1 = nc1 * nr1;
const out = new Float32Array(n1 * 2);
for (let r = 0; r < nr1; r++) for (let c = 0; c < nc1; c++) {
  let mx = -Infinity, s = 0;
  for (let dr = 0; dr < 2; dr++) for (let dc = 0; dc < 2; dc++) {
    const i = (2 * r + dr) * NC + 2 * c + dc;
    if (dsm[i] > mx) mx = dsm[i]; s += dtm[i];
  }
  out[r * nc1 + c] = mx; out[n1 + r * nc1 + c] = s / 4;
}
writeFileSync('terrain_study.bin', Buffer.from(out.buffer));
// The 2x2 mean of 0.5 m samples sits a quarter metre NE of the block corner.
writeFileSync('terrain_study_meta.json', JSON.stringify({
  note: 'Elevations in FEET (NAVD88). Grid row0=SOUTH, col0=WEST. World: +X=East, +Z=South, North=-Z. Subtract baseFt for y near 0.',
  source: 'USGS 3DEP CA_SaltonSea_EarthMRI_2021_D21 (flown 2021) — sight-line study box, built by make_study.mjs',
  nc: nc1, nr: nr1, cellFt: FT, cellM: 1,
  utm: { x0: X0 + 0.25, y0: Y0 + 0.25, addrE: ADDR_E, addrN: ADDR_N },
  baseFt: BASE_FT,
  bin: { file: 'terrain_study.bin', layout: 'Float32LE: DSM[nc*nr] then DTM[nc*nr]' },
  sizeFt: [nc1 * FT, nr1 * FT],
}, null, 2));
console.log(`wrote study/{dsm,dtm}.f32 vox.u8 cnt.u8 meta.json, terrain_study.bin (${(out.byteLength / 1e6).toFixed(1)} MB)`);
