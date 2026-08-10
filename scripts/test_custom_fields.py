"""Smoke-тест конструктора полей."""
from __future__ import annotations

import uuid
from werkzeug.datastructures import ImmutableMultiDict

from app import create_app
from app.core.custom_field_service import CustomFieldPayload, CustomFieldService, OptionPayload
from app.core.permission_service import PermissionService
from app.extensions import db
from app.models.auth.user import User


def main() -> None:
    app = create_app()
    with app.app_context():
        admin = db.session.scalar(db.select(User).where(User.email == app.config["ADMIN_EMAIL"]))
        if admin is None:
            print("SKIP: admin user not found")
            return

        payload = CustomFieldPayload(
            module_code="requests",
            code=f"test_support_{uuid.uuid4().hex[:8]}",
            name="Номер опоры (тест)",
            field_type="number",
            description="Тестовое поле",
            is_required=False,
            is_visible=True,
            sort_order=100,
            options=[],
        )
        field = CustomFieldService.create_field(payload, admin.id)
        print(f"Created field: {field.code}")

        fields_dict = PermissionService.module_fields_dict("requests")
        assert field.code in fields_dict, "Field missing in RBAC catalog"
        print("RBAC catalog: OK")

        # Выдать право редактирования поля (как в UI ролей)
        from app.models.auth.role_field_permission import RoleFieldPermission, FIELD_ACCESS_EDIT

        role = admin.roles[0] if admin.roles else None
        if role is None:
            print("SKIP save/search: у пользователя нет роли")
        else:
            db.session.add(
                RoleFieldPermission(
                    role_id=role.id,
                    module="requests",
                    field_name=field.code,
                    access_level=FIELD_ACCESS_EDIT,
                    can_view=True,
                    can_edit=True,
                )
            )
            db.session.commit()
            PermissionService.clear_cache()

        form_ctx = CustomFieldService.form_context("requests")
        assert any(f.code == field.code for f in form_ctx["custom_fields"])
        print("Form context: OK")

        if role is not None:
            entity_id = uuid.uuid4()
            form_data = ImmutableMultiDict([(f"cf_{field.code}", "100")])
            CustomFieldService.save_from_form("requests", entity_id, form_data, admin)
            values = CustomFieldService.get_values_map("requests", entity_id)
            assert values.get(field.code) == "100"
            print("Save value: OK")

            hits = CustomFieldService.search_hits("100", admin, limit=10)
            assert any(h["meta"]["field"] == field.code for h in hits)
            print("Search: OK")

        CustomFieldService.delete_field(field, admin.id)
        print("Delete: OK")
        print("All checks passed.")


if __name__ == "__main__":
    main()
