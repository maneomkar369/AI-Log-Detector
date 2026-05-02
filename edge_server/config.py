"""
Edge Server Configuration
=========================
Loads all settings from environment variables / .env file.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment or .env file."""

    model_config = SettingsConfigDict(
        env_file="../.env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── Database ──
    database_url: str = "sqlite+aiosqlite:///./anomaly_detection.db"

    # ── Redis ──
    redis_url: str = "redis://localhost:6379/0"

    # ── Server ──
    edge_server_host: str = "0.0.0.0"
    edge_server_port: int = 8000

    # ── Anomaly Detection ──
    anomaly_k_value: float = 3.0           # k multiplier for dynamic threshold
    ema_learning_rate: float = 0.05        # EMA α for baseline updates
    cusum_threshold: float = 5.0           # CUSUM drift detection threshold (legacy fallback)
    baseline_days: int = 7                 # Days to build initial baseline
    data_retention_days: int = 30          # Auto-delete data older than this

    # ── Robust Mahalanobis (Flaw #1) ──
    use_robust_mahalanobis: bool = True    # Use MinCovDet instead of raw inverse
    use_yeo_johnson_transform: bool = True # Apply Yeo-Johnson before distance calc

    # ── Self-Tuning CUSUM (Flaw #2) ──
    cusum_c1: float = 0.5                 # Allowance factor (δ = c1 · σ_D)
    cusum_c2: float = 5.0                 # Threshold factor (h = c2 · σ_D)
    cusum_window: int = 1000              # Rolling window size for σ_D estimation

    # ── Platt Scaling (Flaw #10) ──
    platt_slope: float = 2.0              # Slope for sigmoid calibration of anomaly probability

    # ── Supervised ML Ensemble Inference ──
    ml_ensemble_enabled: bool = True
    ml_ensemble_mode: str = "fallback"    # "primary", "fallback", or "disabled" (Flaw #5)
    ml_nsl_model_path: str = "ml_pipeline/output/nslkdd_real/rf_pipeline.pkl"
    ml_loghub_model_path: str = "ml_pipeline/output/loghub_real/loghub_text_pipeline.pkl"
    ml_ensemble_config_path: str = "ml_pipeline/output/ensemble/ensemble_config.json"
    ml_nsl_attack_threshold: float = 0.34
    ml_loghub_attack_threshold: float = 0.50
    ml_ensemble_weight_nsl: float = 0.70
    ml_ensemble_weight_loghub: float = 0.30
    ml_ensemble_threshold: float = 0.42

    # ── Feature Extraction ──
    feature_dim: int = 72                  # Total feature vector dimensions
    temporal_dim: int = 24                 # Hour-of-day bins
    sequential_dim: int = 28              # Markov transitions (top 10 apps → 10+10+8)
    interaction_dim: int = 20             # Keystroke / touch / swipe stats

    # ── NGROK ──
    ngrok_auth_token: Optional[str] = None
    ngrok_domain: Optional[str] = None

    # ── Authentication & Encryption ──
    device_shared_secret: str = "default_shared_secret_for_dev_only"
    database_encryption_key: Optional[str] = None

    # ── Rate Limiting & Feedback (Flaws #23, #25, #26) ──
    max_ws_rate_per_sec: int = 100
    tz_shift_threshold_multiplier: float = 2.0
    feedback_learning_multiplier: float = 5.0
    yeo_johnson_refit_interval: int = 5000

    # ── FCM ──
    fcm_server_key: Optional[str] = None

    # ── Dashboard ──
    dashboard_secret_key: str = "change-me-to-a-random-secret"
    dashboard_port: int = 5000

    # ── Rule-based Threat Intel ──
    # Comma-separated package names (lowercase) that should immediately trigger alerts.
    # Keep empty by default in production-safe mode; set explicit IOCs in .env when needed.
    malicious_apps: str = "com.google.android.calculator"
    # Comma-separated domains/hosts (lowercase) that should immediately trigger alerts.
    # Keep empty by default in production-safe mode; set explicit IOCs in .env when needed.
    malicious_domains: str = ""
    # Cooldown to avoid duplicate immediate alerts for the same indicator.
    rule_alert_cooldown_seconds: int = 120
    # Ignore known synthetic/test sources so they never generate production alerts.
    ignored_alert_device_ids: str = "ioc_test_device"
    ignored_alert_device_prefixes: str = "test_device_,ioc_test_"
    ignored_alert_packages: str = "com.bad.malware"

    # ── Dashboard CSP ──
    dashboard_csp_allow_unsafe_eval: bool = False

    # ── Phishing / URL Threat Detection ──
    safe_browsing_api_key: Optional[str] = None
    phishing_alert_threshold: float = 0.7       # Risk score to trigger immediate alert
    phishing_suspicious_threshold: float = 0.4  # Risk score for "suspicious" tagging

    # ── Federated Learning (Scaffold) ──
    fl_min_updates_per_round: int = 2
    fl_max_delta_dim: int = 4096

settings = Settings()
