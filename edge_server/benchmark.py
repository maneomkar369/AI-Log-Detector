#!/usr/bin/env python3
"""
Edge Server Benchmark Script (Flaw #7)
========================================
Measures inference latency, memory usage, and throughput for the
anomaly detection pipeline on the target hardware.

Usage:
    python benchmark.py --duration 60 --devices 1
    python benchmark.py --duration 300 --devices 5 --output results.json

Metrics collected:
    - Per-window inference latency (p50, p95, p99)
    - Feature extraction time
    - Mahalanobis distance computation time
    - Memory usage (RSS peak, average)
    - Throughput (windows/second)
    - Power consumption placeholder (requires USB power meter)
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime

import numpy as np

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.feature_extractor import FeatureExtractor
from services.anomaly_detector import AnomalyDetector
from services.baseline_manager import BaselineManager

# Optional memory tracking
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


def generate_synthetic_events(n_events: int = 50) -> list:
    """Generate a batch of synthetic behavioral events for benchmarking."""
    events = []
    base_ts = int(time.time() * 1000)
    apps = [
        "com.whatsapp", "com.chrome", "com.instagram",
        "com.twitter", "com.gmail", "com.youtube",
        "com.spotify", "com.maps", "com.camera", "com.phone",
    ]

    for i in range(n_events):
        ts = base_ts + i * 200  # 200ms apart

        # Mix of event types
        if i % 5 == 0:
            events.append({
                "event_type": "APP_USAGE",
                "package_name": apps[i % len(apps)],
                "timestamp": ts,
                "data": "{}",
            })
        elif i % 5 == 1:
            events.append({
                "event_type": "KEYSTROKE",
                "package_name": apps[i % len(apps)],
                "timestamp": ts,
                "data": json.dumps({"latency": np.random.exponential(100)}),
            })
        elif i % 5 == 2:
            events.append({
                "event_type": "TOUCH",
                "package_name": apps[i % len(apps)],
                "timestamp": ts,
                "data": json.dumps({"duration": np.random.exponential(200)}),
            })
        elif i % 5 == 3:
            events.append({
                "event_type": "NETWORK_TRAFFIC",
                "package_name": apps[i % len(apps)],
                "timestamp": ts,
                "data": json.dumps({
                    "rxBytesDelta": int(np.random.exponential(5000)),
                    "txBytesDelta": int(np.random.exponential(2000)),
                }),
            })
        else:
            events.append({
                "event_type": "SYSTEM_STATE",
                "package_name": "",
                "timestamp": ts,
                "data": json.dumps({
                    "lowMemory": False,
                    "batteryPct": np.random.randint(20, 95),
                }),
            })

    return events


def run_benchmark(duration_seconds: int, n_devices: int):
    """Run the benchmark loop and collect metrics."""
    print(f"\n{'='*60}")
    print(f"  AI-Log-Detector Edge Benchmark")
    print(f"  Duration: {duration_seconds}s | Simulated devices: {n_devices}")
    print(f"{'='*60}\n")

    extractor = FeatureExtractor()
    detector = AnomalyDetector()
    baseline_mgr = BaselineManager()

    # Initialize baseline from synthetic data
    print("[1/4] Generating synthetic baseline...")
    baseline_samples = []
    for _ in range(100):
        events = generate_synthetic_events(50)
        vec, _ = extractor.extract(events)
        baseline_samples.append(vec)

    samples_array = np.array(baseline_samples)
    baseline_mean, baseline_cov = baseline_mgr.initialize_baseline(samples_array)
    print(f"  Baseline initialized: mean shape={baseline_mean.shape}, cov shape={baseline_cov.shape}")

    # Warm-up
    print("[2/4] Warming up...")
    for _ in range(10):
        events = generate_synthetic_events(50)
        vec, mask = extractor.extract(events)
        detector.detect(
            feature_vector=vec,
            baseline_mean=baseline_mean,
            baseline_cov=baseline_cov,
            feature_mask=mask,
        )

    # Benchmark
    print(f"[3/4] Running benchmark for {duration_seconds}s...")
    extract_times = []
    detect_times = []
    total_times = []
    memory_samples = []
    process = psutil.Process() if HAS_PSUTIL else None

    start_time = time.monotonic()
    iterations = 0

    while (time.monotonic() - start_time) < duration_seconds:
        for device_idx in range(n_devices):
            t0 = time.perf_counter()

            # Feature extraction
            events = generate_synthetic_events(50)
            t1 = time.perf_counter()
            vec, mask = extractor.extract(events)
            t2 = time.perf_counter()

            # Anomaly detection
            result = detector.detect(
                feature_vector=vec,
                baseline_mean=baseline_mean,
                baseline_cov=baseline_cov,
                feature_mask=mask,
            )
            t3 = time.perf_counter()

            extract_times.append((t2 - t1) * 1000)  # ms
            detect_times.append((t3 - t2) * 1000)    # ms
            total_times.append((t3 - t0) * 1000)     # ms
            iterations += 1

        # Memory sample
        if process:
            mem_info = process.memory_info()
            memory_samples.append(mem_info.rss / (1024 * 1024))  # MB

    elapsed = time.monotonic() - start_time

    # Compute statistics
    print("[4/4] Computing results...\n")

    def percentiles(data):
        arr = np.array(data)
        return {
            "mean": float(np.mean(arr)),
            "p50": float(np.percentile(arr, 50)),
            "p95": float(np.percentile(arr, 95)),
            "p99": float(np.percentile(arr, 99)),
            "min": float(np.min(arr)),
            "max": float(np.max(arr)),
        }

    results = {
        "timestamp": datetime.utcnow().isoformat(),
        "config": {
            "duration_seconds": duration_seconds,
            "n_devices": n_devices,
            "iterations": iterations,
        },
        "feature_extraction_ms": percentiles(extract_times),
        "anomaly_detection_ms": percentiles(detect_times),
        "total_pipeline_ms": percentiles(total_times),
        "throughput": {
            "windows_per_second": round(iterations / elapsed, 2),
            "elapsed_seconds": round(elapsed, 2),
        },
        "memory_mb": {},
        "power": {
            "note": "Requires USB power meter. Placeholder values.",
            "idle_watts": None,
            "detection_watts": None,
        },
    }

    if memory_samples:
        results["memory_mb"] = {
            "mean": round(float(np.mean(memory_samples)), 1),
            "peak": round(float(np.max(memory_samples)), 1),
            "min": round(float(np.min(memory_samples)), 1),
        }

    # Pretty print
    print(f"{'Metric':<40} {'Value':>15}")
    print(f"{'-'*55}")
    print(f"{'Total iterations':<40} {iterations:>15}")
    print(f"{'Throughput (windows/sec)':<40} {results['throughput']['windows_per_second']:>15.1f}")
    print()
    print(f"{'Feature extraction p50 (ms)':<40} {results['feature_extraction_ms']['p50']:>15.3f}")
    print(f"{'Feature extraction p99 (ms)':<40} {results['feature_extraction_ms']['p99']:>15.3f}")
    print(f"{'Anomaly detection p50 (ms)':<40} {results['anomaly_detection_ms']['p50']:>15.3f}")
    print(f"{'Anomaly detection p99 (ms)':<40} {results['anomaly_detection_ms']['p99']:>15.3f}")
    print(f"{'Total pipeline p50 (ms)':<40} {results['total_pipeline_ms']['p50']:>15.3f}")
    print(f"{'Total pipeline p99 (ms)':<40} {results['total_pipeline_ms']['p99']:>15.3f}")

    if memory_samples:
        print()
        print(f"{'Memory RSS mean (MB)':<40} {results['memory_mb']['mean']:>15.1f}")
        print(f"{'Memory RSS peak (MB)':<40} {results['memory_mb']['peak']:>15.1f}")

    print(f"\n{'='*55}")

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Benchmark AI-Log-Detector edge inference pipeline"
    )
    parser.add_argument(
        "--duration", type=int, default=60,
        help="Benchmark duration in seconds (default: 60)",
    )
    parser.add_argument(
        "--devices", type=int, default=1,
        help="Number of simulated devices (default: 1)",
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Output JSON file path (optional)",
    )
    args = parser.parse_args()

    results = run_benchmark(args.duration, args.devices)

    if args.output:
        with open(args.output, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\nResults saved to {args.output}")


if __name__ == "__main__":
    main()
