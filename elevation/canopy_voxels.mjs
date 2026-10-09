// canopy_voxels.mjs — vertical LiDAR return profile per 0.5 m cell around the
// 68075 Alva Ct lot, so shade analysis can let low sun pass UNDER a palm crown
// instead of treating every tree as a solid pillar from the ground to its top.
//
// The DSM keeps only the highest surface in each cell; that is right for a roof
// and badly wrong for a Washingtonia, which is 40 ft of bare trunk under a crown.
// The point cloud still knows the difference: pulses that slip through the
// fronds return from the trunk and the ground, and nothing returns from the
// empty air in between.
//
// Output, on the terrain_fine grid (0.5 m, row 0 = SOUTH, col 0 = WEST):
//   canopy_voxels.bin   uint8 [row][col][bin]  non-ground returns per 1-ft bin
//                       of height above the DTM, bins 0..NB-1, saturating at 255
//   canopy_ground.bin   uint8 [row][col]       ground (class 2) returns per cell
//   canopy_voxels_meta.json
//
// Run from elevation/:  node canopy_voxels.mjs
import { readFileSync, writeFileSync } from 'fs';
import lp from 'laz-perf';
const createLazPerf = lp.createLazPerf || lp.create;

const FT = 3.280839895, CELL = 0.5;
const GX0 = 548000, GY0 = 3744000, GNC = 2000, GNR = 2000;   // terrain_fine georef
// Window: the lot plus 130 m of casters. terrain_fine stops at N 3744000, which
// is 135 m south of the lot's back line — farther than a winter shadow reaches
// from anything this neighbourhood grows.
const C0 = +(process.env.CV_C0 ?? 1040), C1 = +(process.env.CV_C1 ?? 1620);
const R0 = +(process.env.CV_R0 ?? 0),    R1 = +(process.env.CV_R1 ?? 680);
const W = C1 - C0, H = R1 - R0, NB = 96;
const LAZ = process.env.CV_LAZ ?? 'raw/LPC_SaltonSea_2021_11SNT480440.laz';

const tf = readFileSync('terrain_fine.bin');
const dtm = new Float32Array(tf.buffer, tf.byteOffset + GNC * GNR * 4, GNC * GNR);

const vox = new Uint8Array(W * H * NB);
const gnd = new Uint8Array(W * H);
const classCount = new Map();

const buf = readFileSync(LAZ);
const dv = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
const xs = dv.getFloat64(131, true), ys = dv.getFloat64(139, true), zs = dv.getFloat64(147, true);
const xo = dv.getFloat64(155, true), yo = dv.getFloat64(163, true), zo = dv.getFloat64(171, true);
const mod = await createLazPerf();
const z = new mod.LASZip();
const fptr = mod._malloc(buf.length); mod.HEAPU8.set(buf, fptr); z.open(fptr, buf.length);
const count = z.getCount(), ptLen = z.getPointLength();
const fmt = z.getPointFormat() & 0x3f;
const classOff = fmt >= 6 ? 16 : 15, classMask = fmt >= 6 ? 0xff : 0x1f;
const dest = mod._malloc(ptLen); const i32 = mod.HEAP32, u8 = mod.HEAPU8; const di = dest >> 2;

let kept = 0;
for (let i = 0; i < count; i++) {
  z.getPoint(dest);
  const e = i32[di] * xs + xo, n = i32[di + 1] * ys + yo;
  const col = Math.round((e - GX0) / CELL) - C0, row = Math.round((n - GY0) / CELL) - R0;
  if (col < 0 || col >= W || row < 0 || row >= H) continue;
  const cls = u8[dest + classOff] & classMask;
  classCount.set(cls, (classCount.get(cls) ?? 0) + 1);
  if (cls === 7 || cls === 18) continue;                       // low / high noise
  const cell = row * W + col;
  if (cls === 2) { if (gnd[cell] < 255) gnd[cell]++; continue; }
  const h = (i32[di + 2] * zs + zo) * FT - dtm[(row + R0) * GNC + (col + C0)];
  if (h < 1) continue;                                          // ground clutter
  const b = Math.min(NB - 1, Math.floor(h));
  const k = cell * NB + b;
  if (vox[k] < 255) vox[k]++;
  kept++;
}

writeFileSync('canopy_voxels.bin', vox);
writeFileSync('canopy_ground.bin', gnd);
const meta = {
  note: 'Non-ground LiDAR returns per 1-ft height bin above the terrain_fine DTM, per 0.5 m cell. Grid row0=SOUTH, col0=WEST.',
  source: LAZ.replace(/^raw\//, '') + ' (USGS 3DEP, CA_SaltonSea 2021)',
  grid: { x0: GX0, y0: GY0, cellM: CELL, c0: C0, c1: C1, r0: R0, r1: R1, w: W, h: H },
  bins: { count: NB, ft: 1, from: 0 },
  points: { inWindow: [...classCount.values()].reduce((a, b) => a + b, 0), nonGroundKept: kept, pointFormat: fmt },
  classes: Object.fromEntries([...classCount.entries()].sort((a, b) => a[0] - b[0])),
  bin: { voxels: 'canopy_voxels.bin uint8 [row][col][bin]', ground: 'canopy_ground.bin uint8 [row][col]' },
};
writeFileSync('canopy_voxels_meta.json', JSON.stringify(meta, null, 1));
console.log(`${count.toLocaleString()} points read · ${meta.points.inWindow.toLocaleString()} in window · ` +
            `${kept.toLocaleString()} non-ground kept · classes ${JSON.stringify(meta.classes)}`);
