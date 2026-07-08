from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from pydantic import BaseModel, computed_field

from core.dataclasses import AuthorData
from features.feature_states.models import FeatureValueType


class Conflict(BaseModel):
    """A change published since a change set's creation that touches its target."""

    segment_id: int | None = None
    original_cr_id: int | None = None
    published_at: datetime | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_environment_default(self) -> bool:
        return self.segment_id is None


@dataclass(frozen=True)
class FeatureValue:
    """A typed feature value, transported as a string."""

    value: str
    type_: FeatureValueType


@dataclass
class FlagChangeSetOptionA:
    """A single-state change: `None` parts are left intact on the target."""

    author: AuthorData
    enabled: bool | None = None
    value: FeatureValue | None = None

    segment_id: int | None = None
    segment_priority: int | None = None
    multivariate_values: list[MultivariateValueChangeSet] | None = None
    # Environment-level reconcile; segment re-weights travel in multivariate_values.
    multivariate_options: list[MultivariateOptionChangeSet] | None = None


@dataclass
class MultivariateValueChangeSet:
    """A weight to set for an existing multivariate option."""

    multivariate_feature_option_id: int
    percentage_allocation: float


@dataclass
class MultivariateOptionChangeSet:
    """An environment-level variant to create, update, or re-weight."""

    percentage_allocation: float
    # Absent id creates the option; value present (re)sets its variant value.
    id: int | None = None
    value: FeatureValue | None = None


@dataclass
class SegmentOverrideChangeSet:
    """A segment override change: `None` parts are left intact on the target."""

    segment_id: int
    enabled: bool | None = None
    value: FeatureValue | None = None
    priority: int | None = None
    multivariate_values: list[MultivariateValueChangeSet] | None = None


@dataclass
class FlagChangeSetOptionB:
    """A whole-feature change: environment default plus segment overrides."""

    author: AuthorData
    environment_default_enabled: bool | None = None
    environment_default_value: FeatureValue | None = None
    environment_default_multivariate_options: (
        list[MultivariateOptionChangeSet] | None
    ) = None

    segment_overrides: list[SegmentOverrideChangeSet] = field(default_factory=list)
