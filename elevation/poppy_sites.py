"""poppy_sites.py — where on the 68075 Alva Ct lot California poppies get enough sun.

Eschscholzia californica is direct-sown here in Oct–Nov, grows through the
winter and blooms Feb–Apr. It wants full sun (6 h+ of direct light) on bare,
well-drained ground, and it does not transplant — so the only real decision is
WHERE the seed goes. That is a winter-sun question, and this script answers it
from measurement rather than by eye:

  1. Mountain horizon   San Jacinto (3 285 m, 19 km WSW) takes the low winter
                        sun early. Horizon per azimuth is marched across the
                        10 m NED mosaic built by the sibling Coachella Valley 3D
                        project (socal_dem_utm11n.tif), with earth curvature.
  2. Local shade        The house, walls, fences and trees, from the 2021 3DEP
                        LiDAR first-return surface (terrain_fine.bin DSM, 0.5 m).
                        Each cell ray-marches toward the sun for every 10 min of
                        six representative days, Oct 15 → Mar 15.
  3. What is plantable  Inside the lot (Riverside County parcel polygon) or the
                        front parkway, not under a roof / canopy / wall (LiDAR
                        nDSM), not already green (NAIP NDVI), and not hard
                        against a structure.

Outputs (scene frame: +X east, +Z SOUTH, feet, address = (0,0), y=0 at BASE_FT):
  poppy_sites.json   house, lot ring, ranked beds, sun summary, provenance
  poppy_sun.png      season sun-hours overlay, north-up, georef in the json
  ../renders/poppy/site_plan.png, sun_path.png   2D figures

Run from elevation/:   PYTHONPATH="<CV3D>/pylibs" python poppy_sites.py
"""
import json
import math
import os
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
OUT_FIG = HERE.parent / "renders" / "poppy"
DEM = os.environ.get("ALVA_DEM", r"C:/Users/dmcge/Desktop/Coachella Valley 3D/socal_dem_utm11n.tif")

FT = 3.280839895
BASE_FT = 399.57349381574863
ADDR_E, ADDR_N = 548660.3, 3744180.9
ADDR_LONLAT = (-116.474082, 33.836760)
APN = "675212027"          # Census geocoder puts 68075 on side R of TIGER 194765113 = south side

# terrain_fine / naip_fine georef: 0.5 m, 2000², row 0 = SOUTH, col 0 = WEST
X0, Y0, CELL, NC, NR = 548000.0, 3744000.0, 0.5, 2000, 2000
CELL_FT = CELL * FT

# Six days that bracket the season; the growing-season figure is Nov–Feb.
DAYS = [("Oct 15", "sow"), ("Nov 15", "germinate"), ("Dec 21", "solstice"),
        ("Jan 15", "grow"), ("Feb 15", "bud"), ("Mar 15", "bloom")]
SEASON = ["Nov 15", "Dec 21", "Jan 15", "Feb 15", "Mar 15"]   # germination through first bloom
YEAR = {"Oct": 2026, "Nov": 2026, "Dec": 2026, "Jan": 2027, "Feb": 2027, "Mar": 2027}
STEP_MIN = 10

NDSM_STRUCT_FT = 2.0     # anything this far above bare earth is roof, canopy, wall or fence
NDSM_CASTER_FT = 1.0     # below this the DSM is surface noise (p99 over bare dirt here is 1.05 ft),
                         # and letting it cast makes low winter sun shade bare ground falsely
NDVI_GREEN = 0.20        # naip_analyze.mjs's threshold for vegetation
SOIL_WARM = 9.0          # NAIP R−B: this yard's bare dirt measures +16.5, the driveway +4.6,
                         # the parkway −0.2..+1.5, asphalt −5. Grey can be gravel, rock mulch or
                         # concrete — NAIP cannot separate those — so it is flagged, not ranked first.
PLANT_H_FT = 0.5         # poppy foliage height the ray starts from
FULL_SUN_H = 6.0
MIN_BED_SQFT = 15.0
MAX_MARCH_M = 120.0


# ── projection: UTM 11N <-> lon/lat (GRS80, same series as utm11.mjs) ─────────
_a, _f = 6378137.0, 1 / 298.257222101
_e2 = _f * (2 - _f); _ep2 = _e2 / (1 - _e2); _k0 = 0.9996
_M0 = [1 - _e2 / 4 - 3 * _e2**2 / 64 - 5 * _e2**3 / 256,
       3 * _e2 / 8 + 3 * _e2**2 / 32 + 45 * _e2**3 / 1024,
       15 * _e2**2 / 256 + 45 * _e2**3 / 1024, 35 * _e2**3 / 3072]
_LON0 = math.radians(-117)


