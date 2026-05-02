"""
Train a second model on the real LogHub Android dataset.

Dataset source:
    omduggineni/loghub-android-log-data (Kaggle via kagglehub)

This script builds a supervised text classifier using weak labels:
    suspicious (1): log levels W/E/F
    normal (0): log levels V/D/I

Outputs:
    edge_server/ml_pipeline/output/loghub_real/
      - loghub_text_pipeline.pkl
      - training_report_text_model.json
      - threshold_config_text_model.json
      - high_risk_preview.csv
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

import joblib
import kagglehub
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_score, recall_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline


DATASET_REF = "omduggineni/loghub-android-log-data"
OUTPUT_DIR = Path(__file__).resolve().parent / "output" / "loghub_real"


LOG_LINE_RE = re.compile(
    r"^(?P<date>\d{2}-\d{2})\s+"
    r"(?P<time>\d{2}:\d{2}:\d{2}\.\d+)\s+"
    r"(?P<pid>\d+)\s+"
    r"(?P<tid>\d+)\s+"
    r"(?P<level>[VDIWEF])\s+"
    r"(?P<tag>[^:]+):\s*"
    r"(?P<message>.*)$"
)


@dataclass
class ParsedLog:
    level: str
    tag: str
    message: str

    @property
    def text(self) -> str:
        return f"{self.level} {self.tag} {self.message}".strip()

    @property
    def weak_label(self) -> int:
        return 1 if self.level in {"W", "E", "F"} else 0


def dataset_path() -> Path:
    return Path(kagglehub.dataset_download(DATASET_REF))


def find_log_file(dataset_dir: Path) -> Path:
    candidates = sorted(dataset_dir.rglob("*.log"))
    if not candidates:
        raise FileNotFoundError(f"No .log files found in dataset: {dataset_dir}")
    return candidates[0]


def parse_lines(lines: Iterable[str]) -> List[ParsedLog]:
    parsed: List[ParsedLog] = []
    for line in lines:
        match = LOG_LINE_RE.match(line.strip("\n"))
        if not match:
            continue
        gd = match.groupdict()
        parsed.append(
            ParsedLog(
                level=gd["level"],
                tag=gd["tag"].strip(),
                message=gd["message"].strip(),
            )
        )
    return parsed


def compute_metrics(y_true: np.ndarray, y_pred: np.ndarray, y_prob: np.ndarray) -> dict:
    metrics = {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1_score": float(f1_score(y_true, y_pred, zero_division=0)),
        "confusion_matrix": confusion_matrix(y_true, y_pred).tolist(),
    }
    try:
        metrics["roc_auc"] = float(roc_auc_score(y_true, y_prob))
    except ValueError:
        metrics["roc_auc"] = None
    return metrics


def threshold_stats(y_true: np.ndarray, y_prob: np.ndarray, threshold: float) -> dict:
    y_pred = (y_prob >= threshold).astype(int)
    precision = float(precision_score(y_true, y_pred, zero_division=0))
    recall = float(recall_score(y_true, y_pred, zero_division=0))
    f1 = float(f1_score(y_true, y_pred, zero_division=0))
    f2_denom = (4.0 * precision) + recall
    f2 = float((5.0 * precision * recall) / f2_denom) if f2_denom > 0 else 0.0
    return {
        "threshold": float(threshold),
        "precision": precision,
        "recall": recall,
        "f1_score": f1,
        "f2_score": f2,
    }


def choose_recall_tuned_threshold(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    min_precision: float = 0.65,
) -> dict:
    thresholds = np.linspace(0.05, 0.95, 91)
    best = None
    fallback = None

    for threshold in thresholds:
        stats = threshold_stats(y_true, y_prob, float(threshold))

        if fallback is None or stats["f2_score"] > fallback["f2_score"]:
            fallback = stats

        if stats["precision"] >= min_precision:
            if (
                best is None
                or stats["recall"] > best["recall"]
                or (
                    stats["recall"] == best["recall"]
                    and stats["f2_score"] > best["f2_score"]
                )
            ):
                best = stats

    if best is not None:
        best["selection_reason"] = f"max recall with precision >= {min_precision:.2f}"
        return best

    fallback["selection_reason"] = "fallback to best F2 score (precision floor unmet)"
    return fallback


def build_pipeline() -> Pipeline:
    return Pipeline(
        steps=[
            (
                "tfidf",
                TfidfVectorizer(
                    max_features=12000,
                    ngram_range=(1, 2),
                    min_df=2,
                    sublinear_tf=True,
                ),
            ),
            (
                "clf",
                LogisticRegression(
                    max_iter=1200,
                    class_weight="balanced",
                    solver="liblinear",
                    random_state=42,
                ),
            ),
        ]
    )


def train() -> None:
    print("=" * 72)
    print("Training second LogHub model (weak-label supervised text classifier)")
    print("=" * 72)

    ds_dir = dataset_path()
    log_file = find_log_file(ds_dir)

    with log_file.open("r", encoding="utf-8", errors="ignore") as fh:
        parsed = parse_lines(fh)

    if len(parsed) < 100:
        raise ValueError(f"Parsed too few valid lines: {len(parsed)}")

    df = pd.DataFrame(
        {
            "text": [p.text for p in parsed],
            "level": [p.level for p in parsed],
            "tag": [p.tag for p in parsed],
            "message": [p.message for p in parsed],
            "weak_label": [p.weak_label for p in parsed],
        }
    )

    if df["weak_label"].nunique() < 2:
        raise ValueError("Weak labels contain only one class; cannot train classifier")

    train_df, test_df = train_test_split(
        df,
        test_size=0.20,
        random_state=42,
        stratify=df["weak_label"],
    )
    train_sub_df, val_df = train_test_split(
        train_df,
        test_size=0.20,
        random_state=42,
        stratify=train_df["weak_label"],
    )

    threshold_pipeline = build_pipeline()
    threshold_pipeline.fit(train_sub_df["text"], train_sub_df["weak_label"])
    val_prob = threshold_pipeline.predict_proba(val_df["text"])[:, 1]

    tuned_threshold_info = choose_recall_tuned_threshold(
        val_df["weak_label"].to_numpy(),
        val_prob,
        min_precision=0.65,
    )
    tuned_threshold = float(tuned_threshold_info["threshold"])

    pipeline = build_pipeline()
    pipeline.fit(train_df["text"], train_df["weak_label"])

    test_prob = pipeline.predict_proba(test_df["text"])[:, 1]
    test_pred_default = (test_prob >= 0.50).astype(int)
    test_pred_tuned = (test_prob >= tuned_threshold).astype(int)

    default_metrics = compute_metrics(test_df["weak_label"].to_numpy(), test_pred_default, test_prob)
    tuned_metrics = compute_metrics(test_df["weak_label"].to_numpy(), test_pred_tuned, test_prob)

    preview_df = test_df.copy()
    preview_df["attack_probability"] = test_prob
    preview_df["predicted_attack_tuned"] = test_pred_tuned
    preview_df = preview_df.sort_values("attack_probability", ascending=False).head(300)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    model_path = OUTPUT_DIR / "loghub_text_pipeline.pkl"
    report_path = OUTPUT_DIR / "training_report_text_model.json"
    threshold_path = OUTPUT_DIR / "threshold_config_text_model.json"
    preview_path = OUTPUT_DIR / "high_risk_preview.csv"

    joblib.dump(pipeline, model_path)
    threshold_path.write_text(
        json.dumps(
            {
                "loghub_attack_threshold": tuned_threshold,
                "selection": tuned_threshold_info,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    preview_df.to_csv(preview_path, index=False)

    report = {
        "dataset": {
            "kaggle_ref": DATASET_REF,
            "dataset_path": str(ds_dir),
            "log_file": str(log_file),
            "parsed_rows": int(len(df)),
            "train_rows": int(len(train_df)),
            "validation_rows": int(len(val_df)),
            "test_rows": int(len(test_df)),
            "positive_ratio": float(df["weak_label"].mean()),
            "task": "weak-label text anomaly classification",
        },
        "model": {
            "type": "TfidfVectorizer + LogisticRegression",
            "max_features": 12000,
            "ngram_range": [1, 2],
            "class_weight": "balanced",
        },
        "threshold_tuning": {
            "selected_threshold": tuned_threshold,
            "selection_details": tuned_threshold_info,
            "baseline_threshold": 0.50,
        },
        "metrics": {
            "default_threshold_0_5": default_metrics,
            "tuned_threshold": tuned_metrics,
            "recall_delta": float(tuned_metrics["recall"] - default_metrics["recall"]),
            "precision_delta": float(tuned_metrics["precision"] - default_metrics["precision"]),
        },
        "artifacts": {
            "pipeline": str(model_path),
            "report": str(report_path),
            "threshold_config": str(threshold_path),
            "preview": str(preview_path),
        },
    }

    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("\n[Training Complete]")
    print(f"Parsed rows: {len(df)}")
    print(f"Selected threshold: {tuned_threshold:.2f}")
    print(
        "Default @0.50 -> "
        f"Precision: {default_metrics['precision']:.4f}, "
        f"Recall: {default_metrics['recall']:.4f}, "
        f"F1: {default_metrics['f1_score']:.4f}"
    )
    print(
        f"Tuned @{tuned_threshold:.2f} -> "
        f"Precision: {tuned_metrics['precision']:.4f}, "
        f"Recall: {tuned_metrics['recall']:.4f}, "
        f"F1: {tuned_metrics['f1_score']:.4f}"
    )
    print(f"Model: {model_path}")
    print(f"Report: {report_path}")
    print(f"Threshold config: {threshold_path}")


if __name__ == "__main__":
    train()
