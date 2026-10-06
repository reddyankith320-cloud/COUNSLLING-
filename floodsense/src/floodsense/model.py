"""The FloodSense LSTM.

Architecture, and why each piece is there:

``LSTM`` over the 5-minute feature sequence
    The target depends on accumulated state - how saturated the catchment
    already is, how long the rain has been building - not on the latest
    reading.  That is a recurrence, so the recurrent net is the natural
    hypothesis class rather than a fashionable one.  Unidirectional by
    default: a backward pass would read the future, which does not exist at
    inference time.

Additive attention pooling over time
    Taking only the last hidden state throws away *when* the signal
    appeared.  Attention produces a weighted summary and, as a side effect,
    a per-timestep weight vector that the EXPLAIN layer reports directly
    ("most of the risk comes from the last 25 minutes").

Separate static branch
    Station vulnerability (distance to flood-prone locations, historical
    alert rate) is constant within a sequence.  Feeding it through the
    recurrence would make the LSTM re-learn a constant at every step; a
    small MLP joined at the head is both cheaper and easier to interpret.

Single logit output
    Probability of a flood alert in the next 30-60 minutes.  Thresholding
    is a separate, explicit decision - see ``metrics.threshold_for_recall``.
"""

from __future__ import annotations

import json
from pathlib import Path

import torch
from torch import nn

from .config import ModelConfig