def to_lonlat(E, N):
    x, y = E - 500000, N / _k0
    e1 = (1 - math.sqrt(1 - _e2)) / (1 + math.sqrt(1 - _e2))
    mu = y / (_a * _M0[0])
    p1 = (mu + (3 * e1 / 2 - 27 * e1**3 / 32) * math.sin(2 * mu)
          + (21 * e1**2 / 16 - 55 * e1**4 / 32) * math.sin(4 * mu)
          + (151 * e1**3 / 96) * math.sin(6 * mu) + (1097 * e1**4 / 512) * math.sin(8 * mu))
    s1, c1, t1 = math.sin(p1), math.cos(p1), math.tan(p1)
    C1, T1 = _ep2 * c1 * c1, t1 * t1
    N1 = _a / math.sqrt(1 - _e2 * s1 * s1)
    R1 = _a * (1 - _e2) / (1 - _e2 * s1 * s1) ** 1.5
    D = x / (N1 * _k0)
    lat = p1 - (N1 * t1 / R1) * (D**2 / 2 - (5 + 3 * T1 + 10 * C1 - 4 * C1**2 - 9 * _ep2) * D**4 / 24
                                 + (61 + 90 * T1 + 298 * C1 + 45 * T1**2 - 252 * _ep2 - 3 * C1**2) * D**6 / 720)
    lon = _LON0 + (D - (1 + 2 * T1 + C1) * D**3 / 6
                   + (5 - 2 * C1 + 28 * T1 - 3 * C1**2 + 8 * _ep2 + 24 * T1**2) * D**5 / 120) / c1
    return math.degrees(lon), math.degrees(lat)


_chk = to_lonlat(ADDR_E, ADDR_N)
assert abs(_chk[0] - ADDR_LONLAT[0]) < 2e-5 and abs(_chk[1] - ADDR_LONLAT[1]) < 2e-5, _chk

scene_x = lambda E: (E - ADDR_E) * FT
scene_z = lambda N: (ADDR_N - N) * FT
cell_E = lambda col: X0 + col * CELL
cell_N = lambda row: Y0 + row * CELL


def scene_to_lonlat(x, z):
    return to_lonlat(ADDR_E + x / FT, ADDR_N - z / FT)


# ── sun position (NOAA) ───────────────────────────────────────────────────────
def sun_pos(t_utc, lat, lon):
    jd = t_utc.timestamp() / 86400 + 2440587.5
    jc = (jd - 2451545) / 36525
    L0 = (280.46646 + jc * (36000.76983 + jc * 0.0003032)) % 360
    M = 357.52911 + jc * (35999.05029 - 0.0001537 * jc)
    e = 0.016708634 - jc * (0.000042037 + 0.0000001267 * jc)
    r = math.radians
    C = (math.sin(r(M)) * (1.914602 - jc * (0.004817 + 0.000014 * jc))
         + math.sin(r(2 * M)) * (0.019993 - 0.000101 * jc) + math.sin(r(3 * M)) * 0.000289)
    om = 125.04 - 1934.136 * jc
    lam = L0 + C - 0.00569 - 0.00478 * math.sin(r(om))
    eps0 = 23 + (26 + (21.448 - jc * (46.815 + jc * (0.00059 - jc * 0.001813))) / 60) / 60
    eps = eps0 + 0.00256 * math.cos(r(om))
    decl = math.asin(math.sin(r(eps)) * math.sin(r(lam)))
    y = math.tan(r(eps / 2)) ** 2
    eqt = 4 * math.degrees(y * math.sin(2 * r(L0)) - 2 * e * math.sin(r(M))
                           + 4 * e * y * math.sin(r(M)) * math.cos(2 * r(L0))
                           - 0.5 * y * y * math.sin(4 * r(L0)) - 1.25 * e * e * math.sin(2 * r(M)))
    mins = t_utc.hour * 60 + t_utc.minute + t_utc.second / 60
    ha = ((mins + eqt + 4 * lon) % 1440) / 4 - 180
    phi = r(lat)
    cz = math.sin(phi) * math.sin(decl) + math.cos(phi) * math.cos(decl) * math.cos(r(ha))
    zen = math.acos(max(-1, min(1, cz)))
    alt = 90 - math.degrees(zen)
    # Bennett refraction, only matters within a few degrees of the horizon
    if alt > -1:
        alt += 1.02 / math.tan(r(alt + 10.3 / (alt + 5.11))) / 60
    az_c = (math.sin(phi) * math.cos(zen) - math.sin(decl)) / (math.cos(phi) * math.sin(zen))
    az0 = math.degrees(math.acos(max(-1, min(1, az_c))))
    az = (az0 + 180) % 360 if ha > 0 else (540 - az0) % 360
    return az, alt


def day_samples(label):
    mon, d = label.split()
    base = datetime(YEAR[mon], datetime.strptime(mon, "%b").month, int(d), 13, 0, tzinfo=timezone.utc)  # 05:00 PST
    out = []
    for k in range(0, 15 * 60, STEP_MIN):
        t = base + timedelta(minutes=k)
        az, alt = sun_pos(t, ADDR_LONLAT[1], ADDR_LONLAT[0])
        out.append((t - timedelta(hours=8), az, alt))   # keep local PST for reporting
    return out


