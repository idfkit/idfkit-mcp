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


def serialize_object_description(desc: ObjectDescription, schema: EpJSONSchema | None = None) -> dict[str, Any]:
    """Convert an ObjectDescription to a dict.

    When *schema* is provided and the object type is extensible, the inner
    extensible item fields are lifted out of the flat ``fields`` list into an
    ``extensible_group`` entry that names the array wrapper key and shows an
    example payload. This matches the actual epJSON shape that ``add_object``
    expects (e.g. ``{"vertices": [{...}, {...}, ...]}``).
    """
    fields_serialized = [serialize_field_description(f) for f in desc.fields]

    extensible_group: dict[str, Any] | None = None
    if schema is not None and desc.is_extensible:
        wrapper_key, item_field_names = get_extensible_group_info(schema, desc.obj_type)
        if wrapper_key and item_field_names:
            inner_set = set(item_field_names)
            base_fields = [f for f in fields_serialized if f["name"] not in inner_set]
            item_fields = [f for f in fields_serialized if f["name"] in inner_set]
            fields_serialized = base_fields
            extensible_group = {
                "key": wrapper_key,
                "item_fields": item_fields,
                "example": {wrapper_key: [_example_item(item_fields) for _ in range(3)]},
                "note": (
                    f"Prefer the structured array form: pass repeated entries "
                    f"as an array under '{wrapper_key}'. Each item is an object "
                    f"with {', '.join(item_field_names)}. Flat numbered keys "
                    f"(e.g. '{item_field_names[0]}_2', '{item_field_names[0]}_3') "
                    f"are accepted for back-compat but emit a deprecation "
                    f"warning (surfaced on the tool response) and may be removed "
                    f"in a future idfkit release."
                ),
            }

    result: dict[str, Any] = {
        "object_type": desc.obj_type,
        "memo": desc.memo,
        "has_name": desc.has_name,
        "is_extensible": desc.is_extensible,
        "extensible_size": desc.extensible_size,
        "required_fields": desc.required_fields,
        "fields": fields_serialized,
    }
    if extensible_group is not None:
        result["extensible_group"] = extensible_group
    return result


def get_extensible_group_info(schema: EpJSONSchema, obj_type: str) -> tuple[str | None, list[str]]:
    """Return ``(wrapper_key, item_field_names)`` for an extensible object.

    *wrapper_key* is the name of the epJSON array property that holds repeated
    items (e.g. ``"vertices"`` for ``BuildingSurface:Detailed``). It is ``None``
    if the object is not extensible.
    """
    wrapper_key = schema.get_extensible_wrapper_key(obj_type)
    item_fields = list(schema.get_extensible_field_names(obj_type))
    return wrapper_key, item_fields


def _example_item(item_fields: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a one-item example payload for an extensible group.

    Use informative placeholders so agents copying the payload can tell which
    slots need real values: first enum value for enum fields, an angle-bracketed
    reference hint for object-list fields, and ``""`` for plain strings.
    """
    example: dict[str, Any] = {}
    for f in item_fields:
        ftype = f.get("field_type")
        if ftype == "number":
            example[f["name"]] = 0.0
            continue
        enum_values = f.get("enum_values")
        if enum_values:
            non_empty = [v for v in enum_values if v]
            example[f["name"]] = non_empty[0] if non_empty else ""
            continue
        if f.get("is_reference"):
            object_list: list[str] = f.get("object_list") or []
            target: str = object_list[0] if object_list else "reference"
            example[f["name"]] = f"<{target}-name>"
            continue
        example[f["name"]] = ""
    return example


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
