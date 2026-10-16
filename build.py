"""Build every assessment once and save it to disk (run by cache.py in a fresh process, or by hand)."""
import pickle
import time

import config
from cache import signature
from pipeline import assess_all, prepare

if __name__ == "__main__":
    t = time.time()
    base = prepare()
    print(f"network: {base.G.number_of_nodes()} junctions, {base.G.number_of_edges()} segments, {len(base.facilities)} facilities", flush=True)
    results = assess_all(base)
    for o in results.values():
        o.res.ev.reset()
    with open(config.RESULT_CACHE, "wb") as f:
        pickle.dump((signature(), base, results), f, protocol=5)
    print(f"built in {time.time() - t:.0f} s", flush=True)
