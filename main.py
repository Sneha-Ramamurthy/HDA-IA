"""CLI: build (or load) every disaster assessment and write outputs/."""
import pandas as pd

from cache import load_or_build
from emdat_chart import make_emdat_charts
from visualize import make_map, plot_curves


def main():
    base, out = load_or_build()
    print(f"{base.G.number_of_nodes()} junctions, {base.G.number_of_edges()} road segments, {len(base.facilities)} facilities "
          f"({base.facilities.group.value_counts().to_dict()})")
    pd.set_option("display.width", 250)
    for key, o in out.items():
        r = o.res
        print(f"\n== {r.hazard.label}: severe case ({r.hazard.rung}) ==")
        print(o.table.to_string(index=False))
        assert r.ev.J_pre <= r.ev.evaluate()[0] + 1e-6
        for u in list(r.ev.damaged):
            r.ev.repair(u)
        assert abs(r.ev.evaluate()[0] - r.ev.J_pre) < 1e-6  # everything repaired -> back to normal
        r.ev.reset()
        if hasattr(r, "ranking"):
            r.ranking.drop(columns=["key"]).to_csv(f"outputs/repair_plan_{key}.csv", index=False)
            make_map(r, path=f"outputs/map_{key}.html")
            plot_curves(r.curves, r.grid, path=f"outputs/recovery_curve_{key}.png")
    make_emdat_charts()
    print("\nDone: outputs/map_<disaster>.html, repair_plan_<disaster>.csv, recovery_curve_<disaster>.png")


if __name__ == "__main__":
    main()
