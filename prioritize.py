"""Lazy-greedy repair ranking (roads, bridges and facilities together) plus longest-first and random baselines."""
import heapq
import itertools
import random
from collections import defaultdict

import numpy as np

import config


def _cost(ev, u):
    return max(ev.damaged[u]["cost"], 0.01)  # rupee lakh; floor avoids divide-by-zero


def greedy_ranking(ev, max_steps=config.MAX_STEPS, cost_aware=config.COST_AWARE):
    """Repeatedly repair the damaged asset with the best service-access gain per rupee until all lost access is back.

    Lazy evaluation: stored scores are upper-bound estimates, refreshed only for the current best candidate. A damaged
    road can only help if it touches the area already served by some facility, so only those are scored; damaged
    facilities are always candidates.
    """
    ev.reset()
    J, reached = ev.evaluate()
    node_units = defaultdict(list)
    for u, d in ev.damaged.items():
        if d["kind"] == "road":
            for n in d["nodes"]:
                node_units[n].append(u)
    tick = itertools.count()
    heap, seen = [], set()

    def score(u):
        ev.repair(u)
        gain = J - ev.evaluate()[0]
        ev.undo(u)
        return (gain / _cost(ev, u) if cost_aware else gain), gain

    def push(units):
        for u in units:
            if u not in seen and u not in ev.repaired:
                seen.add(u)
                s, g = score(u)
                heapq.heappush(heap, (-s, next(tick), u, g))

    push([u for u, d in ev.damaged.items() if d["kind"] == "facility"])
    push([u for n in np.flatnonzero(reached) for u in node_units.get(n, [])])
    order, gains = [], []
    while heap and len(order) < max_steps and J > ev.J_pre + 1e-6:
        while True:
            _, _, u, _ = heapq.heappop(heap)
            if u in ev.repaired:
                continue
            s, g = score(u)
            if not heap or s >= -heap[0][0] - 1e-12:
                break
            heapq.heappush(heap, (-s, next(tick), u, g))
        if g <= 0:  # no single repair helps: extend reach with the cheapest road that leaves the served area
            heapq.heappush(heap, (0.0, next(tick), u, 0.0))
            pool = [x[2] for x in heap if x[2] not in ev.repaired]
            roads = [x for x in pool if ev.damaged[x]["kind"] == "road" and reached[ev.damaged[x]["nodes"][0]] != reached[ev.damaged[x]["nodes"][1]]]
            u = min(roads or pool, key=lambda x: _cost(ev, x))
            g = 0.0
        ev.repair(u)
        old = reached
        J, reached = ev.evaluate()
        order.append(u)
        gains.append(g)
        push([x for n in np.flatnonzero(reached & ~old) for x in node_units.get(n, [])])
    ev.reset()
    return order, gains


def longest_first(ev, max_steps=config.MAX_STEPS):
    return sorted(ev.damaged, key=lambda u: -ev.damaged[u]["length"])[:max_steps]


def random_orders(ev, n=config.N_RANDOM, max_steps=config.MAX_STEPS, seed=config.SEED):
    rng = random.Random(seed)
    base = list(ev.damaged)
    out = []
    for _ in range(n):
        rng.shuffle(base)
        out.append(base[:max_steps])
    return out


def recovery_curve(ev, order, samples=None):
    """Return (cumulative repair cost in rupee crore, % of lost access recovered), starting at 0.

    Evaluated after every repair, or, when `samples` is given, after about that many evenly spaced repairs.
    """
    ev.reset()
    J_post = ev.evaluate()[0]
    n = len(order)
    marks = set(range(1, n + 1)) if not samples or samples >= n else set(np.unique(np.linspace(1, n, samples).astype(int)).tolist())
    cost, rec = [0.0], [0.0]
    total = 0.0
    for i, u in enumerate(order, 1):
        ev.repair(u)
        total += ev.damaged[u]["cost"] / 100
        if i in marks:
            cost.append(total)
            rec.append(100 * (J_post - ev.evaluate()[0]) / (J_post - ev.J_pre) if J_post > ev.J_pre else 100.0)
    ev.reset()
    return np.array(cost), np.array(rec)


def auc(cost, rec, grid):
    return float(np.trapezoid(np.interp(grid, cost, rec), grid) / grid[-1])