class AdditiveAttention(nn.Module):
    """Bahdanau-style pooling over the time axis.

    ``score_t = v^T tanh(W h_t)``, softmaxed over ``t``.
    """

    def __init__(self, hidden_size: int, attn_size: int | None = None) -> None:
        super().__init__()
        attn_size = attn_size or max(hidden_size // 2, 8)
        self.project = nn.Linear(hidden_size, attn_size)
        self.score = nn.Linear(attn_size, 1, bias=False)

    def forward(self, hidden: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        """Args: ``hidden`` ``(B, L, H)``.  Returns context ``(B, H)`` and
        weights ``(B, L)``."""
        scores = self.score(torch.tanh(self.project(hidden))).squeeze(-1)
        weights = torch.softmax(scores, dim=1)
        context = torch.bmm(weights.unsqueeze(1), hidden).squeeze(1)
        return context, weights


class FloodSenseLSTM(nn.Module):
    """Sequence classifier over rainfall features plus static vulnerability.

    Args:
        n_dynamic: number of per-timestep feature channels.
        n_static: number of per-station static features.
        cfg: architecture hyper-parameters.
        feature_names / static_names: recorded on the checkpoint so an
            inference job can verify it is being fed the same columns, in
            the same order, that the model was trained on.
    """

    def __init__(
        self,
        n_dynamic: int,
        n_static: int,
        cfg: ModelConfig | None = None,
        feature_names: list[str] | None = None,
        static_names: list[str] | None = None,
    ) -> None:
        super().__init__()
        cfg = cfg or ModelConfig()
        self.cfg = cfg
        self.n_dynamic = int(n_dynamic)
        self.n_static = int(n_static)
        self.feature_names = list(feature_names or [])
        self.static_names = list(static_names or [])

        if cfg.input_norm == "layer":
            self.input_norm: nn.Module = nn.LayerNorm(n_dynamic)
        elif cfg.input_norm == "none":
            self.input_norm = nn.Identity()
        else:
            raise ValueError(
                f"input_norm must be 'none' or 'layer', got {cfg.input_norm!r}"
            )
        self.lstm = nn.LSTM(
            input_size=n_dynamic,
            hidden_size=cfg.hidden_size,
            num_layers=cfg.num_layers,
            batch_first=True,
            dropout=cfg.dropout if cfg.num_layers > 1 else 0.0,
            bidirectional=cfg.bidirectional,
        )
        directions = 2 if cfg.bidirectional else 1
        pooled = cfg.hidden_size * directions

        self.attention = AdditiveAttention(pooled) if cfg.attention else None

        self.static_mlp = (
            nn.Sequential(
                nn.Linear(n_static, cfg.static_hidden),
                nn.ReLU(),
            )
            if n_static > 0
            else None
        )

        self.skip_mlp = (
            nn.Sequential(
                nn.Linear(n_dynamic, cfg.skip_hidden),
                nn.ReLU(),
            )
            if cfg.last_step_skip
            else None
        )

        head_in = (
            pooled
            + (cfg.static_hidden if self.static_mlp is not None else 0)
            + (cfg.skip_hidden if self.skip_mlp is not None else 0)
        )
        self.head = nn.Sequential(
            nn.Linear(head_in, cfg.head_hidden),
            nn.ReLU(),
            nn.Dropout(cfg.dropout),
            nn.Linear(cfg.head_hidden, 1),
        )

    def forward(
        self,
        sequence: torch.Tensor,
        static: torch.Tensor | None = None,
        return_attention: bool = False,
    ):
        """Args:
            sequence: ``(B, L, n_dynamic)``.
            static: ``(B, n_static)``, or ``None`` when the model was built
                without static features.
            return_attention: also return the ``(B, L)`` attention weights.

        Returns:
            Logits ``(B,)``, optionally with attention weights.
        """
        x = self.input_norm(sequence)
        hidden, _ = self.lstm(x)

        if self.attention is not None:
            pooled, weights = self.attention(hidden)
        else:
            pooled = hidden[:, -1, :]
            weights = torch.zeros(
                hidden.shape[0], hidden.shape[1], device=hidden.device
            )
            weights[:, -1] = 1.0

        if self.skip_mlp is not None:
            pooled = torch.cat([pooled, self.skip_mlp(x[:, -1, :])], dim=1)

        if self.static_mlp is not None:
            if static is None:
                raise ValueError("model expects static features but got None")
            pooled = torch.cat([pooled, self.static_mlp(static)], dim=1)

        logits = self.head(pooled).squeeze(-1)
        if return_attention:
            return logits, weights
        return logits

    @torch.no_grad()
    def predict_proba(
        self, sequence: torch.Tensor, static: torch.Tensor | None = None
    ) -> torch.Tensor:
        self.eval()
        return torch.sigmoid(self.forward(sequence, static))

    def n_parameters(self) -> int:
        return sum(p.numel() for p in self.parameters() if p.requires_grad)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def metadata(self) -> dict:
        return {
            "n_dynamic": self.n_dynamic,
            "n_static": self.n_static,
            "feature_names": self.feature_names,
            "static_names": self.static_names,
            "model_config": {
                "hidden_size": self.cfg.hidden_size,
                "num_layers": self.cfg.num_layers,
                "dropout": self.cfg.dropout,
                "bidirectional": self.cfg.bidirectional,
                "attention": self.cfg.attention,
                "static_hidden": self.cfg.static_hidden,
                "head_hidden": self.cfg.head_hidden,
                "last_step_skip": self.cfg.last_step_skip,
                "skip_hidden": self.cfg.skip_hidden,
                "input_norm": self.cfg.input_norm,
            },
        }

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        torch.save(
            {"state_dict": self.state_dict(), "metadata": self.metadata()}, path
        )
        path.with_suffix(".meta.json").write_text(
            json.dumps(self.metadata(), indent=2)
        )

    @classmethod
    def load(cls, path: str | Path, map_location: str = "cpu") -> "FloodSenseLSTM":
        blob = torch.load(path, map_location=map_location, weights_only=False)
        meta = blob["metadata"]
        # Older checkpoints predate some architecture flags; ModelConfig
        # defaults must not silently change a saved model's shape, so unknown
        # keys are dropped and known-missing ones fall back explicitly.
        from dataclasses import fields as _fields

        allowed = {f.name for f in _fields(ModelConfig)}
        saved = {k: v for k, v in meta["model_config"].items() if k in allowed}
        saved.setdefault("last_step_skip", False)
        saved.setdefault("skip_hidden", 48)
        # Checkpoints written before input_norm became configurable all used
        # LayerNorm, and their state_dict carries its weights.
        saved.setdefault("input_norm", "layer")

        model = cls(
            n_dynamic=meta["n_dynamic"],
            n_static=meta["n_static"],
            cfg=ModelConfig(**saved),
            feature_names=meta.get("feature_names"),
            static_names=meta.get("static_names"),
        )
        model.load_state_dict(blob["state_dict"])
        model.eval()
        return model
