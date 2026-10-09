# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## File layout — renamed for publishing

The site is public on GitHub Pages, which serves `main` from `/`, so the landing
page has to literally be `index.html`. As of this change:

| file | what it is | URL |
|---|---|---|
| `index.html` | **Valley Map** — the city-scale scene (was `sim of alva court.html`) | `/` |
| `neighbourhood.html` | the Alva Court block: LiDAR DTM + 108 extruded houses (was `index.html`) | `/neighbourhood.html` |

The subject address is still 68075 Alva Court and still scene (0, 0). Only the
*site* was renamed to Valley Map; the address references throughout these docs
are factual and unchanged.

## What this is

A browser-based Three.js render of the neighbourhood around **68075 Alva Court, Cathedral City, CA 92234** (Coachella Valley desert floor; lon/lat −116.474082, 33.836760), built from public geospatial data.

**Read `PLAN.md` first.** It holds the purpose (a traffic-safety case for city council about hit-and-run collisions at stop signs), the ground rules, and the current priority list. This file covers only *how the code works*.

There is **no build system, framework, or bundler**. Scenes are standalone HTML importing Three.js from the unpkg CDN via an `importmap`. Offline Node scripts in `elevation/` decode raw LiDAR/imagery into binaries the page fetches at load.

## Running it

Must be served over **HTTP** — ES-module imports and `fetch()` both fail from `file://`. Use the committed server, from the repo root:

```
node serve.mjs            # http://127.0.0.1:7432/   (port is an optional arg; --open launches the browser)
```

Do **not** write a fresh server in the scratchpad each session — a new path every time means the user gets a new permission prompt every time. `Open Alva Court.bat` (and the desktop shortcut) runs `node serve.mjs --open` for the user. The `/run` skill is pre-approved.

**Do not serve the repo root with a directory-listing or dotfile-serving server** — `.git/config` contains a plaintext GitHub PAT. `serve.mjs` binds `127.0.0.1` (no firewall prompt) and 403s any path segment starting with `.`, checked against the realpath so the `GIT~1` 8.3 alias is blocked too.

No tests, no lint, no build. "Verify a change" = serve it, load it, read the console.

## Coordinate system — get this right

