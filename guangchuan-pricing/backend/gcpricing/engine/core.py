"""计价引擎公共类型。纯计算，不依赖数据库和 Web 框架，全程 Decimal。"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

D = Decimal
ZERO = D(0)


class EngineError(ValueError):
    """输入不满足计价规则（例如锁定费率低于下限）。"""


def dec(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        raise EngineError("金额和数量不接受浮点数，请传入字符串或 Decimal")
    return D(str(value))


def rnd(value: Decimal, places: int) -> Decimal:
    return value.quantize(D(1).scaleb(-places), rounding=ROUND_HALF_UP)


def pct(rate) -> Decimal:
    return dec(rate) / D(100)


@dataclass(frozen=True)
class Line:
    """组价子目：每清单计量单位的含量，以及子目单位人工、材料、机具费。"""

    name: str
    content: Decimal
    labor: Decimal = ZERO
    material: Decimal = ZERO
    machine: Decimal = ZERO


@dataclass(frozen=True)
class Item:
    boq_item_id: int
    quantity: Decimal
    lines: tuple[Line, ...]


@dataclass
class ItemResult:
    boq_item_id: int
    quantity: Decimal
    labor: Decimal
    material: Decimal
    machine: Decimal
    management: Decimal
    profit: Decimal
    unit_price: Decimal
    amount: Decimal

    @property
    def labor_amount(self) -> Decimal:
        return self.labor * self.quantity

    @property
    def machine_amount(self) -> Decimal:
        return self.machine * self.quantity


@dataclass
class Fee:
    """一行费用及其计算轨迹。"""

    code: str
    name: str
    amount: Decimal
    formula: str = ""
    base: Decimal | None = None
    rate: Decimal | None = None
    locked: bool = False
    basis: str = ""
    children: list["Fee"] = field(default_factory=list)


@dataclass
class Result:
    pricing_system: str
    rule_code: str | None
    items: list[ItemResult]
    fees: list[Fee]
    total: Decimal
    warnings: list[str] = field(default_factory=list)

    def fee(self, code: str) -> Fee:
        def walk(fees):
            for f in fees:
                if f.code == code:
                    return f
                found = walk(f.children)
                if found:
                    return found
            return None

        found = walk(self.fees)
        if not found:
            raise KeyError(code)
        return found


def direct_costs(item: Item, places: int) -> tuple[Decimal, Decimal, Decimal]:
    labor = rnd(sum((l.content * l.labor for l in item.lines), ZERO), places)
    material = rnd(sum((l.content * l.material for l in item.lines), ZERO), places)
    machine = rnd(sum((l.content * l.machine for l in item.lines), ZERO), places)
    return labor, material, machine
