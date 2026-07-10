from typing import Literal, NotRequired, TypedDict

from features.models import Feature


class FeatureIdentifierPayload(TypedDict):
    """Identifies a feature by exactly one of `name` or `id`."""

    name: NotRequired[str]
    id: NotRequired[int]


class FeatureValuePayload(TypedDict):
    """A typed feature value, always transported as a string."""

    type: Literal["integer", "string", "boolean"]
    value: str


class SegmentPayload(TypedDict):
    """Targets a segment override, optionally re-prioritising it."""

    id: int
    priority: NotRequired[int | None]


class SegmentIdentifierPayload(TypedDict):
    """Identifies a segment by `id`."""

    id: int


class MultivariateValuePayload(TypedDict):
    """A weight for an existing multivariate option."""

    multivariate_feature_option: int
    percentage_allocation: float


class _BaseMultivariateOptionPayload(TypedDict):
    percentage_allocation: float


class MultivariateOptionPayload(_BaseMultivariateOptionPayload):
    """An environment-level variant: absent `id` creates it; `value` (re)sets it."""

    id: NotRequired[int]
    value: NotRequired[FeatureValuePayload]


class SegmentOverrideMultivariateOptionPayload(_BaseMultivariateOptionPayload):
    """A re-weight of a variant that already exists on the feature."""

    id: int


class EnvironmentDefaultPayload(TypedDict):
    """The environment-default part of a flag update (Option B).

    https://docs.flagsmith.com/integrating-with-flagsmith/flagsmith-api-overview/admin-api/updating-flags
    """

    enabled: NotRequired[bool]
    value: NotRequired[FeatureValuePayload]
    multivariate_options: NotRequired[list[MultivariateOptionPayload]]


class SegmentOverridePayload(TypedDict):
    """One segment override in a flag update (Option B).

    https://docs.flagsmith.com/integrating-with-flagsmith/flagsmith-api-overview/admin-api/updating-flags"""

    segment_id: int
    priority: NotRequired[int | None]
    enabled: NotRequired[bool]
    value: NotRequired[FeatureValuePayload]
    multivariate_feature_state_values: NotRequired[list[MultivariateValuePayload]]
    multivariate_options: NotRequired[list[SegmentOverrideMultivariateOptionPayload]]


class UpdateFlagOptionAPayload(TypedDict):
    """Flag update (Option A) request body, with `feature` resolved."""

    feature: Feature
    segment: NotRequired[SegmentPayload]
    enabled: NotRequired[bool]
    value: NotRequired[FeatureValuePayload]
    multivariate_options: NotRequired[list[MultivariateOptionPayload]]


class UpdateFlagOptionBPayload(TypedDict):
    """Flag update (Option B) request body, with `feature` resolved."""

    feature: Feature
    environment_default: NotRequired[EnvironmentDefaultPayload]
    segment_overrides: NotRequired[list[SegmentOverridePayload]]


class DeleteSegmentOverridePayload(TypedDict):
    """Delete request body, with `feature` resolved."""

    feature: Feature
    segment: SegmentIdentifierPayload
