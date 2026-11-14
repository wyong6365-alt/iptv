"""平台测试：全专业建项目、清单保护、锁定、数据隔离、能力矩阵。"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from gcpricing import models as m
from gcpricing.api import create_app
from gcpricing.catalog import PROFESSIONS

BOQ = [
    {"code": "010401001001", "name": "砖基础", "features": "M5 水泥砂浆", "unit": "m3", "quantity": "100"},
    {"code": "010401003001", "name": "实心砖墙", "features": "240 厚", "unit": "m3", "quantity": "50.5"},
]


@pytest.fixture()
def ctx(monkeypatch, tmp_path):
    monkeypatch.setenv("GC_DATA_DIR", str(tmp_path))
    app = create_app("sqlite:///:memory:")
    client = TestClient(app)
    token = client.post("/api/auth/setup", json={"username": "admin", "password": "admin-pass-1"}).json()["token"]
    client.headers["Authorization"] = f"Bearer {token}"
    client.app_state = app.state
    return client


def new_unit(client, profession="building", **extra):
    pid = client.post("/api/projects", json={"name": "测试项目"}).json()["id"]
    body = {"name": "单位工程", "profession": profession, **extra}
    resp = client.post(f"/api/projects/{pid}/units", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def building_unit(client):
    unit = new_unit(client, fee_category="building", grade="III")
    client.post(f"/api/units/{unit['id']}/boq", json={"kind": "original", "items": BOQ})
    return unit["id"]


def test_setup_closes_after_first_admin(ctx):
    assert ctx.post("/api/auth/setup", json={"username": "x", "password": "another-pass"}).status_code == 409
    assert TestClient(ctx.app).get("/api/professions").status_code == 401


def test_all_16_professions_have_adapters_and_can_create_units(ctx):
    profs = ctx.get("/api/professions").json()
    assert len(profs) == 16 and all(p["pricing_system"] for p in profs)
    assert all(len(p["subcategories"]) >= 6 for p in profs)
    for p in profs:
        extra = {}
        if p["fee_categories"]:
            cat = p["fee_categories"][0]
            extra = {"fee_category": cat["code"], **({"grade": "II"} if cat["graded"] else {})}
        unit = new_unit(ctx, p["code"], **extra)
        if p["pricing_system"]["engine"] == "manual":
            assert unit["notices"], p["code"]  # 明确提示数据缺口


def test_capability_matrix_is_honest(ctx):
    rows = {r["profession"]: r for r in ctx.get("/api/capabilities").json()["rows"]}
    assert len(rows) == len(PROFESSIONS)
    for row in rows.values():
        caps = row["capabilities"]
        assert caps["established"]["status"] == "可用"
        assert caps["manual_pricing"]["status"] == "可用"
        assert caps["quota_data"]["status"] == "数据缺失"
        assert caps["auto_pricing"]["status"] == "不可用"
        assert caps["real_validation"]["status"] == "未验证"
        assert "验证" not in row["overall"] and "自动" not in row["overall"]
    assert rows["building"]["capabilities"]["pricing_rules"]["status"] == "已录入待复核"
    assert rows["highway"]["capabilities"]["pricing_rules"]["status"] == "数据缺失"
    assert rows["highway"]["overall"] == "支持人工组价（数据缺失）"


def test_rule_review_signoff_changes_capability(ctx):
    assert ctx.post("/api/fee-rules/SD-FEE-2025/review").status_code == 200
    rows = {r["profession"]: r for r in ctx.get("/api/capabilities").json()["rows"]}
    assert rows["municipal"]["capabilities"]["pricing_rules"]["status"] == "可用"


def test_boq_is_read_only_even_for_raw_sql(ctx):
    building_unit(ctx)
    engine = ctx.app_state.engine
    for sql in ("UPDATE tender_boq_items SET quantity='999'", "DELETE FROM tender_boq_items",
                "UPDATE tender_boq_versions SET content_hash='x'", "DELETE FROM audit_log",
                "UPDATE audit_log SET action='x'"):
        with pytest.raises(DBAPIError, match="只读"):
            with engine.begin() as conn:
                conn.execute(text(sql))


def test_boq_versions_addendum_keeps_original(ctx):
    uid = building_unit(ctx)
    again = ctx.post(f"/api/units/{uid}/boq", json={"kind": "original", "items": BOQ})
    assert again.status_code == 422
    changed = [dict(BOQ[0], quantity="120"), BOQ[1]]
    assert ctx.post(f"/api/units/{uid}/boq", json={"kind": "addendum", "items": changed}).status_code == 422  # 无依据
    resp = ctx.post(f"/api/units/{uid}/boq", json={"kind": "addendum", "note": "补遗第1号", "items": changed}).json()
    assert resp["version_no"] == 2
    assert resp["diff"] == [{"change": "modified", "code": "010401001001", "fields": {"quantity": ["100", "120"]}}]
    boq = ctx.get(f"/api/units/{uid}/boq").json()
    assert boq["intact"] and boq["items"][0]["quantity"] == "120"
    with ctx.app_state.session_factory() as s:
        v1 = s.query(m.TenderBoqVersion).filter_by(version_no=1).one()
        assert str(v1.items[0].quantity) == "100"


def test_no_api_field_can_change_boq_or_locked_fees(ctx):
    uid = building_unit(ctx)
    for bad in ({"vat_rate": "0"}, {"injury_insurance_rate": "0"}, {"provisional_sum": "0"}, {"tax_method": "simple"}):
        assert ctx.put(f"/api/units/{uid}/pricing-params", json=bad).status_code == 422
    assert ctx.put(f"/api/units/{uid}/boq/1/lines", json=[{"name": "x", "content": "1", "quantity": "5",
                                                            "basis_note": "y"}]).status_code == 422
    # 招标要求必须注明出处
    assert ctx.put(f"/api/units/{uid}/tender-requirements", json={"provisional_sum": "5000"}).status_code == 422


def test_end_to_end_calculation_and_locks(ctx):
    uid = building_unit(ctx)
    line = [{"name": "砌体", "content": "1", "labor": "120.00", "material": "300.00", "machine": "10.00",
             "basis_note": "企业补充子目"}]
    assert ctx.put(f"/api/units/{uid}/boq/1/lines", json=line).status_code == 200
    ctx.put(f"/api/units/{uid}/tender-requirements", json={
        "source_ref": "招标文件第 12 页", "provisional_sum": "5000", "specialty_provisional": "10000"})
    first = ctx.post(f"/api/units/{uid}/calculate").json()
    assert first["total"] == "71601.30"
    assert any("尚未组价" in w for w in first["warnings"])  # 第 2 项未组价，如实提示
    again = ctx.post(f"/api/units/{uid}/calculate").json()
    assert again["input_hash"] == first["input_hash"] and again["total"] == first["total"]

    # 低于下限的安全文明措施费费率在计算时被拒绝
    ctx.put(f"/api/units/{uid}/pricing-params", json={"safety_rates": {"safety_production": "1"}})
    resp = ctx.post(f"/api/units/{uid}/calculate")
    assert resp.status_code == 422 and "低于规定下限" in resp.json()["detail"]

    # 下调可竞争费率：总价下降，锁定费率不变
    ctx.put(f"/api/units/{uid}/pricing-params", json={"management_rate": "10", "profit_rate": "5"})
    cut = ctx.post(f"/api/units/{uid}/calculate").json()
    assert float(cut["total"]) < float(first["total"])
    fees = {f["code"]: f for top in cut["fees"] for f in [top, *top["children"]]}
    assert fees["3.5"]["rate"] == "0.077" and fees["3.5"]["locked"] and fees["4"]["rate"] == "9"
    assert fees["3.1"]["amount"] == "5000.00"

    actions = [a["action"] for a in ctx.get("/api/audit").json()]
    assert {"boq.import", "pricing.set_lines", "pricing.params", "tender.requirements", "calc.run"} <= set(actions)


def test_quota_from_another_version_is_rejected(ctx):
    uid = building_unit(ctx)
    with ctx.app_state.session_factory() as s:
        other = s.query(m.QuotaVersion).filter_by(code="SD-SZ-2025").one()
        quota = m.QuotaItem(quota_version_id=other.id, code="TEST-1", name="测试子目", unit="m3")
        s.add(quota)
        s.commit()
        qid, other_id = quota.id, other.id
    resp = ctx.put(f"/api/units/{uid}/boq/1/lines", json=[{"name": "测试子目", "content": "1", "quota_item_id": qid}])
    assert resp.status_code == 422 and "禁止跨专业、跨版本" in resp.json()["detail"]
    # 数据库层面：子目与版本不匹配的引用被复合外键拒绝
    with pytest.raises(DBAPIError):
        with ctx.app_state.engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO composition_lines (unit_project_id,boq_code,boq_seq,sort,source,quota_item_id,"
                "quota_version_id,name,unit,content,labor,material,machine,basis_note) "
                f"VALUES ({uid},'c',1,1,'quota',{qid},{other_id + 100},'x','','1','0','0','0','')"))


def test_manual_engine_for_profession_without_rules(ctx):
    unit = new_unit(ctx, "highway")
    uid = unit["id"]
    ctx.post(f"/api/units/{uid}/boq", json={"kind": "original", "items": BOQ[:1]})
    ctx.put(f"/api/units/{uid}/boq/1/lines", json=[{"name": "路基填方", "content": "1", "labor": "120.00",
                                                     "material": "300.00", "machine": "10.00",
                                                     "basis_note": "人工录入"}])
    ctx.put(f"/api/units/{uid}/pricing-params", json={"management_rate": "5", "profit_rate": "3"})
    ctx.put(f"/api/units/{uid}/tender-requirements", json={"source_ref": "招标文件第 3 页", "tax_rate": "9",
                                                           "tender_amounts": [{"name": "暂列金额", "amount": "1000"}]})
    result = ctx.post(f"/api/units/{uid}/calculate").json()
    assert result["total"] == "51709.60" and result["rule_code"] is None
    assert "尚未录入计价规则" in result["warnings"][0]
    # 山东房建的费用类别不能套到公路专业上
    pid = ctx.post("/api/projects", json={"name": "p"}).json()["id"]
    assert ctx.post(f"/api/projects/{pid}/units", json={"name": "u", "profession": "highway",
                                                         "fee_category": "building", "grade": "I"}).status_code == 422


def test_roles(ctx):
    ctx.post("/api/users", json={"username": "viewer1", "password": "viewer-pass-1", "role": "viewer"})
    token = ctx.post("/api/auth/login", json={"username": "viewer1", "password": "viewer-pass-1"}).json()["token"]
    viewer = TestClient(ctx.app, headers={"Authorization": f"Bearer {token}"})
    assert viewer.get("/api/professions").status_code == 200
    assert viewer.post("/api/projects", json={"name": "x"}).status_code == 403
    assert viewer.get("/api/audit").status_code == 403
    assert ctx.post("/api/auth/login", json={"username": "viewer1", "password": "wrong-pass-1"}).status_code == 401
