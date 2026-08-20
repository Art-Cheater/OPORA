"""Константы ролей и разрешений системы безопасности."""

# Коды ролей
ROLE_ADMIN = "admin"
ROLE_DIRECTOR = "director"
ROLE_DISPATCHER = "dispatcher"
ROLE_MASTER = "master"
ROLE_EXECUTOR = "executor"

ROLE_LABELS = {
    ROLE_ADMIN: "Администратор",
    ROLE_DIRECTOR: "Директор",
    ROLE_DISPATCHER: "Диспетчер",
    ROLE_MASTER: "Мастер",
    ROLE_EXECUTOR: "Исполнитель",
}

ALL_ROLE_CODES = tuple(ROLE_LABELS.keys())

# Коды разрешений
PERM_USERS_VIEW = "users.view"
PERM_USERS_CREATE = "users.create"
PERM_USERS_EDIT = "users.edit"
PERM_USERS_DELETE = "users.delete"
PERM_USERS_BLOCK = "users.block"
PERM_ROLES_VIEW = "roles.view"
PERM_ROLES_MANAGE = "roles.manage"
PERM_PROFILE_VIEW = "profile.view"
PERM_PROFILE_EDIT = "profile.edit"
PERM_AUTH_LOGIN_LOGS_VIEW = "auth.login_logs.view"
PERM_REQUESTS_VIEW = "requests.view"
PERM_REQUESTS_CREATE = "requests.create"
PERM_REQUESTS_EDIT = "requests.edit"
PERM_REQUESTS_DELETE = "requests.delete"
PERM_REQUESTS_APPROVE = "requests.approve"
PERM_REQUESTS_DISPATCH = "requests.dispatch"
PERM_OBJECTS_VIEW = "objects.view"
PERM_OBJECTS_CREATE = "objects.create"
PERM_OBJECTS_EDIT = "objects.edit"
PERM_OBJECTS_DELETE = "objects.delete"
PERM_PROJECTS_VIEW = "projects.view"
PERM_PROJECTS_CREATE = "projects.create"
PERM_PROJECTS_EDIT = "projects.edit"
PERM_PROJECTS_DELETE = "projects.delete"
PERM_TENDERS_VIEW = "tenders.view"
PERM_TENDERS_CREATE = "tenders.create"
PERM_TENDERS_EDIT = "tenders.edit"
PERM_TENDERS_DELETE = "tenders.delete"
PERM_CONTRACTS_VIEW = "contracts.view"
PERM_CONTRACTS_CREATE = "contracts.create"
PERM_CONTRACTS_EDIT = "contracts.edit"
PERM_CONTRACTS_DELETE = "contracts.delete"
PERM_CONTRACTORS_VIEW = "contractors.view"
PERM_CONTRACTORS_CREATE = "contractors.create"
PERM_CONTRACTORS_EDIT = "contractors.edit"
PERM_CONTRACTORS_DELETE = "contractors.delete"
PERM_EIS_VIEW = "eis.view"
PERM_EIS_RUN = "eis.run"
PERM_AGREEMENTS_VIEW = "agreements.view"
PERM_AGREEMENTS_CREATE = "agreements.create"
PERM_AGREEMENTS_EDIT = "agreements.edit"
PERM_AGREEMENTS_DELETE = "agreements.delete"
PERM_AUDIT_VIEW = "audit.view"
PERM_AUDIT_EXPORT = "audit.export"
PERM_REPORTS_VIEW = "reports.view"
PERM_REPORTS_EXPORT = "reports.export"
PERM_MESSENGER_USE = "messenger.use"
PERM_SEARCH_USE = "search.use"
