"""山东省建设工程计价体系引擎（招投标阶段）。

依据：《山东省建设工程费用项目组成及计算规则》（鲁建标字〔2025〕7号）第二章“一、工程招投标阶段”。
费率和计费基础全部来自规则数据（data/sd_fee_rules_2025.json），本模块不写死任何费率。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from .core import ZERO, EngineError, Fee, Item, ItemResult, Result, dec, direct_costs, pct, rnd

CODE = "sd_construction"

GENERAL_MEASURE_NAMES = {
    "night": "夜间施工增加费",
    "secondary_transport": "二次搬运费",
    "winter_rain": "冬雨季施工增加费",
    "protection": "已完工程及设备保护费",
    "existing_protection": "既有建（构）筑物及设施保护",
    "positioning": "工程定位复测费",
    "pipeline_crossing": "地下管线交叉处理费",
}
SAFETY_NAMES = {
    "safety_production": "安全生产费",
    "environment": "环境保护费",
    "civilized": "文明施工费",
    "temporary": "临时设施费",
}


@dataclass(frozen=True)
class SpecialMeasure:
    """专业措施项目。all_in=True 表示包含增值税的全费用价格（市政工程智慧工地建设费），直接汇总至合计。"""

    name: str
    amount: Decimal
    all_in: bool = False


@dataclass
class Params:
    category: str  # 规则数据中的工程类别键，如 building / road
    tax_method: str = "general"  # general 一般计税 / simple 简易计税
    grade: str | None = None  # 工程类别 I / II / III，仅分级专业需要
    # 可竞争（规则仅供参考）：不填则取规则参考值
    management_rate: Decimal | None = None
    profit_rate: Decimal | None = None
    general_measure_rates: dict[str, Decimal] = field(default_factory=dict)
    special_measures: list[SpecialMeasure] = field(default_factory=list)
    service_owner_material_rate: Decimal | None = None
    service_subcontract_rate: Decimal | None = None
    service_direct_lump: Decimal = ZERO  # 发包人直接发包的专业工程，按合同约定以“项”计算
    daywork: Decimal = ZERO
    other: Decimal = ZERO
    # 费率不得低于规则下限：不填取下限
    safety_rates: dict[str, Decimal] = field(default_factory=dict)
    # 招标文件给定，投标人不得改动
    provisional_sum: Decimal = ZERO
    specialty_provisional: Decimal = ZERO
    owner_material: Decimal = ZERO  # A.1 发包人提供的材料费
    quality_level: str | None = None  # national / provincial / municipal
    # 招标文件对锁定费率的明确规定（须附出处，由上层校验）
    tender_rate_overrides: dict[str, Decimal] = field(default_factory=dict)


def _rates(rules: dict, p: Params) -> dict:
    try:
        cat = rules["categories"][p.category]
    except KeyError:
        raise EngineError(f"规则 {rules['code']} 中没有工程类别 {p.category}") from None
    try:
        tm = rules["tax_methods"][p.tax_method]
    except KeyError:
        raise EngineError(f"未知计税方法 {p.tax_method}") from None
    mp = tm["management_profit"][p.category]
    if cat["graded"]:
        if p.grade not in ("I", "II", "III"):
            raise EngineError(f"{cat['name']}需要指定工程类别（I、II、III）")
        management, profit = mp["management"][p.grade], mp["profit"][p.grade]
    else:
        management, profit = mp["management"], mp["profit"]
    as_key = cat["measure_rates_as"]
    group = cat["other_fee_group"]
    return {
        "cat": cat,
        "management": dec(management),
        "profit": dec(profit),
        "general_measures": {k: dec(v) for k, v in tm["general_measures"][as_key].items() if v is not None},
        "safety": {k: dec(v) for k, v in tm["safety_measures"][as_key].items()},
        "injury": dec(tm["injury_insurance"][group]),
        "quality": {lvl: dec(v[group]) for lvl, v in tm["quality_bonus"].items()},
        "vat": dec(tm["vat"]),
    }


def compute(items: list[Item], p: Params, rules: dict) -> Result:
    r = _rates(rules, p)
    up = rules["rounding"]["unit_price_places"]
    ap = rules["rounding"]["amount_places"]
    warnings: list[str] = []
    if rules.get("review", {}).get("status") != "reviewed":
        warnings.append("费用规则数据尚未经造价人员对照原件复核签字")

    uses_machine = r["cat"]["fee_base"] == "labor_machine"
    base_label = "人工费+施工机具使用费" if uses_machine else "人工费"
    m_rate = r["management"] if p.management_rate is None else dec(p.management_rate)
    pr_rate = r["profit"] if p.profit_rate is None else dec(p.profit_rate)

    # 一、分部分项工程费
    results: list[ItemResult] = []
    for it in items:
        labor, material, machine = direct_costs(it, up)
        base1 = labor + machine if uses_machine else labor
        management = rnd(base1 * pct(m_rate), up)
        profit = rnd(base1 * pct(pr_rate), up)
        unit_price = labor + material + machine + management + profit
        results.append(
            ItemResult(it.boq_item_id, it.quantity, labor, material, machine, management, profit,
                       unit_price, rnd(unit_price * it.quantity, ap))
        )
    part1 = sum((x.amount for x in results), ZERO)
    base2 = rnd(sum((x.labor_amount + (x.machine_amount if uses_machine else ZERO) for x in results), ZERO), ap)

    # 二、措施项目费
    unknown = set(p.general_measure_rates) - set(r["general_measures"])
    if unknown:
        raise EngineError(f"该工程类别没有通用措施项目：{sorted(unknown)}")
    general_children = []
    for key, ref in r["general_measures"].items():
        rate = dec(p.general_measure_rates.get(key, ref))
        general_children.append(
            Fee(f"2.1.{key}", GENERAL_MEASURE_NAMES[key], rnd(base2 * pct(rate), ap),
                f"计费基础2（{base_label}合计）×费率", base2, rate, basis="第三章一（参考费率）")
        )
    f21 = Fee("2.1", "通用措施项目费", sum((c.amount for c in general_children), ZERO), children=general_children)

    special_in = [m for m in p.special_measures if not m.all_in]
    special_all_in = [m for m in p.special_measures if m.all_in]
    f22 = Fee("2.2", "专业措施项目费", sum((rnd(dec(m.amount), ap) for m in special_in), ZERO),
              "按各专业工程措施项目计算方法计算",
              children=[Fee(f"2.2.{i + 1}", m.name, rnd(dec(m.amount), ap)) for i, m in enumerate(special_in)])

    owner_material = rnd(dec(p.owner_material), ap)
    safety_base = part1 + f21.amount + f22.amount + owner_material
    unknown = set(p.safety_rates) - set(r["safety"])
    if unknown:
        raise EngineError(f"未知安全文明措施费项目：{sorted(unknown)}")
    safety_children = []
    for key, floor in r["safety"].items():
        floor = dec(p.tender_rate_overrides.get(f"safety.{key}", floor))
        rate = dec(p.safety_rates.get(key, floor))
        if rate < floor:
            raise EngineError(f"{SAFETY_NAMES[key]}费率 {rate}% 低于规定下限 {floor}%")
        safety_children.append(
            Fee(f"2.3.{key}", SAFETY_NAMES[key], rnd(safety_base * pct(rate), ap),
                "［（一）＋2.1＋2.2＋A.1］×费率", safety_base, rate, locked=True,
                basis="第二章说明（四）：费率不低于第三章规定的费率")
        )
    f23 = Fee("2.3", "安全文明措施费", sum((c.amount for c in safety_children), ZERO), locked=True,
              children=safety_children)
    part2 = f21.amount + f22.amount + f23.amount

    # 三、其他项目费
    f31 = Fee("3.1", "暂列金额", rnd(dec(p.provisional_sum), ap), "招标文件给定", locked=True,
              basis="第一章三（一）")
    f32 = Fee("3.2", "专业工程暂估价", rnd(dec(p.specialty_provisional), ap), "招标文件给定（含增值税）",
              locked=True, basis="第一章三（二）")
    f33 = Fee("3.3", "计日工", rnd(dec(p.daywork), ap))
    svc = rules["general_contract_service"]
    om_rate = dec(svc["owner_material"] if p.service_owner_material_rate is None else p.service_owner_material_rate)
    sub_rate = dec(svc["subcontract"] if p.service_subcontract_rate is None else p.service_subcontract_rate)
    svc_children = [
        Fee("3.4.1", "发包人提供材料", rnd(owner_material * pct(om_rate), ap), "发包人提供的材料费×费率",
            owner_material, om_rate, basis="第三章三（二）（参考费率）"),
        Fee("3.4.2", "合同范围内专业分包工程", rnd(f32.amount * pct(sub_rate), ap), "专业工程暂估价×费率",
            f32.amount, sub_rate, basis="第三章三（二）（参考费率）"),
        Fee("3.4.3", "发包人直接发包的专业工程", rnd(dec(p.service_direct_lump), ap), "按合同约定以“项”计算"),
    ]
    f34 = Fee("3.4", "总承包服务费", sum((c.amount for c in svc_children), ZERO), children=svc_children)

    injury_rate = dec(p.tender_rate_overrides.get("injury_insurance", r["injury"]))
    injury_base = part1 + part2 + f31.amount + f32.amount + f33.amount + f34.amount
    f35 = Fee("3.5", "建设项目工伤保险", rnd(injury_base * pct(injury_rate), ap),
              "［（一）+（二）＋3.1＋3.2＋3.3＋3.4］×费率", injury_base, injury_rate, locked=True,
              basis="第三章三（一）")
    if p.quality_level is None:
        f36 = Fee("3.6", "优质优价费", ZERO, "招标文件未提出创建目标", locked=True, basis="第一章三（六）")
    else:
        if p.quality_level not in r["quality"]:
            raise EngineError(f"未知创建目标 {p.quality_level}")
        q_rate = dec(p.tender_rate_overrides.get("quality_bonus", r["quality"][p.quality_level]))
        q_base = part1 + part2 + f31.amount + f33.amount + f34.amount
        f36 = Fee("3.6", "优质优价费", rnd(q_base * pct(q_rate), ap),
                  "［（一）+（二）＋3.1＋3.3＋3.4］×费率", q_base, q_rate, locked=True, basis="第一章三（六）")
    f37 = Fee("3.7", "其他", rnd(dec(p.other), ap), "按合同约定计算")
    others = [f31, f32, f33, f34, f35, f36, f37]
    part3 = sum((f.amount for f in others), ZERO)

    # 四、增值税
    vat_rate = dec(p.tender_rate_overrides.get("vat", r["vat"]))
    vat_base = part1 + part2 + part3 - f32.amount
    f4 = Fee("4", "增值税", rnd(vat_base * pct(vat_rate), ap), "［（一）+（二）+（三）-3.2］×税率",
             vat_base, vat_rate, locked=True, basis="第三章四")

    fees = [
        Fee("1", "分部分项工程费", part1, "∑（综合单价×分部分项工程量）"),
        Fee("2", "措施项目费", part2, "2.1＋2.2＋2.3", children=[f21, f22, f23]),
        Fee("3", "其他项目费", part3, "3.1＋3.2＋…＋3.7", children=others),
        f4,
    ]
    total = part1 + part2 + part3 + f4.amount
    if special_all_in:
        extra = Fee("X", "全费用措施项目（已含增值税，直接汇总至合计）",
                    sum((rnd(dec(m.amount), ap) for m in special_all_in), ZERO),
                    basis="第二章招投标阶段计算程序说明 5",
                    children=[Fee(f"X.{i + 1}", m.name, rnd(dec(m.amount), ap)) for i, m in enumerate(special_all_in)])
        fees.append(extra)
        total += extra.amount
        warnings.append("全费用措施项目未计入安全文明措施费、工伤保险、优质优价费和增值税的计算基数，此处理方式需造价人员确认")
    fees.append(Fee("A.1", "发包人提供的材料费（不计入合计）", owner_material, "作为 2.3 和 3.4 的计算基础"))
    return Result(CODE, rules["code"], results, fees, total, warnings)
