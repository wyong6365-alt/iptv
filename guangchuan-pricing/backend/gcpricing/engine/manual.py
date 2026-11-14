"""人工组价引擎：用于尚未录入计价规则的计价体系。

所有费率由造价人员输入，结果标注为“非规则依据”。招标文件给定的金额和税率仍然锁定。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from .core import ZERO, EngineError, Fee, Item, ItemResult, Result, dec, direct_costs, pct, rnd

CODE = "manual"
BASES = {"labor", "labor_machine", "direct"}


@dataclass(frozen=True)
class NamedAmount:
    name: str
    amount: Decimal


@dataclass
class Params:
    fee_base: str = "direct"
    management_rate: Decimal = ZERO
    profit_rate: Decimal = ZERO
    measures: list[NamedAmount] = field(default_factory=list)
    others: list[NamedAmount] = field(default_factory=list)
    # 招标文件给定，锁定
    tender_amounts: list[NamedAmount] = field(default_factory=list)
    tax_rate: Decimal | None = None
    unit_price_places: int = 2
    amount_places: int = 2


def compute(items: list[Item], p: Params) -> Result:
    if p.fee_base not in BASES:
        raise EngineError(f"计费基础须为 {sorted(BASES)} 之一")
    up, ap = p.unit_price_places, p.amount_places
    results = []
    for it in items:
        labor, material, machine = direct_costs(it, up)
        base = {"labor": labor, "labor_machine": labor + machine, "direct": labor + material + machine}[p.fee_base]
        management = rnd(base * pct(p.management_rate), up)
        profit = rnd(base * pct(p.profit_rate), up)
        unit_price = labor + material + machine + management + profit
        results.append(ItemResult(it.boq_item_id, it.quantity, labor, material, machine, management, profit,
                                  unit_price, rnd(unit_price * it.quantity, ap)))
    part1 = sum((x.amount for x in results), ZERO)

    def group(code, name, rows, locked=False):
        children = [Fee(f"{code}.{i + 1}", r.name, rnd(dec(r.amount), ap), locked=locked,
                        basis="招标文件给定" if locked else "人工输入")
                    for i, r in enumerate(rows)]
        return Fee(code, name, sum((c.amount for c in children), ZERO), locked=locked, children=children)

    f2 = group("2", "措施项目费", p.measures)
    f3 = group("3", "其他项目费", p.others)
    f4 = group("4", "招标文件给定金额", p.tender_amounts, locked=True)
    warnings = ["该专业尚未录入计价规则，费率和取费程序为人工输入，结果不代表按适用计价依据计算"]
    pre_tax = part1 + f2.amount + f3.amount + f4.amount
    if p.tax_rate is None:
        tax = Fee("5", "税金", ZERO, "未提供税率", locked=True)
        warnings.append("未提供税率，税金按 0 计，合计为不含税金额")
    else:
        tax = Fee("5", "税金", rnd(pre_tax * pct(p.tax_rate), ap), "税前合计×税率", pre_tax, dec(p.tax_rate),
                  locked=True, basis="招标文件给定")
    fees = [Fee("1", "分部分项工程费", part1, "∑（综合单价×工程量）"), f2, f3, f4, tax]
    return Result(CODE, None, results, fees, pre_tax + tax.amount, warnings)