- **`+X = East`, `+Z = SOUTH`, `North = −Z`, `Y = up`. All world units are FEET.**
- The street address is scene **(0, 0)**. Cul-de-sac bulb rounds **due east** at x≈+213; the road runs **west**. Road centreline z ≈ −21 → −42 (i.e. *north* of the address).
- Scene `y = 0` is `BASE_FT` = **399.573 ft** (DTM at the address, NAVD88). Both terrain tiles share this datum.
- Source CRS **UTM 11N / NAD83 (EPSG:26911)**, vertical **NAVD88 m**, ×3.280839895 → feet.
- Grid convention for **every** binary: `row 0 = SOUTH`, `col 0 = WEST`. Grid sample `(row, col)` is the value at UTM `(X0 + col·cell, Y0 + row·cell)`. NAIP PNGs are north-up, so rows get flipped on read.
- Derive scene↔grid transforms from the UTM georef directly (see `neighbourhood.html`'s `cellX`/`cellZ`/`colAt`/`rowAt`). Note `NC` samples span `NC−1` cell widths, not `NC` — getting this wrong stretches terrain against building placement.

### Three traps that have already cost real time

1. **`.claude/commands/lighting-setup.md` assumes `−Z = south`. This scene uses `+Z = south`.** Its "negative Z component" advice is wrong here, and is why `neighbourhood.html`'s sun still sits north (`z = −200`) casting shadows the wrong way. Measured shadow directions in the NAIP put the real sun **south-southwest**; `index.html` has been corrected to `(-150, 420, 320)`, `neighbourhood.html` has not.
2. **`terrain_meta.json`'s `road.*LocalFt` pairs are already world `[x, z]`** (`make_terrain.mjs` writes `z = -(N - addrN)`) — *not* `[E, N]`. Negating `z` "to convert" lands you 83 ft off, and because desert soil and asphalt are the same tone here, the wrong sample still returns grey and looks like a successful registration check. By contrast **`houses.json` uses `{E, N}` with N north-positive**, so scene `z = −N`. Two different conventions in two files; check which one you're holding.
3. **A footprint cluster is not one roof.** The flood fill merges main house + garage extension + patio awnings + (on the subject house) a semi-attached corrugated RV cover into one id at different heights. Never fit a single height per house; extrude the DSM per cell. Roof area whose NAIP colour differs from the main roof is usually an awning.

## Data pipeline (`elevation/`)

Node ESM (`"type": "module"`; deps `laz-perf` WASM + `pngjs`). **Run with `elevation/` as cwd** — scripts use bare relative paths.

```
cd elevation && npm install
node process_laz.mjs     # LAZ -> DSM/DTM .asc + 16-bit heightmap + meta
node make_terrain.mjs    # .asc -> terrain.bin + terrain_meta.json
node classify.mjs        # terrain.bin + LAZ -> classify.bin (routes A & B)
node naip_analyze.mjs    # naip/*.png + classify.bin -> naip.bin, houses.bin, houses.json
node make_osm.mjs        # osm_raw.json -> osm.json  (street network + stop signs)
node fetch_valley_osm.mjs        # Overpass -> raw/osm/{buildings,roads,vegetation,aeroway,water}.json
node make_valley_buildings.mjs   # OSM footprints + heights -> valley_buildings.bin
node make_psc_surfaces.mjs       # OSM ways -> psc_surfaces.bin  (PS + Cathedral City paving)
node preview.mjs         # optional hillshade PNG
```

Three Python steps calibrate the look against the orthophoto rather than
guessing at it — see **Calibration** below:

```
python naip_sites.py          # 8 NAIP tiles, 500 m @ 0.5 m, straight into UTM 11N
python measure_psc_tones.py   # NAIP medians per surface -> out/psc_tones.json
python render_vs_naip_psc.py <site> <render.png>    # scores a render against them
```

One step is Python, not Node — it reads a GeoTIFF, and rasterio is the tool for that:

```
ALVA_DEM="C:/Users/dmcge/Desktop/Coachella Valley 3D/socal_dem_utm11n.tif" \
PYTHONPATH="C:/Users/dmcge/Desktop/Coachella Valley 3D/pylibs" python make_valley.py
```

`make_valley.py` cuts a 40 km box at 39 m posting out of the 10 m NED/3DEP mosaic built by
the sibling **Coachella Valley 3D** project (510 MB, EPSG:26911, not committed here) and
writes `valley.bin` in exactly the `terrain.bin` convention. It hard-codes the same
`BASE_FT`, so the valley shares `y = 0` with the LiDAR tiles — the same rule `ALVA_BASE_FT`
enforces above. The box reaches San Jacinto Peak (3285 m, 19 km WSW of the address).

`process_laz.mjs` and `make_terrain.mjs` take **env overrides** so one code path cuts both tiles. Bare invocation reproduces the original detail-tile outputs exactly. The wide tile:

```
ALVA_CELL=1 ALVA_X0=548000 ALVA_Y0=3744000 ALVA_NC=1000 ALVA_NR=1000 \
  ALVA_PREFIX=wide node process_laz.mjs
ALVA_IN=wide ALVA_OUT=terrain_wide ALVA_BASE_FT=399.57349381574863 node make_terrain.mjs
```

`ALVA_BASE_FT` is **required** for any additional tile — without it each tile computes its own datum and they won't share `y = 0`.

### Buildings (`make_valley_buildings.mjs`)

Extrudes every OpenStreetMap building inside the `valley.bin` box — 33 127 of
them, Desert Hot Springs to west Indio — from `raw/osm/buildings.json`.

**Source policy: OSM only.** PLAN.md approves 3DEP, NAIP, OSM and TIGER, and
`swarm/core/CONVENTIONS.md` is stricter still. An earlier pass used Microsoft's
ML footprints (142 462 buildings, 87% carrying a photogrammetric height); those
are ODbL but outside the approved list, and were removed. `raw/msbf/` may still
hold that download — nothing reads it.

**Know what that trade actually is.** OSM's outlines are better: hand-traced,
not ML-traced. OSM's heights are far worse — it tags `height` on **3** of the
33 477 buildings in this box and `building:levels` on **122**. So:

| flag | source | n |
|---|---|---|
| 1 | 3DEP LiDAR nDSM, p75 of the cells inside the ring | 153 |
| 2 | stated — OSM `height=` / `building:levels=` | 124 |
| 0 | inferred — `building=*` type, then footprint area | 32 850 |

`inferHeight()` leans on `building=*` rather than area alone because a type is
the better prior: a 3 000 sq ft `roof` is a carport at 9 ft and a 3 000 sq ft
`apartments` is two storeys at 22 ft, and no area rule separates them. The
table is anchored on this valley's own measured distribution — median LiDAR
roof 14.4 ft, almost entirely single-storey.

Losing the ML heights cost measurable fidelity, and the number is on record:
structural MS-SSIM against NAIP fell from 0.148 to 0.143 at Palm Springs and
0.164 to 0.137 at Cathedral City. Footprint *count* drives that score, and OSM
has a quarter as many buildings.

`utm11.mjs` does lon/lat to UTM 11N and back, verified against the address
georef to 5 cm. NAD83-vs-WGS84 (~1 m here) is below footprint accuracy and is
not corrected.

Ground comes from `terrain` then `terrain_wide` then `valley` **in the order
the scene's own `groundY()` walks them**, not from the finer analysis-only
tiles — otherwise a building seats itself on a surface the scene never draws
and floats. Each ring gets a roof datum from its centroid and a skirt 8 ft
below its lowest ring sample, so 39 m ground cells never leave a gap under a
wall.

### Palm Springs + Cathedral City paving (`make_psc_surfaces.mjs`)

1 100 miles of OSM roadway and 100 miles of sidewalk, swept into draped ribbons
the same way the Alva Court road is, split into four material groups (asphalt /
concrete / unpaved / sidewalk) by `surface=*` where OSM states it and by
highway class otherwise.

Two things in here are load-bearing:

- **Sidewalks are only where OSM maps one.** OSM in this valley barely uses the
  `sidewalk=*` tag on roads (36 ways in the whole box) but maps 1 027 separate
  `highway=footway` + `footway=sidewalk` ways. Those are the only sidewalks
  drawn. Generating concrete alongside every residential street would be the
  invented geometry PLAN.md forbids, in the exact layer a sight-line argument
  depends on.
- **Draping interpolates the mesh, it does not round to a cell.** The scene's
  `groundY()` rounds to the nearest sample, which is harmless on a 0.5 m LiDAR
  tile and ruinous on `valley.bin` at 39 m: a road pinned to cell-centre values
  sinks feet below the interpolated surface on any slope and disappears. This
  script reproduces the ground builder's own triangulation — `(a,b,d)` and
  `(b,e,d)` per quad — so the ribbon lands exactly on the surface drawn over it,
  and the per-class lift (0.16–0.34 ft) does nothing but order the junctions.

Ribbon winding is `(a,b,c) + (b,d,c)` for vertices emitted left-then-right per
station. The transpose faces the ground and is back-face culled into
invisibility — which is exactly how it failed the first time.

Texture tile is 40 ft, not the 20 ft the Alva Court street uses. A 2048 px
texture repeated every 20 ft across 1 100 miles seen from 1 500 ft up lands
about one texel per screen pixel and reads as salt-and-pepper noise; the city
materials also drop anisotropy from 16 to 4, which puts the mip chain back in
charge. The city therefore does **not** share `matRoad`.

### The corridor tile, and what the wash actually proved

`reconcile_cc.py` measured `valley.bin` against 1 m 3DEP over the Whitewater
wash corridor (the marked reach past Cimarron, Escena and PSP) and found
**nothing to correct**:

| control | result |
|---|---|
| horizontal | hillshade correlation peaks at dE=0, dN=0 — already registered |
| bulk vertical | median −0.17 ft over 18 476 samples — no datum offset |
| along-wash | median −0.10 ft, no significant tilt over 113 cross-sections |

The entire disagreement is **resolution**, and the two controls show it with
opposite signs: 39 m posting bridges over a 100 m channel, so the coarse
surface floats **4.8 ft above the real bed** and its **13.1 ft walls do not
exist at all**; the same posting shaves down PSP's engineered platform, which
sits **3.6 ft low**. So the fix is a finer tile, not an offset field —
`terrain_corridor.bin`, 4 m over E 544000..550000 / N 3742000..3747000, built
by `fetch_3dep_utm.py` → `make_corridor_tile.py`.

Two traps this dug up:

- **`raw/USGS_1M_DEM_CaliforniaGaps_B23.tif` does not cover this ground.** Its
  bounds say E 539994..550006 and it is a *gap-fill* tile: 9.6% valid, real data
  only to E 544379 / N 3744386. Every sample over the airport, the corridor and
  Cathedral City returns NoData.
- **Adding a fourth tile moved every ground `polygonOffset`**, which was
  hard-coded as `ti - 2` for exactly three. It is `ti - (tiles.length - 1)` now.
  Note that `logarithmicDepthBuffer` writes `gl_FragDepth`, which makes
  fixed-function polygon offset **inert** — overlays must be separated
  geometrically, not by offset.

**Known defect:** the vegetation drape and the rendered ground disagree by up to
~2.2 ft in places (raycast into Cimarron put `terrain_corridor` in front at
y=10.1 with turf behind at y=7.9, while sampling the same vertices against
`groundY()` claims +1.3..1.7 ft). Subdividing 80 → 24 → 12 ft changed the render
not at all, which rules out the flat-chord explanation. The 4 ft lift in
`make_psc_vegetation.mjs` covers the measured worst case; it hides the defect
rather than fixing it, and the cause is still open.

### Calibration — matching the orthophoto instead of guessing

`measure_psc_tones.py` takes NAIP medians under the OSM road, sidewalk and
bare-ground masks; `render_vs_naip_psc.py` renders the same 500 m box top-down,
measures the same masks, and reports dE76 plus the correction to apply. It also
scores MS-SSIM on Sobel edge magnitude across all four flips: cross-modal, so
per `CONVENTIONS.md` the absolute value means nothing and only the margin over
the wrong flips does — if `as-is` does not win, the framing is wrong and every
tone number measured through it is worthless.

Three findings came out of that loop, none of which were visible by eye:

1. **Diffuse maps had no `colorSpace`.** three then reads sRGB bytes as linear,
   lifting an 82/255 asphalt texel from 0.087 to 0.32 — a 3.7x over-brightening.
   That is why the roadway had always rendered as pale grey. Roughness and
   normal maps stay linear: they carry data, not colour.
2. **`asphalt_02` is the wrong asphalt.** Mean albedo 0.087 linear is *fresh*
   asphalt. Twenty years of desert sun puts these streets at 0.18–0.25, which is
   where the orthophoto measures them. The city composite is re-levelled onto a
   measured per-channel mean (`relevel()` in the scene), not multiplied by a
   tint over 1 — same lie, worse dynamic range.
3. **The terrain ramp fed lit pixels back in as albedo.** Its stops were raw
   NAIP values, which the sun then lights a second time; the floor rendered
   #8a8774 against a measured #9e9c92. The stops now carry the measured
   correction (x1.21, 1.21, 1.31). Only the lower two stops sit inside ground
   the NAIP sites cover; the upper two carry the same factor to keep the
   gradient's shape and are extrapolation, not measurement.

Where that landed, render vs NAIP, dE76:

| | roadway | sidewalk | bare ground |
|---|---|---|---|
| Palm Springs | 90.1 -> **3.2** | 52.0 -> **4.5** | 21.6 -> **9.1** |
| Cathedral City | (same pass) -> **1.0** | -> **4.6** | 35.1 -> **5.5** |

One calibration fits both cities, and the two sites now pull in opposite
directions, so that is the optimum for a single shared set of constants rather
than a Palm Springs fit that Cathedral City merely tolerates.

### The classifier chain (why there are three opinions)

Trees and buildings are both "tall", and getting that distinction wrong puts fake sight-line blockers in a safety render. So three independent routes vote:

- **A** (`classify.mjs`) — LiDAR return structure: tall + porous/multi-return ⇒ tree.
- **B** (`classify.mjs`) — surface geometry: tall + planar ⇒ building.
- **C** (`naip_analyze.mjs`) — NDVI from 4-band NAIP: irrigated vegetation is bright NIR / dark red. A cue the LiDAR cannot see.

A/B agree ~80%; all three are unanimous on 59% of tall cells. `classify_review.html` is a standalone 2D canvas tool for eyeballing the **disagreement** map — that's its purpose, not the agreement.

### Products and who consumes them

| file | what | consumed by |
|---|---|---|
| `terrain.bin` | 0.5 m, 640², `[DSM][DTM]` Float32LE ft | ground mesh, `groundY()`, house seating |
| `terrain_wide.bin` | 1 m, 1000², same layout + datum | mid-field ground in `index.html` |
| `valley.bin` | 39 m, 1024², DTM only, same datum | valley ground in `index.html` |
| `houses.bin` | Uint16 per cell, `0`=none else `houseId+1` | **building geometry source** |
| `houses.json` | 108 houses: centroid, bbox, heights, roof colour | roof colours, façade location |
| `naip.bin` | `[labelC, ndvi, R, G, B]` uint8 per cell | per-cell roof colour |
| `classify.bin` | `[A, B, nDSM, mfrac, rough, disc]` uint8 | `classify_review.html` |
| `osm.json` | 78 ways, 37 stop signs, 22 intersections, scene-local ft | roads/signs (not yet wired in) |
| `valley_buildings.bin` | 33 127 OSM rings + roof triangles + top/bottom/flag, scene ft | valley buildings in `index.html` |
| `psc_surfaces.bin` | 4 material groups of draped ribbon: position, uv, index | PS + Cathedral City paving |
| `raw/osm/*.json` | Overpass dumps: buildings, roads, vegetation, aeroway, water | every OSM-derived product |
| `raw/naip_sites/*.npy` | 8 NAIP tiles, 500 m @ 0.5 m, uint8 RGB+NIR | tone + MS-SSIM calibration |

`valley_buildings_meta.json` and `psc_surfaces_meta.json` both carry a `bin.sections` list — `{name, type, byteOffset, length}` per array, so the reader never hard-codes an offset. Sections are `ringOff`, `triOff`, `xz`, `tri`, `top`, `bot`, `flag`; roof triangles are ear-clipped offline and already wound to face `+Y`, and the walls the scene builds from `(Ti, Bi, Tj) + (Tj, Bi, Bj)` face outward for that same winding.

`osm_raw.json` and `wide_*.asc` are gitignored intermediates; regenerate via the header comment in `make_osm.mjs` / the env vars above. `raw/msbf/` is likewise gitignored — the footprint download, not a product.

## The scene

- **`neighbourhood.html`** — the live scene. LiDAR DTM ground; all 108 buildings extruded from `houses.bin` (roof quad per cell at measured DSM height, per-cell NAIP colour, wall quads wherever a neighbour is lower — so internal height breaks render as the garage/awning faces they are). Palm-frond spikes are capped per cluster at p99 + 2 ft. Doors/windows/garage are placed by finding the real façade in the mask (street-most cell per column, longest coplanar run) for the 10 houses fronting Alva Ct.
- **`index.html`** — the valley-context scene. It now also carries the **142 462 valley buildings**, split into three merged meshes: `buildings-near` (within 900 ft of the address — the only one that casts shadows, because that is all the 600 ft shadow frustum covers), `buildings-measured`, and `buildings-inferred` (cooler `#9d9689`, so an inferred height never reads as a measurement). `B` toggles the layer, `I` toggles the inferred buildings alone. Roof-cap and wall vertices are **shared** — the materials are `flatShading`, so normals come from screen-space derivatives and splitting them would only double 2 M vertices. It is still the reference for **PBR asphalt compositing** (`blendWithNoise`, seeded value noise, cul-de-sac UV remap, async `EXRLoader`). Ground is three nested 3DEP tiles (`terrain` → `terrain_wide` → `valley`, 0.5 m → 39 m) drawn finest-first; each coarser tile drops the quads whose centre falls inside the next finer tile's footprint, and polygon offset settles the half-cell of overlap left at the seam. The road is no longer the idealised straight 360 ft strip — it is a ribbon swept along `terrain_meta.json`'s surveyed centreline, resampled at 3 ft and draped on the DTM, with the sidewalk slabs and bulb following it.
- **`elevation/classify_review.html`** — classifier review tool, no Three.js.

**`src/` split is planned but does not exist yet** (P0 in `PLAN.md`). Until it lands, `neighbourhood.html` holds the whole scene inline.

## Textures & assets

- `textures/asphalt/` and `textures/cement/` are the paths the scenes load. `asphalt assets/` and `cement assets/` are the older duplicates, still tracked. One live reference remains to the old path: `neighbourhood.html` loads `cement assets/painted-gray-wall.jpg`, which has **no copy** under `textures/cement/`.
- `grass/` and `stucco/` are committed (4K/2K diffuse+normal+bump sets) but **not yet referenced by any scene**. Source `.zip`s are gitignored; extracted folders are committed.
- Directory names contain **spaces** — URL-encode in HTML (`asphalt%20assets/...`, `%20(1)`).
- `asphalt_02_nor_gl_4k.exr` is not loadable by `TextureLoader`; use `EXRLoader` from `three/addons` or convert to PNG offline in linear space.
- Measured surface colours from the aerial, if you need them without re-deriving: ground/gravel `#9a988d`, roadway `#9d9a8e`, turf `#596b52`, canopy `#476047`, roofs `#b9ada3`. The old flat ground colour `#c4956a` is too warm and too saturated.

## Git tracking

`git ls-files` is authoritative — **not `.gitignore`**. Several ignore rules are inert no-ops because the files were committed before being ignored (`asphalt assets/`, `cement assets/`, `asphalt_02/`, `visual examples/`, the `.blend`, and `index.html` are all on GitHub regardless).

As of this writing, still untracked: **`.claude/settings.json`** (permission allowlists only) and `elevation/raw/` (~200 MB, intentionally out). Everything else the app needs is committed.

## Design intent (`.claude/commands/`)

- **`/lighting-setup`** — desert sun from the southeast, warm `0xfff4e0`, sky `0x87CEEB`, sandy bounce `0xd4a76a`, low ambient for hard shadows, cul-de-sac all asphalt, no HDRI/fog/post. **Its Z-sign is wrong for this scene — see trap 1.**
- **`/satellite-critique`** — render-vs-aerial accuracy report format.
- **`/texture-integrate`** — spec for wiring the 4K PBR asphalt maps in.

All three name `index.html` explicitly; apply their intent to whichever scene you're editing.

## Security

`.git/config`'s `origin` **no longer embeds a PAT** — it is a clean
`https://github.com/...` URL and pushes authenticate through the `gh` keyring.
The warning that used to live here is resolved; if a token ever reappears in
the remote URL, rotate it rather than committing around it.

The repo is **public** and Pages serves `main` from `/`, so anything committed
is published. Check before adding data you did not mean to publish.
