"""https://docs.flagsmith.com/integrating-with-flagsmith/flagsmith-api-overview/admin-api/updating-flags"""

from collections.abc import Callable
from typing import Any

import pytest
from rest_framework.test import APIClient

from environments.models import Environment
from features.models import FeatureState
from features.multivariate.models import MultivariateFeatureOption
from features.versioning.tasks import enable_v2_versioning
from tests.integration.helpers import create_mv_option_with_api

type FeatureUpdatePayload = dict[str, Any]


@pytest.fixture(params=["feature_versioning_v1", "feature_versioning_v2"], autouse=True)
def versioned_environment(
    request: pytest.FixtureRequest,
    environment: int,
) -> Environment:
    if request.param == "feature_versioning_v2":
        enable_v2_versioning(environment_id=environment)
    return Environment.objects.get(id=environment)  # type: ignore[no-any-return]


@pytest.mark.parametrize(
    "endpoint,payload",
    [
        pytest.param(
            "update-flag-v1",
            lambda feature: {
                "feature": {"id": feature},
                "value": {"type": "string", "value": "control"},
                "multivariate_options": [
                    {
                        "percentage_allocation": 50,
                        "value": {"type": "string", "value": "half"},
                    },
                    {
                        "percentage_allocation": 10,
                        "value": {"type": "string", "value": "bit more"},
                    },
                ],
            },
            id="option_a",
        ),
        pytest.param(
            "update-flag-v2",
            lambda feature: {
                "feature": {"id": feature},
                "environment_default": {
                    "value": {"type": "string", "value": "control"},
                    "multivariate_options": [
                        {
                            "percentage_allocation": 50,
                            "value": {"type": "string", "value": "half"},
                        },
                        {
                            "percentage_allocation": 10,
                            "value": {"type": "string", "value": "bit more"},
                        },
                    ],
                },
            },
            id="option_b",
        ),
    ],
)
def test_update_flag__environment_defaults__adds_multivariate_options(
    admin_client: APIClient,
    environment_api_key: str,
    feature: int,
    versioned_environment: Environment,
    endpoint: str,
    payload: Callable[[int], FeatureUpdatePayload],
) -> None:
    # Given / When
    response = admin_client.post(
        f"/api/experiments/environments/{environment_api_key}/{endpoint}/",
        payload(feature),
        format="json",
    )

    # Then
    assert response.status_code == 204
    assert dict(
        FeatureState.objects.get_live_feature_states(
            environment=versioned_environment,
            feature_id=feature,
            feature_segment=None,
        )
        .get()
        .multivariate_feature_state_values.values_list(
            "multivariate_feature_option__string_value", "percentage_allocation"
        )
    ) == {"half": 50, "bit more": 10}


@pytest.mark.parametrize(
    "endpoint,payload",
    [
        pytest.param(
            "update-flag-v1",
            lambda feature, option: {
                "feature": {"id": feature},
                "multivariate_options": [
                    {
                        "id": option,
                        "percentage_allocation": 25,
                        "value": {"type": "string", "value": "halfer"},
                    },
                ],
            },
            id="option_a",
        ),
        pytest.param(
            "update-flag-v2",
            lambda feature, option: {
                "feature": {"id": feature},
                "environment_default": {
                    "multivariate_options": [
                        {
                            "id": option,
                            "percentage_allocation": 25,
                            "value": {"type": "string", "value": "halfer"},
                        },
                    ],
                },
            },
            id="option_b",
        ),
    ],
)
def test_update_flag__environment_defaults__updates_multivariate_options(
    admin_client: APIClient,
    environment_api_key: str,
    feature: int,
    mv_option_50_percent: int,
    versioned_environment: Environment,
    endpoint: str,
    payload: Callable[[int, int], FeatureUpdatePayload],
) -> None:
    # Given / When
    response = admin_client.post(
        f"/api/experiments/environments/{environment_api_key}/{endpoint}/",
        payload(feature, mv_option_50_percent),
        format="json",
    )

    # Then
    assert response.status_code == 204
    assert dict(
        FeatureState.objects.get_live_feature_states(
            environment=versioned_environment,
            feature_id=feature,
            feature_segment=None,
        )
        .get()
        .multivariate_feature_state_values.values_list(
            "multivariate_feature_option__string_value", "percentage_allocation"
        )
    ) == {"halfer": 25}


