"""HTTP 接口。"""
from __future__ import annotations

from decimal import Decimal
from typing import Literal

import hashlib
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import adapters, boq_excel, capabilities, models as m, protection, security, seed, services
from .engine import sd_construction as sd_engine
from .catalog import CAPABILITIES, PRICING_SYSTEMS
from .db import Base, data_dir, make_engine, make_session_factory

MAX_UPLOAD = 30 * 1024 * 1024
STATIC_DIR = Path(__file__).parent / "static"

WRITE_ROLES = {"admin", "estimator"}


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Credentials(Strict):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=8, max_length=200)


class NewUser(Credentials):
    role: str


class NewProject(Strict):
    name: str = Field(min_length=1, max_length=200)
    region_code: str = "370000"


class NewUnit(Strict):
    name: str = Field(min_length=1, max_length=200)
    profession: str
    subcategory: str | None = None
    fee_category: str | None = None
    grade: Literal["I", "II", "III"] | None = None


class BoqRow(Strict):
    section: str = ""
    code: str
    name: str
    features: str = ""
    unit: str
    quantity: Decimal
    source_ref: str = ""
    anomalies: list[str] = []


class BoqImport(Strict):
    kind: Literal["original", "addendum", "re_recognition"]
    source_file: str = ""
    note: str = ""
    items: list[BoqRow]


class LineIn(Strict):
    name: str
    unit: str = ""
    content: Decimal
    labor: Decimal = Decimal(0)
    material: Decimal = Decimal(0)
    machine: Decimal = Decimal(0)
    quota_item_id: int | None = None
    basis_note: str = ""


class NamedAmount(Strict):
    name: str
    amount: Decimal
    all_in: bool = False


class PricingParams(Strict):
    """造价人员可调的参数。锁定费用（安全文明措施费下限、工伤保险、税金、暂列金额、暂估价等）不在此列，
    多传任何字段都会被拒绝。"""

    management_rate: Decimal | None = Field(None, ge=0)
    profit_rate: Decimal | None = Field(None, ge=0)
    general_measure_rates: dict[str, Decimal] = {}
    special_measures: list[NamedAmount] = []
    service_owner_material_rate: Decimal | None = Field(None, ge=0)
    service_subcontract_rate: Decimal | None = Field(None, ge=0)
    service_direct_lump: Decimal = Decimal(0)
    daywork: Decimal = Decimal(0)
    other: Decimal = Decimal(0)
    safety_rates: dict[str, Decimal] = {}  # 只能不低于规则下限，由引擎校验
    # 仅人工组价引擎使用
    fee_base: Literal["labor", "labor_machine", "direct"] | None = None
    measures: list[NamedAmount] = []
    others: list[NamedAmount] = []


class TenderRequirements(Strict):
    """招标文件确定的内容。必须注明出处（文件名和页码），修改全部进入审计日志。"""

    source_ref: str = Field(min_length=2)
    tax_method: Literal["general", "simple"] = "general"
    provisional_sum: Decimal = Decimal(0)
    specialty_provisional: Decimal = Decimal(0)
    owner_material: Decimal = Decimal(0)
    quality_level: Literal["national", "provincial", "municipal"] | None = None
    rate_overrides: dict[str, Decimal] = {}
    tax_rate: Decimal | None = None
    tender_amounts: list[NamedAmount] = []


def _json(model: BaseModel) -> dict:
    return model.model_dump(mode="json", exclude_none=True)


