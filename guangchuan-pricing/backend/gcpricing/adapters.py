"""专业适配器。每个专业一个适配器类，可独立升级；通过注册表登记并同步到 profession_adapters 表。"""
from __future__ import annotations

from .catalog import PRICING_SYSTEMS, PROFESSIONS


class NotAvailable(RuntimeError):
    """该专业的这项能力尚未开发或缺少数据。"""


class ProfessionAdapter:
    code: str = ""
    name: str = ""
    pricing_system: str = ""
    version: str = "0.1.0"
    # 使用山东省建设工程计价体系时，本专业可选的费用规则工程类别
    fee_categories: tuple[str, ...] = ()

    def engine_code(self) -> str:
        """实际执行计算的引擎：计价体系的规则引擎未开发时退回人工组价引擎。"""
        return self.pricing_system if PRICING_SYSTEMS[self.pricing_system][1] else "manual"

    def parse_features(self, item):
        raise NotAvailable(f"{self.name}：项目特征解析尚未开发")

    def retrieve_quota_candidates(self, item, quota_version_id):
        raise NotAvailable(f"{self.name}：定额检索尚未开发")

    def special_checks(self, result) -> list[str]:
        return []


_MUNICIPAL = ("road", "bridge", "tunnel", "water_supply", "drainage", "gas", "heating", "water_treatment", "waste",
              "street_light", "utility_tunnel", "maint_road", "maint_pipe")
_FEE_CATEGORIES = {
    "building": ("building", "structure", "earthwork", "piling", "decoration", "repair_building", "heritage_repair",
                 "antique"),
    "municipal": _MUNICIPAL,
    "installation": ("installation", "repair_installation"),
    "steel": ("building", "structure", "installation"),
    "landscaping": ("landscaping",),
    "curtain_special": ("decoration", "building", "structure", "earthwork", "piling", "installation",
                        "repair_building", "repair_installation"),
    "environmental": ("water_treatment", "waste", "building", "structure", "earthwork", "installation") + _MUNICIPAL[:7],
}

REGISTRY: dict[str, ProfessionAdapter] = {}


def register(cls: type[ProfessionAdapter]) -> type[ProfessionAdapter]:
    REGISTRY[cls.code] = cls()
    return cls


for _code, _name, _system, _subs in PROFESSIONS:
    register(type(
        f"{_code.title().replace('_', '')}Adapter",
        (ProfessionAdapter,),
        {"code": _code, "name": _name, "pricing_system": _system,
         "fee_categories": tuple(dict.fromkeys(_FEE_CATEGORIES.get(_code, ())))},
    ))


def get(code: str) -> ProfessionAdapter:
    try:
        return REGISTRY[code]
    except KeyError:
        raise NotAvailable(f"专业 {code} 没有注册适配器") from None
