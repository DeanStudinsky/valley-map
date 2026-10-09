// fetch_ept.mjs — pull 3DEP LiDAR points for a UTM box out of USGS's public
// Entwine Point Tile (EPT) copy of the same 2021 flight, for ground the local
// LAZ tiles do not cover.
//
// Why this exists: the four stop-controlled intersections on Calada / Tachevah
// east of x = +1114 ft sit in tile 11SNT490440, and the per-tile LAZ server
// (rockyweb.usgs.gov) refuses connections from here. The same project —
// CA_SaltonSea_EarthMRI_3_D21, the flight every local tile comes from — is
// published as EPT on s3://usgs-lidar-public, reprojected to Web Mercator
// (EPSG:3857). This script walks the octree, downloads only the nodes whose
// footprint overlaps the box, inverts the projection back to UTM 11N and
// writes a flat point list.
//
// The projection round trip is checked, not assumed: run it over a box that
// overlaps a local tile and make_study.mjs reports the DTM offset between the
// two sources in the overlap (it must be ~0 in all three axes).
//
// Output: raw/ept_<name>.bin — records of
//   Float32 dE, Float32 dN (metres from the box's SW corner), Float32 Z (m),
//   Uint8 classification, Uint8 (returnNumber | numberOfReturns << 4)
// plus raw/ept_<name>.json describing the box.
//
// Run from elevation/:
//   EPT_BOX=548950,3743550,549400,3744950 EPT_NAME=east node fetch_ept.mjs
import { writeFileSync, existsSync, mkdirSync, readFileSync } from 'fs';
import lp from 'laz-perf';
import { toLonLat, toUTM } from './utm11.mjs';
const createLazPerf = lp.createLazPerf || lp.create;

const ROOT = 'https://s3-us-west-2.amazonaws.com/usgs-lidar-public/CA_SaltonSea_EarthMRI_3_D21/';
const [E0, N0, E1, N1] = (process.env.EPT_BOX ?? '548950,3743550,549400,3744950').split(',').map(Number);
const NAME = process.env.EPT_NAME ?? 'east';
const CACHE = 'raw/ept_cache/';
mkdirSync(CACHE, { recursive: true });

const R = 6378137;
const merc = (lon, lat) => [R * lon * Math.PI / 180,
                            R * Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360))];
const unmerc = (x, y) => [x / R * 180 / Math.PI,
                          (2 * Math.atan(Math.exp(y / R)) - Math.PI / 2) * 180 / Math.PI];

// Box in 3857: project all four corners, take the hull, pad 5 m.
let mx0 = Infinity, my0 = Infinity, mx1 = -Infinity, my1 = -Infinity;
for (const [e, n] of [[E0, N0], [E1, N0], [E0, N1], [E1, N1]]) {
  const [x, y] = merc(...toLonLat(e, n));
  mx0 = Math.min(mx0, x); my0 = Math.min(my0, y); mx1 = Math.max(mx1, x); my1 = Math.max(my1, y);
}
mx0 -= 5; my0 -= 5; mx1 += 5; my1 += 5;

async function get(url, binary) {
  for (let a = 0; a < 5; a++) {
    try {
      const r = await fetch(url);
      if (!r.ok) throw new Error(`${r.status} ${url}`);
      return binary ? Buffer.from(await r.arrayBuffer()) : await r.json();
    } catch (e) {
      if (a === 4) throw e;
      await new Promise(res => setTimeout(res, 2000 * (a + 1)));
    }
  }
}

const ept = await get(ROOT + 'ept.json');
const [bx0, by0, , bx1] = ept.bounds;
const W = bx1 - bx0;

// Walk the hierarchy. A count of -1 means "this subtree lives in its own file".
const nodes = [];
async function walk(file) {
  const h = await get(ROOT + 'ept-hierarchy/' + file + '.json');
  for (const [key, count] of Object.entries(h)) {
    const [d, x, y] = key.split('-').map(Number);
    const s = W / 2 ** d;
    const nx0 = bx0 + x * s, ny0 = by0 + y * s;
    if (nx0 > mx1 || nx0 + s < mx0 || ny0 > my1 || ny0 + s < my0) continue;
    if (count === -1) { if (key !== file) await walk(key); }
    else if (count > 0) nodes.push(key);
  }
}
await walk('0-0-0-0');
console.log(`${nodes.length} EPT nodes overlap E[${E0}..${E1}] N[${N0}..${N1}]`);

