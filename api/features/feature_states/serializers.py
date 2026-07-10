from collections.abc import Mapping
from typing import Any, TypeAlias, TypeVar, cast

from rest_framework import serializers

from core.dataclasses import AuthorData
from environments.models import Environment
from features.feature_states.types import (
    DeleteSegmentOverridePayload,
    EnvironmentDefaultPayload,
    FeatureIdentifierPayload,
    FeatureValuePayload,
    MultivariateOptionPayload,
    MultivariateValuePayload,
    SegmentIdentifierPayload,
    SegmentOverrideMultivariateOptionPayload,
    SegmentOverridePayload,
    SegmentPayload,
    UpdateFlagOptionAPayload,
    UpdateFlagOptionBPayload,
)
from features.models import Feature, FeatureState
from features.versioning.dataclasses import (
    FeatureValue,
    FlagChangeSetOptionA,
    FlagChangeSetOptionB,
    MultivariateOptionChangeSet,
    MultivariateValueChangeSet,
    SegmentOverrideChangeSet,
)
from features.versioning.versioning_service import (
    delete_segment_override,
    update_flag,
    update_flag_option_b,
)
from segments.models import Segment

_InstanceT = TypeVar("_InstanceT")

_MultivariateOptionPayloads: TypeAlias = (
    list[MultivariateOptionPayload] | list[SegmentOverrideMultivariateOptionPayload]
)


class BaseFeatureUpdateSerializer(serializers.Serializer[_InstanceT]):
    """Shared environment context and segment ownership check."""

    def validate_segment_id(self, segment_id: int) -> None:
        if not Segment.objects.filter(
            id=segment_id, project_id=_environment(self.context).project_id
        ).exists():
            raise serializers.ValidationError(
                f"Segment with id {segment_id} not found in project"
            )


class FeatureIdentifierSerializer(serializers.Serializer[Feature]):
    """Resolves a feature from exactly one of `name` or `id`."""

    name = serializers.CharField(required=False, allow_blank=False)
    id = serializers.IntegerField(required=False)

    def validate(self, attrs: FeatureIdentifierPayload) -> Feature:
        has_name = "name" in attrs
        has_id = "id" in attrs
        if not has_name and not has_id:
            raise serializers.ValidationError(
                "Either 'name' or 'id' is required for feature identification"
            )
        if has_name and has_id:
            raise serializers.ValidationError("Provide either 'name' or 'id', not both")
        project_id = _environment(self.context).project_id
        try:
            return Feature.objects.get(project_id=project_id, **attrs)  # type: ignore[no-any-return]
        except Feature.DoesNotExist:
            raise serializers.ValidationError(f"Feature '{attrs}' not found in project")


class FeatureUpdateSegmentDataSerializer(serializers.Serializer[SegmentPayload]):
    """Targets a segment override, optionally re-prioritising it."""

    id = serializers.IntegerField(required=True)
    priority = serializers.IntegerField(required=False, allow_null=True)


class FeatureValueSerializer(serializers.Serializer[FeatureValuePayload]):
    """A typed feature value, always transported as a string."""

    type = serializers.ChoiceField(
        choices=["integer", "string", "boolean"], required=True
    )
    value = serializers.CharField(required=True, allow_blank=True)

    def validate(self, attrs: FeatureValuePayload) -> FeatureValuePayload:
        value_type = attrs["type"]
        string_val = attrs["value"]

        if value_type == "integer":
            try:
                int(string_val)
            except ValueError:
                raise serializers.ValidationError(
                    f"'{string_val}' is not a valid integer"
                )
        elif value_type == "boolean":
            if string_val.lower() not in ("true", "false"):
                raise serializers.ValidationError(
                    f"'{string_val}' is not a valid boolean (use 'true' or 'false')"
                )

        return attrs


