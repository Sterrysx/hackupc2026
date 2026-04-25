"""Train the Stage 2 RUL head — distilled from `02_finetune_rul.ipynb`.

Loads the SSL-pretrained PatchTST encoder, attaches a regression head with
6 RUL outputs (one per component), trains on the canonical printer split,
and saves the fitted weights to ``ml_models/02_ssl/models/rul_head_ssl.pt``.

Defaults match the notebook (``pretrained_frozen`` regime). ``--quick``
trims epochs / dataset stride for fast smoke testing on CPU.

Usage::

    uv run python -m ml_models.02_ssl.train_rul_head            # full train
    uv run python -m ml_models.02_ssl.train_rul_head --quick    # ~minutes on CPU

The ``--quick`` flag still writes a real ``rul_head_ssl.pt`` so the
``Ai_Agent.forecast`` SSL branch can be exercised end-to-end without
needing a GPU.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset

# `ml_models/02_ssl/` is not a Python package (folder name starts with a digit),
# so `train_rul_head.py` is invoked as a script. Make the repo root importable.
HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ml_models.lib.data import (  # noqa: E402
    DEFAULT_FLEET_PATH, TEST_PRINTERS, TRAIN_PRINTERS, VAL_PRINTERS,
    filter_printers, load_fleet,
)
from ml_models.lib.features import build_feature_matrix  # noqa: E402
from sdg.schema import COMPONENT_IDS  # noqa: E402

MODELS_DIR = PROJECT_ROOT / "ml_models" / "02_ssl" / "models"
RESULTS_DIR = PROJECT_ROOT / "ml_models" / "02_ssl" / "results"
RUL_HEAD_PATH = MODELS_DIR / "rul_head_ssl.pt"
RUL_META_PATH = MODELS_DIR / "rul_head_meta.json"

RUL_CLIP = 365.0  # days — match notebook
RUL_COLS = [f"rul_{component_id}" for component_id in COMPONENT_IDS]


# --------------------------------------------------------- dataset / model


class RULDataset(Dataset):
    """Sliding-window dataset over the long-form parquet."""

    def __init__(
        self,
        df: pd.DataFrame,
        printer_ids,
        day_range: range,
        feature_cols: list[str],
        rul_cols: list[str],
        context_length: int,
        mean: np.ndarray,
        std: np.ndarray,
        stride: int = 14,
    ) -> None:
        self.context_length = int(context_length)
        self.stride = int(stride)
        self.feature_cols = feature_cols
        self.mean = mean.astype(np.float32)
        self.std = std.astype(np.float32)
        keep = filter_printers(df, printer_ids)
        keep = keep[(keep["day"] >= day_range.start) & (keep["day"] < day_range.stop)]
        self.samples: list[tuple[np.ndarray, np.ndarray]] = []
        for _pid, group in keep.groupby("printer_id", sort=False):
            arr = group[feature_cols].to_numpy(dtype=np.float32)
            ruls = group[rul_cols].to_numpy(dtype=np.float32)
            T = arr.shape[0]
            if T < self.context_length:
                continue
            for end in range(self.context_length, T, self.stride):
                window = arr[end - self.context_length : end]
                target = ruls[end - 1]
                if np.isnan(target).all():
                    continue
                self.samples.append((window, target))

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, idx: int):
        window, target = self.samples[idx]
        normed = (window - self.mean) / self.std
        clipped = np.minimum(np.where(np.isnan(target), RUL_CLIP, target), RUL_CLIP)
        mask = (~np.isnan(target)).astype(np.float32)
        return (
            torch.from_numpy(normed),
            torch.from_numpy(clipped.astype(np.float32) / RUL_CLIP),
            torch.from_numpy(mask),
        )


def build_regression_model(patch_cfg_dict: dict, load_pretrained: bool, device: torch.device):
    """Build the PatchTST regression model, optionally seeded from the SSL encoder."""
    from transformers import PatchTSTConfig, PatchTSTForRegression

    patch_cfg = PatchTSTConfig(**patch_cfg_dict)
    patch_cfg.num_targets = len(RUL_COLS)
    patch_cfg.prediction_length = 1
    patch_cfg.use_cls_token = False
    model = PatchTSTForRegression(patch_cfg)
    if load_pretrained:
        state = torch.load(MODELS_DIR / "ssl_encoder.pt", map_location="cpu", weights_only=True)
        encoder_state = {k: v for k, v in state.items() if k.startswith("model.")}
        missing, unexpected = model.load_state_dict(encoder_state, strict=False)
        print(f"  pretrained encoder loaded: {len(missing)} missing, {len(unexpected)} unexpected")
    return model.to(device)


# --------------------------------------------------------------- training


@dataclass
class TrainCfg:
    epochs: int = 3
    batch_size: int = 64
    lr_head: float = 5e-4
    weight_decay: float = 1e-4
    grad_clip: float = 1.0
    stride: int = 14


def freeze_encoder(model: nn.Module) -> None:
    for name, param in model.named_parameters():
        if not name.startswith("regression_head") and "head" not in name:
            param.requires_grad = False


def train_one_pass(
    model: nn.Module,
    loader: DataLoader,
    cfg: TrainCfg,
    device: torch.device,
) -> None:
    params = [p for p in model.parameters() if p.requires_grad]
    optim = torch.optim.AdamW(params, lr=cfg.lr_head, weight_decay=cfg.weight_decay)
    use_amp = device.type == "cuda"
    for epoch in range(cfg.epochs):
        model.train()
        running = 0.0
        steps = 0
        t0 = time.time()
        for x, y, m in loader:
            x = x.to(device); y = y.to(device); m = m.to(device)
            optim.zero_grad(set_to_none=True)
            with torch.amp.autocast("cuda", dtype=torch.bfloat16, enabled=use_amp):
                pred = model(past_values=x).regression_outputs.squeeze(-1)
                if pred.shape != y.shape:
                    pred = pred.view(y.shape)
                loss = ((pred - y) ** 2 * m).sum() / m.sum().clamp(min=1.0)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(params, cfg.grad_clip)
            optim.step()
            running += float(loss.detach().item())
            steps += 1
        elapsed = time.time() - t0
        avg = running / max(1, steps)
        print(f"  epoch {epoch:02d} | loss {avg:.4f} | {elapsed:.1f}s | {steps} steps")


@torch.no_grad()
def evaluate(model: nn.Module, loader: DataLoader, device: torch.device) -> dict:
    model.eval()
    sse = np.zeros(len(RUL_COLS), dtype=np.float64)
    abs_err = np.zeros(len(RUL_COLS), dtype=np.float64)
    n = np.zeros(len(RUL_COLS), dtype=np.float64)
    for x, y, m in loader:
        x = x.to(device); y = y.to(device); m = m.to(device)
        pred = model(past_values=x).regression_outputs.squeeze(-1)
        if pred.shape != y.shape:
            pred = pred.view(y.shape)
        err = (pred - y).cpu().numpy() * RUL_CLIP
        mask = m.cpu().numpy()
        sse     += (err ** 2 * mask).sum(axis=0)
        abs_err += (np.abs(err) * mask).sum(axis=0)
        n       += mask.sum(axis=0)
    rmse = np.sqrt(sse / np.maximum(n, 1.0))
    mae = abs_err / np.maximum(n, 1.0)
    return {
        "rmse_per_component": dict(zip(RUL_COLS, rmse.tolist())),
        "mae_per_component": dict(zip(RUL_COLS, mae.tolist())),
        "rmse_mean": float(rmse.mean()),
        "mae_mean": float(mae.mean()),
    }


# ----------------------------------------------------------------- main


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true",
                        help="Smoke-test mode: 1 epoch, large stride, train printers only.")
    parser.add_argument("--epochs", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--stride", type=int, default=None)
    args = parser.parse_args()

    cfg = TrainCfg()
    if args.quick:
        cfg.epochs = 1
        cfg.stride = 60      # 1 sample per ~2 months per printer
        cfg.batch_size = 32
    if args.epochs is not None:    cfg.epochs = args.epochs
    if args.batch_size is not None: cfg.batch_size = args.batch_size
    if args.stride is not None:    cfg.stride = args.stride

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"[train_rul_head] device={device}, cfg={cfg}, quick={args.quick}")

    # --- load the SSL artefacts produced by 01_pretrain.ipynb -------------
    saved = json.loads((MODELS_DIR / "ssl_config.json").read_text())
    patch_cfg_dict = saved["patch_cfg"]
    train_cfg = saved["train_cfg"]
    context_length = int(train_cfg["context_length"])
    scaler = np.load(MODELS_DIR / "feature_scaler.npz", allow_pickle=True)
    channel_mean = scaler["mean"]
    channel_std = scaler["std"]

    fleet = load_fleet(DEFAULT_FLEET_PATH)
    feat_fleet, feature_cols = build_feature_matrix(fleet)
    feat_fleet[RUL_COLS] = fleet[RUL_COLS].astype("float32").to_numpy()
    print(f"[train_rul_head] feature_cols={len(feature_cols)} channel_mean={channel_mean.shape}")

    n_days = int(feat_fleet["day"].max() + 1)
    train_range = range(0, n_days - 365)
    test_range = range(n_days - 365, n_days)

    train_ds = RULDataset(
        feat_fleet, TRAIN_PRINTERS, train_range,
        feature_cols, RUL_COLS, context_length,
        channel_mean, channel_std, stride=cfg.stride,
    )
    val_ds = RULDataset(
        feat_fleet, VAL_PRINTERS, test_range,
        feature_cols, RUL_COLS, context_length,
        channel_mean, channel_std, stride=cfg.stride,
    )
    test_ds = RULDataset(
        feat_fleet, TEST_PRINTERS, test_range,
        feature_cols, RUL_COLS, context_length,
        channel_mean, channel_std, stride=cfg.stride,
    )
    print(f"[train_rul_head] dataset sizes — train={len(train_ds)} val={len(val_ds)} test={len(test_ds)}")
    if len(train_ds) == 0:
        print("[train_rul_head] empty training set — aborting", file=sys.stderr)
        return 1

    nw = 0  # CPU runs hit DataLoader-pickle pain on Windows; 0 workers is safer.
    train_loader = DataLoader(train_ds, batch_size=cfg.batch_size, shuffle=True,
                              drop_last=True, num_workers=nw)
    val_loader   = DataLoader(val_ds,   batch_size=cfg.batch_size, shuffle=False, num_workers=nw)
    test_loader  = DataLoader(test_ds,  batch_size=cfg.batch_size, shuffle=False, num_workers=nw)

    print("[train_rul_head] building model (frozen SSL encoder + regression head)…")
    model = build_regression_model(patch_cfg_dict, load_pretrained=True, device=device)
    freeze_encoder(model)

    print("[train_rul_head] training…")
    train_one_pass(model, train_loader, cfg, device)

    print("[train_rul_head] evaluating on val printers…")
    val_metrics = evaluate(model, val_loader, device) if len(val_ds) else {}
    print("[train_rul_head] evaluating on test printers…")
    test_metrics = evaluate(model, test_loader, device) if len(test_ds) else {}

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    torch.save(model.state_dict(), RUL_HEAD_PATH)
    metadata = {
        "trained_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "device": str(device),
        "cfg": cfg.__dict__,
        "rul_clip_days": RUL_CLIP,
        "feature_cols": feature_cols,
        "context_length": context_length,
        "rul_targets": RUL_COLS,
        "patch_cfg": patch_cfg_dict,
        "train_size": len(train_ds),
        "val_size": len(val_ds),
        "test_size": len(test_ds),
        "val_metrics": val_metrics,
        "test_metrics": test_metrics,
        "quick_mode": bool(args.quick),
    }
    RUL_META_PATH.write_text(json.dumps(metadata, indent=2))
    print(f"[train_rul_head] wrote {RUL_HEAD_PATH}  ({RUL_HEAD_PATH.stat().st_size/1e6:.2f} MB)")
    print(f"[train_rul_head] wrote {RUL_META_PATH}")
    if test_metrics:
        print(f"[train_rul_head] test metrics: rmse_mean={test_metrics['rmse_mean']:.2f}d  mae_mean={test_metrics['mae_mean']:.2f}d")
    return 0


if __name__ == "__main__":
    sys.exit(main())
