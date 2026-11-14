"""业务服务：清单导入与保护、组价、计算。"""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import adapters, models as m
from .engine import manual as manual_engine
from .engine import sd_construction as sd_engine
from .engine.core import EngineError, Fee, Item, Line, Result

BOQ_FIELDS = ("code", "name", "features", "unit", "quantity")


class ServiceError(ValueError):
    pass


def audit(session: Session, user_id: int | None, action: str, target: str = "", **detail) -> None:
    session.add(m.AuditLog(user_id=user_id, action=action, target=target, detail=detail))


# ---------- 原始清单 ----------

def _norm_qty(value) -> Decimal:
    if isinstance(value, float):
        raise ServiceError("工程量请以字符串传入，避免浮点误差")
    try:
        return Decimal(str(value))
    except InvalidOperation:
        raise ServiceError(f"工程量不是数字：{value!r}") from None


def row_hash(seq: int, section: str, code: str, name: str, features: str, unit: str, quantity: Decimal) -> str:
    payload = json.dumps([seq, section, code, name, features, unit, str(quantity)], ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def import_boq(session: Session, unit: m.UnitProject, rows: list[dict], kind: str, user_id: int,
               source_file: str = "", note: str = "") -> tuple[m.TenderBoqVersion, list[dict]]:
    """导入清单生成新版本。任何情况下都不修改既有版本。返回新版本及与上一有效版本的差异。"""
    if kind not in ("original", "addendum", "re_recognition"):
        raise ServiceError("kind 须为 original、addendum 或 re_recognition")
    last_no = session.scalar(select(func.max(m.TenderBoqVersion.version_no)).filter_by(unit_project_id=unit.id)) or 0
    if kind == "original" and last_no:
        raise ServiceError("已存在原始清单。补遗请用 addendum，纠正识别错误请用 re_recognition")
    if kind != "original" and not last_no:
        raise ServiceError("尚未导入原始清单")
    if kind != "original" and not note.strip():
        raise ServiceError("补遗或重新识别必须说明依据")
    if not rows:
        raise ServiceError("清单为空")

    items, hashes = [], []
    for seq, row in enumerate(rows, start=1):
        missing = [f for f in ("code", "name", "unit", "quantity") if not str(row.get(f, "")).strip()]
        if missing:
            raise ServiceError(f"第 {seq} 行缺少 {missing}")
        qty = _norm_qty(row["quantity"])
        section, features = row.get("section", ""), row.get("features", "")
        h = row_hash(seq, section, row["code"], row["name"], features, row["unit"], qty)
        hashes.append(h)
        items.append(m.TenderBoqItem(seq=seq, section=section, code=row["code"], name=row["name"], features=features,
                                     unit=row["unit"], quantity=qty, source_ref=row.get("source_ref", ""), row_hash=h))
    version = m.TenderBoqVersion(
        unit_project_id=unit.id, version_no=last_no + 1, kind=kind, source_file=source_file, note=note,
        content_hash=hashlib.sha256("".join(hashes).encode()).hexdigest(), created_by=user_id, items=items)
    session.add(version)
    session.flush()

    diff: list[dict] = []
    if unit.effective_boq_version_id:
        previous = session.get(m.TenderBoqVersion, unit.effective_boq_version_id)
        diff = diff_versions(previous, version)
    unit.effective_boq_version_id = version.id
    for item in items:
        if item.quantity <= 0:
            session.add(m.BoqAnomaly(boq_item_id=item.id, kind="quantity", message="工程量不大于 0，请对照原件核实"))
    audit(session, user_id, "boq.import", f"unit:{unit.id}", version=version.version_no, kind=kind,
          content_hash=version.content_hash, changes=len(diff))
    session.commit()
    return version, diff



def diff_versions(old: m.TenderBoqVersion, new: m.TenderBoqVersion) -> list[dict]:
    def index(version):
        out, seen = {}, {}
        for it in version.items:
            n = seen.get(it.code, 0)
            seen[it.code] = n + 1
            out[(it.code, n)] = it
        return out

    a, b = index(old), index(new)
    diff = []
    for key in a.keys() - b.keys():
        diff.append({"change": "removed", "code": key[0], "name": a[key].name})
    for key in b.keys() - a.keys():
        diff.append({"change": "added", "code": key[0], "name": b[key].name})
    for key in a.keys() & b.keys():
        fields = {f: [str(getattr(a[key], f)), str(getattr(b[key], f))]
                  for f in ("name", "features", "unit", "quantity") if getattr(a[key], f) != getattr(b[key], f)}
        if fields:
            diff.append({"change": "modified", "code": key[0], "fields": fields})
    return sorted(diff, key=lambda d: d["code"])


def verify_boq_integrity(version: m.TenderBoqVersion) -> bool:
    hashes = []
    for it in version.items:
        h = row_hash(it.seq, it.section, it.code, it.name, it.features, it.unit, it.quantity)
        if h != it.row_hash:
            return False
        hashes.append(h)
    return hashlib.sha256("".join(hashes).encode()).hexdigest() == version.content_hash


def check_export_consistency(version: m.TenderBoqVersion, rows: list[dict]) -> list[str]:
    """导出内容与有效清单逐项逐字段比对，返回差异说明；为空才允许导出。"""
    problems = []
    if len(rows) != len(version.items):
        problems.append(f"清单项数量不一致：导出 {len(rows)} 项，招标清单 {len(version.items)} 项")
    for it, row in zip(version.items, rows):
        for f in BOQ_FIELDS:
            mine = it.quantity if f == "quantity" else getattr(it, f)
            theirs = row.get(f)
            if f == "quantity":
                try:
                    theirs = Decimal(str(theirs))
                except InvalidOperation:
                    theirs = None
            if mine != theirs:
                problems.append(f"第 {it.seq} 项 {it.code} 的 {f} 不一致：招标清单 {mine!s}，导出 {theirs!s}")
    return problems


# ---------- 组价 ----------

def set_lines(session: Session, unit: m.UnitProject, boq_seq: int, lines: list[dict], user_id: int) -> None:
    version = session.get(m.TenderBoqVersion, unit.effective_boq_version_id) if unit.effective_boq_version_id else None
    item = next((i for i in version.items if i.seq == boq_seq), None) if version else None
    if not item:
        raise ServiceError("清单项不存在")
    old = session.scalars(select(m.CompositionLine).filter_by(unit_project_id=unit.id, boq_seq=boq_seq)).all()
    before = [{"name": l.name, "content": str(l.content), "labor": str(l.labor), "material": str(l.material),
               "machine": str(l.machine)} for l in old]
    for line in old:
        session.delete(line)
    for sort, row in enumerate(lines, start=1):
        quota_item_id = row.get("quota_item_id")
        quota_version_id = None
        if quota_item_id is not None:
            quota = session.get(m.QuotaItem, quota_item_id)
            if not quota:
                raise ServiceError(f"定额子目 {quota_item_id} 不存在")
            if quota.quota_version_id != unit.quota_version_id:
                raise ServiceError("该定额子目不属于本单位工程绑定的定额版本，禁止跨专业、跨版本套用")
            quota_version_id = quota.quota_version_id
        elif not str(row.get("basis_note", "")).strip():
            raise ServiceError("非定额子目（补充子目）必须填写依据说明")
        session.add(m.CompositionLine(
            unit_project_id=unit.id, boq_code=item.code, boq_seq=boq_seq, sort=sort,
            source="quota" if quota_item_id is not None else "supplementary",
            quota_item_id=quota_item_id, quota_version_id=quota_version_id,
            name=row["name"], unit=row.get("unit", ""), content=Decimal(str(row["content"])),
            labor=Decimal(str(row.get("labor", "0"))), material=Decimal(str(row.get("material", "0"))),
            machine=Decimal(str(row.get("machine", "0"))), basis_note=row.get("basis_note", "")))
    audit(session, user_id, "pricing.set_lines", f"unit:{unit.id}/boq:{boq_seq}", before=before, after=lines)
    session.commit()


def _fee_dict(fee: Fee) -> dict:
    return {
        "code": fee.code, "name": fee.name, "amount": str(fee.amount), "formula": fee.formula,
        "base": None if fee.base is None else str(fee.base), "rate": None if fee.rate is None else str(fee.rate),
        "locked": fee.locked, "basis": fee.basis, "children": [_fee_dict(c) for c in fee.children],
    }


def result_dict(result: Result) -> dict:
    return {
        "pricing_system": result.pricing_system, "rule_code": result.rule_code, "total": str(result.total),
        "warnings": result.warnings, "fees": [_fee_dict(f) for f in result.fees],
        "items": [{"boq_item_id": i.boq_item_id, "quantity": str(i.quantity), "labor": str(i.labor),
                   "material": str(i.material), "machine": str(i.machine), "management": str(i.management),
                   "profit": str(i.profit), "unit_price": str(i.unit_price), "amount": str(i.amount)}
                  for i in result.items],
    }


def _d(value, default="0") -> Decimal:
    return Decimal(str(default if value is None else value))


def calculate(session: Session, unit: m.UnitProject, user_id: int) -> m.CalcRun:
    if not unit.effective_boq_version_id:
        raise ServiceError("尚未导入招标清单")
    version = session.get(m.TenderBoqVersion, unit.effective_boq_version_id)
    if not verify_boq_integrity(version):
        raise ServiceError("招标清单完整性校验失败，数据可能被改动，已停止计算")
    lines = session.scalars(select(m.CompositionLine).filter_by(unit_project_id=unit.id)
                            .order_by(m.CompositionLine.boq_seq, m.CompositionLine.sort)).all()
    by_seq: dict[int, list[m.CompositionLine]] = {}
    for line in lines:
        by_seq.setdefault(line.boq_seq, []).append(line)
    items = [Item(it.id, it.quantity, tuple(Line(l.name, l.content, l.labor, l.material, l.machine)
                                            for l in by_seq.get(it.seq, [])))
             for it in version.items]
    unpriced = [it.code for it in version.items if it.seq not in by_seq]

    tender, pp = unit.tender_requirements or {}, unit.pricing_params or {}
    profession = session.get(m.Profession, unit.profession_id)
    engine_code = adapters.get(profession.code).engine_code()
    try:
        if engine_code == sd_engine.CODE:
            rule_set = session.get(m.FeeRuleSet, unit.fee_rule_set_id)
            params = sd_engine.Params(
                category=unit.fee_category, grade=unit.grade, tax_method=tender.get("tax_method", "general"),
                management_rate=pp.get("management_rate"), profit_rate=pp.get("profit_rate"),
                general_measure_rates=pp.get("general_measure_rates", {}),
                special_measures=[sd_engine.SpecialMeasure(x["name"], _d(x["amount"]), x.get("all_in", False))
                                  for x in pp.get("special_measures", [])],
                service_owner_material_rate=pp.get("service_owner_material_rate"),
                service_subcontract_rate=pp.get("service_subcontract_rate"),
                service_direct_lump=_d(pp.get("service_direct_lump")), daywork=_d(pp.get("daywork")),
                other=_d(pp.get("other")), safety_rates=pp.get("safety_rates", {}),
                provisional_sum=_d(tender.get("provisional_sum")),
                specialty_provisional=_d(tender.get("specialty_provisional")),
                owner_material=_d(tender.get("owner_material")), quality_level=tender.get("quality_level"),
                tender_rate_overrides=tender.get("rate_overrides", {}))
            result = sd_engine.compute(items, params, rule_set.data)
        else:
            params = manual_engine.Params(
                fee_base=pp.get("fee_base", "direct"), management_rate=_d(pp.get("management_rate")),
                profit_rate=_d(pp.get("profit_rate")),
                measures=[manual_engine.NamedAmount(x["name"], _d(x["amount"])) for x in pp.get("measures", [])],
                others=[manual_engine.NamedAmount(x["name"], _d(x["amount"])) for x in pp.get("others", [])],
                tender_amounts=[manual_engine.NamedAmount(x["name"], _d(x["amount"]))
                                for x in tender.get("tender_amounts", [])],
                tax_rate=None if tender.get("tax_rate") is None else _d(tender["tax_rate"]))
            result = manual_engine.compute(items, params)
    except EngineError as exc:
        raise ServiceError(str(exc)) from None
    if unpriced:
        result.warnings.append(f"有 {len(unpriced)} 个清单项尚未组价，综合单价为 0：" + "、".join(unpriced[:10]))

    payload = result_dict(result)
    inputs = json.dumps({
        "boq": version.content_hash, "tender": tender, "params": pp, "category": unit.fee_category,
        "grade": unit.grade, "rule": result.rule_code,
        "lines": [[l.boq_seq, l.name, str(l.content), str(l.labor), str(l.material), str(l.machine)] for l in lines],
    }, ensure_ascii=False, sort_keys=True)
    run = m.CalcRun(unit_project_id=unit.id, boq_version_id=version.id, pricing_system=result.pricing_system,
                    rule_code=result.rule_code, input_hash=hashlib.sha256(inputs.encode()).hexdigest(),
                    result=payload, total=result.total, created_by=user_id)
    session.add(run)
    audit(session, user_id, "calc.run", f"unit:{unit.id}", total=str(result.total), input_hash=run.input_hash)
    session.commit()
    return run
