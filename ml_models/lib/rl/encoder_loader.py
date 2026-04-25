"""Load the frozen PatchTST SSL encoder produced by ``02_ssl/01_pretrain.ipynb``.

The encoder is the ``model`` attribute of ``PatchTSTForPretraining`` — i.e. a
plain ``PatchTSTModel`` that maps a 360-day × 50-feature window onto a
``(num_channels, num_patches, d_model)`` hidden state. We mean-pool over the
channel and patch axes to get a fixed-size ``d_model``-dim embedding suitable
as an RL observation.

The bundle is frozen (``requires_grad_(False)``) and put in ``eval()`` mode so
it acts as a deterministic feature extractor — no dropout, no gradient flow
into the encoder during PPO updates.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
from torch import nn
from transformers import PatchTSTConfig, PatchTSTModel

from ml_models import PROJECT_ROOT

DEFAULT_MODELS_DIR = PROJECT_ROOT / "ml_models" / "02_ssl" / "models"


@dataclass
class SSLEncoderBundle:
    """Container for the frozen encoder + per-channel scaler + metadata."""

    encoder: nn.Module
    feature_columns: list[str]
    channel_mean: np.ndarray  # shape: (n_channels,)
    channel_std: np.ndarray   # shape: (n_channels,)
    context_length: int
    d_model: int
    device: torch.device

    def normalize(self, window: np.ndarray) -> np.ndarray:
        """Apply the train-fit per-channel standardization used by Stage 02."""
        if window.shape[-1] != self.channel_mean.shape[0]:
            raise ValueError(
                f"window has {window.shape[-1]} channels but scaler expects "
                f"{self.channel_mean.shape[0]}"
            )
        return ((window - self.channel_mean) / self.channel_std).astype(np.float32)

    @torch.no_grad()
    def embed(self, window: np.ndarray) -> np.ndarray:
        """Encode one (context_length, n_channels) window into (d_model,) numpy."""
        normed = self.normalize(window)
        x = torch.from_numpy(normed).unsqueeze(0).to(self.device)
        return self._embed_tensor(x)[0].cpu().numpy()

    @torch.no_grad()
    def embed_batch(self, batch: np.ndarray) -> np.ndarray:
        """Encode a (B, context_length, n_channels) batch into (B, d_model) numpy."""
        normed = np.stack([self.normalize(w) for w in batch], axis=0)
        x = torch.from_numpy(normed).to(self.device)
        return self._embed_tensor(x).cpu().numpy()

    def _embed_tensor(self, past_values: torch.Tensor) -> torch.Tensor:
        """Mean-pool over (channel, patch) → (batch, d_model)."""
        out = self.encoder(past_values=past_values)
        h = out.last_hidden_state  # (B, n_channels, n_patches, d_model)
        if h.ndim != 4:
            raise RuntimeError(f"unexpected hidden-state shape {tuple(h.shape)}")
        return h.mean(dim=(1, 2))


def load_ssl_encoder(
    models_dir: str | Path = DEFAULT_MODELS_DIR,
    *,
    device: torch.device | str | None = None,
) -> SSLEncoderBundle:
    """Build a frozen PatchTSTModel from Stage 02 artefacts.

    Parameters
    ----------
    models_dir
        Folder containing ``ssl_encoder.pt``, ``ssl_config.json`` and
        ``feature_scaler.npz`` — produced by ``02_ssl/01_pretrain.ipynb``.
    device
        Torch device for the encoder. Defaults to CUDA if available.
    """
    models_dir = Path(models_dir)
    if device is None:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    elif isinstance(device, str):
        device = torch.device(device)

    config_path = models_dir / "ssl_config.json"
    weights_path = models_dir / "ssl_encoder.pt"
    scaler_path = models_dir / "feature_scaler.npz"
    for path in (config_path, weights_path, scaler_path):
        if not path.exists():
            raise FileNotFoundError(
                f"missing Stage 02 artefact: {path} — run 02_ssl/01_pretrain.ipynb first"
            )

    with config_path.open() as handle:
        saved = json.load(handle)
    patch_cfg = PatchTSTConfig(**saved["patch_cfg"])
    encoder = PatchTSTModel(patch_cfg)

    state = torch.load(weights_path, map_location="cpu", weights_only=True)
    # PatchTSTForPretraining wraps the encoder as ``self.model`` — strip the
    # prefix so weights land on the bare PatchTSTModel.
    prefix = "model."
    encoder_state = {
        k[len(prefix):]: v for k, v in state.items() if k.startswith(prefix)
    }
    missing, unexpected = encoder.load_state_dict(encoder_state, strict=False)
    if unexpected:
        raise RuntimeError(f"unexpected weights when loading encoder: {unexpected[:5]}")
    encoder.to(device)
    encoder.eval()
    for param in encoder.parameters():
        param.requires_grad_(False)

    scaler = np.load(scaler_path, allow_pickle=True)
    feature_columns = [str(c) for c in scaler["columns"]]
    channel_mean = scaler["mean"].astype(np.float32)
    channel_std = scaler["std"].astype(np.float32)

    return SSLEncoderBundle(
        encoder=encoder,
        feature_columns=feature_columns,
        channel_mean=channel_mean,
        channel_std=channel_std,
        context_length=int(saved["train_cfg"]["context_length"]),
        d_model=int(patch_cfg.d_model),
        device=device,
    )


def random_encoder_bundle(
    feature_columns: list[str],
    *,
    context_length: int = 360,
    patch_length: int = 30,
    d_model: int = 64,
    n_layers: int = 2,
    n_heads: int = 4,
    device: torch.device | str | None = None,
) -> SSLEncoderBundle:
    """Build a *randomly initialised* encoder bundle for tests / smoke runs.

    Use this when ``02_ssl/models/ssl_encoder.pt`` doesn't yet exist (e.g. CI,
    fresh checkout, dev sanity). The returned bundle has the same API as the
    pretrained one — embeddings are uninformative but shape-correct, which is
    enough to exercise downstream code paths.
    """
    if device is None:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    elif isinstance(device, str):
        device = torch.device(device)

    patch_cfg = PatchTSTConfig(
        num_input_channels=len(feature_columns),
        context_length=context_length,
        patch_length=patch_length,
        patch_stride=patch_length,
        d_model=d_model,
        num_attention_heads=n_heads,
        num_hidden_layers=n_layers,
        use_cls_token=False,
    )
    encoder = PatchTSTModel(patch_cfg).to(device)
    encoder.eval()
    for param in encoder.parameters():
        param.requires_grad_(False)

    n_channels = len(feature_columns)
    channel_mean = np.zeros(n_channels, dtype=np.float32)
    channel_std = np.ones(n_channels, dtype=np.float32)

    return SSLEncoderBundle(
        encoder=encoder,
        feature_columns=list(feature_columns),
        channel_mean=channel_mean,
        channel_std=channel_std,
        context_length=int(context_length),
        d_model=int(d_model),
        device=device,
    )
