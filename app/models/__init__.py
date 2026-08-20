"""Реестр всех моделей SQLAlchemy для Alembic и приложения."""

from app.models.audit.audit_log import AuditLog
from app.models.auth.associations import RolePermission, UserRole
from app.models.auth.field_definition import FieldDefinition
from app.models.auth.login_log import LoginLog
from app.models.auth.permission import Permission
from app.models.auth.position import Position
from app.models.auth.role import Role
from app.models.auth.role_field_permission import RoleFieldPermission
from app.models.auth.system_module import SystemModule
from app.models.auth.user import User
from app.models.base import ActiveRecordMixin, BaseModel, utcnow
from app.models.communication.comment import Comment
from app.models.communication.message import Message
from app.models.messenger.messenger_conversation import MessengerConversation
from app.models.messenger.messenger_message import MessengerMessage
from app.models.messenger.user_presence import UserPresence
from app.models.communication.notification import Notification
from app.models.contracts.contract import Contract
from app.models.contracts.contract_contractor import ContractContractor
from app.models.contracts.contract_document import ContractDocument
from app.models.contracts.contract_history import ContractHistory
from app.models.contracts.contract_object import ContractObject
from app.models.contractors.contractor import Contractor
from app.models.agreements.pole_agreement import PoleAgreement
from app.models.agreements.pole_agreement_site import PoleAgreementSite
from app.models.eis.eis_import_event import EisImportEvent
from app.models.eis.eis_import_run import EisImportRun
from app.models.inquiries.inquiry import Inquiry
from app.models.inquiries.mailbox_state import InquiryMailboxState
from app.models.files.attachment import Attachment
from app.models.projects.project import Project
from app.models.projects.project_document import ProjectDocument
from app.models.projects.project_history import ProjectHistory
from app.models.projects.project_member import ProjectMember
from app.models.custom_fields.custom_field import CustomField
from app.models.custom_fields.custom_field_value import CustomFieldValue
from app.models.custom_fields.field_option import FieldOption
from app.models.requests.request import Request
from app.models.requests.request_dispatcher import RequestDispatcher
from app.models.requests.request_history import RequestHistory
from app.models.requests.request_material import RequestMaterial
from app.models.requests.request_status import RequestStatus
from app.models.tenders.tender_application import TenderApplication
from app.models.tenders.tender_document import TenderDocument
from app.models.tenders.tender_project import TenderProject
from app.models.work_objects.work_object import WorkObject

__all__ = [
    "BaseModel",
    "ActiveRecordMixin",
    "utcnow",
    "User",
    "Role",
    "RoleFieldPermission",
    "FieldDefinition",
    "SystemModule",
    "Position",
    "Permission",
    "UserRole",
    "RolePermission",
    "LoginLog",
    "Request",
    "RequestDispatcher",
    "RequestStatus",
    "RequestHistory",
    "RequestMaterial",
    "WorkObject",
    "Project",
    "ProjectMember",
    "ProjectDocument",
    "ProjectHistory",
    "TenderApplication",
    "TenderDocument",
    "TenderProject",
    "Contract",
    "ContractContractor",
    "ContractDocument",
    "ContractHistory",
    "ContractObject",
    "Contractor",
    "PoleAgreement",
    "PoleAgreementSite",
    "EisImportRun",
    "EisImportEvent",
    "Inquiry",
    "InquiryMailboxState",
    "Message",
    "MessengerConversation",
    "MessengerMessage",
    "UserPresence",
    "Notification",
    "Comment",
    "Attachment",
    "CustomField",
    "CustomFieldValue",
    "FieldOption",
    "AuditLog",
]
