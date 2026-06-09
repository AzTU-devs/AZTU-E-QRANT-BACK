"""
AZTU E-Grant — new (v2) database schema.

Standalone SQLAlchemy 2.0 models on their own DeclarativeBase, so they can:
  1. create the fresh target database for the data migration, and
  2. later be promoted into the Flask app (Flask-SQLAlchemy 3.1 accepts a custom
     base via `SQLAlchemy(model_class=Base)`).

Implements docs/DB_ARCHITECTURE.md: surrogate PKs, real FKs, enum statuses,
unified budget line items, and DB-computed line totals.
"""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, Computed, DateTime, ForeignKey, Integer, String, Text,
    UniqueConstraint, Index, func,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #
class AcademicType(enum.Enum):
    TEACHER = "TEACHER"
    PHD = "PHD"
    MASTER = "MASTER"


class AccountStatus(enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    BLOCKED = "BLOCKED"


class GlobalRole(enum.Enum):
    APPLICANT = "APPLICANT"
    ADMIN = "ADMIN"
    SUPER_ADMIN = "SUPER_ADMIN"


class ProjectStatus(enum.Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class MemberRole(enum.Enum):
    OWNER = "OWNER"
    COLLABORATOR = "COLLABORATOR"


class MemberStatus(enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class AssignmentStatus(enum.Enum):
    ASSIGNED = "ASSIGNED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    COMPLETED = "COMPLETED"


class BudgetCategory(enum.Enum):
    EQUIPMENT = "EQUIPMENT"
    SERVICES = "SERVICES"
    RENT = "RENT"
    OTHER = "OTHER"


def _enum(py_enum, name):
    """Postgres enum that stores the member *value* strings."""
    return SAEnum(py_enum, name=name, values_callable=lambda e: [m.value for m in e])


# Shared timestamp helpers -------------------------------------------------- #
def _created():
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def _updated():
    return mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)


# --------------------------------------------------------------------------- #
# Identity & access
# --------------------------------------------------------------------------- #
class Institution(Base):
    __tablename__ = "institutions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    created_at = _created()
    updated_at = _updated()


class Priority(Base):
    __tablename__ = "priorities"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at = _created()
    updated_at = _updated()


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    fin_kod: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    global_role: Mapped[GlobalRole] = mapped_column(
        _enum(GlobalRole, "global_role"), nullable=False, default=GlobalRole.APPLICANT
    )
    academic_type: Mapped[AcademicType | None] = mapped_column(
        _enum(AcademicType, "academic_type"), nullable=True
    )

    # identity
    name: Mapped[str | None] = mapped_column(Text)
    surname: Mapped[str | None] = mapped_column(Text)
    father_name: Mapped[str | None] = mapped_column(Text)
    born_date: Mapped[datetime | None] = mapped_column(DateTime)
    born_place: Mapped[str | None] = mapped_column(Text)
    sex: Mapped[str | None] = mapped_column(Text)
    citizenship: Mapped[str | None] = mapped_column(Text)
    personal_id_number: Mapped[str | None] = mapped_column(Text)
    living_location: Mapped[str | None] = mapped_column(Text)

    # contact
    home_phone: Mapped[str | None] = mapped_column(Text)
    personal_mobile_number: Mapped[str | None] = mapped_column(Text, unique=True)
    personal_email: Mapped[str | None] = mapped_column(Text, unique=True)

    # work
    work_place: Mapped[str | None] = mapped_column(Text)
    department: Mapped[str | None] = mapped_column(Text)
    duty: Mapped[str | None] = mapped_column(Text)
    work_location: Mapped[str | None] = mapped_column(Text)
    work_phone: Mapped[str | None] = mapped_column(Text, unique=True)
    work_email: Mapped[str | None] = mapped_column(Text, unique=True)

    # education / science
    main_education: Mapped[str | None] = mapped_column(Text)
    additional_education: Mapped[str | None] = mapped_column(Text)
    scientific_degree: Mapped[str | None] = mapped_column(Text)
    scientific_degree_date: Mapped[datetime | None] = mapped_column(DateTime)
    scientific_title: Mapped[str | None] = mapped_column(Text)
    scientific_title_date: Mapped[datetime | None] = mapped_column(DateTime)

    institution_id: Mapped[int | None] = mapped_column(
        ForeignKey("institutions.id", ondelete="RESTRICT")
    )
    avatar_url: Mapped[str | None] = mapped_column(Text)
    profile_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at = _created()
    updated_at = _updated()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    credential: Mapped["Credential"] = relationship(back_populates="user", uselist=False)


class Credential(Base):
    __tablename__ = "credentials"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[AccountStatus] = mapped_column(
        _enum(AccountStatus, "account_status"), nullable=False, default=AccountStatus.PENDING
    )
    otp_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    blocked_at: Mapped[datetime | None] = mapped_column(DateTime)
    unblocked_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at = _created()
    updated_at = _updated()

    user: Mapped[User] = relationship(back_populates="credential")


class OtpCode(Base):
    __tablename__ = "otp_codes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(String, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_otp_user_expires", "user_id", "expires_at"),)


