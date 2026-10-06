"""Losses for a very imbalanced binary target.

At a ~1:500 base rate, plain BCE is dominated by easy negatives: the model
can drive the loss down by predicting "no flood" everywhere.  Two standard
corrections are provided, both selectable from ``TrainConfig.loss``:

* ``weighted_bce`` - re-weight the positive class by ``n_neg / n_pos``.
  Simple, unbiased in expectation, but noisy when the weight is large.
* ``focal`` - down-weight examples the model already classifies
  confidently, so gradient keeps flowing from the hard cases near the
  decision boundary.  Usually the better choice here.
"""

from __future__ import annotations

import torch
import torch.nn.functional as F
from torch import nn


class FocalLossWithLogits(nn.Module):
    """Focal loss (Lin et al., 2017) on raw logits.

    Args:
        gamma: focusing strength.  0 reduces to weighted BCE.
        alpha: weight on the positive class, in ``[0, 1]``.  ``None``
            disables class balancing.
    """

    def __init__(self, gamma: float = 2.0, alpha: float | None = 0.25) -> None:
        super().__init__()
        self.gamma = float(gamma)
        self.alpha = alpha

    def forward(self, logits: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        logits = logits.reshape(-1)
        target = target.reshape(-1).to(logits.dtype)

        bce = F.binary_cross_entropy_with_logits(logits, target, reduction="none")
        # p_t: probability assigned to the true class, computed from the
        # logit without a second sigmoid pass for numerical stability.
        p = torch.sigmoid(logits)
        p_t = p * target + (1.0 - p) * (1.0 - target)
        loss = bce * (1.0 - p_t).clamp_min(1e-7).pow(self.gamma)

        if self.alpha is not None:
            a_t = self.alpha * target + (1.0 - self.alpha) * (1.0 - target)
            loss = loss * a_t
        return loss.mean()


class WeightedBCEWithLogits(nn.Module):
    """BCE with a fixed positive-class weight."""

    def __init__(self, pos_weight: float) -> None:
        super().__init__()
        self.register_buffer("pos_weight", torch.tensor(float(pos_weight)))

    def forward(self, logits: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        return F.binary_cross_entropy_with_logits(
            logits.reshape(-1),
            target.reshape(-1).to(logits.dtype),
            pos_weight=self.pos_weight,
        )


def build_loss(name: str, *, pos_weight: float, gamma: float, alpha: float) -> nn.Module:
    """Factory used by the training script."""
    key = name.lower()
    if key == "focal":
        return FocalLossWithLogits(gamma=gamma, alpha=alpha)
    if key in {"weighted_bce", "bce"}:
        return WeightedBCEWithLogits(pos_weight=pos_weight if key == "weighted_bce" else 1.0)
    raise ValueError(f"unknown loss {name!r}; expected 'focal' or 'weighted_bce'")
