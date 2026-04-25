# Stage 02 — SSL surrogate

PatchTST self-supervised pretraining + supervised RUL head → fast surrogate for
τ search.

## Notebooks (run in order)

1. `00_generate_policy_runs.ipynb` — Latin-Hypercube sample K τ vectors and run
   the SDG simulator under each, on **train printers only**. Produces
   `data/policy_runs/policy_{k:03d}.parquet` and a `manifest.json`. Optional —
   the pretraining notebook falls back to `fleet_baseline.parquet` alone if
   no policy runs exist.
2. `01_pretrain.ipynb` — masked-patch SSL on multivariate telemetry windows.
   Saves `models/ssl_encoder.pt`, `models/ssl_config.json`,
   `models/feature_scaler.npz`.
3. `02_finetune_rul.ipynb` — frozen-encoder RUL regression head; sliding-cumulative
   CV on val printers; final test on held-out test printers; ablation against
   from-scratch baseline. Saves `models/rul_head_ssl.pt` and metrics under
   `results/`.
4. `03_surrogate_search.ipynb` — uses the RUL model + an analytical event-rate
   model to score candidate τ vectors quickly; Optuna runs 500 trials in
   seconds, then the top 5 are re-evaluated with the **real simulator** on the
   test split. The winning τ is saved to `results/best_tau_surrogate.yaml`.

## Data splits (locked in `lib/data.py`)

- Train: printer_id 0..69 (70 printers) — SSL pretraining + supervised fit.
- Val: printer_id 70..84 (15 printers) — expanding-window time-series CV.
- Test: printer_id 85..99 (15 printers) — final eval, held out throughout.

## Architecture

- HuggingFace `PatchTSTConfig` / `PatchTSTForPretraining` for the pretext task.
- `PatchTSTForRegression` re-using the pretrained backbone for RUL.
- Default backbone: `d_model=256`, 4 layers, 8 heads, patch_length=30 days,
  context_length=360 days. All overridable via Optuna (see end of
  `01_pretrain.ipynb`).

## GPU notes

- Mixed precision (`torch.amp.autocast` with `bf16`) on by default for CUDA.
- Multi-GPU: notebooks opportunistically wrap the model in `nn.DataParallel`
  when `torch.cuda.device_count() > 1`. For long sweeps prefer DDP via
  `accelerate launch` from the CLI.
