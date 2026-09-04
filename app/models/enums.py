"""Перечисления доменной модели."""

from enum import Enum


class Priority(str, Enum):
  LOW = "low"
  MEDIUM = "medium"
  HIGH = "high"
  CRITICAL = "critical"


class WorkObjectStatus(str, Enum):
  FREE = "free"
  IN_PROJECT = "in_project"
  IN_TENDER = "in_tender"
  IN_CONTRACT = "in_contract"
  COMPLETED = "completed"
  ARCHIVED = "archived"


class WorkObjectKind(str, Enum):
  """Раздел плана освещения (не тип работ)."""

  PLANNED = "planned"
  COURT = "court"
  TECH_CONNECT = "tech_connect"
  OTHER = "other"


class ProjectStatus(str, Enum):
  DRAFT = "draft"
  ACTIVE = "active"
  IN_TENDER = "in_tender"
  IN_CONTRACT = "in_contract"
  COMPLETED = "completed"
  CANCELLED = "cancelled"
  # legacy
  ON_HOLD = "on_hold"
  ARCHIVED = "archived"


class ProjectMemberRole(str, Enum):
  LEAD = "lead"
  EXECUTOR = "executor"
  MEMBER = "member"
  OBSERVER = "observer"


class ProjectDocumentType(str, Enum):
  TECH_SPEC = "tech_spec"
  OBJECT_DESCRIPTION = "object_description"
  ESTIMATE = "estimate"
  OTHER = "other"
  # legacy
  CONTRACT = "contract"
  ACT = "act"
  ORDER = "order"
  PLAN = "plan"


class TenderApplicationStatus(str, Enum):
  DRAFT = "draft"
  SUBMITTED = "submitted"
  WON = "won"
  LOST = "lost"
  CANCELLED = "cancelled"


class TenderDocumentType(str, Enum):
  TENDER_APPLICATION = "tender_application"
  PRICE_REQUEST = "price_request"
  OTHER = "other"


class ContractStatus(str, Enum):
  DRAFT = "draft"
  ACTIVE = "active"
  WORK_DOCS_PENDING = "work_docs_pending"
  IN_PROGRESS = "in_progress"
  KS2_PENDING = "ks2_pending"
  REJECTED = "rejected"
  COMPLETED = "completed"
  TERMINATED = "terminated"


class ContractDocumentType(str, Enum):
  CONTRACT = "contract"
  LOCAL_ESTIMATE = "local_estimate"
  WORK_DOCS = "work_docs"
  KS2 = "ks2"
  REJECTION_MEMO = "rejection_memo"
  OTHER = "other"


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
  REQUEST_JOURNAL = "request_journal"
  DEFECT = "defect"
  WAYBILL = "waybill"
  WORK_PLAN = "work_plan"
  WORK_PLAN_ITEM = "work_plan_item"
  WORK_OBJECT = "work_object"
  PROJECT = "project"
  TENDER_APPLICATION = "tender_application"
  CONTRACT = "contract"
  CONTRACTOR = "contractor"
  EIS_IMPORT = "eis_import"
  MESSAGE = "message"
  NOTIFICATION = "notification"
  COMMENT = "comment"
  ATTACHMENT = "attachment"
  MESSENGER_MESSAGE = "messenger_message"
  PERSONAL_DOCUMENT = "personal_document"
  PERSONAL_CONTRACT = "personal_contract"
