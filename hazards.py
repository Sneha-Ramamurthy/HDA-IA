"""Hazard models for flood, storm and earthquake. Each returns a class (0-4) and a physical metric per road and facility.

Class 3 or higher means damaged. All severities are fixed or taken from data; none are user inputs.
"""
import io
import os
import ssl
from types import SimpleNamespace

import certifi
import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import requests
from pyproj import Transformer
from shapely.geometry import Point

import config
import dem_hazard

TO_LL = Transformer.from_crs(config.CRS_PROJECTED, 4326, always_xy=True)


def _classify(values, cuts):
    """cuts: [(threshold, class)]; the highest threshold reached wins."""
    cls = np.zeros(len(values), dtype=int)
    for thr, c in sorted(cuts):
        cls[np.asarray(values) >= thr] = c
    return cls


def _line_samples(geom, step=config.SAMPLE_STEP_M, ends_only=False):
    if ends_only:
        return [geom.interpolate(0.0, normalized=True), geom.interpolate(1.0, normalized=True)]
    n = max(3, int(geom.length // step) + 1)
    return [geom.interpolate(t, normalized=True) for t in np.linspace(0, 1, n)]


def _result(ec, em, fc, fm):
    return SimpleNamespace(edge_class=np.asarray(ec), edge_metric=np.asarray(em, float), fac_class=np.asarray(fc), fac_metric=np.asarray(fm, float))


# ------------------------------------------------------------------ flood
class Flood:
    key, label, unit = "flood", "Flood", "flood depth (m)"

    def __init__(self, stage):
        self.stage = stage
        self.rung = f"{stage:g} m above river"

    def assess(self, base):
        depth, tr = dem_hazard.flood_depth_grid(base.water, self.stage)
        inv = ~tr

        def at(p):
            c, r = inv * (p.x, p.y)
            return depth[min(max(int(r), 0), depth.shape[0] - 1), min(max(int(c), 0), depth.shape[1] - 1)]

        em = []
        for e in base.edges.itertuples():
            vals = [at(p) for p in _line_samples(e.geometry, ends_only=bool(e.bridge))]  # bridge decks stand above the water: judge by approaches
            em.append(max(vals) if e.bridge else np.percentile(vals, 75))
        fm = [at(p) for p in base.facilities.geometry]
        cuts = [(lim if lim > 0 else 1e-9, c) for lim, c in config.DEPTH_CLASSES_M]
        return _result(_classify(em, cuts), em, _classify(fm, cuts), fm)

    def event_text(self, base):
        return None


# ------------------------------------------------------------------ storm
def _worldcover():
    path = "data/worldcover.tif"
    if not os.path.exists(path):
        import planetary_computer as pc
        from pystac_client import Client
        from rasterio.windows import from_bounds

        lat, lon = config.CENTER
        d = config.DIST_M / 111320 * 1.3
        cat = Client.open("https://planetarycomputer.microsoft.com/api/stac/v1", modifier=pc.sign_inplace)
        item = sorted(cat.search(collections=["esa-worldcover"], bbox=[lon, lat, lon, lat]).items(), key=lambda i: i.id)[-1]
        with rasterio.open(item.assets["map"].href) as src:
            win = from_bounds(lon - d, lat - d, lon + d, lat + d, src.transform)
            arr = src.read(1, window=win)
            tr = src.window_transform(win)
        with rasterio.open(path, "w", driver="GTiff", height=arr.shape[0], width=arr.shape[1], count=1, dtype="uint8", crs="EPSG:4326", transform=tr) as dst:
            dst.write(arr, 1)
    return path


def tree_share(edges):
    """Share of tree cover (ESA WorldCover class 10) on and beside each road: samples every ~10 m and one pixel to each side."""
    with rasterio.open(_worldcover()) as src:
        a, inv = src.read(1), ~src.transform
    out = []
    for geom in edges.geometry:
        pts = _line_samples(geom, 10)
        lon, lat = TO_LL.transform([p.x for p in pts], [p.y for p in pts])
        cols, rows = inv * (np.array(lon), np.array(lat))
        hits = []
        for dc, dr in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)):
            r = np.clip((rows + dr).astype(int), 0, a.shape[0] - 1)
            c = np.clip((cols + dc).astype(int), 0, a.shape[1] - 1)
            hits.append(a[r, c] == 10)
        out.append(float(np.mean(hits)))
    return np.array(out)


def _holland(vmax, r_km, rmax_km, b=1.5):
    x = (rmax_km / np.maximum(r_km, 1.0)) ** b
    return vmax * np.sqrt(x * np.exp(1 - x))


