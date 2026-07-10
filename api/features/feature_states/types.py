from typing import Literal, NotRequired, TypedDict


class FeatureIdentifierPayload(TypedDict):
    name: NotRequired[str]
    id: NotRequired[int]


class FeatureValuePayload(TypedDict):
    type: Literal["integer", "string", "boolean"]
    value: str


class SegmentPayload(TypedDict):
    id: int
    priority: NotRequired[int | None]


class SegmentIdentifierPayload(TypedDict):
    id: int


class MultivariateValuePayload(TypedDict):
    multivariate_feature_option: int
    percentage_allocation: float


class EnvironmentDefaultPayload(TypedDict):
    enabled: NotRequired[bool]
    value: NotRequired[FeatureValuePayload]


class SegmentOverridePayload(TypedDict):
    segment_id: int
    priority: NotRequired[int | None]
    enabled: NotRequired[bool]
    value: NotRequired[FeatureValuePayload]
    multivariate_feature_state_values: NotRequired[list[MultivariateValuePayload]]
