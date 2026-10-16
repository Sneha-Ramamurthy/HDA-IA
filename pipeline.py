"""Assessment pipeline for any disaster: hazard -> damaged roads, bridges and facilities -> service access -> repair plan."""
from types import SimpleNamespace

import numpy as np
import pandas as pd

import config
import hazards
from assets import load_assets
from data_loader import load_data
from graph_model import Evaluator, build_graph, edges_gdf, snap_points
from prioritize import auc, greedy_ranking, longest_first, random_orders, recovery_curve


def road_cost_lakh(length_m, highway, hazard, lanes, bridge):
    """Estimated road repair cost in rupee lakh: length x lanes x rate per lane-km x share needing reconstruction (x bridge factor)."""
    rate = config.RUPEE_LAKH_PER_LANE_KM.get(str(highway).replace("_link", ""), config.DEFAULT_RATE_LAKH_PER_LANE_KM)
    cost = length_m / 1000 * lanes * rate * config.DAMAGE_FRACTION.get(int(hazard), 0.0)
    return cost * (config.BRIDGE_COST_FACTOR if bridge else 1)


def facility_cost_lakh(kind, hazard):
    return config.FACILITY_COST_LAKH.get(kind, config.DEFAULT_FACILITY_COST_LAKH) * config.DAMAGE_FRACTION.get(int(hazard), 0.0)


def prepare():
    """Load OpenStreetMap roads, facilities and the river once."""
    Gm, _, water = load_data()
    G = build_graph(Gm)
    fac = load_assets()
    fac["node"] = snap_points(G, fac.geometry)
    return SimpleNamespace(G=G, water=water, edges=edges_gdf(G), facilities=fac)


def run(base, hazard, t_cap_min=config.T_CAP_MIN, max_steps=None, cost_aware=config.COST_AWARE,
        n_random=config.N_RANDOM, baselines=True):
    G = base.G
    a = hazard.assess(base)
    edges, fac = base.edges.copy(), base.facilities.copy().reset_index(drop=True)
    edges["hazard"], edges["metric"] = a.edge_class, a.edge_metric
    fac["hazard"], fac["metric"] = a.fac_class, a.fac_metric
    edges["damaged"] = edges.hazard >= config.DAMAGE_THRESHOLD
    fac["damaged"] = fac.hazard >= config.DAMAGE_THRESHOLD
    edges["cost_lakh"] = [road_cost_lakh(r.length, r.highway, r.hazard, r.lanes, r.bridge) for r in edges.itertuples()]
    fac["cost_lakh"] = [facility_cost_lakh(r.kind, r.hazard) for r in fac.itertuples()]
    for r in edges.itertuples():
        G.edges[r.u, r.v]["cost"] = r.cost_lakh
    dam_e = [(r.u, r.v) for r in edges[edges.damaged].itertuples()]
    dam_f = [int(i) for i in fac.index[fac.damaged]]
    facs = [dict(group=r.group, kind=r.kind, name=r.name, node=r.node, cost=r.cost_lakh) for r in fac.itertuples()]
    ev = Evaluator(G, facs, dam_e, dam_f, config.T_CAP_MIN * 60.0 if t_cap_min is None else t_cap_min * 60.0)
    res = SimpleNamespace(hazard=hazard, base=base, edges=edges, fac=fac, dam_e=dam_e, dam_f=dam_f, ev=ev,
                          pre_groups=ev.pre_groups, post_groups=ev.group_metrics(), n_units=len(ev.damaged))
    res.total_cost_crore = float((edges.loc[edges.damaged, "cost_lakh"].sum() + fac.loc[fac.damaged, "cost_lakh"].sum()) / 100)
    if not ev.damaged:
        return res
    res.cut_nodes = ev.cut_off_nodes("health")
    res.order, res.gains = greedy_ranking(ev, max_steps or len(ev.damaged), cost_aware)
    res.curves = {"greedy": recovery_curve(ev, res.order)}
    if baselines:
        res.curves["longest"] = recovery_curve(ev, longest_first(ev, len(res.order)), config.CURVE_POINTS)
        res.curves["random"] = [recovery_curve(ev, o, config.CURVE_POINTS) for o in random_orders(ev, n_random, len(res.order))]
        ends = [res.curves["greedy"][0][-1], res.curves["longest"][0][-1]] + [k[-1] for k, _ in res.curves["random"]]
        res.grid = np.linspace(0, min(ends), 200)
        res.scores = {"Greedy": auc(*res.curves["greedy"], res.grid), "Longest-first": auc(*res.curves["longest"], res.grid),
                      "Random (mean)": float(np.mean([auc(k, r, res.grid) for k, r in res.curves["random"]]))}
    cost, rec = res.curves["greedy"]
    phase = np.select([rec[1:] < 50, rec[1:] < 80], [1, 2], 3)
    rows = []
    for i, u in enumerate(res.order):
        d = ev.damaged[u]
        if d["kind"] == "road":
            r = edges[(edges.u == u[0]) & (edges.v == u[1])].iloc[0]
            asset, typ, grp, metric, ln = (d["name"] or d["highway"]), ("bridge" if d["bridge"] else d["highway"]), "road", r.metric, round(d["length"])
        else:
            r = fac.loc[u[1]]
            asset, typ, grp, metric, ln = (d["name"] or d["highway"]), d["highway"], d["group"], r.metric, None
        rows.append(dict(priority=i + 1, phase=int(phase[i]), kind=d["kind"], asset=asset, type=typ, group=grp, length_m=ln, hazard_metric=round(float(metric), 3),
                         repair_cost_lakh=round(d["cost"], 1), cum_cost_crore=round(cost[i + 1], 2), cum_access_recovered_pct=round(rec[i + 1], 1), key=u))
    res.ranking = pd.DataFrame(rows)
    res.plan_cost_crore = float(cost[-1])
    return res


