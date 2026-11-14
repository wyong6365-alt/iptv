"""初始化目录数据。可重复执行。"""
from __future__ import annotations

import json
from datetime import date
from importlib import resources

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import adapters, models as m
from .catalog import PROFESSIONS, SD_NOTICE_URL, SD_QUOTAS_2025, SHANDONG, SHANDONG_CITIES


def _get(session: Session, model, **by):
    return session.scalar(select(model).filter_by(**by))


def load_rule_file(name: str) -> dict:
    return json.loads(resources.files("gcpricing.data").joinpath(name).read_text(encoding="utf-8"))


def run(session: Session) -> None:
    china = _get(session, m.Region, code="100000") or m.Region(code="100000", name="中国", level="country")
    session.add(china)
    session.flush()
    sd = _get(session, m.Region, code=SHANDONG[0]) or m.Region(
        code=SHANDONG[0], name=SHANDONG[1], level="province", parent_id=china.id)
    session.add(sd)
    session.flush()
    for code, name in SHANDONG_CITIES:
        if not _get(session, m.Region, code=code):
            session.add(m.Region(code=code, name=name, level="city", parent_id=sd.id))

    by_code: dict[str, m.Profession] = {}
    for sort, (code, name, _system, subs) in enumerate(PROFESSIONS, start=1):
        prof = _get(session, m.Profession, code=code)
        if not prof:
            prof = m.Profession(code=code, name=name, sort=sort)
            session.add(prof)
            session.flush()
            for i, sub in enumerate(subs, start=1):
                session.add(m.ProfessionSubcategory(profession_id=prof.id, code=f"{code}-{i:02d}", name=sub, sort=i))
        by_code[code] = prof
        adapter = adapters.REGISTRY.get(code)
        row = _get(session, m.ProfessionAdapter, profession_id=prof.id)
        if adapter and not row:
            session.add(m.ProfessionAdapter(profession_id=prof.id, adapter_code=adapter.code,
                                            pricing_system=adapter.pricing_system, version=adapter.version,
                                            status="registered"))
        elif adapter and row:
            row.version, row.pricing_system = adapter.version, adapter.pricing_system

    gb = _get(session, m.PricingStandard, code="GB/T 50500-2024")
    if not gb:
        session.add(m.PricingStandard(
            code="GB/T 50500-2024", name="建设工程工程量清单计价标准", issuer="住房和城乡建设部", region_id=china.id,
            note="执行日期未在已取得的官方文件中载明，待核实"))
    std = _get(session, m.PricingStandard, code="SD-FEE-2025")
    if not std:
        std = m.PricingStandard(
            code="SD-FEE-2025", name="山东省建设工程费用项目组成及计算规则", issuer="山东省住房和城乡建设厅",
            doc_no="鲁建标字〔2025〕7号", region_id=sd.id, source_url=SD_NOTICE_URL,
            note="执行日期同 GB/T 50500-2024；发文日期 2025-08-29。自执行之日起鲁建标字〔2022〕7号费用规则停止使用")
        session.add(std)
        session.flush()

    rules = load_rule_file("sd_fee_rules_2025.json")
    rule_set = _get(session, m.FeeRuleSet, code=rules["code"])
    if not rule_set:
        rule_set = m.FeeRuleSet(code=rules["code"], name=rules["name"], pricing_system=rules["pricing_system"],
                                pricing_standard_id=std.id, data=rules)
        session.add(rule_set)
        session.flush()

    for code, name, professions in SD_QUOTAS_2025:
        qv = _get(session, m.QuotaVersion, code=code)
        if not qv:
            qv = m.QuotaVersion(
                code=code, name=name, issuer="山东省住房和城乡建设厅", version="2025",
                effective_from=date(2025, 11, 1), region_id=sd.id,
                source="鲁建标字〔2025〕7号发布，在省住房城乡建设厅门户网站“标准造价”专栏公开；定额正文尚未取得",
                import_status="not_imported")
            session.add(qv)
            session.flush()
        for pcode in professions:
            if not _get(session, m.ProfessionQuotaMapping, profession_id=by_code[pcode].id, quota_version_id=qv.id):
                session.add(m.ProfessionQuotaMapping(profession_id=by_code[pcode].id, quota_version_id=qv.id,
                                                     region_id=sd.id))

    for code, adapter in adapters.REGISTRY.items():
        if adapter.pricing_system == rules["pricing_system"]:
            if not _get(session, m.ProfessionFeeRuleMapping, profession_id=by_code[code].id,
                        fee_rule_set_id=rule_set.id):
                session.add(m.ProfessionFeeRuleMapping(profession_id=by_code[code].id, fee_rule_set_id=rule_set.id,
                                                       region_id=sd.id))
    session.commit()