# ── 1. mountain horizon from the 10 m NED mosaic ──────────────────────────────
def mountain_horizon(site_E, site_N, site_z_m):
    import rasterio
    from rasterio.windows import from_bounds
    R = 45000.0
    with rasterio.open(DEM) as ds:
        b = ds.bounds
        w = from_bounds(max(b.left, site_E - R), max(b.bottom, site_N - R),
                        min(b.right, site_E + R), min(b.top, site_N + R), ds.transform)
        dec = 3                                             # 30 m posting is plenty for a 19 km ridge
        h, wd = int(w.height // dec), int(w.width // dec)
        arr = ds.read(1, window=w, out_shape=(h, wd)).astype(np.float64)
        wt = ds.window_transform(w)
        px = wt.a * dec; py = wt.e * dec                    # py negative: row 0 = north
        ox, oy = wt.c, wt.f
        arr[arr < -1000] = np.nan
    az = np.arange(0, 360, 0.5)
    d = np.arange(150, R, 30.0)
    A, D = np.meshgrid(np.radians(az), d, indexing="ij")
    E = site_E + D * np.sin(A); N = site_N + D * np.cos(A)
    c = ((E - ox) / px).astype(int); r = ((N - oy) / py).astype(int)
    ok = (c >= 0) & (c < wd) & (r >= 0) & (r < h)
    z = np.full(E.shape, np.nan); z[ok] = arr[r[ok], c[ok]]
    drop = D**2 / (2 * 6371000.0) * (1 - 0.13)               # curvature less standard refraction
    ang = np.degrees(np.arctan2(z - site_z_m - drop, D))
    hz = np.nanmax(np.where(np.isnan(ang), -90, ang), axis=1)
    peak_d = d[np.nanargmax(np.where(np.isnan(ang), -90, ang), axis=1)]
    return az, hz, peak_d


def horizon_at(az_tab, hz_tab, az):
    return float(np.interp(az % 360, np.append(az_tab, 360), np.append(hz_tab, hz_tab[0])))


# ── load rasters ──────────────────────────────────────────────────────────────
tf = np.fromfile(HERE / "terrain_fine.bin", dtype="<f4")
DSM = tf[:NC * NR].reshape(NR, NC); DTM = tf[NC * NR:].reshape(NR, NC)
naip = np.fromfile(HERE / "naip_fine.bin", dtype=np.uint8).reshape(NR, NC, 4)
Rb = naip[..., 0].astype(np.float32); NIR = naip[..., 3].astype(np.float32)
NDVI = (NIR - Rb) / np.maximum(NIR + Rb, 1)
WARM = Rb - naip[..., 2].astype(np.float32)
NDSM = DSM - DTM
CASTER = np.where(NDSM >= NDSM_CASTER_FT, DSM, DTM)

parcels = json.load(open(HERE / "raw" / "parcels" / "parcels_raw.json"))
assert parcels["spatialReference"]["wkid"] == 26911
lot_ring = next(f["geometry"]["rings"][0] for f in parcels["features"] if f["attributes"]["APN"] == APN)
lot_sqft = next(f["attributes"]["SHAPE.STArea()"] for f in parcels["features"] if f["attributes"]["APN"] == APN)

houses = json.load(open(HERE / "houses.json"))
home = houses["houses"][0]                       # naip_analyze.mjs orders nearest-address first
hb = home["bboxLocalFt"]                         # {E, N} with N north-positive -> scene z = -N
house_x0, house_x1 = hb["E0"], hb["E1"]
house_z0, house_z1 = -hb["N1"], -hb["N0"]
house_x, house_z = home["centerLocalFt"]["E"], -home["centerLocalFt"]["N"]

terrain_meta = json.load(open(HERE / "terrain_meta.json"))
road_cl = terrain_meta["road"]["centerlineLocalFt"]     # already world [x, z]
road_half = terrain_meta["road"]["widthFt"] / 2


def pip(px, py, ring):
    inside = np.zeros(px.shape, bool)
    for (x1, y1), (x2, y2) in zip(ring[:-1], ring[1:]):
        cross = (y1 > py) != (y2 > py)
        xi = x1 + (py - y1) * (x2 - x1) / ((y2 - y1) if y2 != y1 else 1e-12)
        inside ^= cross & (px < xi)
    return inside


# ── analysis window: the lot, its parkway, and every caster within reach ──────
ring = np.array(lot_ring)
c_lo = int((ring[:, 0].min() - X0) / CELL) - 2; c_hi = int((ring[:, 0].max() - X0) / CELL) + 3
r_lo = int((ring[:, 1].min() - Y0) / CELL) - 2; r_hi = int((ring[:, 1].max() - Y0) / CELL) + 3
lot_north_N = ring[:, 1].max()
# Parkway: from the lot's front line north to the curb — the road edge off the
# surveyed centreline (z ≈ -21) plus a 1 ft curb.
cl_z = np.interp((scene_x(ring[:, 0].min()) + scene_x(ring[:, 0].max())) / 2,
                 [p[0] for p in road_cl], [p[1] for p in road_cl])
curb_N = ADDR_N - (cl_z + road_half + 1.0) / FT
r_hi = max(r_hi, int((curb_N - Y0) / CELL) + 2)

rows = np.arange(r_lo, r_hi); cols = np.arange(c_lo, c_hi)
CC, RR = np.meshgrid(cols, rows)
EE, NN = cell_E(CC), cell_N(RR)
in_lot = pip(EE, NN, lot_ring)
in_park = (~in_lot) & (EE >= ring[:, 0].min()) & (EE <= ring[:, 0].max()) & (NN > lot_north_N - 0.25) & (NN <= curb_N)
region = in_lot | in_park

sub = (slice(r_lo, r_hi), slice(c_lo, c_hi))
ndsm, ndvi, dtm, warm = NDSM[sub], NDVI[sub], DTM[sub], WARM[sub]
struct = ndsm > NDSM_STRUCT_FT
near_struct = struct.copy()                          # one-cell setback: foundations, drip lines, wall footings
for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
    near_struct |= np.roll(np.roll(struct, dr, 0), dc, 1)
green = ndvi > NDVI_GREEN
plantable = region & ~near_struct & ~green
soil = warm >= SOIL_WARM

# ── 2. horizon + local shade ──────────────────────────────────────────────────
site_z_m = float(DTM[int((ADDR_N - Y0) / CELL), int((ADDR_E - X0) / CELL)]) / FT
print(f"lot {APN}: {lot_sqft:.0f} sqft, {in_lot.sum()} cells; parkway {in_park.sum()} cells; "
      f"plantable {plantable.sum()} cells ({plantable.sum() * CELL_FT**2:.0f} sqft)")
print("horizon: marching the NED mosaic …")
hz_az, hz_deg, hz_dist = mountain_horizon(ADDR_E, ADDR_N, site_z_m + 1.5)

mr0, mr1 = max(0, r_lo - int(MAX_MARCH_M / CELL)), min(NR, r_hi + int(MAX_MARCH_M / CELL))
mc0, mc1 = max(0, c_lo - int(MAX_MARCH_M / CELL)), min(NC, c_hi + int(MAX_MARCH_M / CELL))
W = CASTER[mr0:mr1, mc0:mc1]
wmax = float(np.nanmax(W))
ri, ci = np.nonzero(region)
gr, gc = ri + (r_lo - mr0), ci + (c_lo - mc0)        # region cells in march-window indices
z0 = dtm[ri, ci] + PLANT_H_FT

sun_h = {}            # day -> hours per region cell
open_sky_h, mtn_lost_h, first_last = {}, {}, {}
for label, _ in DAYS:
    lit_minutes = np.zeros(len(ri))
    open_min = mtn_min = 0
    sunrise = sunset = None
    for t, az, alt in day_samples(label):
        if alt <= 0:
            continue
        open_min += STEP_MIN
        if alt <= horizon_at(hz_az, hz_deg, az):
            mtn_min += STEP_MIN
            continue
        sunrise = sunrise or t; sunset = t
        tan_a = math.tan(math.radians(alt))
        dcol, drow = math.sin(math.radians(az)), math.cos(math.radians(az))
        n_steps = int(min(MAX_MARCH_M / CELL, math.ceil((wmax - z0.min()) / (CELL_FT * tan_a)) + 1))
        shaded = np.zeros(len(ri), bool)
        for s in range(1, n_steps + 1):
            rr = gr + int(round(drow * s)); cc = gc + int(round(dcol * s))
            ok = (rr >= 0) & (rr < W.shape[0]) & (cc >= 0) & (cc < W.shape[1])
            hit = np.zeros(len(ri), bool)
            hit[ok] = W[rr[ok], cc[ok]] > z0[ok] + s * CELL_FT * tan_a
            shaded |= hit
        lit_minutes[~shaded] += STEP_MIN
    sun_h[label] = lit_minutes / 60
    open_sky_h[label] = open_min / 60; mtn_lost_h[label] = mtn_min / 60
    first_last[label] = (sunrise.strftime("%H:%M") if sunrise else None, sunset.strftime("%H:%M") if sunset else None)
    print(f"  {label}: daylight {open_min / 60:.1f} h, mountains take {mtn_min / 60:.1f} h, "
          f"direct sun {sunrise:%H:%M}–{sunset:%H:%M} PST; lot cells median {np.median(sun_h[label][plantable[ri, ci]]):.1f} h")

season = np.mean([sun_h[d] for d in SEASON], axis=0)
SEASON_G = np.full(region.shape, np.nan); SEASON_G[ri, ci] = season
DEC_G = np.full(region.shape, np.nan); DEC_G[ri, ci] = sun_h["Dec 21"]
best_possible = float(np.mean([open_sky_h[d] - mtn_lost_h[d] for d in SEASON]))

# ── 3. beds: connected runs of plantable, sunny ground ────────────────────────
def components(mask):
    lab = np.zeros(mask.shape, bool); comps = []
    for r0, c0 in zip(*np.nonzero(mask)):
        if lab[r0, c0]:
            continue
        q = deque([(r0, c0)]); lab[r0, c0] = True; cells = []
        while q:
            r, c = q.popleft(); cells.append((r, c))
            for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                a, b = r + dr, c + dc
                if 0 <= a < mask.shape[0] and 0 <= b < mask.shape[1] and mask[a, b] and not lab[a, b]:
                    lab[a, b] = True; q.append((a, b))
        comps.append(cells)
    return comps


# Bare soil is what poppy seed needs, so it is ranked on its own terms: 6 h if
# any real patch of soil reaches it, otherwise the sunniest 15% of the soil —
# the best this yard has, labelled as short of full sun rather than hidden.
soil_ok = plantable & soil
thr = FULL_SUN_H
if (soil_ok & (SEASON_G >= thr)).sum() * CELL_FT**2 < 60:
    thr = float(np.nanpercentile(SEASON_G[soil_ok], 85))
cands = [(c, "soil") for c in components(soil_ok & (SEASON_G >= thr))]
# Grey ground that does reach full sun is still worth showing — gravel can be
# raked back to soil — but it ranks after soil and says why.
cands += [(c, "grey") for c in components(plantable & ~soil & (SEASON_G >= FULL_SUN_H))]
SURFACE = {"soil": "bare soil (tan in NAIP)",
           "grey": "grey surface: gravel / rock mulch or concrete (NAIP cannot tell which). "
                   "Rake gravel back to soil before sowing; skip it if it is concrete."}


def where(x, z, parkway):
    if parkway:
        return "front parkway (city right-of-way between the curb and your lot line)"
    if z < house_z0:
        return "front yard"
    if z > house_z1:
        return "back yard"
    return "west side yard" if x < house_x else "east side yard"


beds = []
for cells, surf in cands:
    area = len(cells) * CELL_FT**2
    if area < MIN_BED_SQFT:
        continue
    rr = np.array([c[0] for c in cells]); cc = np.array([c[1] for c in cells])
    E = cell_E(cc + c_lo); N = cell_N(rr + r_lo)
    x, z = scene_x(E), scene_z(N)
    # anchor on the sunniest cell nearest the centroid, so a C-shaped bed's pin lands on the bed
    s = SEASON_G[rr, cc]
    best = np.argmin((x - x.mean())**2 + (z - z.mean())**2 - 4.0 * (s - s.max()))
    park = bool(in_park[rr, cc].mean() > 0.5)
    lon, lat = scene_to_lonlat(float(x[best]), float(z[best]))
    beds.append(dict(
        areaSqft=round(area, 1),
        seasonSunH=round(float(s.mean()), 2), seasonSunMinH=round(float(s.min()), 2),
        dec21SunH=round(float(DEC_G[rr, cc].mean()), 2),
        bySunDay={d: round(float(np.mean([sun_h[d][np.flatnonzero((ri == r) & (ci == c))[0]] for r, c in zip(rr, cc)])), 2)
                  for d, _ in DAYS},
        anchor={"x": round(float(x[best]), 2), "z": round(float(z[best]), 2), "lon": round(lon, 7), "lat": round(lat, 7)},
        extentFt=[round(float(x.max() - x.min()) + CELL_FT, 1), round(float(z.max() - z.min()) + CELL_FT, 1)],
        where=where(float(x.mean()), float(z.mean()), park),
        surface=SURFACE[surf], surfaceKind=surf,
        fullSun=bool(s.mean() >= FULL_SUN_H),
        meanNDVI=round(float(ndvi[rr, cc].mean()), 3),
        meanWarmth=round(float(warm[rr, cc].mean()), 1),
        cells=[[int(c + c_lo), int(r + r_lo)] for r, c in zip(rr, cc)],
    ))
# Rank: soil before grey, then sun (it is the requirement), then room to sow a real patch.
beds.sort(key=lambda b: (b["surfaceKind"] != "soil", -round(b["seasonSunH"] * 4) / 4, -b["areaSqft"]))
beds = [b for b in beds if b["surfaceKind"] == "soil"][:4] + [b for b in beds if b["surfaceKind"] == "grey"][:2]
for i, b in enumerate(beds):
    b["id"] = f"P{i + 1}"
    print(f"  {b['id']}: {b['areaSqft']:.0f} sqft {b['where']} [{b['surfaceKind']}], season {b['seasonSunH']:.1f} h "
          f"(Dec 21 {b['dec21SunH']:.1f} h, Mar 15 {b['bySunDay']['Mar 15']:.1f} h) @ {b['anchor']['lat']:.6f},{b['anchor']['lon']:.6f}")
print(f"soil threshold used: {thr:.2f} h; soil-plantable season sun p50 {np.nanmedian(SEASON_G[soil_ok]):.1f} "
      f"p90 {np.nanpercentile(SEASON_G[soil_ok], 90):.1f} max {np.nanmax(SEASON_G[soil_ok]):.1f} h")

# ── outputs ───────────────────────────────────────────────────────────────────
x_w, x_e = scene_x(cell_E(c_lo)), scene_x(cell_E(c_hi - 1))
z_n, z_s = scene_z(cell_N(r_hi - 1)), scene_z(cell_N(r_lo))

STOPS = [(0, (49, 54, 149)), (2, (69, 117, 180)), (4, (116, 173, 209)), (5, (171, 217, 233)),
         (6, (254, 224, 144)), (7, (253, 174, 97)), (8, (244, 109, 67))]


def ramp(h):
    if not np.isfinite(h):
        return (0, 0, 0)
    for (h0, c0), (h1, c1) in zip(STOPS[:-1], STOPS[1:]):
        if h <= h1:
            t = max(0.0, (h - h0) / (h1 - h0))
            return tuple(int(a + (b - a) * t) for a, b in zip(c0, c1))
    return STOPS[-1][1]


H, Wd = region.shape
ov = np.zeros((H, Wd, 4), np.uint8)
for r in range(H):
    for c in range(Wd):
        if region[r, c] and not near_struct[r, c]:
            ov[r, c, :3] = ramp(SEASON_G[r, c])
            ov[r, c, 3] = 120 if green[r, c] else 205
Image.fromarray(ov[::-1]).save(HERE / "poppy_sun.png")          # north-up

lot_scene = [[round(scene_x(e), 2), round(scene_z(n), 2)] for e, n in lot_ring]
park_scene = [[round(x_, 2), round(z_, 2)] for x_, z_ in [
    (scene_x(ring[:, 0].min()), scene_z(curb_N)), (scene_x(ring[:, 0].max()), scene_z(curb_N)),
    (scene_x(ring[:, 0].max()), scene_z(lot_north_N)), (scene_x(ring[:, 0].min()), scene_z(lot_north_N))]]
hlon, hlat = scene_to_lonlat(house_x, house_z)

out = {
    "note": "Poppy planting analysis for 68075 Alva Ct. Scene frame: +X east, +Z SOUTH, feet, address=(0,0), y=0 at BASE_FT. lon/lat NAD83 (~1 m from WGS84 here).",
    "generatedBy": "elevation/poppy_sites.py",
    "plant": {"name": "California poppy", "taxon": "Eschscholzia californica",
              "needs": "full sun (6 h+ direct), bare well-drained ground, direct-sown Oct–Nov, blooms Feb–Apr in the low desert"},
    "house": {"label": "Home — 68075 Alva Ct", "apn": APN, "lotSqft": round(lot_sqft),
              "x": house_x, "z": house_z, "lon": round(hlon, 7), "lat": round(hlat, 7),
              "roofSqft": home["footprint_sqft"], "heightFt": home["heightFt"],
              "geocoder": {"lon": ADDR_LONLAT[0], "lat": ADDR_LONLAT[1],
                           "note": "Census TIGER interpolation; lands in the street right-of-way, side R = south"}},
    "lotRing": lot_scene, "parkway": park_scene,
    "sun": {
        "days": [{"day": d, "stage": s, "daylightH": open_sky_h[d], "lostToMountainsH": mtn_lost_h[d],
                  "directSunPST": first_last[d],
                  "plantableMedianH": round(float(np.median(sun_h[d][plantable[ri, ci]])), 2)} for d, s in DAYS],
        "seasonDays": SEASON, "bestPossibleSeasonH": round(best_possible, 2),
        "fullSunThresholdH": FULL_SUN_H, "bedThresholdUsedH": round(thr, 2),
        "horizon": {"azDeg": hz_az[::4].tolist(), "altDeg": [round(v, 2) for v in hz_deg[::4]],
                    "distM": hz_dist[::4].tolist()},
    },
    "beds": beds,
    "overlay": {"file": "poppy_sun.png", "xWest": x_w, "xEast": x_e, "zNorth": z_n, "zSouth": z_s,
                "value": "mean direct-sun hours/day over " + ", ".join(SEASON),
                "ramp": [[h, "#%02x%02x%02x" % c] for h, c in STOPS],
                "cellFt": CELL_FT},
    "provenance": {
        "shade": "USGS 3DEP LiDAR CA_SaltonSea_EarthMRI_2021 first-return DSM, 0.5 m (terrain_fine.bin)",
        "horizon": "USGS NED 1/3 arc-second mosaic, 10 m, EPSG:26911 (Coachella Valley 3D/socal_dem_utm11n.tif), sampled at 30 m to 45 km",
        "green": "USDA NAIP 4-band, NDVI > 0.20 (naip_fine.bin)",
        "lot": "Riverside County parcel GIS, APN " + APN,
        "sun": "NOAA solar position, 10-minute steps, Bennett refraction",
    },
    "caveats": [
        "Shade is from the 2021 LiDAR. A tree, wall or patio cover added or removed since then is not in it.",
        "NAIP cannot tell bare soil from gravel, pavers or a concrete pad of the same tone — check each bed on the ground.",
        "Sun hours ignore cloud; they are clear-sky direct-beam hours.",
    ],
}
json.dump(out, open(HERE / "poppy_sites.json", "w"), indent=1)
print(f"wrote poppy_sites.json, poppy_sun.png; best possible season sun {best_possible:.1f} h/day")

# ── figures ───────────────────────────────────────────────────────────────────
OUT_FIG.mkdir(parents=True, exist_ok=True)


def font(sz):
    for name in ("segoeui.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, sz)
        except OSError:
            pass
    return ImageFont.load_default()


# Site plan: NAIP true colour with the sun-hours overlay, the lot, house and beds.
PAD = 30                                             # cells of neighbourhood context around the window
fr0, fr1 = max(0, r_lo - PAD), min(NR, r_hi + PAD); fc0, fc1 = max(0, c_lo - PAD), min(NC, c_hi + PAD)
S = 10                                               # px per 0.5 m cell
rgb = naip[fr0:fr1, fc0:fc1, :3][::-1]
base = Image.fromarray(rgb).resize(((fc1 - fc0) * S, (fr1 - fr0) * S), Image.BICUBIC).convert("RGBA")
ovi = Image.fromarray(ov[::-1]).resize((Wd * S, H * S), Image.NEAREST)
canvas = Image.new("RGBA", base.size, (0, 0, 0, 0))
canvas.paste(ovi, ((c_lo - fc0) * S, (fr1 - r_hi) * S))
plan = Image.alpha_composite(base, canvas)
dr = ImageDraw.Draw(plan)
to_px = lambda E, N: ((E - cell_E(fc0)) / CELL * S + S / 2, (cell_N(fr1 - 1) - N) / CELL * S + S / 2)
dr.line([to_px(e, n) for e, n in lot_ring], fill=(255, 255, 255, 255), width=4)
for b in beds:
    for c, r in b["cells"]:
        x_, y_ = to_px(cell_E(c), cell_N(r))
        dr.rectangle([x_ - S / 2, y_ - S / 2, x_ + S / 2, y_ + S / 2], outline=(242, 140, 40, 255), width=2)
    ax, ay = to_px(ADDR_E + b["anchor"]["x"] / FT, ADDR_N - b["anchor"]["z"] / FT)
    dr.ellipse([ax - 16, ay - 16, ax + 16, ay + 16], fill=(242, 140, 40, 255), outline=(60, 20, 0, 255), width=3)
    dr.text((ax, ay), b["id"][1:], fill=(30, 10, 0, 255), font=font(20), anchor="mm")
hx, hy = to_px(ADDR_E + house_x / FT, ADDR_N - house_z / FT)
dr.ellipse([hx - 18, hy - 18, hx + 18, hy + 18], fill=(37, 99, 235, 255), outline=(255, 255, 255, 255), width=3)
dr.text((hx, hy), "H", fill=(255, 255, 255, 255), font=font(20), anchor="mm")
# north arrow + 10 ft scale bar
Wp, Hp = plan.size
dr.polygon([(Wp - 50, 30), (Wp - 64, 70), (Wp - 36, 70)], fill=(255, 255, 255, 255), outline=(0, 0, 0, 255))
dr.text((Wp - 50, 86), "N", fill=(255, 255, 255, 255), font=font(24), anchor="mm", stroke_width=2, stroke_fill=(0, 0, 0))
bar = 20 / FT / CELL * S
dr.rectangle([30, Hp - 46, 30 + bar, Hp - 36], fill=(255, 255, 255, 255), outline=(0, 0, 0, 255))
dr.text((30 + bar + 10, Hp - 41), "20 ft", fill=(255, 255, 255, 255), font=font(20), anchor="lm", stroke_width=2, stroke_fill=(0, 0, 0))
# legend panel
LW = 520
fig = Image.new("RGBA", (Wp + LW, max(Hp, 760)), (24, 24, 27, 255))
fig.paste(plan, (0, 0))
d2 = ImageDraw.Draw(fig); x0_ = Wp + 24; y_ = 24
d2.text((x0_, y_), "Poppy planting — 68075 Alva Ct", fill=(240, 240, 240), font=font(28)); y_ += 44
d2.text((x0_, y_), f"APN {APN} · lot {lot_sqft:,.0f} sq ft · white = lot line", fill=(170, 170, 170), font=font(17)); y_ += 34
d2.text((x0_, y_), "Direct sun, h/day (Nov 15 – Mar 15 mean)", fill=(220, 220, 220), font=font(19)); y_ += 30
for i, (h, c) in enumerate(STOPS):
    d2.rectangle([x0_ + i * 62, y_, x0_ + i * 62 + 56, y_ + 22], fill=c + (255,))
    d2.text((x0_ + i * 62 + 28, y_ + 34), f"{h}{'+' if i == len(STOPS) - 1 else ''}", fill=(200, 200, 200), font=font(16), anchor="mm")
y_ += 60
d2.text((x0_, y_), "Uncoloured = roof, canopy, wall, or within", fill=(170, 170, 170), font=font(16)); y_ += 22
d2.text((x0_, y_), "1.6 ft of one. Faded = already green (NDVI).", fill=(170, 170, 170), font=font(16)); y_ += 36
for b in beds:
    d2.ellipse([x0_, y_ + 2, x0_ + 26, y_ + 28], fill=(242, 140, 40))
    d2.text((x0_ + 13, y_ + 15), b["id"][1:], fill=(30, 10, 0), font=font(16), anchor="mm")
    d2.text((x0_ + 38, y_), f"{b['seasonSunH']:.1f} h sun · {b['areaSqft']:.0f} sq ft · "
                            f"{'soil' if b['surfaceKind'] == 'soil' else 'grey surface'}", fill=(240, 240, 240), font=font(19))
    d2.text((x0_ + 38, y_ + 25), f"{b['where'].split(' (')[0]} · Dec 21 {b['dec21SunH']:.1f} h · "
                                 f"Mar 15 {b['bySunDay']['Mar 15']:.1f} h", fill=(170, 170, 170), font=font(16))
    d2.text((x0_ + 38, y_ + 46), f"{b['anchor']['lat']:.6f}, {b['anchor']['lon']:.6f}", fill=(140, 140, 140), font=font(15))
    y_ += 78
y_ += 6
dec = next(d for d in out["sun"]["days"] if d["day"] == "Dec 21")
d2.text((x0_, y_), f"Dec 21 sun clears the mountains {dec['directSunPST'][0]}–{dec['directSunPST'][1]} PST;", fill=(200, 200, 200), font=font(16)); y_ += 22
d2.text((x0_, y_), f"terrain takes {dec['lostToMountainsH']:.1f} h of {dec['daylightH']:.1f} h daylight.", fill=(200, 200, 200), font=font(16)); y_ += 34
for line in ["Sources: 3DEP LiDAR 2021 (shade), NED 10 m (horizon),",
             "NAIP (imagery/NDVI), Riverside Co. parcels.",
             "Shade is as of 2021 — check for newer trees/structures."]:
    d2.text((x0_, y_), line, fill=(130, 130, 130), font=font(15)); y_ += 20
fig.convert("RGB").save(OUT_FIG / "site_plan.png")

# Sun path vs the mountain horizon.
SW_, SH_ = 1400, 640
sp = Image.new("RGB", (SW_, SH_), (24, 24, 27)); d3 = ImageDraw.Draw(sp)
AZ0, AZ1, AL1 = 90, 290, 45
mx, my, mw, mh = 70, 50, SW_ - 110, SH_ - 120
P = lambda az, al: (mx + (az - AZ0) / (AZ1 - AZ0) * mw, my + mh - al / AL1 * mh)
for al in range(0, AL1 + 1, 5):
    d3.line([P(AZ0, al), P(AZ1, al)], fill=(50, 50, 55)); d3.text((mx - 10, P(AZ0, al)[1]), f"{al}°", fill=(150, 150, 150), font=font(14), anchor="rm")
for az, nm in [(90, "E"), (135, "SE"), (180, "S"), (225, "SW"), (270, "W")]:
    d3.line([P(az, 0), P(az, AL1)], fill=(50, 50, 55)); d3.text((P(az, 0)[0], my + mh + 16), nm, fill=(150, 150, 150), font=font(16), anchor="mm")
hpoly = [P(AZ0, 0)] + [P(a, max(0, h)) for a, h in zip(hz_az, hz_deg) if AZ0 <= a <= AZ1] + [P(AZ1, 0)]
d3.polygon(hpoly, fill=(92, 80, 70))
d3.text(P(252, 2.0), "San Jacinto", fill=(230, 210, 190), font=font(16), anchor="mm")
cols_ = {"Oct 15": (171, 217, 233), "Dec 21": (116, 173, 209), "Feb 15": (254, 224, 144), "Mar 15": (244, 109, 67)}
for d, c in cols_.items():
    pts = [(az, alt) for _, az, alt in day_samples(d) if alt > 0]
    d3.line([P(a, al) for a, al in pts if AZ0 <= a <= AZ1], fill=c, width=3)
    a_, al_ = max(pts, key=lambda p: p[1]); d3.text(P(a_, al_ + 1.8), d, fill=c, font=font(16), anchor="mm")
d3.text((mx, 16), "Sun path vs. the real mountain horizon at 68075 Alva Ct (NED 10 m)", fill=(235, 235, 235), font=font(20))
sp.save(OUT_FIG / "sun_path.png")

# NAIP crop for eyeballing the beds on the imagery
Image.fromarray(rgb).resize(((fc1 - fc0) * 6, (fr1 - fr0) * 6), Image.BICUBIC).save(OUT_FIG / "naip_lot.png")
print("figures ->", OUT_FIG)
