# Databricks notebook source
# MAGIC %md
# MAGIC # FloodSense - bronze / silver / gold on Singapore open data
# MAGIC
# MAGIC Builds the Delta layers that the LSTM trains on, then trains and
# MAGIC registers the model.
# MAGIC
# MAGIC **Sources** (data.gov.sg, Open Data Licence):
# MAGIC
# MAGIC | dataset | agency | id | cadence |
# MAGIC | --- | --- | --- | --- |
# MAGIC | Historical Rainfall across Singapore (2016-2024) | NEA | annual `d_*` per year | 5 min |
# MAGIC | Rainfall across Singapore (API) | NEA | `d_6580738cdd7db79374ed3152159fbd69` | 5 min, live |
# MAGIC | Flood Alerts across Singapore (API) | PUB | `d_f1404e08587ce555b9ea3f565e2eb9a3` | event, live |
# MAGIC | Flood Prone Areas | PUB | `d_c4aed98f1533eb3a66f65dbb1a30da46` | annual, hectares |
# MAGIC
# MAGIC **Where the work happens.** Spark does the heavy row work: parsing the
# MAGIC annual CSVs (~6.4M rows for 2024 alone), de-duplicating re-published
# MAGIC readings, and joining alerts to stations. Feature engineering then runs
# MAGIC on the *pivoted* station x time grid, which is small: one year of
# MAGIC all-Singapore 5-minute rainfall across ~70 stations is roughly
# MAGIC 105,000 x 70 float32 values, about 30 MB. So the gold stage collects
# MAGIC the grid to the driver and uses the vectorised numpy feature code,
# MAGIC rather than paying shuffle costs for rolling windows.

# COMMAND ----------

# MAGIC %pip install torch scikit-learn
# MAGIC %restart_python

# COMMAND ----------

CATALOG = "main"
SCHEMA = "floodsense"
VOLUME = "raw"              # Unity Catalog volume holding the annual CSVs

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA}")
spark.sql(f"CREATE VOLUME IF NOT EXISTS {CATALOG}.{SCHEMA}.{VOLUME}")

