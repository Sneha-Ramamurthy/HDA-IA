"""Critical infrastructure (health, emergency, power, water, transport) from OpenStreetMap."""
import os

import geopandas as gpd
import osmnx as ox

import config
from data_loader import overpass_retry

PATH = "data/assets.geojson"
TAG_COLUMNS = ("amenity", "power", "man_made", "railway", "station")


def _kind(row):
    for group, tags in config.ASSET_GROUPS.items():
        for col, vals in tags.items():
            v = row.get(col)
            if isinstance(v, str) and v in vals:
                return group, v
    return None, None


def load_assets():
    """GeoDataFrame (projected CRS) with columns group, kind, name, geometry (points)."""
    if os.path.exists(PATH):
        return gpd.read_file(PATH).to_crs(config.CRS_PROJECTED)
    tags = {}
    for t in config.ASSET_GROUPS.values():
        for col, vals in t.items():
            tags.setdefault(col, []).extend(vals)
    g = overpass_retry(lambda: ox.features_from_point(config.CENTER, tags, dist=config.DIST_M)).reset_index(drop=True)
    rows = []
    for _, r in g.iterrows():
        grp, kind = _kind(r)
        if grp:
            rows.append(dict(group=grp, kind=kind, name=r.get("name") if isinstance(r.get("name"), str) else "", geometry=r.geometry))
    out = gpd.GeoDataFrame(rows, crs=g.crs).to_crs(config.CRS_PROJECTED)
    out["geometry"] = out.geometry.centroid
    out = out.drop_duplicates(subset=["group", "kind", "name", "geometry"]).reset_index(drop=True)
    out.to_crs(4326).to_file(PATH, driver="GeoJSON")
    return out
