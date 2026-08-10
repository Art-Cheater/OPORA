"""Единый каталог полей модулей: встроенные + пользовательские."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.custom_field_service import CustomFieldService
from app.core.permission_service import PermissionService
from app.models.custom_fields.constants import CUSTOM_FIELD_MODULES
from app.seed.security_catalog import MODULE_FIELDS as SECURITY_MODULE_FIELDS


@dataclass(frozen=True, slots=True)
class FieldCatalogRow:
    code: str
    name: str
    field_type: str
    source: str  # builtin | custom
    is_required: bool = False
    is_visible: bool = True
    sort_order: int = 0
    field_id: str | None = None
    description: str | None = None
    is_editable: bool = False


def catalog_fields_dict() -> dict[str, dict[str, str]]:
    """Полный словарь полей по модулям для RBAC (каталог + БД + custom)."""
    merged: dict[str, dict[str, str]] = {}

    for module_code, items in SECURITY_MODULE_FIELDS.items():
        merged[module_code] = {code: name for code, name, _sort in items}

    for module_code in CUSTOM_FIELD_MODULES:
        merged.setdefault(module_code, {})
        merged[module_code].update(PermissionService.get_module_fields(module_code))
        merged[module_code].update(CustomFieldService.custom_fields_dict(module_code))

    for mod in PermissionService.get_modules():
        if mod.code not in merged:
            fields = PermissionService.module_fields_dict(mod.code)
            if fields:
                merged[mod.code] = fields

    return {mod: fields for mod, fields in merged.items() if fields}


def list_field_builder_rows(module_code: str) -> list[FieldCatalogRow]:
    """Строки конструктора полей: встроенные (просмотр) + пользовательские (редактирование)."""
    builtin = PermissionService.get_module_fields(module_code)
    custom_by_code = {f.code: f for f in CustomFieldService.list_for_module(module_code, include_hidden=True)}

    rows: list[FieldCatalogRow] = []
    seen: set[str] = set()

    for code, name in sorted(builtin.items(), key=lambda item: item[1].lower()):
        if code in custom_by_code:
            continue
        rows.append(
            FieldCatalogRow(
                code=code,
                name=name,
                field_type="builtin",
                source="builtin",
                is_editable=False,
            )
        )
        seen.add(code)

    for field in sorted(custom_by_code.values(), key=lambda f: (f.sort_order, f.name)):
        rows.append(
            FieldCatalogRow(
                code=field.code,
                name=field.name,
                field_type=field.field_type,
                source="custom",
                is_required=field.is_required,
                is_visible=field.is_visible,
                sort_order=field.sort_order,
                field_id=str(field.id),
                description=field.description,
                is_editable=True,
            )
        )
        seen.add(field.code)

    return rows
