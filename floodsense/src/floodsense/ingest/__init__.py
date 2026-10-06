"""Loaders for Singapore national open data, and for staged local copies.

Every loader returns the canonical schema defined in ``floodsense.schema``,
so the rest of the package is source-agnostic: the synthetic generator, a
staged Parquet directory and a live API call are interchangeable inputs to
``floodsense.pipeline.prepare``.

Sources (all on data.gov.sg, Open Data Licence):

=================================================  ========  ==============
dataset                                            agency    cadence
=================================================  ========  ==============
Historical Rainfall across Singapore (2016-2024)   NEA       5 min, annual CSV
Rainfall across Singapore (API)                    NEA       5 min, live
Flood Alerts across Singapore (API)                PUB       event, live
Flood Prone Areas                                  PUB       annual (ha)
=================================================  ========  ==============
"""

from .flood_prone import (
    load_flood_prone_areas,
    load_flood_prone_points,
    flood_prone_trend,
)
from .historical import load_historical_csv, load_historical_dir
from .local import load_canonical, save_canonical
from .realtime import fetch_flood_alerts, fetch_rainfall

__all__ = [
    "load_historical_csv",
    "load_historical_dir",
    "fetch_rainfall",
    "fetch_flood_alerts",
    "load_flood_prone_areas",
    "load_flood_prone_points",
    "flood_prone_trend",
    "load_canonical",
    "save_canonical",
]
