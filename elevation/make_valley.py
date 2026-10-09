"""
make_valley.py — cut the wide Coachella Valley context tile out of the 10 m
USGS 3DEP / NED mosaic and write it in the same binary convention as
terrain.bin / terrain_wide.bin so a scene can drop it straight in.

Source raster lives in the sibling "Coachella Valley 3D" project (510 MB, way
too big to fetch from a page and not committed here). Point ALVA_DEM at it:

    ALVA_DEM="C:/Users/dmcge/Desktop/Coachella Valley 3D/socal_dem_utm11n.tif" \
    PYTHONPATH="C:/Users/dmcge/Desktop/Coachella Valley 3D/pylibs" \
      python make_valley.py

Env overrides: ALVA_HALF_M (half box width, m), ALVA_N (samples per side),
ALVA_OUT (output prefix).

Output — valley.bin: Float32LE, N*N bare-earth elevations in FEET (NAVD88),
row 0 = SOUTH, col 0 = WEST, identical to the DTM half of terrain.bin. Shares
BASE_FT with every other tile so y = 0 is the same ground everywhere.
"""

import json
import os
import struct

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.windows import from_bounds

FT = 3.280839895
BASE_FT = 399.57349381574863          # DTM at the address — the shared datum
ADDR_E, ADDR_N = 548660.3, 3744180.9  # street address = scene (0, 0)

DEM = os.environ.get("ALVA_DEM", r"C:/Users/dmcge/Desktop/Coachella Valley 3D/socal_dem_utm11n.tif")
HALF = float(os.environ.get("ALVA_HALF_M", 20000))   # 40 km box — reaches San Jacinto Peak
N = int(os.environ.get("ALVA_N", 1024))
OUT = os.environ.get("ALVA_OUT", "valley")

# Sample centres run from ADDR-HALF to ADDR+HALF inclusive, so N samples span
# (N-1) cells — the same off-by-one that stretched the terrain once already.
cell = (2 * HALF) / (N - 1)
x0, y0 = ADDR_E - HALF, ADDR_N - HALF

src = rasterio.open(DEM)
print(f"source {DEM}\n  crs {src.crs}  {src.width}x{src.height}")

# Read a window covering the sample centres plus a half-cell margin, resampled
# straight to N x N. Bilinear: this is terrain, not a categorical mask.
win = from_bounds(x0 - cell / 2, y0 - cell / 2,
                  x0 + (N - 1) * cell + cell / 2, y0 + (N - 1) * cell + cell / 2,
                  src.transform)
arr = src.read(1, window=win, out_shape=(N, N), resampling=Resampling.bilinear)

nod = src.nodata
if nod is not None:
    bad = arr <= nod + 1
    if bad.any():
        arr = np.where(bad, np.nan, arr)
        # fill holes with the tile median so the mesh has no spikes
        arr = np.where(np.isnan(arr), np.nanmedian(arr), arr)
        print(f"  filled {int(bad.sum())} nodata cells")

arr = np.flipud(arr) * FT           # raster is north-up; our grids are row0 = SOUTH
arr = arr.astype("<f4")

with open(f"{OUT}.bin", "wb") as f:
    f.write(arr.tobytes())

meta = {
    "note": "Elevations in FEET (NAVD88). Grid row0=SOUTH, col0=WEST. World: +X=East, +Z=South, North=-Z. Subtract baseFt for y near 0.",
    "source": "USGS 3DEP / NED 1/3 arc-second mosaic, reprojected EPSG:26911 (Coachella Valley 3D project)",
    "nc": N, "nr": N,
    "cellFt": cell * FT, "cellM": cell,
    "utm": {"x0": x0, "y0": y0, "addrE": ADDR_E, "addrN": ADDR_N},
    "baseFt": BASE_FT,
    "bin": {"file": f"{OUT}.bin", "layout": "Float32LE: DTM[nc*nr] (bare earth only — NED has no surface return)"},
    "address": {"localFt": [0, 0], "lonlat": [-116.474082, 33.83676]},
    "sizeFt": [(N - 1) * cell * FT, (N - 1) * cell * FT],
    "elevFt": [float(arr.min()), float(arr.max())],
}
with open(f"{OUT}_meta.json", "w") as f:
    json.dump(meta, f, indent=2)

print(f"  {OUT}.bin  {N}x{N} @ {cell:.1f} m  ({arr.nbytes/1e6:.1f} MB)")
print(f"  elevation {arr.min()/FT:.0f}..{arr.max()/FT:.0f} m  "
      f"({arr.min():.0f}..{arr.max():.0f} ft)")