class MultivariateOptionSerializer(serializers.Serializer[MultivariateOptionPayload]):
    """An environment-level variant: absent `id` creates it; `value` (re)sets it."""

    id = serializers.IntegerField(required=False)
    percentage_allocation = serializers.FloatField(
        required=True, min_value=0, max_value=100
    )
    value = FeatureValueSerializer(required=False)

    def validate(self, attrs: MultivariateOptionPayload) -> MultivariateOptionPayload:
        if "id" not in attrs and "value" not in attrs:
            raise serializers.ValidationError(
                "A new multivariate option requires a 'value'."
            )
        return attrs


class UpdateFlagOptionASerializer(BaseFeatureUpdateSerializer[FeatureState]):
    """Updates the environment default or one segment override per request."""

    feature = FeatureIdentifierSerializer(required=True)
    segment = FeatureUpdateSegmentDataSerializer(required=False)
    enabled = serializers.BooleanField(required=False)
    value = FeatureValueSerializer(required=False)
    multivariate_options = MultivariateOptionSerializer(many=True, required=False)

    def validate_segment(self, value: SegmentPayload) -> SegmentPayload:
        if value and "id" in value:
            self.validate_segment_id(value["id"])
        return value

    def validate(self, attrs: UpdateFlagOptionAPayload) -> UpdateFlagOptionAPayload:
        options = attrs.get("multivariate_options")
        if options is None:
            return attrs
        if attrs.get("segment"):
            _validate_segment_multivariate_options(attrs["feature"], options)
            _validate_segment_multivariate_options_values(
                self.initial_data.get("multivariate_options", [])
            )
        else:
            _validate_environment_multivariate_options(attrs["feature"], options)
        return attrs

    @property
    def flag_change_set(self) -> FlagChangeSetOptionA:
        validated_data: UpdateFlagOptionAPayload = self.validated_data
        value = _feature_value(validated_data.get("value"))
        segment_data = validated_data.get("segment")
        segment_id = segment_data.get("id") if segment_data else None
        options = validated_data.get("multivariate_options")

        multivariate_values = None
        multivariate_options = None
        if options is not None:
            if segment_id is None:
                multivariate_options = _multivariate_option_change_sets(options)
            else:
                multivariate_values = _reweight_change_sets(options)

        return FlagChangeSetOptionA(
            author=AuthorData.from_request(self.context["request"]),
            enabled=validated_data.get("enabled"),
            value=value,
            segment_id=segment_id,
            segment_priority=segment_data.get("priority") if segment_data else None,
            multivariate_values=multivariate_values,
            multivariate_options=multivariate_options,
        )

    def save(self, **kwargs: object) -> FeatureState:
        validated_data: UpdateFlagOptionAPayload = self.validated_data
        return update_flag(
            _environment(self.context), validated_data["feature"], self.flag_change_set
        )


class EnvironmentDefaultSerializer(serializers.Serializer[EnvironmentDefaultPayload]):
    """The environment-default part of an Option B update."""

    enabled = serializers.BooleanField(required=False)
    value = FeatureValueSerializer(required=False)
    multivariate_options = MultivariateOptionSerializer(many=True, required=False)


class MultivariateValueSerializer(serializers.Serializer[MultivariateValuePayload]):
    """A weight for an existing multivariate option."""

    multivariate_feature_option = serializers.IntegerField(required=True)
    percentage_allocation = serializers.FloatField(
        required=True, min_value=0, max_value=100
    )


class SegmentOverrideMultivariateOptionSerializer(
    serializers.Serializer[SegmentOverrideMultivariateOptionPayload]
):
    """A re-weight of a variant that already exists on the feature."""

    id = serializers.IntegerField(required=True)
    percentage_allocation = serializers.FloatField(
        required=True, min_value=0, max_value=100
    )


class SegmentOverrideSerializer(serializers.Serializer[SegmentOverridePayload]):
    """One segment override in an Option B update."""

    segment_id = serializers.IntegerField(required=True)
    priority = serializers.IntegerField(required=False, allow_null=True)
    enabled = serializers.BooleanField(required=False)
    value = FeatureValueSerializer(required=False)
    multivariate_feature_state_values = MultivariateValueSerializer(
        many=True, required=False
    )
    multivariate_options = SegmentOverrideMultivariateOptionSerializer(
        many=True, required=False
    )


