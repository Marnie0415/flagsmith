from typing import Any, TypeVar

from rest_framework import serializers

from core.dataclasses import AuthorData
from environments.models import Environment
from features.feature_states.types import (
    EnvironmentDefaultPayload,
    FeatureIdentifierPayload,
    FeatureValuePayload,
    MultivariateValuePayload,
    SegmentIdentifierPayload,
    SegmentOverridePayload,
    SegmentPayload,
)
from features.models import Feature, FeatureState
from features.versioning.dataclasses import (
    FlagChangeSetOptionA,
    FlagChangeSetOptionB,
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


class BaseFeatureUpdateSerializer(serializers.Serializer[_InstanceT]):
    @property
    def environment(self) -> Environment:
        environment: Environment | None = self.context.get("environment")
        if not environment:
            raise serializers.ValidationError("Environment context is required")
        return environment

    def get_feature(self) -> Feature:
        feature_data = self.validated_data["feature"]
        try:
            feature: Feature = Feature.objects.get(
                project_id=self.environment.project_id, **feature_data
            )
            return feature
        except Feature.DoesNotExist:
            raise serializers.ValidationError(
                f"Feature '{feature_data}' not found in project"
            )

    def validate_segment_id(self, segment_id: int) -> None:
        if not Segment.objects.filter(
            id=segment_id, project_id=self.environment.project_id
        ).exists():
            raise serializers.ValidationError(
                f"Segment with id {segment_id} not found in project"
            )


class FeatureIdentifierSerializer(serializers.Serializer[FeatureIdentifierPayload]):
    name = serializers.CharField(required=False, allow_blank=False)
    id = serializers.IntegerField(required=False)

    def validate(self, attrs: FeatureIdentifierPayload) -> FeatureIdentifierPayload:
        has_name = "name" in attrs
        has_id = "id" in attrs
        if not has_name and not has_id:
            raise serializers.ValidationError(
                "Either 'name' or 'id' is required for feature identification"
            )
        if has_name and has_id:
            raise serializers.ValidationError("Provide either 'name' or 'id', not both")
        return attrs


class FeatureUpdateSegmentDataSerializer(serializers.Serializer[SegmentPayload]):
    id = serializers.IntegerField(required=True)
    priority = serializers.IntegerField(required=False, allow_null=True)


class FeatureValueSerializer(serializers.Serializer[FeatureValuePayload]):
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


class UpdateFlagOptionASerializer(BaseFeatureUpdateSerializer[FeatureState]):
    feature = FeatureIdentifierSerializer(required=True)
    segment = FeatureUpdateSegmentDataSerializer(required=False)
    enabled = serializers.BooleanField(required=True)
    value = FeatureValueSerializer(required=True)

    def validate_segment(self, value: SegmentPayload) -> SegmentPayload:
        if value and "id" in value:
            self.validate_segment_id(value["id"])
        return value

    @property
    def flag_change_set(self) -> FlagChangeSetOptionA:
        validated_data = self.validated_data
        value_data = validated_data["value"]
        segment_data = validated_data.get("segment")

        return FlagChangeSetOptionA(
            author=AuthorData.from_request(self.context["request"]),
            enabled=validated_data["enabled"],
            feature_state_value=value_data["value"],
            type_=value_data["type"],
            segment_id=segment_data.get("id") if segment_data else None,
            segment_priority=segment_data.get("priority") if segment_data else None,
        )

    def save(self, **kwargs: object) -> FeatureState:
        feature = self.get_feature()
        return update_flag(self.environment, feature, self.flag_change_set)


class EnvironmentDefaultSerializer(serializers.Serializer[EnvironmentDefaultPayload]):
    enabled = serializers.BooleanField(required=True)
    value = FeatureValueSerializer(required=True)


class MultivariateValueSerializer(serializers.Serializer[MultivariateValuePayload]):
    multivariate_feature_option = serializers.IntegerField(required=True)
    percentage_allocation = serializers.FloatField(
        required=True, min_value=0, max_value=100
    )


def validate_multivariate_state_values(
    feature: Feature, multivariate_values: list[MultivariateValuePayload]
) -> None:
    if not multivariate_values:
        return
    option_ids = [mv["multivariate_feature_option"] for mv in multivariate_values]
    if len(option_ids) != len(set(option_ids)):
        raise serializers.ValidationError("Multivariate options must be unique")
    valid = set(feature.multivariate_options.values_list("id", flat=True))
    if invalid := set(option_ids) - valid:
        raise serializers.ValidationError(
            f"Multivariate options {sorted(invalid)} do not belong to the feature"
        )


class SegmentOverrideSerializer(serializers.Serializer[SegmentOverridePayload]):
    segment_id = serializers.IntegerField(required=True)
    priority = serializers.IntegerField(required=False, allow_null=True)
    enabled = serializers.BooleanField(required=True)
    value = FeatureValueSerializer(required=True)
    multivariate_feature_state_values = MultivariateValueSerializer(
        many=True, required=False
    )


class UpdateFlagOptionBSerializer(BaseFeatureUpdateSerializer[FlagChangeSetOptionB]):
    feature = FeatureIdentifierSerializer(required=True)
    environment_default = EnvironmentDefaultSerializer(required=True)
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

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        overrides: list[SegmentOverridePayload] = attrs.get("segment_overrides", [])
        if any(o.get("multivariate_feature_state_values") for o in overrides):
            feature = Feature.objects.filter(
                project_id=self.environment.project_id, **attrs["feature"]
            ).first()
            if feature is not None:
                for override in overrides:
                    mv_overrides = override.get("multivariate_feature_state_values", [])
                    validate_multivariate_state_values(feature, mv_overrides)
        return attrs

    @property
    def change_set(self) -> FlagChangeSetOptionB:
        validated_data = self.validated_data

        env_default = validated_data["environment_default"]
        env_value_data = env_default["value"]

        segment_overrides_data = validated_data.get("segment_overrides", [])
        segment_overrides = []

        for override_data in segment_overrides_data:
            value_data = override_data["value"]

            multivariate_data = override_data.get("multivariate_feature_state_values")
            segment_override = SegmentOverrideChangeSet(
                segment_id=override_data["segment_id"],
                enabled=override_data["enabled"],
                feature_state_value=value_data["value"],
                type_=value_data["type"],
                priority=override_data.get("priority"),
                multivariate_values=[
                    MultivariateValueChangeSet(
                        multivariate_feature_option_id=mv[
                            "multivariate_feature_option"
                        ],
                        percentage_allocation=mv["percentage_allocation"],
                    )
                    for mv in multivariate_data
                ]
                if multivariate_data
                else None,
            )
            segment_overrides.append(segment_override)

        return FlagChangeSetOptionB(
            author=AuthorData.from_request(self.context["request"]),
            environment_default_enabled=env_default["enabled"],
            environment_default_value=env_value_data["value"],
            environment_default_type=env_value_data["type"],
            segment_overrides=segment_overrides,
        )

    def save(self, **kwargs: object) -> FlagChangeSetOptionB:
        feature = self.get_feature()
        change_set = self.change_set
        update_flag_option_b(self.environment, feature, change_set)
        return change_set


class SegmentIdentifierSerializer(serializers.Serializer[SegmentIdentifierPayload]):
    id = serializers.IntegerField(required=True)


class DeleteSegmentOverrideSerializer(BaseFeatureUpdateSerializer[None]):
    feature = FeatureIdentifierSerializer(required=True)
    segment = SegmentIdentifierSerializer(required=True)

    def validate_segment(
        self, value: SegmentIdentifierPayload
    ) -> SegmentIdentifierPayload:
        if value and value.get("id"):
            self.validate_segment_id(value["id"])
        return value

    def save(self, **kwargs: object) -> None:
        feature = self.get_feature()
        segment_id = self.validated_data["segment"]["id"]
        author = AuthorData.from_request(self.context["request"])

        delete_segment_override(self.environment, feature, segment_id, author)
