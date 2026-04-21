"""
Edge Server Configuration
=========================
Loads all settings from environment variables / .env file.
"""

from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment or .env file."""

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
    cusum_threshold: float = 5.0           # CUSUM drift detection threshold
    baseline_days: int = 7                 # Days to build initial baseline
    data_retention_days: int = 30          # Auto-delete data older than this

    # ── Feature Extraction ──
    feature_dim: int = 72                  # Total feature vector dimensions
    temporal_dim: int = 24                 # Hour-of-day bins
    sequential_dim: int = 28              # Markov transitions (top 10 apps → 10+10+8)
    interaction_dim: int = 20             # Keystroke / touch / swipe stats

    # ── NGROK ──
    ngrok_auth_token: Optional[str] = None
    ngrok_domain: Optional[str] = None

    # ── FCM ──
    fcm_server_key: Optional[str] = None

    # ── Dashboard ──
    dashboard_secret_key: str = "change-me-to-a-random-secret"
    dashboard_port: int = 5000

    # ── Rule-based Threat Intel ──
    # Comma-separated package names (lowercase) that should immediately trigger alerts.
    # Keep empty by default in production-safe mode; set explicit IOCs in .env when needed.
    malicious_apps: str = ""
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

    class Config:
        env_file = "../.env"
        env_file_encoding = "utf-8"
        case_sensitive = False


settings = Settings()