class Expert(Base):
    __tablename__ = "experts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    surname: Mapped[str] = mapped_column(Text, nullable=False)
    father_name: Mapped[str] = mapped_column(Text, nullable=False)
    personal_id_serial_number: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    work_place: Mapped[str | None] = mapped_column(Text)
    duty: Mapped[str | None] = mapped_column(Text)
    scientific_degree: Mapped[str | None] = mapped_column(Text)
    phone_number: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at = _created()
    updated_at = _updated()


# --------------------------------------------------------------------------- #
# Projects
# --------------------------------------------------------------------------- #
class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_code: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    institution_id: Mapped[int | None] = mapped_column(ForeignKey("institutions.id", ondelete="RESTRICT"))
    priority_id: Mapped[int | None] = mapped_column(ForeignKey("priorities.id", ondelete="RESTRICT"))

    project_name: Mapped[str | None] = mapped_column(Text)
    project_purpose: Mapped[str | None] = mapped_column(Text)
    annotation: Mapped[str | None] = mapped_column(Text)
    key_words: Mapped[str | None] = mapped_column(Text)
    scientific_idea: Mapped[str | None] = mapped_column(Text)
    structure: Mapped[str | None] = mapped_column(Text)
    team_characterization: Mapped[str | None] = mapped_column(Text)
    monitoring_plan: Mapped[str | None] = mapped_column(Text)
    assessment_plan: Mapped[str | None] = mapped_column(Text)
    requirements: Mapped[str | None] = mapped_column(Text)
    deadline: Mapped[datetime | None] = mapped_column(DateTime)

    status: Mapped[ProjectStatus] = mapped_column(
        _enum(ProjectStatus, "project_status"), nullable=False, default=ProjectStatus.DRAFT
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    collaborator_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    max_budget_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=30000)

    created_at = _created()
    updated_at = _updated()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProjectMember(Base):
    __tablename__ = "project_members"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[MemberRole] = mapped_column(_enum(MemberRole, "member_role"), nullable=False)
    status: Mapped[MemberStatus] = mapped_column(
        _enum(MemberStatus, "member_status"), nullable=False, default=MemberStatus.PENDING
    )
    joined_at: Mapped[datetime | None] = mapped_column(DateTime)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at = _created()
    updated_at = _updated()

    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_member_project_user"),)


class ProjectActivity(Base):
    __tablename__ = "project_activities"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    activity_name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at = _created()
    updated_at = _updated()

    __table_args__ = (Index("ix_activity_project_month", "project_id", "month"),)


class ExpertAssignment(Base):
    __tablename__ = "expert_assignments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    expert_id: Mapped[int] = mapped_column(ForeignKey("experts.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[AssignmentStatus] = mapped_column(
        _enum(AssignmentStatus, "assignment_status"), nullable=False, default=AssignmentStatus.ASSIGNED
    )
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (UniqueConstraint("project_id", "expert_id", name="uq_assignment_project_expert"),)


class Assessment(Base):
    __tablename__ = "assessments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    expert_id: Mapped[int] = mapped_column(ForeignKey("experts.id", ondelete="RESTRICT"), nullable=False)
    score: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text)
    created_at = _created()
    updated_at = _updated()

    __table_args__ = (UniqueConstraint("project_id", "expert_id", name="uq_assessment_project_expert"),)