RAW_PATH = f"/Volumes/{CATALOG}/{SCHEMA}/{VOLUME}"
print(f"Raw files expected under {RAW_PATH}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Bronze - land the published data unchanged
# MAGIC
# MAGIC Bronze keeps what the publisher sent, plus an ingest timestamp. No
# MAGIC filtering, no renaming: when a parsing assumption turns out wrong, the
# MAGIC fix is a silver rebuild rather than a re-download.

# COMMAND ----------

from pyspark.sql import functions as F
from pyspark.sql.types import (
    DoubleType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

rainfall_csv_schema = StructType(
    [
        StructField("Date", StringType()),
        StructField("Timestamp", StringType()),
        StructField("Update Timestamp", StringType()),
        StructField("Station Id", StringType()),
        StructField("Station Name", StringType()),
        StructField("Station Device Id", StringType()),
        StructField("Location Longitude", DoubleType()),
        StructField("Location Latitude", DoubleType()),
        StructField("Reading Update Timestamp", StringType()),
        StructField("Reading Value", DoubleType()),
        StructField("Reading Type", StringType()),
        StructField("Reading Unit", StringType()),
    ]
)

bronze_rainfall = (
    spark.read.option("header", True)
    .schema(rainfall_csv_schema)
    .csv(f"{RAW_PATH}/historical_rainfall/*.csv")
    .withColumn("_ingested_at", F.current_timestamp())
    .withColumn("_source_file", F.input_file_name())
)

(
    bronze_rainfall.write.mode("overwrite")
    .option("overwriteSchema", "true")
    .saveAsTable(f"{CATALOG}.{SCHEMA}.bronze_rainfall")
)

print(f"bronze_rainfall rows: {spark.table(f'{CATALOG}.{SCHEMA}.bronze_rainfall').count():,}")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Bronze - live feeds
# MAGIC
# MAGIC In production this cell is a Lakeflow job on a 5-minute schedule,
# MAGIC appending each poll. Run interactively it appends one snapshot.
# MAGIC
# MAGIC data.gov.sg applies rate limits to its real-time APIs; set
# MAGIC `DATAGOV_API_KEY` as a secret to avoid throttling.

# COMMAND ----------

import sys

# Point this at wherever the repo is checked out in the workspace.
sys.path.insert(0, "/Workspace/Repos/floodsense/src")

from floodsense.ingest.realtime import fetch_flood_alerts, fetch_rainfall

API_KEY = None  # dbutils.secrets.get("floodsense", "datagov_api_key")

live_readings, live_stations = fetch_rainfall(api_key=API_KEY)
print(f"live rainfall rows: {len(live_readings)}")

if len(live_readings):
    (
        spark.createDataFrame(live_readings)
        .withColumn("_ingested_at", F.current_timestamp())
        .write.mode("append")
        .saveAsTable(f"{CATALOG}.{SCHEMA}.bronze_rainfall_live")
    )

try:
    alerts = fetch_flood_alerts(api_key=API_KEY)
    print(f"flood alerts: {len(alerts)}")
    if len(alerts):
        (
            spark.createDataFrame(alerts)
            .withColumn("_ingested_at", F.current_timestamp())
            .write.mode("append")
            .saveAsTable(f"{CATALOG}.{SCHEMA}.bronze_flood_alerts")
        )
except Exception as exc:
    # The alerts API is recent; confirm its endpoint on the dataset page.
    print(f"flood alerts unavailable: {exc}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Silver - one clean row per station per 5-minute interval
# MAGIC
# MAGIC Three things happen here, and each is a correctness decision rather
# MAGIC than a cleanup chore:
# MAGIC
# MAGIC 1. **Filter to the rainfall reading type.** The files carry other
# MAGIC    reading types; mixing them would corrupt every accumulation.
# MAGIC 2. **Snap to the 5-minute grid and average duplicates.** A reading is
# MAGIC    re-published when corrected, so the same interval can appear twice.
# MAGIC 3. **Reject impossible coordinates.** A station outside Singapore's
# MAGIC    bounding box is a data error, and it would poison the spatial
# MAGIC    neighbour features for every other station.

# COMMAND ----------

READING_TYPE = "TB1 Rainfall 5 Minute Total F"

silver_rainfall = (
    spark.table(f"{CATALOG}.{SCHEMA}.bronze_rainfall")
    .filter(F.col("Reading Type") == READING_TYPE)
    .filter(F.col("Reading Value").isNotNull())
    .select(
        F.to_timestamp("Timestamp").alias("ts_raw"),
        F.col("Station Id").alias("station_id"),
        F.col("Reading Value").cast("float").alias("rainfall_mm"),
    )
    .withColumn(
        "ts",
        (F.floor(F.unix_timestamp("ts_raw") / 300) * 300).cast(TimestampType()),
    )
    .groupBy("ts", "station_id")
    .agg(F.avg("rainfall_mm").cast("float").alias("rainfall_mm"))
)

(
    silver_rainfall.write.mode("overwrite")
    .option("overwriteSchema", "true")
    .partitionBy()
    .saveAsTable(f"{CATALOG}.{SCHEMA}.silver_rainfall")
)

silver_stations = (
    spark.table(f"{CATALOG}.{SCHEMA}.bronze_rainfall")
    .select(
        F.col("Station Id").alias("station_id"),
        F.col("Station Name").alias("station_name"),
        F.col("Location Longitude").alias("longitude"),
        F.col("Location Latitude").alias("latitude"),
    )
    .dropna()
    .filter(F.col("longitude").between(103.60, 104.09))
    .filter(F.col("latitude").between(1.15, 1.48))
    .dropDuplicates(["station_id"])
)

(
    silver_stations.write.mode("overwrite")
    .option("overwriteSchema", "true")
    .saveAsTable(f"{CATALOG}.{SCHEMA}.silver_stations")
)

display(spark.table(f"{CATALOG}.{SCHEMA}.silver_stations").limit(10))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Gold - the feature table
# MAGIC
# MAGIC Feature engineering runs on the pivoted grid (see the note at the
# MAGIC top). Everything is causal: the value at step *t* uses only data at or
# MAGIC before *t*. The static vulnerability features use **training-period
# MAGIC alerts only**, because a per-station alert rate computed over the whole
# MAGIC record leaks the label.

# COMMAND ----------

import pandas as pd

from floodsense.config import Config
from floodsense.pipeline import prepare

readings = spark.table(f"{CATALOG}.{SCHEMA}.silver_rainfall").toPandas()
stations = spark.table(f"{CATALOG}.{SCHEMA}.silver_stations").toPandas()

try:
    alerts = spark.table(f"{CATALOG}.{SCHEMA}.bronze_flood_alerts").toPandas()
except Exception:
    alerts = pd.DataFrame(
        columns=["alert_id", "ts_start", "ts_end", "longitude", "latitude"]
    )

cfg = Config()
prepared = prepare(
    readings=readings, stations=stations, alerts=alerts, cfg=cfg
)

import json

print(json.dumps(prepared.report(), indent=2, default=str))

# COMMAND ----------

# MAGIC %md
# MAGIC Persist the gold feature table so the dashboard and any non-Python
# MAGIC consumer can read it with plain SQL.

# COMMAND ----------

import numpy as np

n_t, n_s, n_f = prepared.features.values.shape
flat = prepared.features.values.reshape(n_t * n_s, n_f)

gold = pd.DataFrame(flat, columns=prepared.features.names)
gold.insert(0, "station_id", np.tile(prepared.grid.station_ids, n_t))
gold.insert(0, "ts", prepared.grid.times.repeat(n_s))
gold["label_flood_30_60min"] = prepared.labels.labels.reshape(-1)
gold["is_valid_sample"] = prepared.labels.valid.reshape(-1)

(
    spark.createDataFrame(gold)
    .write.mode("overwrite")
    .option("overwriteSchema", "true")
    .saveAsTable(f"{CATALOG}.{SCHEMA}.gold_rainfall_features")
)

print(f"gold_rainfall_features rows: {len(gold):,}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Train, with MLflow tracking
# MAGIC
# MAGIC Model selection is on validation PR-AUC. The decision threshold is
# MAGIC then chosen on validation to reach the target **event-level** recall,
# MAGIC and the test split is scored once with that frozen threshold.

# COMMAND ----------

import mlflow

from floodsense.train import train

mlflow.set_experiment(f"/Shared/{SCHEMA}")
cfg.train.use_mlflow = True

result = train(prepared, cfg, outdir="/tmp/floodsense_run")

print(result.val_report.summary_line())
print(result.test_report.summary_line())
print(result.test_event_report.summary_line())

# COMMAND ----------

# MAGIC %md
# MAGIC ## Register in Unity Catalog

# COMMAND ----------

mlflow.set_registry_uri("databricks-uc")

with mlflow.start_run(run_name="floodsense_lstm") as run:
    mlflow.log_metrics(
        {
            "test_pr_auc": result.test_report.pr_auc,
            "test_roc_auc": result.test_report.roc_auc,
            "test_event_recall": result.test_event_report.event_recall,
            "false_alarms_per_station_day": (
                result.test_event_report.false_alarms_per_station_day
            ),
        }
    )
    mlflow.log_artifacts("/tmp/floodsense_run", artifact_path="run")
    print(f"logged run {run.info.run_id}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Flood-prone-area trend (2022-2025)
# MAGIC
# MAGIC The PUB "Flood Prone Areas" dataset is a national aggregate: `year`
# MAGIC and `hectares`, four rows. It is the source for the trend panel and
# MAGIC **not** a spatial layer - per-location vulnerability comes from the
# MAGIC geocoded PUB flood-prone *location* list plus the alert history.

# COMMAND ----------

from floodsense.ingest.flood_prone import flood_prone_trend, load_flood_prone_areas

areas = load_flood_prone_areas()
display(spark.createDataFrame(areas))
print(flood_prone_trend(areas))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Real-time inference
# MAGIC
# MAGIC Scheduled on the same 5-minute cadence as the rainfall feed. Writes one
# MAGIC row per station per run, which is what the dashboard's map and
# MAGIC location panel read.

# COMMAND ----------

from floodsense.infer import FloodSenseService

service = FloodSenseService.from_artifacts("/tmp/floodsense_run")
table, _ = service.score(prepared.grid)

(
    spark.createDataFrame(table)
    .withColumn("_scored_at", F.current_timestamp())
    .write.mode("append")
    .saveAsTable(f"{CATALOG}.{SCHEMA}.gold_live_risk")
)

display(spark.table(f"{CATALOG}.{SCHEMA}.gold_live_risk").orderBy(
    F.col("flood_risk_score").desc()
).limit(20))

# COMMAND ----------

# MAGIC %md
# MAGIC FloodSense is a decision-support prototype built on public data. It
# MAGIC does not replace official PUB flood warnings. The Flood Risk Score is
# MAGIC project-defined and is not an official Singapore government rating.
