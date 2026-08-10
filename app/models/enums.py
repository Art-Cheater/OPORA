"""Перечисления доменной модели."""

from enum import Enum


class Priority(str, Enum):
  LOW = "low"
  MEDIUM = "medium"
  HIGH = "high"
  CRITICAL = "critical"


class ProjectStatus(str, Enum):
  DRAFT = "draft"
  ACTIVE = "active"
  ON_HOLD = "on_hold"
  COMPLETED = "completed"
  ARCHIVED = "archived"


class ProjectMemberRole(str, Enum):
  LEAD = "lead"
  EXECUTOR = "executor"
  MEMBER = "member"
  OBSERVER = "observer"


class ProjectDocumentType(str, Enum):
  CONTRACT = "contract"
  ACT = "act"
  ORDER = "order"
  PLAN = "plan"
  OTHER = "other"


class ContractStatus(str, Enum):
  DRAFT = "draft"
  ACTIVE = "active"
  COMPLETED = "completed"
  TERMINATED = "terminated"


class ContractType(str, Enum):
  SUPPLY = "supply"
  SERVICE = "service"
  WORK = "work"
  LEASE = "lease"
  OTHER = "other"


class NotificationType(str, Enum):
  INFO = "info"
  SUCCESS = "success"
  WARNING = "warning"
  ERROR = "error"


class AuditAction(str, Enum):
  CREATE = "create"
  UPDATE = "update"
  DELETE = "delete"
  SOFT_DELETE = "soft_delete"
  RESTORE = "restore"
  LOGIN = "login"
  LOGOUT = "logout"
  STATUS_CHANGE = "status_change"
  VIEW = "view"
  EXPORT = "export"


class EntityType(str, Enum):
  USER = "user"
  ROLE = "role"
  PERMISSION = "permission"
  REQUEST = "request"
  PROJECT = "project"
  CONTRACT = "contract"
  MESSAGE = "message"
  NOTIFICATION = "notification"
  COMMENT = "comment"
  ATTACHMENT = "attachment"
  MESSENGER_MESSAGE = "messenger_message"