class QuarterlyReport(Base):
    __tablename__ = "quarterly_reports"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    quarter_number: Mapped[int] = mapped_column(Integer, nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    submission_date: Mapped[datetime | None] = mapped_column(DateTime)
    created_at = _created()
    updated_at = _updated()

    __table_args__ = (
        UniqueConstraint("project_id", "year", "quarter_number", name="uq_report_project_year_quarter"),
    )


class QuarterlyReportItem(Base):
    __tablename__ = "quarterly_report_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("quarterly_reports.id", ondelete="CASCADE"), nullable=False)
    item_no: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (UniqueConstraint("report_id", "item_no", name="uq_report_item"),)


# --------------------------------------------------------------------------- #
# Budget (Smeta)
# --------------------------------------------------------------------------- #
class Budget(Base):
    __tablename__ = "budgets"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    total_fee: Mapped[int | None] = mapped_column(Integer, default=0)
    defense_fund: Mapped[int | None] = mapped_column(Integer, default=0)
    # cached rollups (authority = v_budget_totals view; refreshed on writes)
    total_salary: Mapped[int | None] = mapped_column(Integer, default=0)
    total_equipment: Mapped[int | None] = mapped_column(Integer, default=0)
    total_services: Mapped[int | None] = mapped_column(Integer, default=0)
    total_rent: Mapped[int | None] = mapped_column(Integer, default=0)
    total_other: Mapped[int | None] = mapped_column(Integer, default=0)
    grand_total: Mapped[int | None] = mapped_column(Integer, default=0)
    created_at = _created()
    updated_at = _updated()


class BudgetSalary(Base):
    __tablename__ = "budget_salaries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    budget_id: Mapped[int] = mapped_column(ForeignKey("budgets.id", ondelete="CASCADE"), nullable=False)
    member_id: Mapped[int] = mapped_column(ForeignKey("project_members.id", ondelete="CASCADE"), nullable=False)
    salary_per_month: Mapped[int] = mapped_column(Integer, nullable=False)
    months: Mapped[int] = mapped_column(Integer, nullable=False)
    total_amount: Mapped[int] = mapped_column(
        Integer, Computed("salary_per_month * months", persisted=True)
    )

    __table_args__ = (UniqueConstraint("budget_id", "member_id", name="uq_salary_budget_member"),)


class BudgetLineItem(Base):
    __tablename__ = "budget_line_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    budget_id: Mapped[int] = mapped_column(ForeignKey("budgets.id", ondelete="CASCADE"), nullable=False)
    category: Mapped[BudgetCategory] = mapped_column(_enum(BudgetCategory, "budget_category"), nullable=False)
    item_name: Mapped[str] = mapped_column(Text, nullable=False)
    unit_of_measure: Mapped[str | None] = mapped_column(Text)
    unit_price: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    duration: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    total_amount: Mapped[int] = mapped_column(
        Integer, Computed("unit_price * quantity * duration", persisted=True)
    )
    created_at = _created()
    updated_at = _updated()

    __table_args__ = (Index("ix_lineitem_budget_category", "budget_id", "category"),)


# SQL for the authoritative totals view (created by the ETL after load).
V_BUDGET_TOTALS_SQL = """
CREATE OR REPLACE VIEW v_budget_totals AS
SELECT b.id AS budget_id,
       COALESCE(s.salary, 0)                                   AS total_salary,
       COALESCE(li.equipment, 0)                               AS total_equipment,
       COALESCE(li.services, 0)                                AS total_services,
       COALESCE(li.rent, 0)                                    AS total_rent,
       COALESCE(li.other, 0)                                   AS total_other,
       COALESCE(s.salary, 0) + COALESCE(li.total, 0)
         + COALESCE(b.total_fee, 0) + COALESCE(b.defense_fund, 0) AS grand_total
FROM budgets b
LEFT JOIN (SELECT budget_id, SUM(total_amount) AS salary
           FROM budget_salaries GROUP BY budget_id) s ON s.budget_id = b.id
LEFT JOIN (SELECT budget_id,
             SUM(total_amount) AS total,
             SUM(total_amount) FILTER (WHERE category = 'EQUIPMENT') AS equipment,
             SUM(total_amount) FILTER (WHERE category = 'SERVICES')  AS services,
             SUM(total_amount) FILTER (WHERE category = 'RENT')      AS rent,
             SUM(total_amount) FILTER (WHERE category = 'OTHER')     AS other
           FROM budget_line_items GROUP BY budget_id) li ON li.budget_id = b.id;
"""
