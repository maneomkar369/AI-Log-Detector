"""
Build combined ensemble configuration from trained NSL-KDD and LogHub models.

This script does not retrain base models. It reads training reports and
threshold configs, then writes a single ensemble config consumed at runtime by
the edge_server ML inference loader.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


BASE_OUTPUT = Path(__file__).resolve().parent / "output"
NSL_DIR = BASE_OUTPUT / "nslkdd_real"
LOGHUB_DIR = BASE_OUTPUT / "loghub_real"
ENSEMBLE_DIR = BASE_OUTPUT / "ensemble"


def read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Required file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def clip(value: float, low: float, high: float) -> float:
    return max(low, min(value, high))


def main() -> None:
    print("=" * 72)
    print("Building combined ensemble config")
    print("=" * 72)

    nsl_report = read_json(NSL_DIR / "training_report.json")
    nsl_threshold_cfg = read_json(NSL_DIR / "threshold_config.json")

    loghub_report = read_json(LOGHUB_DIR / "training_report_text_model.json")
    loghub_threshold_cfg = read_json(LOGHUB_DIR / "threshold_config_text_model.json")

    nsl_metrics = nsl_report["metrics"]["tuned_threshold"]
    loghub_metrics = loghub_report["metrics"]["tuned_threshold"]

    nsl_precision = float(nsl_metrics["precision"])
    loghub_precision = float(loghub_metrics["precision"])
    nsl_recall = float(nsl_metrics["recall"])
    loghub_recall = float(loghub_metrics["recall"])

    # Weight by precision reliability with a floor to retain NSL signal.
    precision_sum = max(nsl_precision + loghub_precision, 1e-6)
    nsl_weight_raw = nsl_precision / precision_sum
    nsl_weight = round(clip(nsl_weight_raw, 0.55, 0.85), 3)
    loghub_weight = round(1.0 - nsl_weight, 3)

    nsl_threshold = float(nsl_threshold_cfg["nsl_attack_threshold"])
    loghub_threshold = float(loghub_threshold_cfg["loghub_attack_threshold"])

    # Recall-first ensemble threshold; lower value catches more suspicious windows.
    mean_recall = (nsl_recall + loghub_recall) / 2.0
    ensemble_threshold = 0.42 if mean_recall >= 0.75 else 0.38

    config = {
        "version": "ensemble-v1",
        "objective": "high-recall security demo",
        "weights": {
            "nsl": nsl_weight,
            "loghub": loghub_weight,
        },
        "thresholds": {
            "nsl": nsl_threshold,
            "loghub": loghub_threshold,
            "ensemble": ensemble_threshold,
        },
        "model_artifacts": {
            "nsl_pipeline": str((NSL_DIR / "rf_pipeline.pkl").resolve()),
            "loghub_pipeline": str((LOGHUB_DIR / "loghub_text_pipeline.pkl").resolve()),
        },
        "training_snapshot": {
            "nsl": {
                "precision": nsl_precision,
                "recall": nsl_recall,
            },
            "loghub": {
                "precision": loghub_precision,
                "recall": loghub_recall,
            },
        },
    }

    ENSEMBLE_DIR.mkdir(parents=True, exist_ok=True)
    config_path = ENSEMBLE_DIR / "ensemble_config.json"
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")

    print("\n[Ensemble Config Ready]")
    print(f"NSL weight: {nsl_weight:.3f}")
    print(f"LogHub weight: {loghub_weight:.3f}")
    print(f"NSL threshold: {nsl_threshold:.3f}")
    print(f"LogHub threshold: {loghub_threshold:.3f}")
    print(f"Ensemble threshold: {ensemble_threshold:.3f}")
    print(f"Config path: {config_path}")


if __name__ == "__main__":
    main()