class UpdateFlagOptionBSerializer(BaseFeatureUpdateSerializer[FlagChangeSetOptionB]):
    """Updates the environment default and segment overrides in one request."""

    feature = FeatureIdentifierSerializer(required=True)
    environment_default = EnvironmentDefaultSerializer(required=False)
    segment_overrides = SegmentOverrideSerializer(many=True, required=False)

    def validate_segment_overrides(
        self, value: list[SegmentOverridePayload]
    ) -> list[SegmentOverridePayload]:
        if not value:
            return value

        segment_ids = [override["segment_id"] for override in value]
        if len(segment_ids) != len(set(segment_ids)):
            raise serializers.ValidationError(
                "Duplicate segment_id values are not allowed"
            )

        # TODO: optimise this once out of experimentation
        for segment_id in segment_ids:
            self.validate_segment_id(segment_id)

        return value

    def validate(self, attrs: UpdateFlagOptionBPayload) -> UpdateFlagOptionBPayload:
        feature = attrs["feature"]

        environment_default = attrs.get("environment_default", {})
        env_options = environment_default.get("multivariate_options")
        if env_options is not None:
            _validate_environment_multivariate_options(feature, env_options)

        for override in attrs.get("segment_overrides", []):
            options = override.get("multivariate_options")
            if options is not None:
                _validate_segment_multivariate_options(feature, options)
            validate_multivariate_state_values(
                feature, override.get("multivariate_feature_state_values", [])
            )

        for raw_override in self.initial_data.get("segment_overrides", []):
            _validate_segment_multivariate_options_values(
                raw_override.get("multivariate_options", [])
            )
        return attrs

    @property
    def change_set(self) -> FlagChangeSetOptionB:
        validated_data: UpdateFlagOptionBPayload = self.validated_data

        env_default = validated_data.get("environment_default", {})
        env_value = _feature_value(env_default.get("value"))
        env_options = env_default.get("multivariate_options")

        segment_overrides = []
        for override in validated_data.get("segment_overrides", []):
            segment_overrides.append(
                SegmentOverrideChangeSet(
                    segment_id=override["segment_id"],
                    enabled=override.get("enabled"),
                    value=_feature_value(override.get("value")),
                    priority=override.get("priority"),
                    multivariate_values=_segment_override_values(override),
                )
            )

        return FlagChangeSetOptionB(
            author=AuthorData.from_request(self.context["request"]),
            environment_default_enabled=env_default.get("enabled"),
            environment_default_value=env_value,
            environment_default_multivariate_options=(
                _multivariate_option_change_sets(env_options)
                if env_options is not None
                else None
            ),
            segment_overrides=segment_overrides,
        )

    def save(self, **kwargs: object) -> FlagChangeSetOptionB:
        validated_data: UpdateFlagOptionBPayload = self.validated_data
        change_set = self.change_set
        update_flag_option_b(
            _environment(self.context), validated_data["feature"], change_set
        )
        return change_set


class SegmentIdentifierSerializer(serializers.Serializer[SegmentIdentifierPayload]):
    """Identifies a segment by `id`."""

    id = serializers.IntegerField(required=True)


class DeleteSegmentOverrideSerializer(BaseFeatureUpdateSerializer[None]):
    """Removes a feature's override for a segment."""

    feature = FeatureIdentifierSerializer(required=True)
    segment = SegmentIdentifierSerializer(required=True)

    def validate_segment(
        self, value: SegmentIdentifierPayload
    ) -> SegmentIdentifierPayload:
        if value and value.get("id"):
            self.validate_segment_id(value["id"])
        return value

    def save(self, **kwargs: object) -> None:
        validated_data: DeleteSegmentOverridePayload = self.validated_data
        author = AuthorData.from_request(self.context["request"])

        delete_segment_override(
            _environment(self.context),
            validated_data["feature"],
            validated_data["segment"]["id"],
            author,
        )


