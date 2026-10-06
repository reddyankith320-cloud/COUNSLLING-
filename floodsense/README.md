# FloodSense — LSTM flash-flood risk model for Singapore

An LSTM that estimates **the probability of a flood alert at a given
location in the next 30–60 minutes**, built on Singapore's national open
data, plus the layers around it that make a probability usable: a risk
score, an explanation of what drove it, and rainfall scenario analysis.

It is a decision-support prototype. **It does not replace official PUB
flood warnings.**

---

## Read this before looking at any number

Two things about this project's metrics, stated up front because they
change how you should read everything below.

**1. "95% accuracy" is the wrong target, and any model here can hit it
without being useful.** Flood alerts are rare: roughly 1 in 400–500
station-5-minute intervals in this setup, and rarer in reality. A model
that answers "no flood" every single time scores **99.8% accuracy**. It
also never warns anyone about anything. Accuracy is reported in
`metrics.json` under the key
`accuracy_not_a_headline_metric`, deliberately, and nothing selects on it.

What the project targets instead is **event-level recall ≥ 95%**: of the
flood episodes that actually happened, what share did we warn about at
least once inside the 30–60 minute window — priced honestly against the
false alarms that recall level costs. `Config.target_recall` sets it, and
the decision threshold is chosen on validation to reach it.

