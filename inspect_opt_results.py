import os

if "NOJIT" not in os.environ:
    os.environ["NOJIT"] = "true"

import json
import pprint
import numpy as np
from prettytable import PrettyTable
import argparse
import hjson
from procedures import load_live_config, dump_live_config, make_get_filepath
from pure_funcs import config_pretty_str, candidate_to_live_config
from njit_funcs import round_dynamic


def main():

    parser = argparse.ArgumentParser(prog="view conf", description="inspect conf")
    parser.add_argument("results_fpath", type=str, help="path to results file")
    weights_keys = [
        ("psl", "maximum_pa_distance_std_long"),
        ("pss", "maximum_pa_distance_std_short"),
        ("pml", "maximum_pa_distance_mean_long"),
        ("pms", "maximum_pa_distance_mean_short"),
        ("pll", "maximum_loss_profit_ratio_long"),
        ("pls", "maximum_loss_profit_ratio_short"),
        ("hsl", "maximum_hrs_stuck_max_long"),
        ("hss", "maximum_hrs_stuck_max_short"),
        ("erl", "minimum_eqbal_ratio_min_long"),
        ("ers", "minimum_eqbal_ratio_min_short"),
    ]
    for k0, k1 in weights_keys:
        parser.add_argument(
            f"-{k0}",
            f"--{k1}",
            dest=k1,
            type=float,
            required=False,
            default=None,
            help=f"max {k1}",
        )
    parser.add_argument(
        "-i",
        "--index",
        dest="index",
        type=int,
        required=False,
        default=0,
        help="best conf index, default=0",
    )
    parser.add_argument(
        "-d",
        "--dump_live_config",
        action="store_true",
        help="dump config",
    )

    args = parser.parse_args()

    # attempt guessing whether harmony search or particle swarm
    opt_config_path = (
        "configs/optimize/harmony_search.hjson"
        if "harmony" in args.results_fpath
        else "configs/optimize/particle_swarm_optimization.hjson"
    )

    opt_config = hjson.load(open(opt_config_path))
    minsmaxs = {}
    for _, k1 in weights_keys:
        minsmaxs[k1] = opt_config[k1] if getattr(args, k1) is None else getattr(args, k1)
    klen = max([len(k) for k in minsmaxs])
    for k, v in minsmaxs.items():
        print(f"{k: <{klen}} {v}")

    with open(args.results_fpath) as f:
        results = [json.loads(x) for x in f.readlines()]
    print(f"{'n results': <{klen}} {len(results)}")

    sides = ["long", "short"]
    keys = [
        ("adg_realized_per_exposure", True),
        ("pa_distance_std", False),
        ("pa_distance_mean", False),
        ("hrs_stuck_max", False),
        ("loss_profit_ratio", False),
        ("eqbal_ratio_min", True),
    ]
    all_scores = []
    symbols = [s for s in results[0]["results"] if s != "config_no"]
    for r in results:
        cfg = r["config"]
        ress = r["results"]

        means = {s: {} for s in sides}  # adjusted means
        scores = {s: -1.0 for s in sides}
        raws = {s: {} for s in sides}  # unadjusted means
        all_scores.append({})
        for side in sides:
            for key, mult in keys:
                raws[side][key] = np.mean([ress[s][f"{key}_{side}"] for s in symbols])
                if (max_key := f"maximum_{key}_{side}") in minsmaxs:
                    if minsmaxs[max_key] >= 0.0:
                        ms = [max(minsmaxs[max_key], ress[s][f"{key}_{side}"]) for s in symbols]
                        means[side][key] = max(minsmaxs[max_key], np.mean(ms))
                    else:
                        means[side][key] = 1.0
                elif (min_key := f"minimum_{key}_{side}") in minsmaxs:
                    if minsmaxs[min_key] >= 0.0:
                        ms = [min(minsmaxs[min_key], ress[s][f"{key}_{side}"]) for s in symbols]
                        means[side][key] = min(minsmaxs[min_key], np.mean(ms))
                    else:
                        means[side][key] = 1.0
                else:
                    means[side][key] = np.mean([ress[s][f"{key}_{side}"] for s in symbols])
                if mult:
                    scores[side] *= means[side][key]
                else:
                    scores[side] /= means[side][key]
            all_scores[-1][side] = {
                "config": cfg[side],
                "score": scores[side],
                "stats": {s: {k: v for k, v in ress[s].items() if side in k} for s in symbols},
                "config_no": ress["config_no"],
            }
    best_candidate = {}
    for side in sides:
        scoress = sorted([sc[side] for sc in all_scores], key=lambda x: x["score"])
        best_candidate[side] = scoress[args.index]
    best_config = {
        "long": best_candidate["long"]["config"],
        "short": best_candidate["short"]["config"],
    }
    for side in sides:
        row_headers = ["symbol"] + [k[0] for k in keys]
        table = PrettyTable(row_headers)
        for rh in row_headers:
            table.align[rh] = "l"
        table.title = (
            f"{side} (config no. {best_candidate[side]['config_no']},"
            + f" score {round_dynamic(best_candidate[side]['score'], 6)})"
        )
        for s in sorted(
            symbols,
            key=lambda x: best_candidate[side]["stats"][x][f"adg_realized_per_exposure_{side}"],
        ):
            xs = [best_candidate[side]["stats"][s][f"{k[0]}_{side}"] for k in keys]
            table.add_row([s] + [round_dynamic(x, 4) for x in xs])
        means = [
            np.mean([best_candidate[side]["stats"][s_][f"{k[0]}_{side}"] for s_ in symbols])
            for k in keys
        ]
        table.add_row(["mean"] + [round_dynamic(m, 4) for m in means])
        print(table)
    live_config = candidate_to_live_config(best_config)
    if args.dump_live_config:
        lc_fpath = make_get_filepath(f"{args.results_fpath.replace('.txt', '_best_config.json')}")
        print(f"dump_live_config {lc_fpath}")
        dump_live_config(live_config, lc_fpath)
    print(config_pretty_str(live_config))


if __name__ == "__main__":
    main()
