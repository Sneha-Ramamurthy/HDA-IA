"""Terrain-based flood hazard from the Copernicus GLO-30 DEM (automatic, no user inputs).

For every cell: height above the nearest river cell (HAND). During the design flood the water stands
FLOOD_STAGE_M above the river; low ground (HAND <= stage) is flooded only if it connects to the river.
Road flood depth is then taken along each road and mapped to a hazard class.
"""
import os

import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.warp import Resampling, calculate_default_transform, reproject
from rasterio.windows import from_bounds
from scipy import ndimage

import config


def ensure_dem():
    """Download the DEM window around the study area once, reproject to the project CRS and cache it."""
    if os.path.exists(config.DEM_PATH):
        return config.DEM_PATH
    import planetary_computer as pc
    from pystac_client import Client

    lat, lon = config.CENTER
    cat = Client.open("https://planetarycomputer.microsoft.com/api/stac/v1", modifier=pc.sign_inplace)
    item = next(cat.search(collections=["cop-dem-glo-30"], bbox=[lon, lat, lon, lat]).items())
    d = config.DIST_M / 111320 * 1.4
    with rasterio.open(item.assets["data"].href) as src:
        win = from_bounds(lon - d, lat - d, lon + d, lat + d, src.transform)
        arr = src.read(1, window=win).astype("float32")
        tr, crs = src.window_transform(win), src.crs
    tr2, w, h = calculate_default_transform(crs, config.CRS_PROJECTED, arr.shape[1], arr.shape[0], *rasterio.transform.array_bounds(*arr.shape, tr))
    out = np.zeros((h, w), dtype="float32")
    reproject(arr, out, src_transform=tr, src_crs=crs, dst_transform=tr2, dst_crs=config.CRS_PROJECTED, resampling=Resampling.bilinear)
    os.makedirs("data", exist_ok=True)
    with rasterio.open(config.DEM_PATH, "w", driver="GTiff", height=h, width=w, count=1, dtype="float32", crs=config.CRS_PROJECTED, transform=tr2) as dst:
        dst.write(out, 1)
    return config.DEM_PATH


def flood_depth_grid(water, stage=None):
    """Return (depth array in metres, affine transform) for the design flood."""
    stage = config.FLOOD_STAGE_M if stage is None else stage
    with rasterio.open(ensure_dem()) as src:
        dem, tr = src.read(1), src.transform
    river = rasterize([(g, 1) for g in water.geometry], out_shape=dem.shape, transform=tr, all_touched=True).astype(bool)
    if not river.any():
        raise RuntimeError("No waterway inside the DEM window; cannot build the terrain flood.")
    dist, idx = ndimage.distance_transform_edt(~river, return_indices=True)
    hand = dem - dem[idx[0], idx[1]]
    low = (hand <= stage) & (dist * abs(tr.a) <= config.FLOODPLAIN_MAX_M)  # water cannot spread beyond the floodplain
    labels, _ = ndimage.label(low, structure=np.ones((3, 3)))
    connected = np.isin(labels, np.unique(labels[low & river]))
    depth = np.where(low & connected, stage - hand, 0.0)
    return depth, tr


def dem_hazard(edges, water, stage=None):
    """Hazard class per road (0-4) and the 75th-percentile flood depth along it."""
    depth, tr = flood_depth_grid(water, stage)
    inv = ~tr
    depths = np.zeros(len(edges))
    for i, geom in enumerate(edges.geometry):
        n = max(3, int(geom.length // config.SAMPLE_STEP_M) + 1)
        pts = [geom.interpolate(t, normalized=True) for t in np.linspace(0, 1, n)]
        cols, rows = zip(*[inv * (p.x, p.y) for p in pts])
        r = np.clip(np.floor(rows).astype(int), 0, depth.shape[0] - 1)
        c = np.clip(np.floor(cols).astype(int), 0, depth.shape[1] - 1)
        depths[i] = np.percentile(depth[r, c], 75)
    cls = np.zeros(len(edges), dtype=int)
    for limit, k in sorted(config.DEPTH_CLASSES_M):  # shallow first, deeper overrides
        cls[depths > limit if limit == 0 else depths >= limit] = k
    return cls, depths
