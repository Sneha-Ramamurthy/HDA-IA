"""Assign a hazard class (0-4) to every road edge for any disaster type.

Scenario modes turn a hazard source (river, epicentre, storm track) into distance bands.
Raster mode reads real hazard classes from a GeoTIFF and works for any disaster.
"""
import geopandas as gpd
import numpy as np
from shapely.geometry import LineString, Point
from shapely.ops import unary_union

import config


def _bands(base, scale):
    return [(d * scale, c) for d, c in base]


def _classify(dist, bands):
    cls = np.zeros(len(dist), dtype=int)
    for limit, c in sorted(bands, reverse=True):  # far band first, nearer overrides
        cls[np.asarray(dist) <= limit] = c
    return cls


def _centre_xy():
    p = gpd.GeoSeries([Point(config.CENTER[1], config.CENTER[0])], crs=4326).to_crs(config.CRS_PROJECTED).iloc[0]
    return p.x, p.y


def flood_hazard(edges, water, scale=1.0):
    """Distance to the nearest river/canal/stream."""
    if water.empty:
        raise RuntimeError("No waterway found in the study area; use a raster or change CENTER.")
    river = unary_union(list(water.geometry))
    return _classify(edges.geometry.distance(river).values, _bands(config.SIM_BANDS_M, scale))


def earthquake_hazard(edges, scale=1.0, dx=0.0, dy=0.0):
    """Distance to an epicentre placed (dx, dy) metres east/north of the study-area centre."""
    cx, cy = _centre_xy()
    return _classify(edges.geometry.distance(Point(cx + dx, cy + dy)).values, _bands(config.QUAKE_BANDS_M, scale))


def storm_hazard(edges, scale=1.0, dx=0.0, dy=0.0, bearing=0.0):
    """Distance to a straight storm-track corridor through (dx, dy) heading `bearing` degrees clockwise from north."""
    cx, cy = _centre_xy()
    b = np.radians(bearing)
    px, py = cx + dx, cy + dy
    track = LineString([(px - 20000 * np.sin(b), py - 20000 * np.cos(b)), (px + 20000 * np.sin(b), py + 20000 * np.cos(b))])
    return _classify(edges.geometry.distance(track).values, _bands(config.STORM_BANDS_M, scale))


def raster_hazard(edges, tif=None):
    """Max raster value under each road (raster must hold hazard classes 0-4)."""
    import rasterio
    from rasterstats import zonal_stats

    tif = tif or config.RASTER_PATH
    with rasterio.open(tif) as src:
        e = edges.to_crs(src.crs)
    stats = zonal_stats(e.geometry, tif, stats="max", all_touched=True)
    return np.array([int(s["max"]) if s["max"] is not None else 0 for s in stats])


def assign_hazard(edges, water, kind="Flood", scale=1.0, dx=0.0, dy=0.0, bearing=0.0, raster=None):
    if raster:
        return raster_hazard(edges, raster)
    if kind == "Earthquake":
        return earthquake_hazard(edges, scale, dx, dy)
    if kind == "Cyclone / storm":
        return storm_hazard(edges, scale, dx, dy, bearing)
    return flood_hazard(edges, water, scale)
