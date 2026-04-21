"""
Federated Learning Coordinator (Scaffold)
=========================================
Provides a minimal privacy-preserving FL control plane:
- device/client registration
- global model retrieval
- local update submission (weight deltas only)
- weighted aggregation into a new global model version

This scaffold does not store or transmit raw behavioral events.
"""

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


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
    """In-memory federated learning coordinator for API scaffolding."""

    def __init__(self, min_updates_per_round: int = 2, max_delta_dim: int = 4096):
        self._lock = asyncio.Lock()

        self.min_updates_per_round = max(1, int(min_updates_per_round))
        self.max_delta_dim = max(8, int(max_delta_dim))

        self.current_round = 1
        self.global_model_version = 1
        self.global_weights: List[float] = []

        self.clients: Dict[str, FLClientRecord] = {}
        self.updates_by_round: Dict[int, List[FLUpdateRecord]] = {}

    @staticmethod
    def _utcnow_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

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
                    last_seen=self._utcnow_iso(),
                )
                self.clients[resolved_client_id] = record
            else:
                record.device_id = normalized_device
                if capabilities:
                    record.capabilities = capabilities
                record.last_seen = self._utcnow_iso()

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
                    record.last_seen = self._utcnow_iso()

            return {
                "status": "ok",
                "round_id": self.current_round,
                "global_model_version": self.global_model_version,
                "weights": list(self.global_weights),
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

        delta_values = [float(value) for value in weights_delta]
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

            if self.global_weights and len(delta_values) != len(self.global_weights):
                raise ValueError("weights_delta length does not match global model dimensions")

            update = FLUpdateRecord(
                client_id=resolved_client_id,
                round_id=int(round_id),
                base_model_version=int(base_model_version),
                num_samples=max(1, int(num_samples)),
                weights_delta=delta_values,
                metrics=metrics or {},
                submitted_at=self._utcnow_iso(),
            )

            bucket = self.updates_by_round.setdefault(int(round_id), [])
            bucket.append(update)

            self.clients[resolved_client_id].last_seen = self._utcnow_iso()

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

            total_samples = sum(max(1, int(update.num_samples)) for update in compatible_updates)
            aggregate_delta = [0.0] * expected_dim
            for update in compatible_updates:
                weight = max(1, int(update.num_samples)) / max(total_samples, 1)
                for idx, value in enumerate(update.weights_delta):
                    aggregate_delta[idx] += value * weight

            if not self.global_weights:
                self.global_weights = [0.0] * expected_dim

            self.global_weights = [
                self.global_weights[idx] + aggregate_delta[idx]
                for idx in range(expected_dim)
            ]

            self.global_model_version += 1
            self.updates_by_round[target_round] = []

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