def create_app(db_url: str | None = None) -> FastAPI:
    engine = make_engine(db_url)
    Base.metadata.create_all(engine)
    protection.install(engine)
    factory = make_session_factory(engine)
    with factory() as s:
        seed.run(s)

    app = FastAPI(title="广川AI智能工程量清单识别与自主组价平台", version="0.1.0")
    app.state.engine = engine
    app.state.session_factory = factory

    def db():
        with factory() as session:
            yield session

    def current_user(authorization: str = Header(default=""), session: Session = Depends(db)) -> m.User:
        user_id = security.read_token(authorization.removeprefix("Bearer ").strip())
        user = session.get(m.User, user_id) if user_id else None
        if not user or not user.active:
            raise HTTPException(401, "未登录或登录已过期")
        return user

    def require(*roles: str):
        def check(user: m.User = Depends(current_user)) -> m.User:
            if user.role not in roles:
                raise HTTPException(403, "当前角色无此操作权限")
            return user

        return check

    def unit_or_404(session: Session, unit_id: int) -> m.UnitProject:
        unit = session.get(m.UnitProject, unit_id)
        if not unit:
            raise HTTPException(404, "单位工程不存在")
        return unit

    # ----- 用户 -----
    @app.get("/api/auth/status")
    def auth_status(session: Session = Depends(db)):
        return {"initialized": bool(session.scalar(select(func.count()).select_from(m.User)))}

    @app.post("/api/auth/setup")
    def setup(body: Credentials, session: Session = Depends(db)):
        """首次启动时创建管理员。已有用户后此接口关闭。"""
        if session.scalar(select(func.count()).select_from(m.User)):
            raise HTTPException(409, "系统已初始化")
        user = m.User(username=body.username, password_hash=security.hash_password(body.password), role="admin")
        session.add(user)
        session.commit()
        return {"token": security.issue_token(user.id)}

    @app.post("/api/auth/login")
    def login(body: Credentials, session: Session = Depends(db)):
        user = session.scalar(select(m.User).filter_by(username=body.username))
        if not user or not user.active or not security.verify_password(body.password, user.password_hash):
            raise HTTPException(401, "用户名或密码错误")
        return {"token": security.issue_token(user.id), "role": user.role}

    @app.post("/api/users")
    def create_user(body: NewUser, session: Session = Depends(db), admin: m.User = Depends(require("admin"))):
        if body.role not in security.ROLES:
            raise HTTPException(422, f"角色须为 {sorted(security.ROLES)} 之一")
        if session.scalar(select(m.User).filter_by(username=body.username)):
            raise HTTPException(409, "用户名已存在")
        user = m.User(username=body.username, password_hash=security.hash_password(body.password), role=body.role)
        session.add(user)
        services.audit(session, admin.id, "user.create", body.username, role=body.role)
        session.commit()
        return {"id": user.id, "username": user.username, "role": user.role}

    # ----- 目录与能力 -----
    @app.get("/api/professions")
    def professions(session: Session = Depends(db), _: m.User = Depends(current_user)):
        out = []
        sd_rules = session.scalar(select(m.FeeRuleSet).filter_by(pricing_system="sd_construction")).data
        for p in session.scalars(select(m.Profession).order_by(m.Profession.sort)):
            adapter = adapters.REGISTRY.get(p.code)
            out.append({
                "code": p.code, "name": p.name,
                "pricing_system": adapter and {"code": adapter.pricing_system,
                                               "name": PRICING_SYSTEMS[adapter.pricing_system][0],
                                               "engine": adapter.engine_code()},
                "fee_categories": [{"code": c, "name": sd_rules["categories"][c]["name"],
                                    "graded": sd_rules["categories"][c]["graded"]}
                                   for c in (adapter.fee_categories if adapter else ())],
                "subcategories": [{"code": s.code, "name": s.name} for s in p.subcategories],
            })
        return out

    @app.get("/api/capabilities")
    def capability_matrix(region: str = "370000", session: Session = Depends(db), _: m.User = Depends(current_user)):
        return {"columns": [{"key": k, "name": n} for k, n in CAPABILITIES],
                "rows": capabilities.compute(session, region)}

    @app.get("/api/fee-rules/{code}")
    def fee_rules(code: str, session: Session = Depends(db), _: m.User = Depends(current_user)):
        rule = session.scalar(select(m.FeeRuleSet).filter_by(code=code))
        if not rule:
            raise HTTPException(404, "规则不存在")
        return {"code": rule.code, "name": rule.name, "reviewed": rule.reviewed_by is not None, "data": rule.data}

    @app.post("/api/fee-rules/{code}/review")
    def review_rules(code: str, session: Session = Depends(db), user: m.User = Depends(require("admin", "data_admin"))):
        """数据管理员对照依据文件原件复核后签字。"""
        rule = session.scalar(select(m.FeeRuleSet).filter_by(code=code))
        if not rule:
            raise HTTPException(404, "规则不存在")
        rule.reviewed_by, rule.reviewed_at = user.id, m.now()
        rule.data = {**rule.data, "review": {"status": "reviewed", "by": user.username}}
        services.audit(session, user.id, "fee_rules.review", code)
        session.commit()
        return {"code": code, "reviewed": True}

    # ----- 项目 -----
    @app.post("/api/projects")
    def create_project(body: NewProject, session: Session = Depends(db), user: m.User = Depends(require(*WRITE_ROLES))):
        region = session.scalar(select(m.Region).filter_by(code=body.region_code))
        if not region:
            raise HTTPException(422, "地区不存在")
        project = m.Project(name=body.name, region_id=region.id, created_by=user.id)
        session.add(project)
        services.audit(session, user.id, "project.create", body.name)
        session.commit()
        return {"id": project.id, "name": project.name}

    @app.get("/api/projects")
    def list_projects(session: Session = Depends(db), _: m.User = Depends(current_user)):
        return [{"id": p.id, "name": p.name,
                 "units": [{"id": u.id, "name": u.name,
                            "pricing_system": PRICING_SYSTEMS[u.pricing_system][0]} for u in p.units]}
                for p in session.scalars(select(m.Project).order_by(m.Project.id))]

    @app.post("/api/projects/{project_id}/units")
    def create_unit(project_id: int, body: NewUnit, session: Session = Depends(db),
                    user: m.User = Depends(require(*WRITE_ROLES))):
        if not session.get(m.Project, project_id):
            raise HTTPException(404, "项目不存在")
        prof = session.scalar(select(m.Profession).filter_by(code=body.profession))
        if not prof:
            raise HTTPException(422, "专业不存在")
        try:
            adapter = adapters.get(prof.code)
        except adapters.NotAvailable as exc:
            raise HTTPException(422, str(exc)) from None
        sub = None
        if body.subcategory:
            sub = session.scalar(select(m.ProfessionSubcategory).filter_by(code=body.subcategory, profession_id=prof.id))
            if not sub:
                raise HTTPException(422, "子专业不属于该专业")
        engine_code = adapter.engine_code()
        rule_set_id = None
        notices = []
        if engine_code == "sd_construction":
            rule = session.scalar(
                select(m.FeeRuleSet).join(m.ProfessionFeeRuleMapping,
                                          m.ProfessionFeeRuleMapping.fee_rule_set_id == m.FeeRuleSet.id)
                .where(m.ProfessionFeeRuleMapping.profession_id == prof.id))
            if body.fee_category not in adapter.fee_categories:
                raise HTTPException(422, f"请选择费用规则工程类别，可选：{list(adapter.fee_categories)}")
            if rule.data["categories"][body.fee_category]["graded"] and not body.grade:
                raise HTTPException(422, "该工程类别需要指定 I、II、III 类")
            rule_set_id = rule.id
        else:
            if body.fee_category or body.grade:
                raise HTTPException(422, "该专业没有可选的费用规则工程类别")
            notices.append(f"{PRICING_SYSTEMS[adapter.pricing_system][0]}的计价规则和定额尚未录入，"
                           "本单位工程只能人工组价，费率由人工输入")
        unit = m.UnitProject(project_id=project_id, name=body.name, profession_id=prof.id,
                             subcategory_id=sub.id if sub else None, pricing_system=adapter.pricing_system,
                             fee_rule_set_id=rule_set_id, fee_category=body.fee_category, grade=body.grade,
                             tender_requirements={}, pricing_params={})
        session.add(unit)
        services.audit(session, user.id, "unit.create", body.name, profession=prof.code)
        session.commit()
        return {"id": unit.id, "name": unit.name, "pricing_system": unit.pricing_system, "engine": engine_code,
                "notices": notices}

    # ----- 招标清单 -----
    @app.post("/api/units/{unit_id}/boq")
    def import_boq(unit_id: int, body: BoqImport, session: Session = Depends(db),
                   user: m.User = Depends(require(*WRITE_ROLES))):
        unit = unit_or_404(session, unit_id)
        try:
            version, diff = services.import_boq(session, unit, [r.model_dump() for r in body.items], body.kind,
                                                user.id, body.source_file, body.note)
        except services.ServiceError as exc:
            raise HTTPException(422, str(exc)) from None
        return {"version_id": version.id, "version_no": version.version_no, "content_hash": version.content_hash,
                "items": len(version.items), "diff": diff}

    @app.post("/api/units/{unit_id}/boq/recognize")
    async def recognize_boq(unit_id: int, request: Request, filename: str, session: Session = Depends(db),
                            user: m.User = Depends(require(*WRITE_ROLES))):
        """识别上传的 Excel 清单，只返回预览，不入库。人工核对后再调用导入接口。"""
        unit_or_404(session, unit_id)
        content = await request.body()
        if not content or len(content) > MAX_UPLOAD:
            raise HTTPException(413 if content else 422, "文件为空或超过 30MB")
        try:
            result = boq_excel.recognize(content, filename)
        except boq_excel.RecognitionError as exc:
            raise HTTPException(422, str(exc)) from None
        digest = hashlib.sha256(content).hexdigest()
        folder = data_dir() / "files"
        folder.mkdir(exist_ok=True)
        (folder / f"{digest}{Path(filename).suffix.lower()[:6]}").write_bytes(content)
        services.audit(session, user.id, "boq.recognize", f"unit:{unit_id}", filename=filename, sha256=digest,
                       items=len(result["items"]))
        session.commit()
        return {"source_file": f"{Path(filename).name}（SHA-256 {digest[:16]}）", **result}

    @app.get("/api/units/{unit_id}")
    def get_unit(unit_id: int, session: Session = Depends(db), _: m.User = Depends(current_user)):
        unit = unit_or_404(session, unit_id)
        prof = session.get(m.Profession, unit.profession_id)
        adapter = adapters.get(prof.code)
        engine_code = adapter.engine_code()
        tender = unit.tender_requirements or {}
        reference = None
        if engine_code == "sd_construction":
            rule = session.get(m.FeeRuleSet, unit.fee_rule_set_id)
            r = sd_engine._rates(rule.data, sd_engine.Params(category=unit.fee_category, grade=unit.grade,
                                                             tax_method=tender.get("tax_method", "general")))
            reference = {
                "rule_code": rule.code, "rule_name": rule.name, "reviewed": rule.reviewed_by is not None,
                "category_name": r["cat"]["name"],
                "fee_base": "人工费+施工机具使用费" if r["cat"]["fee_base"] == "labor_machine" else "人工费",
                "management": str(r["management"]), "profit": str(r["profit"]),
                "general_measures": [{"key": k, "name": sd_engine.GENERAL_MEASURE_NAMES[k], "rate": str(v)}
                                     for k, v in r["general_measures"].items()],
                "safety": [{"key": k, "name": sd_engine.SAFETY_NAMES[k], "floor": str(v)}
                           for k, v in r["safety"].items()],
                "injury": str(r["injury"]), "vat": str(r["vat"]),
                "quality": {k: str(v) for k, v in r["quality"].items()},
                "service": rule.data["general_contract_service"],
            }
        last = session.scalar(select(m.CalcRun).filter_by(unit_project_id=unit.id).order_by(m.CalcRun.id.desc()))
        project = session.get(m.Project, unit.project_id)
        return {"id": unit.id, "name": unit.name, "project": {"id": project.id, "name": project.name},
                "profession": {"code": prof.code, "name": prof.name},
                "pricing_system": PRICING_SYSTEMS[unit.pricing_system][0], "engine": engine_code,
                "grade": unit.grade, "tender_requirements": tender, "pricing_params": unit.pricing_params or {},
                "reference": reference, "has_boq": unit.effective_boq_version_id is not None,
                "last_run": last and {"run_id": last.id, "at": last.created_at.isoformat(),
                                      "boq_version_id": last.boq_version_id, **last.result}}

    @app.get("/api/units/{unit_id}/lines")
    def get_lines(unit_id: int, session: Session = Depends(db), _: m.User = Depends(current_user)):
        unit_or_404(session, unit_id)
        out: dict[int, list] = {}
        for l in session.scalars(select(m.CompositionLine).filter_by(unit_project_id=unit_id)
                                 .order_by(m.CompositionLine.boq_seq, m.CompositionLine.sort)):
            out.setdefault(l.boq_seq, []).append({
                "name": l.name, "unit": l.unit, "content": str(l.content), "labor": str(l.labor),
                "material": str(l.material), "machine": str(l.machine), "quota_item_id": l.quota_item_id,
                "basis_note": l.basis_note})
        return out

    @app.get("/api/units/{unit_id}/boq")
    def get_boq(unit_id: int, session: Session = Depends(db), _: m.User = Depends(current_user)):
        unit = unit_or_404(session, unit_id)
        if not unit.effective_boq_version_id:
            raise HTTPException(404, "尚未导入招标清单")
        version = session.get(m.TenderBoqVersion, unit.effective_boq_version_id)
        notes: dict[int, list[str]] = {}
        for a in session.scalars(select(m.BoqAnomaly).join(m.TenderBoqItem).where(
                m.TenderBoqItem.version_id == version.id)):
            notes.setdefault(a.boq_item_id, []).append(a.message)
        return {"version_id": version.id, "version_no": version.version_no, "kind": version.kind,
                "source_file": version.source_file, "note": version.note, "content_hash": version.content_hash,
                "intact": services.verify_boq_integrity(version),
                "items": [{"seq": i.seq, "section": i.section, "code": i.code, "name": i.name, "features": i.features,
                           "unit": i.unit, "quantity": str(i.quantity), "source_ref": i.source_ref,
                           "anomalies": notes.get(i.id, [])}
                          for i in version.items]}

    # ----- 组价与计算 -----
    @app.put("/api/units/{unit_id}/boq/{seq}/lines")
    def put_lines(unit_id: int, seq: int, body: list[LineIn], session: Session = Depends(db),
                  user: m.User = Depends(require(*WRITE_ROLES))):
        unit = unit_or_404(session, unit_id)
        try:
            services.set_lines(session, unit, seq, [_json(line) for line in body], user.id)
        except services.ServiceError as exc:
            raise HTTPException(422, str(exc)) from None
        return {"lines": len(body)}

    @app.put("/api/units/{unit_id}/pricing-params")
    def put_params(unit_id: int, body: PricingParams, session: Session = Depends(db),
                   user: m.User = Depends(require(*WRITE_ROLES))):
        unit = unit_or_404(session, unit_id)
        before, unit.pricing_params = unit.pricing_params, _json(body)
        services.audit(session, user.id, "pricing.params", f"unit:{unit.id}", before=before, after=unit.pricing_params)
        session.commit()
        return unit.pricing_params

    @app.put("/api/units/{unit_id}/tender-requirements")
    def put_tender(unit_id: int, body: TenderRequirements, session: Session = Depends(db),
                   user: m.User = Depends(require(*WRITE_ROLES))):
        unit = unit_or_404(session, unit_id)
        before, unit.tender_requirements = unit.tender_requirements, _json(body)
        services.audit(session, user.id, "tender.requirements", f"unit:{unit.id}", before=before,
                       after=unit.tender_requirements)
        session.commit()
        return unit.tender_requirements

    @app.post("/api/units/{unit_id}/calculate")
    def calculate(unit_id: int, session: Session = Depends(db), user: m.User = Depends(require(*WRITE_ROLES))):
        unit = unit_or_404(session, unit_id)
        try:
            run = services.calculate(session, unit, user.id)
        except services.ServiceError as exc:
            raise HTTPException(422, str(exc)) from None
        return {"run_id": run.id, "input_hash": run.input_hash, **run.result}

    @app.get("/api/audit")
    def audit_log(limit: int = 100, session: Session = Depends(db),
                  _: m.User = Depends(require("admin", "reviewer"))):
        rows = session.scalars(select(m.AuditLog).order_by(m.AuditLog.id.desc()).limit(min(limit, 500)))
        return [{"id": r.id, "user_id": r.user_id, "action": r.action, "target": r.target, "detail": r.detail,
                 "at": r.at.isoformat()} for r in rows]

    if STATIC_DIR.is_dir():
        app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="ui")
    return app
