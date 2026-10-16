"""Download (and cache) roads, hospitals and waterways from OpenStreetMap."""
import os
import time

import geopandas as gpd
import osmnx as ox

import config

os.makedirs("data", exist_ok=True)
ox.settings.use_cache = True
OVERPASS = ["https://overpass.kumi.systems/api", "https://overpass-api.de/api", "https://overpass.private.coffee/api"]
ox.settings.requests_timeout = 90  # fail fast on a hung server, then try the next one


def overpass_retry(fn, rounds=3):
    """Call an OSMnx download, retrying across public Overpass servers when one is overloaded (502/504)."""
    last = None
    for i in range(rounds * len(OVERPASS)):
        ox.settings.overpass_url = OVERPASS[i % len(OVERPASS)] + "/interpreter"
        try:
            return fn()
        except Exception as exc:  # server errors, timeouts
            last = exc
            time.sleep(5 * (i // len(OVERPASS) + 1))
    raise last


def _features(tag_name, tags, path):
    if os.path.exists(path):
        return gpd.read_file(path)
    try:
        gdf = overpass_retry(lambda: ox.features_from_point(config.CENTER, tags, dist=config.DIST_M))
        gdf = gdf[["geometry"] + [c for c in ("name",) if c in gdf.columns]].reset_index(drop=True)
    except Exception as exc:  # no features found
        print(f"  no {tag_name} found ({exc.__class__.__name__})")
        gdf = gpd.GeoDataFrame({"geometry": []}, crs="EPSG:4326")
    gdf.to_file(path, driver="GeoJSON")
    return gdf


def load_data():
    """Return (projected road MultiDiGraph, hospitals GeoDataFrame, waterways GeoDataFrame)."""
    path = "data/roads.graphml"
    if os.path.exists(path):
        G = ox.load_graphml(path)
    else:
        G = overpass_retry(lambda: ox.graph_from_point(config.CENTER, dist=config.DIST_M, dist_type="bbox", network_type="drive"))
        ox.save_graphml(G, path)
    G = ox.project_graph(G, to_crs=config.CRS_PROJECTED)

    hosp = None  # hospitals now come from assets.load_assets() with the other facilities
    water = _features("waterways", {"waterway": ["river", "canal", "stream"]}, "data/waterways.geojson")
    water = water.to_crs(config.CRS_PROJECTED)
    water = water[water.geom_type.isin(["LineString", "MultiLineString"])]
    return G, hosp, water