@pytest.mark.parametrize(
    "endpoint,payload",
    [
        pytest.param(
            "update-flag-v1",
            lambda feature, segment, option: {
                "feature": {"id": feature},
                "segment": {"id": segment},
                "multivariate_options": [
                    {"id": option, "percentage_allocation": 80},
                ],
            },
            id="option_a",
        ),
        pytest.param(
            "update-flag-v2",
            lambda feature, segment, option: {
                "feature": {"id": feature},
                "segment_overrides": [
                    {
                        "segment_id": segment,
                        "multivariate_options": [
                            {"id": option, "percentage_allocation": 80},
                        ],
                    },
                ],
            },
            id="option_b",
        ),
    ],
)
def test_update_flag__segment_override__updates_multivariate_options(
    admin_client: APIClient,
    environment_api_key: str,
    feature: int,
    mv_option_value: str,
    mv_option_50_percent: int,
    segment: int,
    # segment_featurestate: int,
    versioned_environment: Environment,
    endpoint: str,
    payload: Callable[[int, int, int], FeatureUpdatePayload],
) -> None:
    # Given / When
    response = admin_client.post(
        f"/api/experiments/environments/{environment_api_key}/{endpoint}/",
        payload(feature, segment, mv_option_50_percent),
        format="json",
    )

    # Then
    assert response.status_code == 204
    live_feature_states = FeatureState.objects.get_live_feature_states(
        environment=versioned_environment,
        feature_id=feature,
    )
    assert dict(
        live_feature_states.get(
            feature_segment__segment_id=segment
        ).multivariate_feature_state_values.values_list(
            "multivariate_feature_option__string_value", "percentage_allocation"
        )
    ) == {mv_option_value: 80}
    assert dict(
        live_feature_states.get(
            feature_segment=None
        ).multivariate_feature_state_values.values_list(
            "multivariate_feature_option__string_value", "percentage_allocation"
        )
    ) == {mv_option_value: 50}


@pytest.mark.parametrize(
    "endpoint,payload",
    [
        pytest.param(
            "update-flag-v1",
            lambda feature, kept_option: {
                "feature": {"id": feature},
                "multivariate_options": [
                    {"id": kept_option, "percentage_allocation": 50},
                ],
            },
            id="option_a",
        ),
        pytest.param(
            "update-flag-v2",
            lambda feature, kept_option: {
                "feature": {"id": feature},
                "environment_default": {
                    "multivariate_options": [
                        {"id": kept_option, "percentage_allocation": 50},
                    ],
                },
            },
            id="option_b",
        ),
    ],
)
def test_update_flag__environment_defaults__deletes_multivariate_options(
    admin_client: APIClient,
    environment_api_key: str,
    project: int,
    feature: int,
    mv_option_50_percent: int,
    endpoint: str,
    payload: Callable[[int, int], FeatureUpdatePayload],
) -> None:
    # Given
    deleted_option = create_mv_option_with_api(
        admin_client, project, feature, 40, "other_mv_value"
    )

    # When
    response = admin_client.post(
        f"/api/experiments/environments/{environment_api_key}/{endpoint}/",
        payload(feature, mv_option_50_percent),
        format="json",
    )

    # Then
    assert response.status_code == 204
    assert not MultivariateFeatureOption.objects.filter(id=deleted_option).exists()
    assert MultivariateFeatureOption.objects.filter(id=mv_option_50_percent).exists()


@pytest.mark.parametrize(
    "endpoint,payload",
    [
        pytest.param(
            "update-flag-v1",
            lambda feature: {
                "feature": {"id": feature},
                "multivariate_options": [
                    {
                        "percentage_allocation": 60,
                        "value": {"type": "string", "value": "more"},
                    },
                    {
                        "percentage_allocation": 50,
                        "value": {"type": "string", "value": "less"},
                    },
                ],
            },
            id="option_a",
        ),
        pytest.param(
            "update-flag-v2",
            lambda feature: {
                "feature": {"id": feature},
                "environment_default": {
                    "multivariate_options": [
                        {
                            "percentage_allocation": 60,
                            "value": {"type": "string", "value": "more"},
                        },
                        {
                            "percentage_allocation": 50,
                            "value": {"type": "string", "value": "less"},
                        },
                    ],
                },
            },
            id="option_b",
        ),
    ],
)
def test_update_flag__multivariate_percentage_allocation_exceeds_100__responds_400(
    admin_client: APIClient,
    environment_api_key: str,
    feature: int,
    endpoint: str,
    payload: Callable[[int], FeatureUpdatePayload],
) -> None:
    # Given / When
    response = admin_client.post(
        f"/api/experiments/environments/{environment_api_key}/{endpoint}/",
        payload(feature),
        format="json",
    )

    # Then
    assert response.status_code == 400
    assert "multivariate_options" in response.json()
    assert not MultivariateFeatureOption.objects.filter(feature_id=feature).exists()
