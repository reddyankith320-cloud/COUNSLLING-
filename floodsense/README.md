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

**1. "95% accuracy" is the wrong target, and the measured numbers show
why.** Flood alerts are rare — 0.35% of station-5-minute intervals in this
setup, rarer in reality. On the test split:

| model | accuracy | flood events caught |
| --- | --- | --- |
| answers "no flood" every time | **99.65%** | **0 of 308** |
| FloodSense at its operating point | **73.0%** | **290 of 308** |

The useful model scores 26 points *lower* on accuracy than the useless one,
because thresholding for recall means accepting false positives and
accuracy punishes those hardest when the positive class is 0.3% of the
data. Accuracy is still reported — under the key
`accuracy_not_a_headline_metric` — and nothing selects on it.

If you need a 95% accuracy figure, it is available without being
meaningless: `--operating-point accuracy --target-accuracy 0.95` gives
95.00% accuracy while still catching 83.1% of flood events. See
[the accuracy curve](#accuracy-and-how-to-hit-95-of-it-honestly) for what
each setting costs.

What the project targets instead is **event-level recall ≥ 95%**: of the
flood episodes that actually happened, what share did we warn about at
least once inside the 30–60 minute window — priced honestly against the
false alarms that recall level costs. `Config.target_recall` sets it, the
threshold is chosen on validation to reach it (95.4% there), and the test
split holds at 94.2% with ~57 minutes of mean lead time.

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

# 280 tests, ~8 seconds
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

Not "rainfall → flood". 54 causal channels per station per 5-minute step:

| group | channels |
| --- | --- |
| current | `rain_5min`, `intensity_mm_hr` |
| accumulation | 10 m, 15 m, 30 m, 1 h, 2 h, 3 h, 6 h, 12 h, 24 h, 72 h |
| **antecedent wetness** | `ewm_1h`, `ewm_6h`, `ewm_1d`, `ewm_3d` |
| intensity | `peak_5min_30m`, `mean_intensity_30m`, `mean_intensity_1h` |
| rolling shape | `roll_mean/max/std` over 30 m and 3 h |
| **acceleration** | `rate_15m/30m`, `accel_15m/30m`, `pct_change_30m/1h`, `trend_slope_30m` |
| lags | `lag_rain_5m/15m/30m/1h` |
| dry history | `dry_spell_log`, `wet_ratio_24h_72h` |
| data quality | `observed`, `gap_log` |
| **spatial** | `nbr_acc_30m/1h`, `nbr_max_acc_30m/1h`, `gradient_30m/1h` |
| seasonality | `hour_sin/cos`, `doy_sin/cos`, `dow_sin/cos`, `monsoon_ne`, `monsoon_sw` |

Static per station (9): coordinates, historical alert rate, distance to the
nearest flood-prone location, flood-prone counts within 1 km and 2 km,
station density within 5 km, distance to the nearest station.

Three of these groups do real work:

**Exponentially weighted rainfall** is the one that matters most. A
catchment's readiness to flood is an antecedent-wetness state: rain charges
it, drainage bleeds it off at a roughly constant fractional rate. That is a
leaky integrator, and an EWM *is* one — whereas a fixed-window accumulation
approximates it badly, counting every minute inside the window equally and
everything outside it not at all. Four half-lives let the model pick the
drainage timescale instead of having one assumed for it.

**The spatial channels** are what give the 30–60 minute horizon a chance: a
storm cell already raining 8 km upstream arrives in tens of minutes. The
gradient channel separates "the cell is centred here" from "it is raining
across the whole district".

**`roll_std`** separates a steady soak from burst-and-pause of identical
total depth — two situations with the same accumulation and different flood
risk.

Warm-up is 9 days, not the 3 days the longest window implies, because an
EWM initialised at zero reads low for a few half-lives and training on that
stretch would teach the model that every record begins dry.

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

## Findings worth your attention

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

### 3. A percentile over *all* intervals disabled half the risk score

The Flood Risk Score normalises its intensity and accumulation terms
against percentiles of the training data. Taking those percentiles over
every station-interval put the 99th percentile at **7.2 mm/h and 3.2 mm** —
a drizzle — because Singapore's gauges read zero in roughly 97% of
5-minute intervals. Both terms therefore saturated at 1.0 during any real
storm and could never rise again, which is how it was found: the what-if
simulator could not move the score upward.

Conditioning the percentile on *raining* intervals puts the references at
**67 mm/h and 19 mm**, which is the range of actual storms. Tested in
`TestRiskScore::test_references_condition_on_wet_intervals`.

### 4. The model's response to scaled rainfall is not monotone

Doubling recent rainfall sometimes *lowers* the predicted probability. That
is not a simulator bug, and it is not smoothed over. Two causes, both
expected: steps where an alert is already open are excluded from training,
which truncates the training distribution exactly at the heaviest
rainfall; and scaling beyond what the record contains asks the network to
extrapolate.

So `SimulationReport` classifies the response direction and attaches a
caveat when it is not monotonically increasing, which travels into the
dashboard payload and the printed table. A simulator that presented a
falling risk under heavier rainfall as if it were a forecast would be worse
than one that says it does not know.

### 5. The gradient-boosting baseline is close, and that is the point

`gbm_window_summary` (gradient boosting on per-channel last/mean/max/slope
over the window) is a genuinely strong competitor. In the **first** run it
*beat* the LSTM on PR-AUC, 0.134 to 0.101 — which is what prompted findings
1 and 2. After those fixes the LSTM leads, 0.1136 to 0.1104 on PR-AUC and
0.874 to 0.831 on ROC-AUC.

That is a narrow PR-AUC margin and it is reported as narrow. The baselines
run on every training run and land in `metrics.json` beside the LSTM, so if
a change makes the recurrence stop earning its keep, that shows up in the
artifact rather than in a reviewer's comment.

---

### 6. With good features, the LSTM stopped earning its keep

After the feature work, gradient boosting on window summaries beats the
recurrent model on validation PR-AUC: **0.1337 vs 0.1122**. That is the
project's own stated test from finding 5, applied honestly to its namesake
model.

The reason is the feature engineering, not a defect in the LSTM. The 54
channels are already multi-timescale temporal aggregates — ten
accumulations, four exponentially weighted states, lags, rolling statistics,
rates and accelerations — so the history the recurrence exists to extract has
already been handed to every model as a plain vector. A boosted tree
ensemble reads that vector with far fewer parameters and far less variance
on 7,269 training positives.

The LSTM is kept, trained and compared on every run. It is simply not
selected, and the selection is written down in
`results/model_comparison.json` rather than asserted.

### 7. An accuracy threshold does not transfer across a seasonal shift

The operating point was chosen on validation at 95.25% accuracy / 82.2%
event recall. The same threshold on the test period gave 98.24% / 68.6%.

Accuracy is base-rate dependent: at a sub-1% positive rate it is essentially
`1 − false-positive rate`, so a drier evaluation period raises it and sinks
recall with the threshold untouched. Anything tuned to hit an accuracy
*number* inherits that fragility. This is the strongest practical argument
for keeping PR-AUC as the selection metric and treating accuracy purely as a
deployment constraint — and, in a real deployment, for re-fitting the
operating point per season rather than freezing one forever.

## Results (synthetic data — see the warning above)

Final run: 540 days, 32 stations, seed 20260601. Eleven candidates
(5 tabular families x 2 feature sets, plus the LSTM) compared on
validation; threshold chosen on validation inside the 95–99% accuracy band;
leakage audit PASS; **test split read exactly once**.

Artifacts: [`results/final_metrics.json`](results/final_metrics.json),
[`results/model_comparison.json`](results/model_comparison.json),
[`results/confusion_matrix.json`](results/confusion_matrix.json),
[`results/accuracy_vs_threshold_test.json`](results/accuracy_vs_threshold_test.json),
[`results/leakage_audit.json`](results/leakage_audit.json).

### Selected model

`hist_gradient_boosting:window_summary` — HistGradientBoosting on
last/mean/max/slope of each of the 54 channels over the 3-hour window, plus
the 9 static channels (225 features). Chosen on **validation PR-AUC
0.1337**.

### Test results, at the frozen threshold 0.464427

| | result | target | |
| --- | --- | --- | --- |
| **Accuracy** | **98.24%** | 95–99% | **met** |
| **Flood-event recall** | **68.6%** (109/159) | ≥80% | **missed** |
| Mean lead time | 51.4 min | ≥50 min | met |
| Median lead time | 55 min | — | |
| False alarms | 1.05 / station-day | reduced vs 4.39 | met |
| PR-AUC | 0.1114 | — | |
| ROC-AUC | 0.8557 | — | |
| Interval precision / F1 | 3.58% / 0.0666 | — | |
| Alarm precision | 3.9% | — | |

Confusion matrix (one cell = one station-5-minute interval,
729,768 total): TP 458 · FP 12,344 ·
TN 716,467 · FN 499. Base rate 0.00131, so a
constant "no flood" predictor scores 99.87%
and catches 0 of 159 events.

Test period: 2024-04-05 12:20:00+08:00 to 2024-06-23 23:55:00+08:00, 2534 station-days.

### The honest trade-off: both targets were not simultaneously reachable

Validation said 95.25% accuracy at **82.2%** event recall. Test, at the same
frozen threshold, gave 98.24% accuracy at **68.6%**.
The threshold did not transfer.

The cause is covariate shift, and the numbers say so plainly: the test
period is drier than validation — test base rate 0.00131 against a
validation period with roughly twice the event rate. Accuracy at a fixed
probability threshold depends on the base rate (at a sub-1% positive rate,
accuracy is essentially `1 − false-positive rate`), so a drier evaluation
period pushes accuracy *up* and recall *down* at the same threshold.

The test threshold sweep (reporting only — the threshold was already frozen)
shows how close the two targets come on this period:

| threshold | accuracy | event recall |
| --- | --- | --- |
| 0.250 | 94.30% | **81.8%** |
| 0.275 | **95.08%** | 77.4% |
| 0.464 (selected) | 98.24% | 68.6% |

At the 95% accuracy edge the best achievable test event recall is **77.4%** —
2.6 points short of the 80% target. So on this test period, with this model,
95% accuracy and 80% event recall are *not* simultaneously achievable. That
is reported rather than engineered around: reaching both would have required
choosing the threshold on the test split, which is precisely what the
data-integrity rules forbid.

The defensible fix is a better model, not a better threshold. A model with
higher PR-AUC moves the whole curve up and buys both at once.

### Model comparison (validation only — test never read)

| Model | PR-AUC | ROC-AUC | Event recall | F1 | Accuracy | Threshold |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| **hist_gradient_boosting:window_summary** | **0.1337** | 0.8790 | 0.822 | 0.062 | 95.25% | 0.4644 |
| lightgbm:window_summary | 0.1309 | 0.8711 | 0.813 | 0.061 | 95.29% | 0.3787 |
| xgboost:window_summary | 0.1301 | 0.8687 | 0.810 | 0.058 | 95.20% | 0.3845 |
| random_forest:window_summary | 0.1189 | 0.8850 | 0.834 | 0.064 | 95.34% | 0.5215 |
| floodsense_lstm:sequence | 0.1122 | 0.8811 | 0.834 | 0.063 | 95.30% | 0.2332 |
| lightgbm:last_step | 0.1073 | 0.8638 | 0.816 | 0.059 | 95.12% | 0.4445 |
| xgboost:last_step | 0.1043 | 0.8493 | 0.788 | 0.057 | 95.33% | 0.4487 |
| random_forest:last_step | 0.1011 | 0.8925 | 0.831 | 0.064 | 95.33% | 0.4873 |
| hist_gradient_boosting:last_step | 0.0984 | 0.8677 | 0.807 | 0.062 | 95.37% | 0.5197 |
| logistic_regression:window_summary | 0.0802 | 0.8813 | 0.847 | 0.061 | 95.09% | 0.6804 |
| logistic_regression:last_step | 0.0669 | 0.8866 | 0.844 | 0.061 | 95.11% | 0.6714 |

Each row is at *its own* 95–99% accuracy operating point, chosen on
validation, so the table says what each candidate would actually do under
the accuracy requirement rather than comparing abstractions.

### Submission language

Supported by the numbers above, for a synthetic-data run:

> FloodSense reached **98.24% accuracy on a held-out test
> period** at a validation-selected operating threshold, detecting
> **68.6% of observed flood events**
> (109 of 159) with a **mean lead time
> of 51 minutes** and
> 1.05 false alarms per station-day.
> Metrics are measured on synthetic data and validate the pipeline, not
> real-world skill on Singapore rainfall.

Do not drop that last sentence while the data is synthetic.

## How a model gets chosen

```
TRAINING (earliest 70%)        fit every candidate
        |
VALIDATION (next 15%)          pick the model   (PR-AUC)
        |                      pick the threshold (accuracy band)
        v
  FROZEN MODEL + FROZEN THRESHOLD
        |
TEST (latest 15%)              read once, report
```

Three phases, three scripts, and the test split is unreachable from the
first two:

```bash
# Phase 1 - five tabular families x two feature sets, validation only
python scripts/experiments.py --days 540 --stations 32 --seed 20260601

# Phase 2 - the LSTM, also validation only
python scripts/train.py --days 540 --stations 32 --seed 20260601     --no-test-eval --epochs 40 --hidden-size 64

# Phase 3 - select, freeze, audit, then one test pass
python scripts/final_evaluation.py --days 540 --stations 32 --seed 20260601
```

`experiments.build_matrices` returns `train` and `val` and has no code path
to `test`; there is a test asserting that. `scripts/train.py --no-test-eval`
skips the test split entirely. Phase 3 refuses to print test metrics at all
if the leakage audit fails, unless `--force`.

**Selection is validation PR-AUC**, ties broken by event recall then F1.
Accuracy never selects: at this base rate it ranks "predict nothing" first.
It is applied afterwards, as a constraint, by choosing the threshold.

### The threshold rule

`events.threshold_for_accuracy_band` filters candidate thresholds to those
whose **validation** accuracy falls in the required band, then takes the
highest **event-level** recall among the survivors, breaking ties on the
lowest threshold. Accuracy is the constraint imposed from outside; catching
floods is the job — so accuracy filters and recall chooses, never the
reverse.

The band has an upper bound for a reason. Above roughly 99%, accuracy is
almost certainly coming from predicting "no flood" nearly everywhere, which
is the degenerate solution the band exists to exclude.

## Leakage audit

`scripts/final_evaluation.py` runs `floodsense.audit` against the real
prepared data before it opens the test split, and writes
`results/leakage_audit.json`. Thirteen checks:

| check | what it would catch |
| --- | --- |
| `future_rainfall_leakage` | an off-by-one in any rolling window — adds 100 mm at one step and asserts no earlier feature moves, across all 54 channels |
| `future_alert_leakage` | the station alert rate computed over the whole record instead of the training period — target leakage, the feature derived from the label |
| `label_horizon_causality` | a label pointing at an alert inside its own input window |
| `temporal_split_order` | random or shuffled splits |
| `split_embargo` | splits adjacent enough that a training input window overlaps an evaluation sample |
| `split_disjoint` | the same (step, station) in two splits |
| `duplicate_events_across_splits` | one flood event contributing positives to two splits |
| `scaler_fit_region` | normalisation fitted on data the model should not have seen |
| `warmup_respected` | samples drawn while long windows are still filling |
| `evaluation_split_integrity` | negative subsampling applied to validation or test |
| `threshold_selected_on_validation` | the operating point chosen on test |
| `station_overlap` | *(INFO)* stations are shared across splits by design — the split is temporal; a model for ungauged locations would need a station-wise split too, and would score worse |
| `feature_selection_on_test` | *(INFO)* no data-driven feature selection exists; the channel list is fixed in `FeatureConfig` before any data is read |

The FAIL branches are themselves tested: `tests/test_audit.py` breaks each
guarantee on purpose and asserts the audit notices. An audit that only ever
returns PASS is indistinguishable from one that is not looking.

## Dashboard

```bash
python scripts/final_evaluation.py     # writes results/final_metrics.json
python scripts/serve_dashboard.py      # http://127.0.0.1:8000/dashboard/
```

Every number on the page is fetched from `results/final_metrics.json` at
load time. Nothing is written into the markup — `tests/test_dashboard.py`
asserts the static markup contains *no digits at all*, so a stale number
cannot survive a model change and still be sitting there at a demo. It
shows accuracy as the hero figure with its band membership, event recall
against the ≥80% target, lead time, false-alarm load, PR-AUC and ROC-AUC,
the confusion matrix, the full threshold sweep as a chart and a table, and
the provenance block (which split chose the threshold, and the audit
result). A synthetic run renders a warning banner driven by the
`synthetic_data` flag.

The palette is the data-viz reference palette, validated by its checker in
both light and dark mode; no dual axis anywhere.

### LIVE and DEMO are never mixed

The page resolves one dataset and says which:

| badge | source file | shown as |
| --- | --- | --- |
| **LIVE / REAL DATA** | `results/real_data_metrics.json` | `DATA SOURCE: Singapore Government Open Data` |
| **DEMO / SYNTHETIC DATA** | `results/final_metrics.json` | `DATA SOURCE: Synthetic Demo Dataset` |

Real data is preferred when present; the two files are never merged. A file
whose `synthetic_data` flag is true cannot be shown under the LIVE badge even
if it is sitting at the real-data path, so a mislabelled file fails closed.

### Distribution shift

`scripts/distribution_report.py` profiles every split — event prevalence,
rainfall distribution, event structure, station coverage, calendar months and
monsoon composition — and warns when validation and test differ enough that
an accuracy operating point will not transfer. On the synthetic run it says
so explicitly:

```
split        period                     events  prevalence  wet share   mm/step
train        2023-01-10 to 2024-01-16     1204     0.00213     0.0240   0.01515   negatives subsampled
validation   2024-01-16 to 2024-04-05      326     0.00271     0.0269   0.01799
test         2024-04-05 to 2024-06-23      159     0.00131     0.0175   0.01086

  test_vs_validation_prevalence_ratio: 0.484
  WARNING: Event prevalence differs by 0.48x between validation and test ...
  WARNING: Northeast-monsoon share differs markedly between validation (95%) and test (0%)
```

That is the threshold-transfer failure of finding 7, visible *before* the
test split is scored. Training prevalence is reported over the eligible
region rather than as sampled, because the training split subsamples
negatives and the raw figure would suggest a shift that is not in the data.

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

### Current status: the official hosts are blocked

`scripts/network_preflight.py` diagnoses access layer by layer and stops at
the first one that fails. On this environment:

```
Network preflight: BLOCKED
  blocking layer : egress_policy
  blocked hosts  : api-open.data.gov.sg, data.gov.sg
  [ok ]  dns    api-open.data.gov.sg   resolves to 104.20.45.103, 172.66.149.179, ...
  [FAIL] proxy  api-open.data.gov.sg   HTTP/1.1 403 Forbidden -
         request blocked: no rule or allowlist entry allows host "api-open.data.gov.sg"
```

DNS resolves and the proxy is reachable; the **CONNECT tunnel is refused with
403 before TLS begins**, which is an egress-allowlist denial rather than a
network fault, a certificate problem or an API error. The full report is in
[`results/network_preflight.json`](results/network_preflight.json).

**To enable real data, allow these hosts** in the environment's Network
access settings (a broader access level, or Custom with these under Allowed
domains, keeping the default package-manager list):

| host | why |
| --- | --- |
| `api-open.data.gov.sg` | real-time rainfall and PUB flood alerts (v2 API) |
| `data.gov.sg` | dataset metadata, CKAN datastore, CSV downloads |
| `www.pub.gov.sg` | *optional* — PUB's published flood-prone location list |

Nothing in FloodSense attempts to work around the policy.

### Endpoints and authentication

Taken from the data.gov.sg developer guide, not invented:

| | |
| --- | --- |
| real-time base | `https://api-open.data.gov.sg/v2/real-time/api` |
| rainfall | `GET /v2/real-time/api/rainfall`, params `date` (`YYYY-MM-DD` or `YYYY-MM-DDTHH:mm:ss`) and `paginationToken` |
| auth | `x-api-key` header |
| rate limits | per 10 s on the v2 real-time API: 6 calls with no key, 12 with a dev key, 30 with a prod key; enforcement began 31 Dec 2025 |
| flood alerts | **path not asserted** — discovered by probing, see below |

A key is not strictly required, but at 6 calls per 10 seconds a multi-month
backfill is impractical without one. Get one by signing in at data.gov.sg and
pass it as `--api-key` or `DATAGOV_API_KEY`.

**The flood-alerts endpoint is deliberately not hardcoded.** Its path is not
documented in the material reachable from here, and an invented path would
404 in a way that looks exactly like "no floods today" — silently producing a
dataset with no positive class. `discover_flood_alert_endpoint` probes
candidates and reports which one answers, or reports none.

### Once the hosts are allowed

```bash
python scripts/network_preflight.py --discover          # expect "REACHABLE"
python scripts/real_data_pipeline.py --fetch     --from 2025-11-01 --to 2026-09-30     --historical-dir ~/nea_rainfall_csvs     --flood-prone-points data/flood_prone_points.csv     --api-key "$DATAGOV_API_KEY"
```

That runs the whole chain — fetch, bronze, validation, silver, event
matching, features, gold, chronological splits, model comparison on
validation, threshold on validation, freeze, leakage audit, one test
evaluation, distribution-shift report — and writes `results/real_*.json`.

Two gates protect the output:

**Preflight gate.** The pipeline aborts if the hosts are unreachable rather
than quietly falling back to synthetic data.

**Provenance gate.** `results/real_data_metrics.json` is written only when
the staged data carries a `provenance.json` recording an official origin. A
file with that name holding synthetic numbers is the single output most
likely to mislead someone downstream, so it cannot be produced by accident.

### Bronze → Silver validation

Real gauge data is messy in ways synthetic data is not, so every table passes
`floodsense.ingest.validate` before it reaches the feature code, and the
report says what was dropped and why: negative depths, readings above 100 mm
per 5 minutes (a gauge fault, not weather), unparseable timestamps,
duplicate publications of a corrected reading, alerts without coordinates or
outside Singapore's bounding box, alerts whose end precedes their start,
readings from stations with no metadata. An empty alert table is an `ERROR`,
not an empty pass — with no positive class there is nothing to learn.

### The binding constraint on real data

Not compute, and not the model: **label history**. PUB began publishing
flood alerts by API in November 2025, so the alert archive available through
the API is short, while rainfall history runs from 2016. A chronological
train/validation/test split needs enough events in *every* split for the
metrics to mean anything, and the validator warns when the alert span is
under 180 days. Accumulate snapshots with
`scripts/fetch_data.py --append-alerts`, or obtain a historical flood record
from PUB directly.

### Databricks### Databricks

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

> *High risk band (61% modelled probability), driven mainly by 30-minute
> rainfall accumulation, the rate at which 30-minute rainfall is increasing
> and rainfall at nearby stations over 30 minutes. Most of the evidence
> (74% of the model's attention) is in the last 30 minutes, so the
> situation is developing now.*

The sentence leads with the **band shown beside it**, not with the
probability. The band comes from the blended score while the probability is
one of its four terms, so a location can sit in the Moderate band on a low
probability — and an explanation that called that "low risk" would
contradict the panel it sits in.

Stated limit, carried in the payload: these are local first-order
attributions of one model's output, not a hydrological causal claim, and
correlated rainfall windows share credit arbitrarily.

**SIMULATE** — `simulate.simulate()` scales rainfall over the recent window
by ×1.25/1.5/2.0 and re-scores, reporting the response direction and
flagging a non-monotone one (finding 4). The scaling is applied to the **raw
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
  audit.py       thirteen leakage checks
  experiments.py the model zoo, validation-only
  distribution.py  per-split distribution-shift report
  ingest/        historical CSVs, live APIs, flood-prone data, staging
    discovery.py   network preflight + endpoint discovery
    validate.py    the Bronze -> Silver validation gate
scripts/         train.py, demo.py, fetch_data.py, ablate.py,
                 experiments.py, final_evaluation.py, refit_risk_score.py,
                 network_preflight.py, real_data_pipeline.py,
                 distribution_report.py, serve_dashboard.py
results/         the metrics record behind the numbers above
notebooks/       Databricks medallion pipeline
tests/           280 tests
```

---

## Limitations

- **Metrics here are synthetic.** The generator is physically motivated,
  not calibrated to Singapore's climate. Real skill is unmeasured. The
  real-data pipeline is built and gated but has never run: the official
  hosts are blocked by this environment's egress policy (see *Running on
  real data*), so no Singapore observation has ever entered the model.
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
- **Scenario analysis is sensitivity, not dose-response** (finding 4). The
  non-monotone region is reported rather than hidden, but it does limit how
  the what-if panel should be read.
- **The synthetic alert rate (3/station/month) is higher than reality**,
  chosen to make the pipeline trainable. A real base rate is lower, which
  makes the problem harder.
- **The 80% event-recall target was missed on test** (68.6%), and at the 95%
  accuracy edge the best this model reaches is 77.4%. Closing that gap needs
  a better-ranking model, not a different threshold — see finding 7.
- **The EWM features suit this generator unusually well.** The synthetic
  hazard includes an exponential saturation term, and an exponentially
  weighted mean is close to its functional form. The feature family is
  physically motivated and belongs on real data too, but expect a smaller
  gain there than the synthetic numbers suggest.
