"""Load the saved assessments, rebuilding them in a separate process when code, settings or data changed."""
import hashlib
import os
import pickle
import subprocess
import sys

import config

CODE = ["config.py", "hazards.py", "pipeline.py", "prioritize.py", "graph_model.py", "dem_hazard.py", "assets.py", "data_loader.py"]


def signature():
    h = hashlib.sha1()
    for f in CODE:
        h.update(open(f, "rb").read())
    h.update(str(os.path.getmtime("data/roads.graphml") if os.path.exists("data/roads.graphml") else 0).encode())
    return h.hexdigest()


def load_or_build():
    """Return (base, results). Builds in a fresh interpreter (fork-safe) if the saved copy is missing or stale."""
    if os.path.exists(config.RESULT_CACHE):
        with open(config.RESULT_CACHE, "rb") as f:
            sig, base, results = pickle.load(f)
        if sig == signature():
            return base, results
    subprocess.run([sys.executable, "build.py"], check=True)
    with open(config.RESULT_CACHE, "rb") as f:
        _, base, results = pickle.load(f)
    return base, results
