"""Serializers for converting idfkit objects to MCP-friendly dicts."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from idfkit.introspection import FieldDescription, ObjectDescription
    from idfkit.objects import IDFObject
    from idfkit.schema import EpJSONSchema
    from idfkit.validation import ValidationError, ValidationResult
    from idfkit.weather.station import WeatherStation


def serialize_object(obj: IDFObject, schema: EpJSONSchema | None = None, brief: bool = False) -> dict[str, Any]:
    """Convert an IDFObject to a dict.

    Args:
        obj: The IDFObject to serialize.
        schema: Optional schema for getting required fields in brief mode.
        brief: If True, only include name and required fields.
    """
    if brief:
        result: dict[str, Any] = {"object_type": obj.obj_type, "name": obj.name}
        if schema is not None:
            required = schema.get_required_fields(obj.obj_type)
            for field_name in required:
                value = obj.data.get(field_name)
                if value is not None:
                    result[field_name] = value
        return result

    result = {"object_type": obj.obj_type, "name": obj.name}

    # Preserve schema field order and include blank trailing fields as None so
    # the MCP response matches the "all field values" contract for get_object.
    field_order = obj.field_order
    if field_order is not None:
        for field_name in field_order:
            result[field_name] = obj.data.get(field_name)

        # Include any populated extensible or non-schema keys that are present
        # on the object but not listed in the base field order.
        for field_name, value in obj.data.items():
            if field_name not in result:
                result[field_name] = value
        return result

    return {**result, **obj.to_dict()}


def serialize_object_description(desc: ObjectDescription) -> dict[str, Any]:
    """Convert an ObjectDescription to a dict."""
    return {
        "object_type": desc.obj_type,
        "memo": desc.memo,
        "has_name": desc.has_name,
        "is_extensible": desc.is_extensible,
        "extensible_size": desc.extensible_size,
        "required_fields": desc.required_fields,
        "fields": [serialize_field_description(f) for f in desc.fields],
    }


def serialize_field_description(f: FieldDescription) -> dict[str, Any]:
    """Convert a FieldDescription to a dict.

    Omits ``note`` to reduce token overhead — use search_docs / get_doc_section
    for detailed field documentation when needed.
    """
    result: dict[str, Any] = {"name": f.name, "field_type": f.field_type, "required": f.required}
    if f.default is not None:
        result["default"] = f.default
    if f.units is not None:
        result["units"] = f.units
    if f.enum_values is not None:
        result["enum_values"] = f.enum_values
    if f.minimum is not None:
        result["minimum"] = f.minimum
    if f.maximum is not None:
        result["maximum"] = f.maximum
    if f.exclusive_minimum is not None:
        result["exclusive_minimum"] = f.exclusive_minimum
    if f.exclusive_maximum is not None:
        result["exclusive_maximum"] = f.exclusive_maximum
    if f.is_reference:
        result["is_reference"] = True
        result["object_list"] = f.object_list
    return result


def serialize_validation_error(err: ValidationError, version: tuple[int, int, int] | None = None) -> dict[str, Any]:
    """Convert a ValidationError to a dict.

    Doc URLs are omitted to reduce token overhead — use the
    ``idfkit://docs/{object_type}`` resource for documentation links.
    """
    return {
        "severity": err.severity.value,
        "object_type": err.obj_type,
        "object_name": err.obj_name,
        "field": err.field,
        "message": err.message,
        "code": err.code,
    }


def serialize_validation_result(
    result: ValidationResult,
    version: tuple[int, int, int] | None = None,
    max_errors: int = 50,
    max_warnings: int = 50,
) -> dict[str, Any]:
    """Convert a ValidationResult to a dict."""
    errors = result.errors[:max_errors]
    warnings = result.warnings[:max_warnings]
    return {
        "is_valid": result.is_valid,
        "error_count": len(result.errors),
        "warning_count": len(result.warnings),
        "info_count": len(result.info),
        "errors": [serialize_validation_error(e) for e in errors],
        "warnings": [serialize_validation_error(w) for w in warnings],
        "errors_truncated": len(result.errors) > max_errors,
        "warnings_truncated": len(result.warnings) > max_warnings,
    }


def serialize_station(station: WeatherStation) -> dict[str, Any]:
    """Convert a WeatherStation to a dict."""
    return station.to_dict()
