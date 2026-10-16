"""Road graph, facility snapping and the multi-service access objective (fast, scipy-based)."""
import geopandas as gpd
import networkx as nx
import numpy as np
import scipy.sparse as sp
from scipy.sparse.csgraph import dijkstra
from shapely.geometry import LineString

import config

SPEED_MS = config.SPEED_KMH / 3.6
T_CAP = config.T_CAP_MIN * 60.0
BIG = 1e9


def eid(u, v):
    return (u, v) if u <= v else (v, u)


def _lanes(tag, highway):
    """Lane count from the OSM `lanes` tag, else a default by road class."""
    for v in (tag if isinstance(tag, list) else [tag]):
        try:
            return max(1, int(float(v)))
        except (TypeError, ValueError):
            pass
    return config.DEFAULT_LANES.get(str(highway).replace("_link", ""), 1)


def build_graph(Gm):
    """Collapse the OSM MultiDiGraph to a simple undirected graph (shortest parallel edge kept)."""
    Gm = Gm.subgraph(max(nx.weakly_connected_components(Gm), key=len)).copy()
    G = nx.Graph()
    for n, d in Gm.nodes(data=True):
        G.add_node(n, x=d["x"], y=d["y"])
    for u, v, d in Gm.edges(data=True):
        if u == v:
            continue
        if G.has_edge(u, v) and G[u][v]["length"] <= d["length"]:
            continue
        geom = d.get("geometry") or LineString([(G.nodes[u]["x"], G.nodes[u]["y"]), (G.nodes[v]["x"], G.nodes[v]["y"])])
        name = d.get("name", "")
        name = ", ".join(name) if isinstance(name, list) else name
        hw = d.get("highway", "")
        hw = hw[0] if isinstance(hw, list) else hw
        br = d.get("bridge")
        br = bool(br) and str(br).lower() not in ("no", "none", "nan")
        G.add_edge(u, v, length=d["length"], travel_time=d["length"] / SPEED_MS, geometry=geom, name=name, highway=hw,
                   lanes=_lanes(d.get("lanes"), hw), bridge=br)
    return G


def edges_gdf(G):
    rows = [dict(u=u, v=v, **{k: d[k] for k in ("length", "name", "highway", "lanes", "bridge", "geometry")}) for u, v, d in G.edges(data=True)]
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=config.CRS_PROJECTED)


def snap_points(G, points):
    """Nearest graph node for each point geometry."""
    ids = list(G.nodes)
    xy = np.array([(G.nodes[n]["x"], G.nodes[n]["y"]) for n in ids])
    return [ids[int(np.argmin(((xy - (p.x, p.y)) ** 2).sum(1)))] for p in points]


class Evaluator:
    """Service-access cost J on a road graph where damaged roads and facilities can be switched back on.

    For every service group (health, emergency, power, water, transport) each junction's travel time to the nearest
    functioning facility is capped at T_CAP; J is the sum over junctions and groups (lower is better). A junction
    farther than T_CAP from every functioning facility of a group counts as "cut off" from that service.
    """

    def __init__(self, G, facilities, damaged_edges, damaged_facs, t_cap=T_CAP):
        self.cap = float(t_cap)
        self.nodes = list(G.nodes)
        self.idx = {n: i for i, n in enumerate(self.nodes)}
        self.N = len(self.nodes)
        edges = list(G.edges(data=True))
        ids, rows, cols = [], [], []
        for k, (u, v, _) in enumerate(edges):
            iu, iv = self.idx[u], self.idx[v]
            rows += [iu, iv]
            cols += [iv, iu]
            ids += [2 * k + 1, 2 * k + 2]
        m = sp.coo_matrix((ids, (rows, cols)), shape=(self.N, self.N)).tocsr()
        self.pos = np.empty(2 * len(edges), dtype=int)
        self.pos[m.data - 1] = np.arange(len(m.data))
        self.tt = np.repeat([d["travel_time"] for _, _, d in edges], 2).astype(float)
        m.data = self.tt[m.data - 1].astype(float)
        self.csr = m
        self.eidx = {eid(u, v): k for k, (u, v, _) in enumerate(edges)}
        # facilities
        self.fac = facilities  # list of dicts: group, node, cost, name, kind
        self.groups = sorted({f["group"] for f in facilities})
        self.func = {g: {} for g in self.groups}
        for f in facilities:
            self._add_fac(f)
        # units that can be repaired
        self.damaged = {}
        for e in damaged_edges:
            d = G.edges[e]
            self.damaged[e] = dict(kind="road", cost=d["cost"], length=d["length"], name=d["name"], highway=d["highway"],
                                   bridge=d["bridge"], nodes=(self.idx[e[0]], self.idx[e[1]]))
        for i in damaged_facs:
            f = facilities[i]
            self.damaged[("F", i)] = dict(kind="facility", cost=f["cost"], length=0.0, name=f["name"] or f["kind"], highway=f["kind"],
                                          bridge=False, group=f["group"], nodes=(self.idx[f["node"]],))
        self.J_pre, _ = self.evaluate()
        self.pre_groups = self.group_metrics()
        self.repaired = set(self.damaged)  # everything is "repaired" until the damage is applied
        self.reset()

    # -- state changes ------------------------------------------------------
    def _add_fac(self, f, delta=1):
        n = self.idx[f["node"]]
        d = self.func[f["group"]]
        d[n] = d.get(n, 0) + delta
        if d[n] <= 0:
            del d[n]

    def _set_edge(self, e, on):
        k = self.eidx[eid(*e)]
        for p in (self.pos[2 * k], self.pos[2 * k + 1]):
            self.csr.data[p] = self.tt[2 * k] if on else BIG

    def repair(self, unit):
        if unit in self.repaired:
            return
        self.repaired.add(unit)
        if unit[0] == "F":
            self._add_fac(self.fac[unit[1]])
        else:
            self._set_edge(unit, True)

    def undo(self, unit):
        if unit not in self.repaired:
            return
        self.repaired.discard(unit)
        if unit[0] == "F":
            self._add_fac(self.fac[unit[1]], -1)
        else:
            self._set_edge(unit, False)

    def reset(self):
        for u in list(self.damaged):
            self.undo(u)

    # -- measurement --------------------------------------------------------
    def _dist(self, g):
        src = list(self.func[g].keys())
        if not src:
            return np.full(self.N, np.inf)
        return dijkstra(self.csr, directed=True, indices=src, min_only=True, limit=self.cap)

    def evaluate(self):
        """Return (J, boolean mask of junctions served by at least one group)."""
        J, reached = 0.0, np.zeros(self.N, dtype=bool)
        for g in self.groups:
            d = self._dist(g)
            J += config.GROUP_WEIGHT * np.minimum(d, self.cap).sum()
            reached |= d <= self.cap
        return J, reached

    def group_metrics(self):
        out = {}
        for g in self.groups:
            d = self._dist(g)
            out[g] = dict(facilities=sum(self.func[g].values()), cut_off=int((d > self.cap).sum()), mean_min=float(np.minimum(d, self.cap).mean() / 60))
        return out

    def cut_off_nodes(self, group="health"):
        d = self._dist(group)
        return [self.nodes[i] for i in np.flatnonzero(d > self.cap)]
