"""
Federated Learning Coordinator (Improved)
=========================================
- Loads initial global model from generic baseline (fixes empty weights)
- Adds gradient norm clipping to prevent model explosion
- Adds stale client cleanup (removes clients not seen for 7 days)
- Provides full async API: register, get_model, submit_update, aggregate, get_status
"""

import asyncio
import logging
import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import numpy as np
from config import settings

logger = logging.getLogger(__name__)


@dataclass
class FLClientRecord:
    client_id: str
    device_id: str
    capabilities: Dict[str, Any] = field(default_factory=dict)
    last_seen: str = ""


@dataclass
class FLUpdateRecord:
    client_id: str
    round_id: int
    base_model_version: int
    num_samples: int
    weights_delta: List[float]
    metrics: Dict[str, Any] = field(default_factory=dict)
    submitted_at: str = ""


class FederatedLearningCoordinator:
    """Improved FL coordinator with initial model, norm clipping, and cleanup."""

    def __init__(self, min_updates_per_round: int = 2, max_delta_dim: int = 4096, use_initial_model: bool = True):
        self._lock = asyncio.Lock()
        self.min_updates_per_round = max(1, int(min_updates_per_round))
        self.max_delta_dim = max(8, int(max_delta_dim))
        self._stop_event = asyncio.Event()

        self.current_round = 1
        self.global_model_version = 1

        # Load initial model from generic baseline (or None if empty)
        if use_initial_model:
            initial_weights = self._load_initial_weights()
            self.global_weights = np.array(initial_weights) if initial_weights else None
        else:
            self.global_weights = None

        self.clients: Dict[str, FLClientRecord] = {}
        self.updates_by_round: Dict[int, List[FLUpdateRecord]] = {}


    def _load_initial_weights(self) -> List[float]:
        """Load initial global model from generic baseline (72‑dim)."""
        try:
            from services.baseline_manager import BaselineManager
            bm = BaselineManager()
            mean, _ = bm.get_warm_start_baseline()
            # Use the baseline mean as initial weights
            return mean.tolist()
        except Exception as e:
            logger.warning("Could not load initial model: %s, using zeros", e)
            return [0.0] * settings.feature_dim

    async def _cleanup_stale_clients(self):
        """Remove clients not seen for 7 days."""
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=3600)
            except asyncio.TimeoutError:
                pass
            
            if self._stop_event.is_set():
                break

            cutoff = datetime.now(timezone.utc) - timedelta(days=7)
            async with self._lock:
                stale = []
                for cid, rec in self.clients.items():
                    try:
                        last_seen = datetime.fromisoformat(rec.last_seen)
                        # Ensure timezone awareness if needed
                        if last_seen.tzinfo is None:
                            last_seen = last_seen.replace(tzinfo=timezone.utc)
                        if last_seen < cutoff:
                            stale.append(cid)
                    except (ValueError, TypeError) as e:
                        logger.warning("Malformed last_seen date for client %s: %s", cid, rec.last_seen)
                        # Prune clients with malformed dates as a safety measure
                        stale.append(cid)

                for cid in stale:
                    del self.clients[cid]
                if stale:
                    logger.info("Removed %d stale FL clients", len(stale))

    async def register_client(
        self,
        device_id: str,
        client_id: Optional[str] = None,
        capabilities: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Register (or refresh) a federated learning client."""
        normalized_device = str(device_id or "").strip()
        if not normalized_device:
            raise ValueError("device_id is required")

        resolved_client_id = str(client_id or "").strip()
        if not resolved_client_id:
            resolved_client_id = f"flc_{uuid.uuid4().hex[:12]}"

        async with self._lock:
            record = self.clients.get(resolved_client_id)
            if record is None:
                record = FLClientRecord(
                    client_id=resolved_client_id,
                    device_id=normalized_device,
                    capabilities=capabilities or {},
                    last_seen=datetime.now(timezone.utc).isoformat(),
                )
                self.clients[resolved_client_id] = record
            else:
                record.device_id = normalized_device
                if capabilities:
                    record.capabilities = capabilities
                record.last_seen = datetime.now(timezone.utc).isoformat()

            return {
                "status": "registered",
                "client_id": resolved_client_id,
                "round_id": self.current_round,
                "global_model_version": self.global_model_version,
                "min_updates_per_round": self.min_updates_per_round,
                "privacy_note": "Only model deltas are accepted; no raw events are uploaded.",
            }

    async def get_model(self, client_id: Optional[str] = None) -> Dict[str, Any]:
        """Return current global model metadata and weight vector."""
        async with self._lock:
            if client_id:
                record = self.clients.get(client_id)
                if record is not None:
                    record.last_seen = datetime.now(timezone.utc).isoformat()

            return {
                "status": "ok",
                "round_id": self.current_round,
                "global_model_version": self.global_model_version,
                "weights": self.global_weights.tolist() if self.global_weights is not None else [],
                "metadata": {
                    "algorithm": "weighted-delta-aggregation",
                    "max_delta_dim": self.max_delta_dim,
                },
            }

    async def submit_update(
        self,
        client_id: str,
        round_id: int,
        base_model_version: int,
        num_samples: int,
        weights_delta: List[float],
        metrics: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Queue a local model update for a federated round."""
        resolved_client_id = str(client_id or "").strip()
        if not resolved_client_id:
            raise ValueError("client_id is required")

        delta_values = [float(v) for v in weights_delta]
        if not delta_values:
            raise ValueError("weights_delta must not be empty")
        if len(delta_values) > self.max_delta_dim:
            raise ValueError(f"weights_delta length exceeds max {self.max_delta_dim}")

        async with self._lock:
            if resolved_client_id not in self.clients:
                raise ValueError("client_id is not registered")

            if round_id != self.current_round:
                raise ValueError(
                    f"round_id {round_id} does not match current round {self.current_round}"
                )

            if base_model_version != self.global_model_version:
                raise ValueError(
                    "base_model_version does not match latest global model version"
                )

            if self.global_weights is not None and self.global_weights.size > 0 and len(delta_values) != len(self.global_weights):
                raise ValueError("weights_delta length does not match global model dimensions")

            update = FLUpdateRecord(
                client_id=resolved_client_id,
                round_id=int(round_id),
                base_model_version=int(base_model_version),
                num_samples=max(1, int(num_samples)),
                weights_delta=delta_values,
                metrics=metrics or {},
                submitted_at=datetime.now(timezone.utc).isoformat(),
            )

            bucket = self.updates_by_round.setdefault(int(round_id), [])
            bucket.append(update)
            self.clients[resolved_client_id].last_seen = datetime.now(timezone.utc).isoformat()

            return {
                "status": "accepted",
                "round_id": int(round_id),
                "pending_updates": len(bucket),
                "min_updates_required": self.min_updates_per_round,
            }

    async def aggregate(self, round_id: Optional[int] = None, force: bool = False) -> Dict[str, Any]:
        """Aggregate queued updates for the requested round (or current round)."""
        async with self._lock:
            target_round = int(round_id or self.current_round)
            queued = list(self.updates_by_round.get(target_round, []))

            if not queued:
                return {
                    "status": "no_updates",
                    "round_id": target_round,
                    "global_model_version": self.global_model_version,
                }

            if len(queued) < self.min_updates_per_round and not force:
                return {
                    "status": "waiting",
                    "round_id": target_round,
                    "pending_updates": len(queued),
                    "min_updates_required": self.min_updates_per_round,
                    "global_model_version": self.global_model_version,
                }

            expected_dim = len(queued[0].weights_delta)
            compatible_updates = [u for u in queued if len(u.weights_delta) == expected_dim]
            if not compatible_updates:
                return {
                    "status": "invalid_updates",
                    "round_id": target_round,
                    "global_model_version": self.global_model_version,
                }

            total_samples = sum(max(1, u.num_samples) for u in compatible_updates)
            aggregate_delta = np.zeros(expected_dim)
            for update in compatible_updates:
                weight = max(1, update.num_samples) / max(total_samples, 1)
                aggregate_delta += np.array(update.weights_delta) * weight

            # Gradient norm clipping
            norm = np.linalg.norm(aggregate_delta)
            max_norm = 5.0
            if norm > max_norm:
                aggregate_delta = (aggregate_delta / norm) * max_norm
                logger.info("Clipped aggregate delta norm from %.2f to %.2f", norm, max_norm)

            if self.global_weights is None or len(self.global_weights) == 0:
                self.global_weights = np.zeros(expected_dim)
            elif len(self.global_weights) != expected_dim:
                raise ValueError("Global weights dimension mismatch")

            # Apply aggregated deltas to global weights
            self.global_weights += aggregate_delta

            self.global_model_version += 1
            self.updates_by_round[target_round] = []  # clear queued updates

            if target_round == self.current_round:
                self.current_round += 1

            return {
                "status": "aggregated",
                "round_id": target_round,
                "aggregated_updates": len(compatible_updates),
                "global_model_version": self.global_model_version,
                "next_round_id": self.current_round,
                "weights_dim": len(self.global_weights),
            }

    async def get_status(self) -> Dict[str, Any]:
        """Return current FL coordinator snapshot."""
        async with self._lock:
            pending_by_round = {
                str(round_id): len(updates)
                for round_id, updates in self.updates_by_round.items()
                if updates
            }
            return {
                "status": "ok",
                "current_round": self.current_round,
                "global_model_version": self.global_model_version,
                "registered_clients": len(self.clients),
                "pending_updates_by_round": pending_by_round,
                "weights_dim": len(self.global_weights),
                "min_updates_per_round": self.min_updates_per_round,
            }