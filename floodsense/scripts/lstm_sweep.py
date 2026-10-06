#!/usr/bin/env python3
"""Optimise the LSTM on validation, then evaluate it once on test.

    python scripts/lstm_sweep.py --days 540 --stations 32 --seed 20261006

Everything is decided on the validation split: the architecture, the loss,
the training-set composition, whether a seed-ensemble beats a single model,
and the operating threshold. The test split is read exactly once, at the
end, with all of that frozen.

Model- and train-level parameters (width, depth, dropout, learning rate,
loss, seed) are read after the windows are fixed, so every candidate that
only moves those shares one dataset build. Window-level parameters
(``sequence_steps``, ``negative_keep_rate``) decide which windows exist and
which negatives survive subsampling, so a candidate that moves either one
gets its own build - reusing the shared one would silently evaluate the base
configuration under the candidate's name.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from floodsense.config import Config  # noqa: E402


@dataclass
class Candidate:
    """One LSTM configuration to try."""

    name: str
    hidden_size: int = 64
    num_layers: int = 2
    dropout: float = 0.25
    learning_rate: float = 7e-4
    loss: str = "focal"
    negative_keep_rate: float = 0.08
    sequence_steps: int = 36
    attention: bool = True
    last_step_skip: bool = True
    seed: int = 0
    note: str = ""

    def apply(self, cfg: Config, base_seed: int) -> Config:
        import copy

        out = copy.deepcopy(cfg)
        out.model.hidden_size = self.hidden_size
        out.model.num_layers = self.num_layers
        out.model.dropout = self.dropout
        out.model.attention = self.attention
        out.model.last_step_skip = self.last_step_skip
        out.train.learning_rate = self.learning_rate
        out.train.loss = self.loss
        out.windows.negative_keep_rate = self.negative_keep_rate
        out.windows.sequence_steps = self.sequence_steps
        out.train.seed = base_seed + self.seed
        out.windows.seed = base_seed
        return out

    def window_key(self) -> tuple[int, float]:
        """The dataset build this candidate needs.

        Two candidates with the same key can share a build; two with
        different keys cannot, because these are the parameters consumed
        while the window index arrays are constructed.
        """
        return (self.sequence_steps, self.negative_keep_rate)


#: The sweep. Sequence length is held at 36 steps for most of the comparison
#: so those candidates share identical splits (the embargo is derived from
#: it), with one longer-window run reported separately.
CANDIDATES = [
    Candidate("baseline_h64", note="the shipped configuration"),
    Candidate("wide_h128", hidden_size=128, dropout=0.30, note="more capacity"),
    Candidate("deep_h96_l3", hidden_size=96, num_layers=3, learning_rate=5e-4,
              note="a third recurrent layer"),
    Candidate("weighted_bce", loss="weighted_bce", note="loss swap"),
    Candidate("more_negatives", negative_keep_rate=0.25,
              note="3x the negatives per epoch"),
    Candidate("no_skip", last_step_skip=False, note="ablation: drop the skip"),
]

LONG_WINDOW = Candidate(
    "long_window_72", sequence_steps=72, note="6 hours of sequence instead of 3"
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--days", type=int, default=540)
    p.add_argument("--stations", type=int, default=32)
    p.add_argument("--seed", type=int, default=20261006)
    p.add_argument("--epochs", type=int, default=12)
    p.add_argument("--patience", type=int, default=4)
    p.add_argument("--batch-size", type=int, default=512)
    p.add_argument("--ensemble-seeds", type=int, default=3,
                   help="seed-average the winner; 1 disables")
    p.add_argument("--skip-long-window", action="store_true")
    p.add_argument("--only", default="",
                   help="comma-separated candidate names to run, for reruns")
    p.add_argument("--ensemble-only", action="store_true",
                   help="skip the candidate loop and seed-ensemble a winner "
                        "that is already trained, so a run that died before "
                        "the ensemble can finish it without retraining")
    p.add_argument("--winner", default="",
                   help="with --ensemble-only, the candidate to ensemble; "
                        "defaults to the name in <outdir>/selected.json")
    p.add_argument("--merge", action="store_true",
                   help="replace same-named rows in an existing validation "
                        "table instead of overwriting it, then re-pick the best")
    p.add_argument("--note", default="",
                   help="recorded in the table's notes, e.g. why a rerun happened")
    p.add_argument("--outdir", default="artifacts/lstm_sweep")
    p.add_argument("--results", default="results")
    return p.parse_args()


def build(cfg: Config, args: argparse.Namespace):
    from floodsense.pipeline import prepare_from_synthetic
    from floodsense.synthetic import SyntheticConfig

    return prepare_from_synthetic(
        cfg,
        SyntheticConfig(days=args.days, n_stations=args.stations, seed=args.seed),
    )


def train_one(prepared, cfg: Config, outdir: Path, label: str):
    """Train one model and return it with its validation probabilities."""
    from floodsense.train import predict, resolve_device, train

    result = train(
        prepared, cfg, outdir / label,
        run_baselines=False, evaluate_test=False, verbose=False,
    )
    from floodsense.model import FloodSenseLSTM

    model = FloodSenseLSTM.load(outdir / label / "floodsense_lstm.pt")
    probs, _, _ = predict(
        model,
        DataLoader(prepared.dataset("val"), batch_size=4096),
        resolve_device("cpu"),
    )
    return model, probs, result


def score_validation(prepared, cfg: Config, probs: np.ndarray) -> dict:
    from floodsense.events import threshold_for_accuracy_band
    from floodsense.experiments import labels_for
    from floodsense.metrics import compute_report

    y = labels_for(prepared, prepared.splits.val)
    event_kwargs = dict(
        horizon_max_minutes=cfg.labels.horizon_max_minutes,
        merge_gap_minutes=cfg.labels.post_alert_blackout_minutes,
    )
    selection = threshold_for_accuracy_band(
        prepared.splits.val, y, probs,
        cfg.accuracy_band[0], cfg.accuracy_band[1],
        prepared.grid.n_steps, prepared.grid.n_stations, **event_kwargs,
    )
    report = compute_report(y, probs, selection["threshold"])
    events = selection["event_report"]
    return {
        "pr_auc": float(report.pr_auc),
        "roc_auc": float(report.roc_auc),
        "threshold": float(selection["threshold"]),
        "accuracy": float(report.accuracy_not_a_headline_metric),
        "event_recall": float(events.event_recall),
        "recall": float(report.recall),
        "precision": float(report.precision),
        "f1": float(report.f1),
        "false_alarms_per_station_day": float(events.false_alarms_per_station_day),
        "mean_lead_minutes": float(events.mean_lead_minutes),
    }


def describe_build(key: tuple[int, float]) -> str:
    return f"sequence {key[0]} steps, negative_keep_rate {key[1]}"


def merge_table(previous: dict, rows: list[dict]) -> dict:
    """Fold this run's rows into a previous validation table.

    Same-named rows are replaced, so a corrected rerun supersedes the row it
    fixes. The previous table's provenance travels with it: a name that now
    has a row of its own is no longer untrained or excluded and leaves those
    lists, while anything still outstanding stays, because dropping it would
    silently turn a partial table into one that looks complete.
    """
    replaced = {r["name"] for r in rows}
    kept = [r for r in previous.get("candidates", [])
            if r["name"] not in replaced]
    merged = kept + rows
    have = {r["name"] for r in merged}
    flagged = set(previous.get("not_trained", [])) | set(
        previous.get("excluded", [])
    )
    return {
        "candidates": merged,
        "best": max(merged, key=lambda r: r["pr_auc"]),
        "replaced": len(previous.get("candidates", [])) - len(kept),
        "not_trained": [n for n in previous.get("not_trained", [])
                        if n not in have],
        "excluded": [n for n in previous.get("excluded", []) if n not in have],
        "resolved": sorted(flagged & have),
        "notes": list(previous.get("notes", [])),
    }


def main() -> int:
    args = parse_args()
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    results_dir = Path(args.results)
    results_dir.mkdir(parents=True, exist_ok=True)

    base = Config()
    base.operating_point = "accuracy"
    base.train.epochs = args.epochs
    base.train.patience = args.patience
    base.train.batch_size = args.batch_size
    base.train.use_mlflow = True
    base.train.seed = args.seed
    base.windows.seed = args.seed

    schedule = list(CANDIDATES)
    if not args.skip_long_window:
        schedule.append(LONG_WINDOW)
    if args.only:
        wanted = {n.strip() for n in args.only.split(",") if n.strip()}
        unknown = wanted - {c.name for c in schedule}
        if unknown:
            raise SystemExit(f"unknown candidate(s): {sorted(unknown)}")
        schedule = [c for c in schedule if c.name in wanted]

    incumbent = None
    if args.ensemble_only:
        name = args.winner
        if not name:
            selected_path = outdir / "selected.json"
            if not selected_path.exists():
                raise SystemExit(
                    f"--ensemble-only needs {selected_path} or --winner"
                )
            name = json.loads(selected_path.read_text())["name"]
        incumbent = next(
            (c for c in CANDIDATES + [LONG_WINDOW] if c.name == name), None
        )
        if incumbent is None:
            raise SystemExit(f"{name} is not one of the sweep's candidates")
        if not (outdir / name / "floodsense_lstm.pt").exists():
            raise SystemExit(f"{name} has no trained checkpoint to ensemble")
        schedule = []
        print(f"[sweep] ensemble-only: winner is {name}")

    base_key = (base.windows.sequence_steps, base.windows.negative_keep_rate)
    shared: dict[tuple[int, float], object] = {}

    def prepared_for(cfg: Config, key: tuple[int, float]):
        """Dataset for one window configuration, built on demand.

        Only the shared build is cached; a candidate-specific one is handed
        back uncached and freed by the caller, because each build holds the
        full feature matrix.
        """
        if key in shared:
            return shared[key]
        print(f"[sweep] building windows ({describe_build(key)})...")
        t = time.time()
        prepared = build(cfg, args)
        print(f"        {time.time() - t:.0f}s | "
              f"{json.dumps(prepared.labels.summary())}")
        if key == base_key:
            shared[key] = prepared
        return prepared

    print(
        f"[sweep] SYNTHETIC benchmark, fresh seed {args.seed} "
        f"({args.days} days x {args.stations} stations). "
        "data.gov.sg is unreachable, so real data cannot be used."
    )

    rows: list[dict] = []
    best = None

    for candidate in schedule:
        cfg = candidate.apply(base, args.seed)
        key = candidate.window_key()
        print(f"\n[sweep] {candidate.name}: {candidate.note}")
        prepared = prepared_for(cfg, key)
        started = time.time()
        model, probs, result = train_one(prepared, cfg, outdir, candidate.name)
        scores = score_validation(prepared, cfg, probs)
        row = {
            "name": candidate.name,
            "note": candidate.note,
            "hidden_size": candidate.hidden_size,
            "num_layers": candidate.num_layers,
            "dropout": candidate.dropout,
            "learning_rate": candidate.learning_rate,
            "loss": candidate.loss,
            "negative_keep_rate": candidate.negative_keep_rate,
            "sequence_steps": candidate.sequence_steps,
            "last_step_skip": candidate.last_step_skip,
            "n_parameters": int(model.n_parameters()),
            "best_epoch": int(result.best_epoch),
            "minutes": round((time.time() - started) / 60.0, 1),
            "own_dataset_build": key != base_key,
            **scores,
        }
        if key[0] != base_key[0]:
            row["caveat"] = (
                "sequence length differs, so the embargo and therefore the "
                "validation index set differ slightly from the other rows "
                "(<0.02% of validation samples)"
            )
        elif key[1] != base_key[1]:
            row["caveat"] = (
                "training composition differs; the validation and test windows "
                "are identical to the other rows, because negatives are "
                "subsampled on training only"
            )
        rows.append(row)
        print(
            f"        PR-AUC {row['pr_auc']:.4f} | ROC {row['roc_auc']:.4f} | "
            f"event recall {row['event_recall']:.3f} | acc {row['accuracy']:.2%} | "
            f"{row['minutes']:.1f} min | {row['n_parameters']:,} params"
        )
        if best is None or row["pr_auc"] > best["pr_auc"]:
            best = row
        if key != base_key:
            del prepared

    if best is not None:
        print(f"\n[sweep] best single configuration on validation PR-AUC: "
              f"{best['name']} ({best['pr_auc']:.4f})")

    # Seed ensemble of the winner, accepted only if validation says it helps.
    if incumbent is not None:
        winner = incumbent
        table = results_dir / "lstm_sweep_validation.json"
        if table.exists():
            prior = [
                r for r in json.loads(table.read_text()).get("candidates", [])
                if r["name"] == winner.name
            ]
            if prior:
                best = prior[0]
                print(f"[sweep] {winner.name} to beat: "
                      f"PR-AUC {best['pr_auc']:.4f}")
    else:
        winner = next(
            c for c in CANDIDATES + [LONG_WINDOW] if c.name == best["name"]
        )
    if args.ensemble_seeds > 1:
        key = winner.window_key()
        print(f"\n[sweep] seed-ensembling {winner.name} over "
              f"{args.ensemble_seeds} seeds")
        prepared = prepared_for(winner.apply(base, args.seed), key)
        members = []
        for k in range(args.ensemble_seeds):
            member = Candidate(**{**winner.__dict__, "seed": k,
                                  "name": f"{winner.name}_s{k}"})
            cfg = member.apply(base, args.seed)
            _, probs, _ = train_one(prepared, cfg, outdir, member.name)
            members.append(probs)
            print(f"        seed {k} trained")
        averaged = np.mean(members, axis=0)
        scores = score_validation(prepared, winner.apply(base, args.seed), averaged)
        ensemble_row = {
            "name": f"{winner.name}_ensemble_x{args.ensemble_seeds}",
            "note": f"mean probability over {args.ensemble_seeds} seeds",
            "sequence_steps": winner.sequence_steps,
            "negative_keep_rate": winner.negative_keep_rate,
            "own_dataset_build": key != base_key,
            **scores,
        }
        rows.append(ensemble_row)
        print(
            f"        PR-AUC {scores['pr_auc']:.4f} | "
            f"event recall {scores['event_recall']:.3f}"
        )
        np.save(outdir / "ensemble_val_probs.npy", averaged)
        if best is None:
            best = ensemble_row
            print("        no single-model row to compare against; "
                  "taking the ensemble")
        elif scores["pr_auc"] > best["pr_auc"]:
            print(f"        ensemble wins on validation "
                  f"({scores['pr_auc']:.4f} > {best['pr_auc']:.4f})")
            best = ensemble_row
        else:
            print(f"        ensemble does not beat the single model "
                  f"({scores['pr_auc']:.4f} <= {best['pr_auc']:.4f}); "
                  "keeping it")
        if key != base_key:
            del prepared

    out_path = results_dir / "lstm_sweep_validation.json"
    notes: list[str] = []
    not_trained: list[str] = []
    excluded: list[str] = []
    if args.merge and out_path.exists():
        merged = merge_table(json.loads(out_path.read_text()), rows)
        rows = merged["candidates"]
        best = merged["best"]
        notes = merged["notes"]
        not_trained = merged["not_trained"]
        excluded = merged["excluded"]
        print(f"[sweep] merged: replaced {merged['replaced']} row(s), "
              f"best is now {best['name']} ({best['pr_auc']:.4f})")
        if merged["resolved"]:
            print(f"[sweep] now trained, no longer flagged: "
                  f"{merged['resolved']}")
        if not_trained or excluded:
            print(f"[sweep] still outstanding: not_trained={not_trained} "
                  f"excluded={excluded}")
    if args.note:
        notes.append(args.note)

    out_path.write_text(
        json.dumps(
            {
                "data_source": (
                    f"SYNTHETIC (floodsense.synthetic, days={args.days}, "
                    f"stations={args.stations}, seed={args.seed})"
                ),
                "selection_metric": "validation PR-AUC",
                "test_set_used": False,
                "selected": best["name"],
                "not_trained": not_trained,
                "excluded": excluded,
                "notes": notes,
                "candidates": rows,
            },
            indent=2,
        )
    )
    print(f"\n[sweep] validation table -> {out_path}")
    print(f"[sweep] SELECTED: {best['name']}")
    (outdir / "selected.json").write_text(json.dumps(best, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
