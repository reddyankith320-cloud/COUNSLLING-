"""FloodSense - LSTM flash-flood risk model for Singapore open data.

Public entry points:

    from floodsense.config import Config
    from floodsense.model import FloodSenseLSTM
    from floodsense.train import train

The package is deliberately split so that the data layer (``ingest``,
``grid``, ``features``, ``labels``) has no dependency on torch.  Only
``model``, ``losses``, ``train``, ``explain`` and ``simulate`` import torch,
so feature engineering can run inside PySpark/Databricks jobs without a
deep-learning runtime.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