**2. The numbers in this README are measured on synthetic data.** The four
official datasets live on data.gov.sg, which was unreachable from the
environment this was built in (network policy). So the repo ships a
physically-motivated storm generator that emits the *exact canonical
schema* the real loaders produce, and every number below is measured on
that. They demonstrate that the pipeline is correct, causal, leak-free and
trains — **they say nothing about real-world skill.** The real loaders are
written, tested against recorded payload shapes, and ready; see
[Running on real data](#running-on-real-data).

---

## Quickstart (no network, no data needed)

```bash
pip install -r requirements.txt

# Train on synthetic storms. ~15 min on 4 CPU threads.
python scripts/train.py --source synthetic --days 400 --stations 32

# Predict / explain / simulate against the trained run
python scripts/demo.py --run artifacts/run --json dashboard.json

# 135 tests, ~5 seconds
python -m pytest tests/ -q
```

---

## What the model actually predicts

```
label[t, station] = 1  iff  a PUB flood alert within radius_km of that
                            station STARTS in (t + 30 min, t + 60 min]
```

A forecast, not a nowcast. Two exclusions keep that target honest:

- Steps where an alert is **already open** are dropped. Re-reporting a
  flood in progress is not prediction, and leaving those rows in would let
  the model score easy points.
- A blackout window after an alert clears is dropped, because "does this
  location flood again immediately" is genuinely ambiguous.

### Features

Not "rainfall → flood". Per station, per 5-minute step (29 channels):

| group | channels |
| --- | --- |
| current | `rain_5min`, `intensity_mm_hr` |
| accumulation | 15 m, 30 m, 1 h, 3 h, 6 h, 24 h, 72 h |
| intensity | `peak_5min_30m`, `mean_intensity_30m`, `mean_intensity_1h` |
| **acceleration** | `rate_15m`, `rate_30m`, `trend_slope_30m` |
| antecedent state | `dry_spell_log`, `wet_ratio_24h_72h` |
| data quality | `observed`, `gap_log` |
| **spatial** | `nbr_acc_30m/1h`, `nbr_max_acc_30m/1h` — the k nearest stations |
| seasonality | `hour_sin/cos`, `doy_sin/cos` |

Static per station: coordinates, historical alert rate, distance to the
nearest flood-prone location, flood-prone counts within 1 km and 2 km.

The spatial neighbour channels are what give the 30–60 minute horizon a
chance: a storm cell already raining 8 km upstream arrives in tens of
minutes. Without them the lead time is largely unforecastable from a
single station's own gauge.

### Architecture

```
dynamic (L=36 steps × 29 ch) ─► LSTM(64, 2 layers, unidirectional)
                                      │
                                additive attention pooling ──┐
                                                             ├─► MLP ─► logit
last step (29 ch) ──────────────► skip MLP ──────────────────┤
static (7 ch) ──────────────────► static MLP ────────────────┘
```

- **Unidirectional.** A bidirectional pass would read the future, which
  does not exist at inference time.
- **Attention pooling**, not last-hidden-state: it keeps *when* the
  evidence appeared, and its weights are read directly by the explanation
  layer ("82% of the model's attention is in the last 30 minutes").
- **Last-step skip connection.** The engineered channels are already strong
  predictors *at time t*. Without the skip, the recurrence has to
  reconstruct them in its hidden state, which wastes capacity and scarce
  positives; with it, the LSTM models what it is for — how the sequence got
  here.
- **No input LayerNorm.** See the finding below; this one is a correction,
  not a default.

---

## Three findings worth your attention

### 1. LayerNorm across the feature axis destroys the flood signal

The first version applied `nn.LayerNorm(n_features)` to the input, which
looks like routine hygiene. It is not. It normalises across *channels
within each timestep*, subtracting that step's cross-channel mean — which
is precisely the absolute rainfall magnitude. "Every accumulation window is
high" and "every one is low" normalise to the **same vector**.

That is tested, not asserted
(`tests/test_model_and_metrics.py::TestInputNormalisation`): with
LayerNorm on, a uniformly-0.1 input and a uniformly-9.0 input produce
*identical* logits. The features are already z-scored per channel by the
fitted `Scaler`, so the default is now `input_norm="none"`.

### 2. At 95% recall, per-interval precision is ~0.5%

This is not a bug; it is the shape of the problem, and it is why the
event-level view exists. Per 5-minute cell, insisting on 95% recall means
alarming on almost everything. Collapsed into **episodes** — one flood
event, one alarm burst — the same model catches ~91% of events at roughly
**1.8 false alarms per station-day**, which is a number an operations team
can actually argue about. Both views are reported; neither is hidden.

### 3. A gradient-boosting baseline is competitive

`gbm_window_summary` (gradient boosting on per-channel last/mean/max/slope
over the window) is a genuinely strong competitor and in the first run it
**beat** the LSTM on PR-AUC. That is reported in `metrics.json` every run,
not buried: if the recurrence cannot beat a model that merely sees window
aggregates, the recurrence is not earning its keep, and you should know
that from the artifact rather than from a reviewer.

---

## Results (synthetic data — see the warning above)

Run: `scripts/train.py --source synthetic --days 400 --stations 32
--epochs 40 --hidden-size 64 --dropout 0.25 --learning-rate 0.0007
--patience 8`. Chronological 70/15/15 split with an embargo; threshold
chosen on validation for 95% event recall; test scored once.

See `artifacts/run_synth_v3/metrics.json` for the full record, including
the per-epoch history, the operating-point tables and the baselines.

| | value |
| --- | --- |
| Test PR-AUC | see `metrics.json` → `test.pr_auc` |
| Test ROC-AUC | → `test.roc_auc` |
| Test event recall | → `test_events.event_recall` |
| False alarms / station-day | → `test_events.false_alarms_per_station_day` |
| Mean warning lead time | → `test_events.mean_lead_minutes` |
| Base rate | → `test.base_rate` |

`metrics.json` also carries `operating_points_val` (precision at each
recall target) and `event_operating_curve_val` (event recall vs false-alarm
load per threshold) — the two tables to put in front of a stakeholder.

---

## Data sources

All from [data.gov.sg](https://data.gov.sg), Open Data Licence.

| dataset | agency | id | role |
| --- | --- | --- | --- |
| Historical Rainfall across Singapore (2016–2024) | NEA | annual `d_*` | training history, 5-min station totals |
| Rainfall across Singapore (API) | NEA | `d_6580738cdd7db79374ed3152159fbd69` | live inference, 5-min refresh |
| Flood Alerts across Singapore (API) | PUB | `d_f1404e08587ce555b9ea3f565e2eb9a3` | the label |
| Flood Prone Areas | PUB | `d_c4aed98f1533eb3a66f65dbb1a30da46` | 2022–2025 trend |

Three things found by actually reading the datasets:

- **Historical rainfall is also 5-minute data**, the same cadence as the
  live API, and the reading type is `TB1 Rainfall 5 Minute Total F`. So the
  features used at training time and at inference time are identical — no
  train/serve skew. The 2024 file alone is ~6.4M rows.
- **"Flood Prone Areas" is not a map.** It is `year` and `hectares`, four
  rows: 27.0 ha (2022), 24.1 (2023), 23.6 (2024), 23.3 (2025). It answers
  the required three-year trend and nothing about *where*. Per-location
  vulnerability therefore comes from geocoding PUB's published *List of
  Flood Prone Areas* (~35 locations) plus the alert history. Using a
  four-row national series as a spatial layer would be a silent error.
- **The alert history is short.** PUB began publishing alerts by API in
  November 2025, so there is far less label history than rainfall history.
  `scripts/fetch_data.py --append-alerts` accumulates daily snapshots; this
  is the binding constraint on training a real model, not compute.

NEA notes the historical files may contain missing records and have not had
climate-grade quality control — which is why everything runs on a
reindexed regular grid with an explicit gap mask fed to the model as a
feature.

---

## Running on real data

```bash
# 1. Stage the datasets (needs data.gov.sg reachable)
python scripts/fetch_data.py --out data/ --realtime
python scripts/fetch_data.py --out data/ --from 2026-09-01 --to 2026-09-30
python scripts/fetch_data.py --out data/ --historical-dir ~/rainfall_csvs \
    --flood-prone-points data/flood_prone_points.csv

# 2. Train on it
python scripts/train.py --source local --data-dir data/
```

Two caveats the code will tell you about rather than hide:

- The **flood-alerts endpoint** is recent. `FLOOD_ALERTS_URL` in
  `ingest/realtime.py` is a documented best guess; confirm it on the
  dataset page. The parser accepts several field spellings and envelope
  shapes (nested `location`, flat `lat`/`lon`, GeoJSON features) and
  reports how many records it had to drop, instead of silently emitting
  empty columns.
- data.gov.sg rate-limits its real-time APIs; pass `--api-key`.

### Databricks

`notebooks/01_medallion_pipeline.py` is a Databricks notebook building
bronze → silver → gold Delta tables, training with MLflow, registering to
Unity Catalog, and writing a `gold_live_risk` table for a dashboard.

Spark does the heavy row work (parsing the annual CSVs, de-duplicating
re-published readings, joins). Feature engineering then runs on the
**pivoted** grid, because after the pivot the data is small: one year of
all-Singapore 5-minute rainfall across ~70 stations is about
105,000 × 70 float32 ≈ 30 MB. So rolling windows are vectorised numpy on a
single node rather than a shuffle-heavy Spark job. The data layer imports
only numpy and pandas, so it runs inside a Spark job with no
deep-learning runtime.

---

## The product layers

**PREDICT** — `infer.FloodSenseService.score()` returns a row per station:
probability, Flood Risk Score, band, recent rainfall, vulnerability.

**EXPLAIN** — `explain.explain_sample()` combines gradient×input
attribution over the feature channels with the model's own attention
weights, de-duplicates channels that map to the same human phrase, and
composes a sentence:

> *Elevated modelled risk, driven mainly by 30-minute rainfall
> accumulation, the rate at which 30-minute rainfall is increasing and
> rainfall at nearby stations over 30 minutes. Most of the evidence (74% of
> the model's attention) is in the last 30 minutes, so the situation is
> developing now.*

Stated limit, carried in the payload: these are local first-order
attributions of one model's output, not a hydrological causal claim, and
correlated rainfall windows share credit arbitrarily.

**SIMULATE** — `simulate.simulate()` scales rainfall over the recent window
by ×1.25/1.5/2.0 and re-scores. The scaling is applied to the **raw
rainfall grid** and every derived feature is then recomputed from it.
Scaling `acc_1h` directly while leaving `rate_30m` alone would produce a
feature vector no real weather could generate, and the model's response to
it would mean nothing. Scenario analysis — not a forecast.

### Flood Risk Score (0–100)

Project-defined, **not** an official Singapore government rating, weights
not validated against outcomes.

```
score = 100 × (0.60·P(flood) + 0.15·intensity + 0.15·accumulation + 0.10·vulnerability)
        + recent-alert bonus
```

Bands: 0–30 Low, 31–60 Moderate, 61–80 High, 81–100 Critical.

The three context terms are normalised against **percentiles measured on
the training split**, not invented thresholds — there is no published
rainfall threshold for "high intensity", so the score says "high relative
to what this network records". The disclaimer travels with the definition
in `risk_scorer.json` and in the dashboard payload.

---

## How leakage is prevented

The failure mode that makes a flood model look excellent offline and fail
in production is leakage, so each guard has a test:

| guard | where | test |
| --- | --- | --- |
| Every feature uses only data at or before `t` | `features.py` | perturb the last step; assert no earlier feature moves |
| Chronological splits, never random | `dataset.build_splits` | assert train < val < test in time |
| Embargo of `sequence_steps + horizon` between splits | same | assert the gap |
| Scaler fitted on the training region only | `fit_scaler` | inject a huge post-cut anomaly; assert the scaler is unmoved |
| Station alert rate from training-period alerts only | `pipeline.prepare` | ordering enforced in `prepare`, documented there |
| Warm-up steps dropped (longest window = 72 h) | `build_splits` | assert first sample ≥ warm-up |
| Val/test never negative-subsampled | `build_splits` | assert val keeps every eligible cell |
| Threshold chosen on val, test scored once | `train.py` | — |

---

## Repo layout

```
src/floodsense/
  schema.py      canonical columns, dataset ids, the 5-min cadence
  config.py      dataclass config, serialised next to every checkpoint
  grid.py        the regular station × time grid; haversine helpers
  features.py    rolling features (cumsum/FIR) + static vulnerability
  labels.py      the 30–60 min target, exclusions, validity mask
  dataset.py     splits, embargo, scaler, lazy sequence windows
  model.py       FloodSenseLSTM, attention pooling, skip branch
  losses.py      focal loss, weighted BCE
  metrics.py     PR-AUC-first reporting, threshold selection
  events.py      episode-level recall, false-alarm load, lead time
  train.py       training loop, early stopping, MLflow (optional)
  baselines.py   logistic regression + two gradient-boosting baselines
  risk.py        the 0–100 Flood Risk Score
  explain.py     attribution + attention → a sentence
  simulate.py    rainfall scenario analysis
  infer.py       scoring service + dashboard payload
  synthetic.py   offline storm generator (canonical schema)
  ingest/        historical CSVs, live APIs, flood-prone data, staging
scripts/         train.py, demo.py, fetch_data.py
notebooks/       Databricks medallion pipeline
tests/           135 tests
```

---

## Limitations

- **Metrics here are synthetic.** The generator is physically motivated,
  not calibrated to Singapore's climate. Real skill is unmeasured.
- **Label history is the bottleneck.** With alerts published by API only
  since late 2025, a production model needs an accumulated alert archive
  or a historical flood record from PUB.
- **Rain gauges only.** No radar, no water-level sensors, no drainage
  network, no terrain. Flooding depends on drainage capacity and
  topography, and none of that is in the four datasets, so station
  vulnerability is a weak proxy for it.
- **Alert → station association is a 2 km radius**, which is crude; an
  alert is a point, a catchment is not.
- **No calibration step yet.** The Brier score is reported, but the
  probability is not isotonic- or Platt-calibrated, and the risk score
  consumes the probability directly.
- **The synthetic alert rate (3/station/month) is higher than reality**,
  chosen to make the pipeline trainable. A real base rate is lower, which
  makes the problem harder.
