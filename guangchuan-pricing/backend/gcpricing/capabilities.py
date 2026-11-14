"""专业能力状态：由证据计算得出，不提供手工改为“可用”的入口。"""
from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from . import adapters, models as m
from .catalog import CAPABILITIES, PRICING_SYSTEMS
from .models import now

OK, PENDING, MISSING, UNBUILT, UNVERIFIED, NO = "可用", "已录入待复核", "数据缺失", "未开发", "未验证", "不可用"

# 平台功能是否已经开发完成。功能上线并通过测试后在此处改为 True。
FEATURES = {
    "boq_file_recognition": True,  # 仅 Excel（.xlsx）；PDF、扫描件、Word 未开发
    "resource_prices": False,
    "ai_matching": False,
    "review": False,
    "export": False,
}
VALIDATION_SAMPLES_REQUIRED = 3


def _profession_status(session: Session, prof: m.Profession) -> dict[str, tuple[str, str]]:
    s: dict[str, tuple[str, str]] = {}
    adapter = adapters.REGISTRY.get(prof.code)
    registered = adapter is not None and session.scalar(
        select(m.ProfessionAdapter).filter_by(profession_id=prof.id)) is not None
    s["established"] = (OK, f"适配器 {adapter.code} v{adapter.version}") if registered else (NO, "适配器未注册")

    s["boq_recognition"] = (UNVERIFIED, "Excel 清单识别已开发，PDF 和扫描件未开发；尚无真实清单样本核对") if FEATURES["boq_file_recognition"] else (
        UNBUILT, "文件识别未开发；可导入结构化清单数据")

    quotas = session.scalars(
        select(m.QuotaVersion).join(m.ProfessionQuotaMapping, m.ProfessionQuotaMapping.quota_version_id == m.QuotaVersion.id)
        .where(m.ProfessionQuotaMapping.profession_id == prof.id)).all()
    usable = [q for q in quotas if q.import_status == "available"]
    if usable:
        s["quota_data"] = (OK, "、".join(q.name for q in usable))
    elif quotas:
        s["quota_data"] = (MISSING, "已登记未导入：" + "、".join(q.name for q in quotas))
    else:
        s["quota_data"] = (MISSING, "未登记任何定额版本")

    rule_sets = session.scalars(
        select(m.FeeRuleSet).join(m.ProfessionFeeRuleMapping, m.ProfessionFeeRuleMapping.fee_rule_set_id == m.FeeRuleSet.id)
        .where(m.ProfessionFeeRuleMapping.profession_id == prof.id)).all()
    if any(r.reviewed_by for r in rule_sets):
        s["pricing_rules"] = (OK, "、".join(r.code for r in rule_sets if r.reviewed_by))
    elif rule_sets:
        s["pricing_rules"] = (PENDING, "、".join(r.code for r in rule_sets) + " 已转录，待造价人员对照原件复核")
    else:
        s["pricing_rules"] = (MISSING, "未录入费用规则")

    s["resource_prices"] = (MISSING, "未导入价格数据") if FEATURES["resource_prices"] else (UNBUILT, "价格库未开发")

    if not FEATURES["ai_matching"]:
        s["ai_matching"] = (UNBUILT, "匹配引擎未开发")
    elif s["quota_data"][0] != OK:
        s["ai_matching"] = (NO, "缺少定额数据")
    else:
        s["ai_matching"] = (UNVERIFIED, "")

    deps = [s[k][0] for k in ("quota_data", "pricing_rules", "resource_prices", "ai_matching")]
    s["auto_pricing"] = (UNVERIFIED, "") if all(d == OK for d in deps) else (NO, "依赖的定额、规则、价格或匹配能力未就绪")

    if registered:
        engine = adapter.engine_code()
        label = PRICING_SYSTEMS[engine][0]
        note = f"计算引擎：{label}" + ("" if engine != "manual" else "；费率由人工输入，结果标注为非规则依据")
        s["manual_pricing"] = (OK, note)
    else:
        s["manual_pricing"] = (NO, "适配器未注册")

    s["review"] = (OK, "") if FEATURES["review"] else (UNBUILT, "审核模块未开发")
    s["export"] = (OK, "") if FEATURES["export"] else (UNBUILT, "导出模块未开发")

    passed = session.scalar(select(func.count()).select_from(m.ProfessionTestCase)
                            .filter_by(profession_id=prof.id, status="passed"))
    s["real_validation"] = (OK if passed >= VALIDATION_SAMPLES_REQUIRED else UNVERIFIED,
                            f"通过样本 {passed}/{VALIDATION_SAMPLES_REQUIRED}")
    return s


def overall(s: dict[str, tuple[str, str]]) -> str:
    st = {k: v[0] for k, v in s.items()}
    if st["established"] != OK:
        return "暂不支持"
    first_ten = [k for k, _ in CAPABILITIES if k != "real_validation"]
    if all(st[k] == OK for k in first_ten) and st["real_validation"] == OK:
        return "已开发并通过真实项目验证"
    if st["auto_pricing"] in (OK, UNVERIFIED) and st["ai_matching"] == OK:
        return "支持自动组价但需人工复核"
    if st["ai_matching"] == OK:
        return "支持AI辅助组价"
    if st["quota_data"] == MISSING and st["pricing_rules"] == MISSING:
        return "支持人工组价（数据缺失）"
    if st["quota_data"] == OK and st["pricing_rules"] == OK:
        return "已开发但仍需完善数据"
    return "支持人工组价（数据待完善）"


def compute(session: Session, region_code: str = "370000") -> list[dict]:
    region = session.scalar(select(m.Region).filter_by(code=region_code))
    session.execute(delete(m.ProfessionCapability).where(m.ProfessionCapability.region_id == region.id))
    matrix = []
    for prof in session.scalars(select(m.Profession).order_by(m.Profession.sort)):
        status = _profession_status(session, prof)
        for key, (value, evidence) in status.items():
            session.add(m.ProfessionCapability(profession_id=prof.id, region_id=region.id, capability=key,
                                               status=value, evidence=evidence, computed_at=now()))
        matrix.append({
            "profession": prof.code, "name": prof.name, "overall": overall(status),
            "capabilities": {k: {"status": v, "evidence": e} for k, (v, e) in status.items()},
        })
    session.commit()
    return matrix
