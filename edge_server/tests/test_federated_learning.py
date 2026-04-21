"""Tests for federated learning scaffold coordinator."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.federated_learning import FederatedLearningCoordinator


@pytest.mark.asyncio
async def test_register_and_get_model():
    coordinator = FederatedLearningCoordinator(min_updates_per_round=2, max_delta_dim=64)

    registered = await coordinator.register_client(device_id="device_a")
    client_id = registered["client_id"]

    model = await coordinator.get_model(client_id=client_id)

    assert registered["status"] == "registered"
    assert model["status"] == "ok"
    assert model["global_model_version"] == 1
    assert model["round_id"] == 1
    assert model["weights"] == []


@pytest.mark.asyncio
async def test_submit_and_aggregate_with_force():
    coordinator = FederatedLearningCoordinator(min_updates_per_round=2, max_delta_dim=64)

    r1 = await coordinator.register_client(device_id="device_1")
    r2 = await coordinator.register_client(device_id="device_2")

    await coordinator.submit_update(
        client_id=r1["client_id"],
        round_id=1,
        base_model_version=1,
        num_samples=10,
        weights_delta=[0.2, -0.1, 0.3],
    )
    await coordinator.submit_update(
        client_id=r2["client_id"],
        round_id=1,
        base_model_version=1,
        num_samples=30,
        weights_delta=[0.0, 0.2, 0.1],
    )

    result = await coordinator.aggregate(round_id=1, force=False)

    assert result["status"] == "aggregated"
    assert result["global_model_version"] == 2
    assert result["next_round_id"] == 2
    assert result["weights_dim"] == 3


@pytest.mark.asyncio
async def test_reject_update_from_unknown_client():
    coordinator = FederatedLearningCoordinator(min_updates_per_round=2, max_delta_dim=64)

    with pytest.raises(ValueError, match="not registered"):
        await coordinator.submit_update(
            client_id="unknown_client",
            round_id=1,
            base_model_version=1,
            num_samples=5,
            weights_delta=[0.1, 0.2],
        )
