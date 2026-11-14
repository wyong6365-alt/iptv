"""数据模型。全专业管理实体对应任务书第十五章；原始清单、组价、审计分表独立。"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import JSON, Date, DateTime, ForeignKey, ForeignKeyConstraint, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, Dec


def now() -> datetime:
    return datetime.now(timezone.utc)


def pk():
    return mapped_column(Integer, primary_key=True)


# ---------- 目录与全专业管理 ----------

class Region(Base):
    __tablename__ = "region_catalog"
    id: Mapped[int] = pk()
    code: Mapped[str] = mapped_column(String(12), unique=True)
    name: Mapped[str] = mapped_column(String(50))
    level: Mapped[str] = mapped_column(String(10))  # country / province / city
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("region_catalog.id"))


class Profession(Base):
    __tablename__ = "engineering_professions"
    id: Mapped[int] = pk()
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(50))
    sort: Mapped[int] = mapped_column(Integer, default=0)
    subcategories: Mapped[list["ProfessionSubcategory"]] = relationship(order_by="ProfessionSubcategory.sort")


class ProfessionSubcategory(Base):
    __tablename__ = "profession_subcategories"
    id: Mapped[int] = pk()
    profession_id: Mapped[int] = mapped_column(ForeignKey("engineering_professions.id"))
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    sort: Mapped[int] = mapped_column(Integer, default=0)


class ProfessionAdapter(Base):
    __tablename__ = "profession_adapters"
    id: Mapped[int] = pk()
    profession_id: Mapped[int] = mapped_column(ForeignKey("engineering_professions.id"), unique=True)
    adapter_code: Mapped[str] = mapped_column(String(40))
    pricing_system: Mapped[str] = mapped_column(String(40))
    version: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))


class ProfessionCapability(Base):
    __tablename__ = "profession_capabilities"
    __table_args__ = (UniqueConstraint("profession_id", "region_id", "capability"),)
    id: Mapped[int] = pk()
    profession_id: Mapped[int] = mapped_column(ForeignKey("engineering_professions.id"))
    region_id: Mapped[int] = mapped_column(ForeignKey("region_catalog.id"))
    capability: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30))
    evidence: Mapped[str] = mapped_column(Text, default="")
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class PricingStandard(Base):
    __tablename__ = "pricing_standard_catalog"
    id: Mapped[int] = pk()
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    issuer: Mapped[str] = mapped_column(String(100))
    doc_no: Mapped[str] = mapped_column(String(60), default="")
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    region_id: Mapped[int | None] = mapped_column(ForeignKey("region_catalog.id"))
    source_url: Mapped[str] = mapped_column(String(300), default="")
    note: Mapped[str] = mapped_column(Text, default="")


class QuotaVersion(Base):
    __tablename__ = "quota_version_catalog"
    id: Mapped[int] = pk()
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    issuer: Mapped[str] = mapped_column(String(100))
    version: Mapped[str] = mapped_column(String(20))
    effective_from: Mapped[date | None] = mapped_column(Date)
    region_id: Mapped[int | None] = mapped_column(ForeignKey("region_catalog.id"))
    source: Mapped[str] = mapped_column(Text, default="")
    license_info: Mapped[str] = mapped_column(Text, default="")
    import_status: Mapped[str] = mapped_column(String(20), default="not_imported")
    chapters_total: Mapped[int | None] = mapped_column(Integer)
    chapters_imported: Mapped[int] = mapped_column(Integer, default=0)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class FeeRuleSet(Base):
    __tablename__ = "fee_rule_sets"
    id: Mapped[int] = pk()
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    pricing_system: Mapped[str] = mapped_column(String(40))
    pricing_standard_id: Mapped[int | None] = mapped_column(ForeignKey("pricing_standard_catalog.id"))
    data: Mapped[dict] = mapped_column(JSON)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProfessionQuotaMapping(Base):
    __tablename__ = "profession_quota_mapping"
    __table_args__ = (UniqueConstraint("profession_id", "quota_version_id"),)
    id: Mapped[int] = pk()
    profession_id: Mapped[int] = mapped_column(ForeignKey("engineering_professions.id"))
    quota_version_id: Mapped[int] = mapped_column(ForeignKey("quota_version_catalog.id"))
    region_id: Mapped[int | None] = mapped_column(ForeignKey("region_catalog.id"))
    scope_note: Mapped[str] = mapped_column(Text, default="")


class ProfessionFeeRuleMapping(Base):
    __tablename__ = "profession_fee_rule_mapping"
    __table_args__ = (UniqueConstraint("profession_id", "fee_rule_set_id"),)
    id: Mapped[int] = pk()
    profession_id: Mapped[int] = mapped_column(ForeignKey("engineering_professions.id"))
    fee_rule_set_id: Mapped[int] = mapped_column(ForeignKey("fee_rule_sets.id"))
    region_id: Mapped[int | None] = mapped_column(ForeignKey("region_catalog.id"))


class ProfessionResourceMapping(Base):
    __tablename__ = "profession_resource_mapping"
    id: Mapped[int] = pk()
    profession_id: Mapped[int] = mapped_column(ForeignKey("engineering_professions.id"))
    resource_category: Mapped[str] = mapped_column(String(80))


class ProfessionExportTemplate(Base):
    __tablename__ = "profession_export_templates"
    id: Mapped[int] = pk()
    profession_id: Mapped[int] = mapped_column(ForeignKey("engineering_professions.id"))
    region_id: Mapped[int | None] = mapped_column(ForeignKey("region_catalog.id"))
    report_code: Mapped[str] = mapped_column(String(40))
    template_file: Mapped[str] = mapped_column(String(300))


class ProfessionTestCase(Base):
    __tablename__ = "profession_test_cases"
    id: Mapped[int] = pk()
    profession_id: Mapped[int] = mapped_column(ForeignKey("engineering_professions.id"))
    project_ref: Mapped[str] = mapped_column(String(200))
    baseline_ref: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending / passed / failed
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)


class ProfessionCoverageReport(Base):
    __tablename__ = "profession_coverage_reports"
    id: Mapped[int] = pk()
    profession_id: Mapped[int | None] = mapped_column(ForeignKey("engineering_professions.id"))
    region_id: Mapped[int | None] = mapped_column(ForeignKey("region_catalog.id"))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    content: Mapped[dict] = mapped_column(JSON)


# ---------- 用户、项目 ----------

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = pk()
    username: Mapped[str] = mapped_column(String(50), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20))
    active: Mapped[bool] = mapped_column(default=True)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = pk()
    name: Mapped[str] = mapped_column(String(200))
    region_id: Mapped[int] = mapped_column(ForeignKey("region_catalog.id"))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    units: Mapped[list["UnitProject"]] = relationship()


class UnitProject(Base):
    """单位工程。每个单位工程绑定一个计价上下文，不同专业互不混用。"""

    __tablename__ = "unit_projects"
    id: Mapped[int] = pk()
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    name: Mapped[str] = mapped_column(String(200))
    profession_id: Mapped[int] = mapped_column(ForeignKey("engineering_professions.id"))
    subcategory_id: Mapped[int | None] = mapped_column(ForeignKey("profession_subcategories.id"))
    pricing_system: Mapped[str] = mapped_column(String(40))
    fee_rule_set_id: Mapped[int | None] = mapped_column(ForeignKey("fee_rule_sets.id"))
    fee_category: Mapped[str | None] = mapped_column(String(40))  # 费用规则中的工程类别键
    grade: Mapped[str | None] = mapped_column(String(5))  # 工程类别 I / II / III
    quota_version_id: Mapped[int | None] = mapped_column(ForeignKey("quota_version_catalog.id"))
    effective_boq_version_id: Mapped[int | None] = mapped_column(Integer)
    # 招标文件确定的参数（锁定）：金额、计税方法、创建目标、费率覆盖，各带出处
    tender_requirements: Mapped[dict] = mapped_column(JSON, default=dict)
    # 造价人员可调的参数
    pricing_params: Mapped[dict] = mapped_column(JSON, default=dict)


# ---------- 原始招标清单（只允许 INSERT，见 protection.py） ----------

class TenderBoqVersion(Base):
    __tablename__ = "tender_boq_versions"
    __table_args__ = (UniqueConstraint("unit_project_id", "version_no"),)
    id: Mapped[int] = pk()
    unit_project_id: Mapped[int] = mapped_column(ForeignKey("unit_projects.id"))
    version_no: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20))  # original / addendum / re_recognition
    source_file: Mapped[str] = mapped_column(String(300), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    content_hash: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    items: Mapped[list["TenderBoqItem"]] = relationship(order_by="TenderBoqItem.seq")


class TenderBoqItem(Base):
    __tablename__ = "tender_boq_items"
    __table_args__ = (UniqueConstraint("version_id", "seq"),)
    id: Mapped[int] = pk()
    version_id: Mapped[int] = mapped_column(ForeignKey("tender_boq_versions.id"))
    seq: Mapped[int] = mapped_column(Integer)
    section: Mapped[str] = mapped_column(String(200), default="")
    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(300))
    features: Mapped[str] = mapped_column(Text, default="")
    unit: Mapped[str] = mapped_column(String(20))
    quantity: Mapped[Decimal] = mapped_column(Dec)
    source_ref: Mapped[str] = mapped_column(String(200), default="")  # 原件页码或单元格
    row_hash: Mapped[str] = mapped_column(String(64))


class BoqAnomaly(Base):
    __tablename__ = "boq_anomalies"
    id: Mapped[int] = pk()
    boq_item_id: Mapped[int] = mapped_column(ForeignKey("tender_boq_items.id"))
    kind: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(Text)
    resolved: Mapped[bool] = mapped_column(default=False)


# ---------- 定额（按版本隔离） ----------

class QuotaItem(Base):
    __tablename__ = "quota_items"
    __table_args__ = (UniqueConstraint("quota_version_id", "code"), UniqueConstraint("id", "quota_version_id"))
    id: Mapped[int] = pk()
    quota_version_id: Mapped[int] = mapped_column(ForeignKey("quota_version_catalog.id"))
    chapter: Mapped[str] = mapped_column(String(100), default="")
    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(300))
    unit: Mapped[str] = mapped_column(String(20))
    work_content: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    source_ref: Mapped[str] = mapped_column(String(200), default="")
    resources: Mapped[list["QuotaItemResource"]] = relationship()


class QuotaItemResource(Base):
    __tablename__ = "quota_item_resources"
    id: Mapped[int] = pk()
    quota_item_id: Mapped[int] = mapped_column(ForeignKey("quota_items.id"))
    kind: Mapped[str] = mapped_column(String(10))  # labor / material / machine
    code: Mapped[str] = mapped_column(String(40), default="")
    name: Mapped[str] = mapped_column(String(200))
    spec: Mapped[str] = mapped_column(String(200), default="")
    unit: Mapped[str] = mapped_column(String(20))
    consumption: Mapped[Decimal] = mapped_column(Dec)


# ---------- 组价（可改，与原始清单分离） ----------

class CompositionLine(Base):
    """清单项下的组价子目。定额子目必须与单位工程绑定的定额版本一致（复合外键 + 服务层校验）。"""

    __tablename__ = "composition_lines"
    __table_args__ = (
        ForeignKeyConstraint(["quota_item_id", "quota_version_id"], ["quota_items.id", "quota_items.quota_version_id"]),
    )
    id: Mapped[int] = pk()
    unit_project_id: Mapped[int] = mapped_column(ForeignKey("unit_projects.id"))
    boq_code: Mapped[str] = mapped_column(String(40))  # 按清单编码关联，补遗换版后仍可对应
    boq_seq: Mapped[int] = mapped_column(Integer)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(15))  # quota / supplementary
    quota_item_id: Mapped[int | None] = mapped_column(Integer)
    quota_version_id: Mapped[int | None] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(300))
    unit: Mapped[str] = mapped_column(String(20), default="")
    content: Mapped[Decimal] = mapped_column(Dec)  # 每清单单位含量
    labor: Mapped[Decimal] = mapped_column(Dec, default=Decimal(0))
    material: Mapped[Decimal] = mapped_column(Dec, default=Decimal(0))
    machine: Mapped[Decimal] = mapped_column(Dec, default=Decimal(0))
    basis_note: Mapped[str] = mapped_column(Text, default="")


class CalcRun(Base):
    """计算快照。只由计价引擎写入。"""

    __tablename__ = "calc_runs"
    id: Mapped[int] = pk()
    unit_project_id: Mapped[int] = mapped_column(ForeignKey("unit_projects.id"))
    boq_version_id: Mapped[int] = mapped_column(ForeignKey("tender_boq_versions.id"))
    pricing_system: Mapped[str] = mapped_column(String(40))
    rule_code: Mapped[str | None] = mapped_column(String(40))
    input_hash: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict] = mapped_column(JSON)
    total: Mapped[Decimal] = mapped_column(Dec)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = pk()
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(60))
    target: Mapped[str] = mapped_column(String(100), default="")
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