// Download (cached, 8 at a time).
let done = 0;
const queue = [...nodes];
await Promise.all(Array.from({ length: 8 }, async () => {
  while (queue.length) {
    const key = queue.shift();
    const path = CACHE + key + '.laz';
    if (!existsSync(path)) writeFileSync(path, await get(ROOT + 'ept-data/' + key + '.laz', true));
    if (++done % 20 === 0) console.log(`  ${done}/${nodes.length}`);
  }
}));

// Decode, unproject, clip.
const mod = await createLazPerf();
const out = [];
let total = 0, kept = 0;
const REC = 14;
let buf = Buffer.alloc(REC << 20), head = 0;
const flush = () => { out.push(buf.subarray(0, head)); buf = Buffer.alloc(REC << 20); head = 0; };
for (const key of nodes) {
  const lz = readFileSync(CACHE + key + '.laz');
  const dv = new DataView(lz.buffer, lz.byteOffset, lz.byteLength);
  const xs = dv.getFloat64(131, true), ys = dv.getFloat64(139, true), zs = dv.getFloat64(147, true);
  const xo = dv.getFloat64(155, true), yo = dv.getFloat64(163, true), zo = dv.getFloat64(171, true);
  const z = new mod.LASZip();
  const fptr = mod._malloc(lz.length); mod.HEAPU8.set(lz, fptr); z.open(fptr, lz.length);
  const count = z.getCount(), ptLen = z.getPointLength();
  const fmt = z.getPointFormat() & 0x3f;
  const classOff = fmt >= 6 ? 16 : 15;
  const dest = mod._malloc(ptLen); const di = dest >> 2;
  for (let i = 0; i < count; i++) {
    z.getPoint(dest);
    const i32 = mod.HEAP32, u8 = mod.HEAPU8;
    const x = i32[di] * xs + xo, y = i32[di + 1] * ys + yo;
    total++;
    if (x < mx0 || x > mx1 || y < my0 || y > my1) continue;
    const [e, n] = toUTM(...unmerc(x, y));
    if (e < E0 || e >= E1 || n < N0 || n >= N1) continue;
    const rb = u8[dest + 14];
    const ret = fmt >= 6 ? (rb & 0x0f) | (((rb >> 4) & 0x0f) << 4)
                         : (rb & 0x07) | (((rb >> 3) & 0x07) << 4);
    if (head + REC > buf.length) flush();
    buf.writeFloatLE(e - E0, head); buf.writeFloatLE(n - N0, head + 4);
    buf.writeFloatLE(i32[di + 2] * zs + zo, head + 8);
    buf[head + 12] = u8[dest + classOff] & (fmt >= 6 ? 0xff : 0x1f);
    buf[head + 13] = ret;
    head += REC; kept++;
  }
  z.delete(); mod._free(fptr); mod._free(dest);
}
flush();
writeFileSync(`raw/ept_${NAME}.bin`, Buffer.concat(out));
writeFileSync(`raw/ept_${NAME}.json`, JSON.stringify({
  source: ROOT, project: 'CA_SaltonSea_EarthMRI_3_D21 (USGS 3DEP, flown 2021)',
  srsIn: 'EPSG:3857', srsOut: 'UTM 11N metres (EPSG:26911 grid; no datum shift applied)',
  box: { E0, N0, E1, N1 }, nodes: nodes.length, points: kept,
  record: 'Float32 dE, Float32 dN, Float32 Z(m), Uint8 class, Uint8 ret|nret<<4',
}, null, 2));
console.log(`decoded ${total.toLocaleString()} points, kept ${kept.toLocaleString()} -> raw/ept_${NAME}.bin`);
