"""Pick the reference flood automatically: the EM-DAT flood whose river basin matches a river in the study area."""
import re

import pandas as pd


def river_keywords(water):
    """Distinctive words from OSM waterway names, e.g. 'Mithi River' -> 'Mithi'."""
    names = water["name"].dropna().unique() if "name" in water else []
    words = set()
    for n in names:
        for w in re.findall(r"[A-Za-z]{4,}", n):
            if w.lower() not in {"river", "creek", "canal", "nalla", "nallah", "stream", "drain"}:
                words.add(w)
    return sorted(words)


def reference_event(water, india):
    """Return the most deadly EM-DAT flood whose River Basin names a study-area river (a pandas Series), or None."""
    fl = india[india["Disaster Type"].eq("Flood")]
    for w in river_keywords(water):
        hit = fl[fl["River Basin"].str.contains(w, na=False, case=False)]
        if len(hit):
            ev = hit.sort_values("Total Deaths", ascending=False).iloc[0].copy()
            ev["matched_river"] = w
            return ev
    return None
