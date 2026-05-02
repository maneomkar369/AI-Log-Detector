"""
Train a supervised anomaly classifier on the real NSL-KDD dataset.

Dataset source:
    hassan06/nslkdd (Kaggle via kagglehub)

Outputs:
    edge_server/ml_pipeline/output/nslkdd_real/
      - rf_pipeline.pkl
      - training_report.json
      - top_feature_importance.csv
      - threshold_config.json

Label mapping:
    normal -> 0
    all attack classes -> 1

This script tunes the attack decision threshold on a validation split to
improve recall (reduce missed attacks) while enforcing a minimum precision
floor suitable for demo/security use.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import joblib
import kagglehub
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_score, recall_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder


DATASET_REF = "hassan06/nslkdd"
OUTPUT_DIR = Path(__file__).resolve().parent / "output" / "nslkdd_real"


NSL_KDD_COLUMNS = [
    "duration",
    "protocol_type",
    "service",
    "flag",
    "src_bytes",
    "dst_bytes",
    "land",
    "wrong_fragment",
    "urgent",
    "hot",
    "num_failed_logins",
    "logged_in",
    "num_compromised",
    "root_shell",
    "su_attempted",
    "num_root",
    "num_file_creations",
    "num_shells",
    "num_access_files",
    "num_outbound_cmds",
    "is_host_login",
    "is_guest_login",
    "count",
    "srv_count",
    "serror_rate",
    "srv_serror_rate",
    "rerror_rate",
    "srv_rerror_rate",
    "same_srv_rate",
    "diff_srv_rate",
    "srv_diff_host_rate",
    "dst_host_count",
    "dst_host_srv_count",
    "dst_host_same_srv_rate",
    "dst_host_diff_srv_rate",
    "dst_host_same_src_port_rate",
    "dst_host_srv_diff_host_rate",
    "dst_host_serror_rate",
    "dst_host_srv_serror_rate",
    "dst_host_rerror_rate",
    "dst_host_srv_rerror_rate",
    "label",
    "difficulty",
]


def dataset_path() -> Path:
    return Path(kagglehub.dataset_download(DATASET_REF))


def load_split(file_path: Path) -> pd.DataFrame:
    return pd.read_csv(file_path, header=None, names=NSL_KDD_COLUMNS)


def to_binary_labels(series: pd.Series) -> np.ndarray:
    return np.where(series.astype(str).str.lower() == "normal", 0, 1)


def compute_metrics(y_true: np.ndarray, y_pred: np.ndarray, y_prob: np.ndarray) -> dict:
    metrics: Dict[str, Any] = {
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
    min_precision: float = 0.80,
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


def build_pipeline(categorical: list[str], numeric: list[str]) -> Pipeline:
    preprocessor = ColumnTransformer(
        transformers=[
            ("cat", OneHotEncoder(handle_unknown="ignore"), categorical),
            ("num", "passthrough", numeric),
        ]
    )

    model = RandomForestClassifier(
        n_estimators=450,
        random_state=42,
        class_weight="balanced_subsample",
        min_samples_leaf=2,
        n_jobs=-1,
    )

    return Pipeline(
        steps=[
            ("preprocess", preprocessor),
            ("model", model),
        ]
    )


def main() -> None:
    print("=" * 72)
    print("Training supervised model on NSL-KDD (real dataset)")
    print("=" * 72)

    ds_dir = dataset_path()
    train_file = ds_dir / "KDDTrain+.txt"
    test_file = ds_dir / "KDDTest+.txt"

    if not train_file.exists() or not test_file.exists():
        raise FileNotFoundError(
            f"Expected files KDDTrain+.txt and KDDTest+.txt not found in {ds_dir}"
        )

    train_df = load_split(train_file)
    test_df = load_split(test_file)

    x_train_full = train_df.drop(columns=["label", "difficulty"])
    y_train_full = to_binary_labels(train_df["label"])
    x_test = test_df.drop(columns=["label", "difficulty"])
    y_test = to_binary_labels(test_df["label"])

    categorical = ["protocol_type", "service", "flag"]
    numeric = [c for c in x_train_full.columns if c not in categorical]

    x_train, x_val, y_train, y_val = train_test_split(
        x_train_full,
        y_train_full,
        test_size=0.20,
        random_state=42,
        stratify=y_train_full,
    )

    validation_pipeline = build_pipeline(categorical, numeric)
    validation_pipeline.fit(x_train, y_train)
    val_prob = validation_pipeline.predict_proba(x_val)[:, 1]
    tuned_threshold_info = choose_recall_tuned_threshold(y_val, val_prob, min_precision=0.80)
    tuned_threshold = float(tuned_threshold_info["threshold"])

    pipeline = build_pipeline(categorical, numeric)
    pipeline.fit(x_train_full, y_train_full)

    y_prob = pipeline.predict_proba(x_test)[:, 1]
    y_pred_default = (y_prob >= 0.50).astype(int)
    y_pred_tuned = (y_prob >= tuned_threshold).astype(int)

    default_metrics = compute_metrics(y_test, y_pred_default, y_prob)
    tuned_metrics = compute_metrics(y_test, y_pred_tuned, y_prob)

    # Feature importance extraction after one-hot expansion.
    pre = pipeline.named_steps["preprocess"]
    clf = pipeline.named_steps["model"]
    feature_names = pre.get_feature_names_out()
    importance_df = pd.DataFrame(
        {
            "feature": feature_names,
            "importance": clf.feature_importances_,
        }
    ).sort_values("importance", ascending=False)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    model_path = OUTPUT_DIR / "rf_pipeline.pkl"
    report_path = OUTPUT_DIR / "training_report.json"
    importance_path = OUTPUT_DIR / "top_feature_importance.csv"
    threshold_path = OUTPUT_DIR / "threshold_config.json"

    joblib.dump(pipeline, model_path)
    importance_df.head(300).to_csv(importance_path, index=False)
    threshold_path.write_text(
        json.dumps(
            {
                "nsl_attack_threshold": tuned_threshold,
                "selection": tuned_threshold_info,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    report = {
        "dataset": {
            "kaggle_ref": DATASET_REF,
            "dataset_path": str(ds_dir),
            "train_file": str(train_file),
            "test_file": str(test_file),
            "train_rows": int(len(train_df)),
            "test_rows": int(len(test_df)),
            "task": "binary anomaly classification (normal vs attack)",
        },
        "model": {
            "type": "RandomForestClassifier",
            "n_estimators": 450,
            "class_weight": "balanced_subsample",
            "min_samples_leaf": 2,
            "categorical_features": categorical,
            "numeric_feature_count": len(numeric),
        },
        "threshold_tuning": {
            "validation_rows": int(len(x_val)),
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
            "feature_importance": str(importance_path),
            "threshold_config": str(threshold_path),
        },
    }

    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("\n[Training Complete]")
    print(f"Train rows: {len(train_df)}")
    print(f"Test rows: {len(test_df)}")
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
    print(f"Model pipeline: {model_path}")
    print(f"Report: {report_path}")
    print(f"Feature importance: {importance_path}")
    print(f"Threshold config: {threshold_path}")


if __name__ == "__main__":
    main()