def summary_row(res, label):
    ev_h = res.post_groups.get("health", {})
    return {"Scenario": label, "Damaged roads": int(res.edges.damaged.sum()), "of which bridges": int((res.edges.damaged & res.edges.bridge).sum()),
            "Damaged facilities": int(res.fac.damaged.sum()), "Junctions cut off from hospitals": ev_h.get("cut_off", 0),
            "Mean time to hospital (min)": round(ev_h.get("mean_min", 0), 1), "Repair budget, all damaged (₹ crore)": round(res.total_cost_crore, 1),
            "Plan to restore access (₹ crore)": round(getattr(res, "plan_cost_crore", 0.0), 1), "Repairs in plan": len(getattr(res, "order", []))}


_BASE, _LADDERS = None, None


def _job(args):
    key, i, full = args
    res = run(_BASE, _LADDERS[key][i], baselines=full)
    res.base = None  # keep the big shared network out of the result; it is re-attached by the parent
    return key, i, res


def assess_all(base, workers=8):
    """Run every severity rung of every disaster in parallel; the most severe rung of each also gets the full recovery curves."""
    import multiprocessing as mp
    from concurrent.futures import ProcessPoolExecutor

    global _BASE, _LADDERS
    _BASE, _LADDERS = base, hazards.ladders(base)
    base.tree = hazards.tree_share(base.edges)  # warm the shared inputs once, before forking
    hazards._vs30_at([config.CENTER[1]], [config.CENTER[0]])
    jobs = [(k, i, i == len(r) - 1) for k, r in _LADDERS.items() for i in range(len(r))]
    jobs.sort(key=lambda j: -(j[1] + (10 if j[0] == "flood" else 0)))  # start the heaviest (most severe flood) first
    with ProcessPoolExecutor(max_workers=min(workers, len(jobs)), mp_context=mp.get_context("fork")) as ex:
        done = {(k, i): r for k, i, r in ex.map(_job, jobs)}
    out = {}
    for key, rungs in _LADDERS.items():
        rows = []
        for i, h in enumerate(rungs):
            done[(key, i)].base = base
            rows.append(summary_row(done[(key, i)], h.rung))
        out[key] = SimpleNamespace(res=done[(key, len(rungs) - 1)], table=pd.DataFrame(rows), rungs=rungs)
    return out