def storm_catalogue():
    """Real cyclones (NOAA IBTrACS, North Indian Ocean) ranked by the wind they would produce at the study area (Holland profile)."""
    if not os.path.exists(config.IBTRACS_CSV):
        open(config.IBTRACS_CSV, "w").write(requests.get(config.IBTRACS_URL, timeout=600).text)
    df = pd.read_csv(config.IBTRACS_CSV, skiprows=[1], low_memory=False)
    for c in ("LAT", "LON", "USA_WIND", "USA_RMW", "WMO_WIND"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["wind_ms"] = df["USA_WIND"].fillna(df["WMO_WIND"]) * 0.5144
    df = df[df.wind_ms.notna()].copy()
    lat, lon = config.CENTER
    p = np.pi / 180
    a = np.sin((df.LAT - lat) * p / 2) ** 2 + np.cos(lat * p) * np.cos(df.LAT * p) * np.sin((df.LON - lon) * p / 2) ** 2
    df["d_km"] = 12742 * np.arcsin(np.sqrt(a))
    df["rmax_km"] = (df.USA_RMW * 1.852).fillna(40.0)  # default radius of maximum wind where the archive has none
    df["v_site"] = _holland(df.wind_ms, df.d_km, df.rmax_km)
    g = df.groupby("SID").agg(name=("NAME", "first"), year=("ISO_TIME", lambda s: int(str(s.iloc[0])[:4])), closest_km=("d_km", "min"),
                              vmax_kt=("wind_ms", lambda s: s.max() / 0.5144), v_site=("v_site", "max")).reset_index()
    return g[g.closest_km < 500].sort_values("v_site", ascending=False)


class Storm:
    key, label, unit = "storm", "Storm (cyclone)", "wind at site (m/s)"

    def __init__(self, name, year, v_site, closest_km, vmax_kt):
        self.name, self.year, self.v, self.closest, self.vmax = name, year, v_site, closest_km, vmax_kt
        self.rung = f"{name.title()} {year}"

    def assess(self, base):
        if not hasattr(base, "tree"):
            base.tree = tree_share(base.edges)
        factor = (self.v / config.STORM_WIND_DAMAGE_MS) ** 2 if self.v >= config.STORM_WIND_DAMAGE_MS else 0.0
        score = base.tree * factor  # tree share x (wind / threshold)^2: wind force grows with the square of speed
        ec = _classify(score, [(1e-9, 1), (1.0, 2), (2.0, 3), (3.0, 4)])
        ec = np.where(base.edges.bridge.values, 0, ec)  # wind does not bring down a bridge deck; tree-fall is a road effect
        power = (base.facilities.group.values == "power") & (self.v >= config.POWER_WIND_FAIL_MS)
        fc = np.where(power, 3, 0)
        return _result(ec, np.full(len(ec), self.v), fc, np.full(len(fc), self.v))

    def event_text(self, base):
        return (f"Real cyclone from NOAA IBTrACS: **{self.name.title()} ({self.year})**, peak {self.vmax:.0f} kt, closest approach {self.closest:.0f} km; "
                f"estimated wind at the study area {self.v:.0f} m/s ({self.v * 3.6:.0f} km/h).")


# ------------------------------------------------------------------ earthquake
# Raghukanth & Iyengar (2007), J. Earth Syst. Sci. 116(3): peninsular India, Southern region (Mumbai lies south of the
# paper's western-central boundary), PGA at bedrock: ln y = c1 + c2 (M-6) + c3 (M-6)^2 - ln R - c4 R, R = hypocentral distance (km).
# Coefficients and site-amplification table (ln Fs = a1 y_br + a2 by NEHRP class) as published in the OpenQuake hazardlib source.
RI_BEDROCK = dict(c1=1.7816, c2=0.9205, c3=-0.0673, c4=0.0035)
RI_SITE = {"A": (0.0, 0.36), "B": (0.0, 0.49), "C": (-0.89, 0.66), "D": (-2.61, 0.80)}  # E (Vs30 < 180) is unsupported: treated as D
VULNERABILITY = {"road": 0.7, "bridge": 1.3, "facility": 1.0}  # assumed multipliers on PGA for damage classification
PGA_CUTS_G = [(0.1, 1), (0.2, 2), (0.3, 3), (0.4, 4)]


def _vs30_at(lons, lats):
    """USGS global Vs30 grid (30 arc-second), read as a small window straight from the remote file."""
    path = "data/vs30_window.npz"
    if not os.path.exists(path):
        import fsspec
        import h5py

        lat, lon = config.CENTER
        d = config.DIST_M / 111320 * 1.6
        fs = fsspec.filesystem("http", ssl=ssl.create_default_context(cafile=certifi.where()))
        with fs.open(config.VS30_GRID_URL, "rb", block_size=2**20) as f, h5py.File(f, "r") as h:
            la, lo = h["lat"][:], h["lon"][:]
            iy = np.where((la >= lat - d) & (la <= lat + d))[0]
            ix = np.where((lo >= lon - d) & (lo <= lon + d))[0]
            np.savez(path, z=h["z"][iy.min():iy.max() + 1, ix.min():ix.max() + 1], lat=la[iy], lon=lo[ix])
    w = np.load(path)
    iy = np.abs(w["lat"][:, None] - np.asarray(lats)[None, :]).argmin(0)
    ix = np.abs(w["lon"][:, None] - np.asarray(lons)[None, :]).argmin(0)
    return w["z"][iy, ix]


def _site_class(vs30):
    return np.where(vs30 >= 1500, "A", np.where(vs30 >= 760, "B", np.where(vs30 >= 360, "C", "D")))


def nearest_fault(base):
    """Distance (km) and name of the nearest mapped active fault in the GEM Global Active Faults database."""
    if not os.path.exists(config.GEM_FAULTS):
        open(config.GEM_FAULTS, "w").write(requests.get(config.GEM_FAULTS_URL, timeout=600).text)
    g = gpd.read_file(config.GEM_FAULTS)
    lat, lon = config.CENTER
    site = gpd.GeoSeries([Point(lon, lat)], crs=4326).to_crs(config.CRS_PROJECTED).iloc[0]
    d = g.to_crs(config.CRS_PROJECTED).geometry.distance(site) / 1000
    i = int(d.idxmin())
    return float(d[i]), str(g.loc[i].get("slip_type", "fault")), g.loc[i].get("name")


def strongest_recorded():
    """Strongest earthquake within 500 km of the study area in the USGS catalogue."""
    lat, lon = config.CENTER
    r = requests.get("https://earthquake.usgs.gov/fdsnws/event/1/query", timeout=120,
                     params=dict(format="csv", latitude=lat, longitude=lon, maxradiuskm=500, minmagnitude=4.5, starttime="1900-01-01", orderby="magnitude", limit=1))
    return pd.read_csv(io.StringIO(r.text)).iloc[0]


class Quake:
    key, label, unit = "quake", "Earthquake", "peak ground acceleration (g)"

    def __init__(self, mag, fault_km, fault_type, depth_km=10.0):
        self.mag, self.fault_km, self.fault_type, self.depth = mag, fault_km, fault_type, depth_km
        self.rung = f"M{mag:g}"

    def pga_bedrock(self):
        c = RI_BEDROCK
        R = np.hypot(self.fault_km, self.depth)
        return float(np.exp(c["c1"] + c["c2"] * (self.mag - 6) + c["c3"] * (self.mag - 6) ** 2 - np.log(R) - c["c4"] * R))

    def _pga_site(self, x, y):
        lon, lat = TO_LL.transform(x, y)
        vs30 = _vs30_at(lon, lat)
        ybr = self.pga_bedrock()
        a1a2 = np.array([RI_SITE[k] for k in _site_class(vs30)])
        return ybr * np.exp(a1a2[:, 0] * ybr + a1a2[:, 1]), vs30

    def assess(self, base):
        mids = [g.interpolate(0.5, normalized=True) for g in base.edges.geometry]
        pe, _ = self._pga_site([m.x for m in mids], [m.y for m in mids])
        vul = np.where(base.edges.bridge.values, VULNERABILITY["bridge"], VULNERABILITY["road"])
        pf, _ = self._pga_site([p.x for p in base.facilities.geometry], [p.y for p in base.facilities.geometry])
        return _result(_classify(pe * vul, PGA_CUTS_G), pe, _classify(pf * VULNERABILITY["facility"], PGA_CUTS_G), pf)

    def event_text(self, base):
        return (f"Scenario earthquake M{self.mag:g} on the nearest mapped fault ({self.fault_km:.0f} km away, GEM Global Active Faults: {self.fault_type}), "
                f"bedrock PGA {self.pga_bedrock():.2f} g, amplified by local soil from the USGS Vs30 grid.")


def ladders(base):
    """The three severity rungs per disaster: flood stages, the three real strongest storms, earthquake magnitudes."""
    out = {"flood": [Flood(s) for s in config.STAGE_LADDER_M]}
    cat = storm_catalogue().head(config.STORM_LADDER_N)
    storms = [Storm(r["name"], int(r.year), r.v_site, r.closest_km, r.vmax_kt) for _, r in cat.iterrows()]
    out["storm"] = sorted(storms, key=lambda s: s.v)
    km, typ, _ = nearest_fault(base)
    out["quake"] = [Quake(m, km, typ) for m in config.QUAKE_LADDER_MAG]
    return out
