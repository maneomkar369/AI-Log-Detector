"""
Train an anomaly detector on the real LogHub Android log dataset.

Dataset source:
    omduggineni/loghub-android-log-data (Kaggle via kagglehub)

Outputs:
    edge_server/ml_pipeline/output/loghub_real/
      - isolation_forest_model.pkl
      - tfidf_vectorizer.pkl
      - training_report.json
      - anomaly_preview.csv

Notes:
    The dataset does not ship with strict anomaly labels, so this script uses
    an unsupervised Isolation Forest model for training.
    For evaluation visibility, it reports "weak-label" metrics where lines with
    log levels W/E/F are treated as suspicious proxies.
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
from sklearn.ensemble import IsolationForest
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_score, recall_score
from sklearn.model_selection import train_test_split


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
        # The model learns both semantic message cues and source context.
        return f"{self.level} {self.tag} {self.message}".strip()

    @property
    def weak_label(self) -> int:
        # Weak proxy label for quality reporting only (not used for training).
        return 1 if self.level in {"W", "E", "F"} else 0


def download_dataset() -> Path:
    path = Path(kagglehub.dataset_download(DATASET_REF))
    return path


def find_log_file(dataset_dir: Path) -> Path:
    candidates = sorted(dataset_dir.rglob("*.log"))
    if not candidates:
        raise FileNotFoundError(f"No .log file found in dataset directory: {dataset_dir}")
    return candidates[0]


def parse_lines(lines: Iterable[str]) -> List[ParsedLog]:
    parsed: List[ParsedLog] = []
    for line in lines:
        line = line.rstrip("\n")
        match = LOG_LINE_RE.match(line)
        if not match:
            continue
        groups = match.groupdict()
        parsed.append(
            ParsedLog(
                level=groups["level"],
                tag=groups["tag"].strip(),
                message=groups["message"].strip(),
            )
        )
    return parsed


def weak_eval_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1_score": float(f1_score(y_true, y_pred, zero_division=0)),
        "confusion_matrix": confusion_matrix(y_true, y_pred).tolist(),
    }


def train() -> None:
    print("=" * 72)
    print("Training on real LogHub Android dataset")
    print("=" * 72)

    dataset_dir = download_dataset()
    log_file = find_log_file(dataset_dir)
    print(f"[Dataset] Downloaded to: {dataset_dir}")
    print(f"[Dataset] Using log file: {log_file}")

    with log_file.open("r", encoding="utf-8", errors="ignore") as fh:
        parsed = parse_lines(fh)

    if len(parsed) < 100:
        raise ValueError(
            f"Parsed too few valid log lines ({len(parsed)}). Expected at least 100."
        )

    df = pd.DataFrame(
        {
            "text": [p.text for p in parsed],
            "level": [p.level for p in parsed],
            "tag": [p.tag for p in parsed],
            "message": [p.message for p in parsed],
            "weak_label": [p.weak_label for p in parsed],
        }
    )

    train_df, test_df = train_test_split(df, test_size=0.2, random_state=42, shuffle=True)

    vectorizer = TfidfVectorizer(max_features=8000, ngram_range=(1, 2), min_df=2)
    x_train = vectorizer.fit_transform(train_df["text"])
    x_test = vectorizer.transform(test_df["text"])

    model = IsolationForest(
        n_estimators=250,
        contamination=0.10,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(x_train)

    pred_test_raw = model.predict(x_test)
    pred_test = np.where(pred_test_raw == -1, 1, 0)
    true_test = test_df["weak_label"].to_numpy()

    metrics = weak_eval_metrics(true_test, pred_test)

    # Build a small anomaly preview for quick manual inspection.
    all_x = vectorizer.transform(df["text"])
    anomaly_score = model.decision_function(all_x)
    pred_all = np.where(model.predict(all_x) == -1, 1, 0)

    preview_df = df.copy()
    preview_df["predicted_anomaly"] = pred_all
    preview_df["anomaly_score"] = anomaly_score
    preview_df = preview_df.sort_values("anomaly_score", ascending=True).head(200)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    model_path = OUTPUT_DIR / "isolation_forest_model.pkl"
    vectorizer_path = OUTPUT_DIR / "tfidf_vectorizer.pkl"
    report_path = OUTPUT_DIR / "training_report.json"
    preview_path = OUTPUT_DIR / "anomaly_preview.csv"

    joblib.dump(model, model_path)
    joblib.dump(vectorizer, vectorizer_path)
    preview_df.to_csv(preview_path, index=False)

    report = {
        "dataset": {
            "kaggle_ref": DATASET_REF,
            "dataset_path": str(dataset_dir),
            "log_file": str(log_file),
            "parsed_lines": int(len(df)),
            "train_rows": int(len(train_df)),
            "test_rows": int(len(test_df)),
        },
        "model": {
            "type": "IsolationForest",
            "n_estimators": 250,
            "contamination": 0.10,
            "vectorizer": "TfidfVectorizer(ngram_range=(1,2), max_features=8000)",
        },
        "weak_label_metrics": metrics,
        "artifacts": {
            "model": str(model_path),
            "vectorizer": str(vectorizer_path),
            "report": str(report_path),
            "anomaly_preview": str(preview_path),
        },
    }

    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("\n[Training Complete]")
    print(f"Parsed lines: {len(df)}")
    print(f"Weak-label F1: {metrics['f1_score']:.4f}")
    print(f"Model saved: {model_path}")
    print(f"Vectorizer saved: {vectorizer_path}")
    print(f"Report saved: {report_path}")
    print(f"Preview saved: {preview_path}")


if __name__ == "__main__":
    train()