def validate_multivariate_state_values(
    feature: Feature, multivariate_values: list[MultivariateValuePayload]
) -> None:
    """Validate the weights reference unique variants belonging to the feature."""
    option_ids = [mv["multivariate_feature_option"] for mv in multivariate_values]
    if error := _multivariate_option_ownership_error(feature, option_ids):
        raise serializers.ValidationError(error)


def _environment(context: Mapping[str, object]) -> Environment:
    try:
        return cast(Environment, context["environment"])
    except KeyError:
        raise serializers.ValidationError("Environment context is required")


def _validate_environment_multivariate_options(
    feature: Feature, options: list[MultivariateOptionPayload]
) -> None:
    # The environment list is absolute, so its allocations must total <= 100%
    total = sum(option["percentage_allocation"] for option in options)
    if total > 100:
        raise serializers.ValidationError(
            {
                "multivariate_options": (
                    f"Multivariate allocations must not exceed 100%, got {total}%."
                )
            }
        )
    if error := _multivariate_option_ownership_error(
        feature, _multivariate_option_ids(options)
    ):
        raise serializers.ValidationError({"multivariate_options": error})


def _validate_segment_multivariate_options(
    feature: Feature, options: _MultivariateOptionPayloads
) -> None:
    """Segment overrides can only re-weight variants already on the feature."""
    if any("id" not in option for option in options):
        raise serializers.ValidationError(
            {"multivariate_options": "Segment overrides require a variant 'id'."}
        )
    if error := _multivariate_option_ownership_error(
        feature, _multivariate_option_ids(options)
    ):
        raise serializers.ValidationError({"multivariate_options": error})


def _validate_segment_multivariate_options_values(raw_options: Any) -> None:
    if any("value" in option for option in raw_options):
        raise serializers.ValidationError(
            {
                "multivariate_options": "Segment overrides can only re-weight existing variants."
            }
        )


def _multivariate_option_ids(options: _MultivariateOptionPayloads) -> list[int]:
    return list(filter(None, [option.get("id") for option in options]))


def _multivariate_option_ownership_error(
    feature: Feature, option_ids: list[int]
) -> str | None:
    if not option_ids:
        return None
    if len(option_ids) != len(set(option_ids)):
        return "Multivariate options must be unique"
    valid = set(feature.multivariate_options.values_list("id", flat=True))
    if invalid := sorted(set(option_ids) - valid):
        return f"Multivariate options {invalid} do not belong to the feature"
    return None


def _segment_override_values(
    override: SegmentOverridePayload,
) -> list[MultivariateValueChangeSet] | None:
    # multivariate_options supersedes the legacy field when both are sent.
    if (options := override.get("multivariate_options")) is not None:
        return _reweight_change_sets(options)
    if (values := override.get("multivariate_feature_state_values")) is not None:
        return [
            MultivariateValueChangeSet(
                multivariate_feature_option_id=value["multivariate_feature_option"],
                percentage_allocation=value["percentage_allocation"],
            )
            for value in values
        ]
    return None


def _multivariate_option_change_sets(
    options: list[MultivariateOptionPayload],
) -> list[MultivariateOptionChangeSet]:
    change_sets = []
    for option in options:
        change_sets.append(
            MultivariateOptionChangeSet(
                percentage_allocation=option["percentage_allocation"],
                id=option.get("id"),
                value=_feature_value(option.get("value")),
            )
        )
    return change_sets


def _reweight_change_sets(
    options: _MultivariateOptionPayloads,
) -> list[MultivariateValueChangeSet]:
    return [
        MultivariateValueChangeSet(
            multivariate_feature_option_id=option_id,
            percentage_allocation=option["percentage_allocation"],
        )
        for option in options
        if (option_id := option.get("id")) is not None
    ]


def _feature_value(value: FeatureValuePayload | None) -> FeatureValue | None:
    return FeatureValue(value["value"], value["type"]) if value else None
