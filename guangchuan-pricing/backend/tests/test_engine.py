"""计价引擎测试。期望值为按费用规则第二章手工验算的结果。"""
from decimal import Decimal as D

import pytest

from gcpricing.engine import manual, sd_construction as sd
from gcpricing.engine.core import EngineError, Item, Line
from gcpricing.seed import load_rule_file

RULES = load_rule_file("sd_fee_rules_2025.json")


def one_item():
    return [Item(1, D("100"), (Line("砌体", D("1"), D("120.00"), D("300.00"), D("10.00")),))]


def test_building_tender_stage_matches_hand_calculation():
    r = sd.compute(one_item(), sd.Params(category="building", grade="III", provisional_sum=D("5000"),
                                         specialty_provisional=D("10000")), RULES)
    item = r.items[0]
    # 管理费 120×23.27%=27.92，利润 120×13.59%=16.31
    assert (item.management, item.profit, item.unit_price) == (D("27.92"), D("16.31"), D("474.23"))
    assert r.fee("1").amount == D("47423.00")
    # 计费基础2=人工费合计 12000；通用措施 2.62+2.24+2.99+0.56=8.41%
    assert r.fee("2.1").amount == D("1009.20")
    # 安全文明：(47423+1009.20)×(3.49+0.57+0.66+0.92)% 各项分别取整
    assert r.fee("2.3").amount == D("2731.57")
    assert r.fee("3.4").amount == D("300.00")  # 暂估价 10000×3%
    assert r.fee("3.5").amount == D("51.18")  # 66463.77×0.077%
    assert r.fee("4").amount == D("5086.35")  # (一+二+三-3.2)×9%
    assert r.total == D("71601.30")


def test_municipal_uses_labor_plus_machine_as_base():
    r = sd.compute(one_item(), sd.Params(category="road"), RULES)
    # 计费基础1=人工+机具=130；管理费 19.35%=25.16（25.155 四舍五入），利润 10.36%=13.47
    assert (r.items[0].management, r.items[0].profit) == (D("25.16"), D("13.47"))
    assert r.fee("2.1.night").base == D("13000.00")
    assert r.fee("3.5").rate == D("0.083")


def test_fee_groups_for_injury_insurance_follow_official_table():
    assert sd.compute(one_item(), sd.Params(category="installation"), RULES).fee("3.5").rate == D("0.077")
    assert sd.compute(one_item(), sd.Params(category="landscaping"), RULES).fee("3.5").rate == D("0.083")


def test_safety_rate_below_floor_is_rejected_and_above_is_allowed():
    with pytest.raises(EngineError, match="低于规定下限"):
        sd.compute(one_item(), sd.Params(category="building", grade="I", safety_rates={"safety_production": D("3.0")}), RULES)
    r = sd.compute(one_item(), sd.Params(category="building", grade="I", safety_rates={"safety_production": D("4")}), RULES)
    assert r.fee("2.3.safety_production").rate == D("4")


def test_competitive_changes_do_not_touch_locked_rates():
    base = sd.compute(one_item(), sd.Params(category="building", grade="II"), RULES)
    cut = sd.compute(one_item(), sd.Params(category="building", grade="II", management_rate=D("10"),
                                           profit_rate=D("0"), general_measure_rates={"night": D("0")}), RULES)
    assert cut.total < base.total
    for code in ("2.3.safety_production", "2.3.temporary", "3.5", "4"):
        assert cut.fee(code).rate == base.fee(code).rate and cut.fee(code).locked


def test_simple_tax_method_uses_its_own_rates():
    r = sd.compute(one_item(), sd.Params(category="building", grade="III", tax_method="simple"), RULES)
    assert r.fee("4").rate == D("3")
    assert r.items[0].management == D("27.71")  # 120×23.09%


def test_graded_category_requires_grade_and_unknown_inputs_fail():
    with pytest.raises(EngineError):
        sd.compute(one_item(), sd.Params(category="building"), RULES)
    with pytest.raises(EngineError):
        sd.compute(one_item(), sd.Params(category="road", general_measure_rates={"nope": D("1")}), RULES)
    with pytest.raises(EngineError):
        sd.compute(one_item(), sd.Params(category="nope"), RULES)


def test_quality_bonus_only_when_tender_sets_a_target():
    none = sd.compute(one_item(), sd.Params(category="building", grade="III"), RULES)
    prov = sd.compute(one_item(), sd.Params(category="building", grade="III", quality_level="provincial"), RULES)
    assert none.fee("3.6").amount == 0
    assert prov.fee("3.6").rate == D("1.06") and prov.fee("3.6").amount > 0


def test_floats_are_refused():
    with pytest.raises(EngineError):
        sd.compute(one_item(), sd.Params(category="road", daywork=1.5), RULES)


def test_rule_data_is_complete_for_every_category():
    for key, cat in RULES["categories"].items():
        for grade in (("I", "II", "III") if cat["graded"] else (None,)):
            for tax in ("general", "simple"):
                r = sd.compute(one_item(), sd.Params(category=key, grade=grade, tax_method=tax), RULES)
                assert r.total > 0, key


def test_manual_engine_marks_result_as_not_rule_based():
    r = manual.compute(one_item(), manual.Params(management_rate=D("5"), profit_rate=D("3"), tax_rate=D("9"),
                                                 tender_amounts=[manual.NamedAmount("暂列金额", D("1000"))]))
    # 直接费 430，管理费 21.50，利润 12.90，单价 464.40
    assert r.items[0].unit_price == D("464.40")
    assert r.total == D("51709.60")  # (46440+1000)×1.09
    assert r.rule_code is None and "尚未录入计价规则" in r.warnings[0]
