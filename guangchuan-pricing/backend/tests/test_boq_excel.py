"""Excel 清单识别测试。"""
import io

import pytest
from openpyxl import Workbook

from gcpricing.boq_excel import RecognitionError, recognize
from tests.test_platform import ctx, new_unit  # noqa: F401

HEADER = ["序号", "项目编码", "项目名称", "项目特征描述", "计量\n单位", "工程量", "综合单价", "合价"]


def workbook() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "分部分项工程量清单"
    ws.append(["分部分项工程和单价措施项目清单与计价表"])
    ws.append(["工程名称：某办公楼"])
    ws.append(HEADER)
    ws.append([None, None, "砌筑工程"])
    ws.append([1, "010401001001", "砖基础", "1.砖品种：实心砖\n2.砂浆：M5", "m3", 100])
    ws.append([2, "010401003001", "实心砖墙", "240 厚", "m3", 50.456])
    ws["F6"].number_format = "0.00"
    ws.append([None, None, None, "3.勾缝要求：原浆"])
    ws.append(["本页小计"])
    ws.append(HEADER)
    ws.append([None, None, "混凝土工程"])
    ws.append([3, "010502001001", "矩形柱", "C30", "m3", "1,234.50"])
    ws.append([4, "010502001001", "矩形柱", "C35", "m3", "详见图纸"])
    ws.append([5, 10515001001, "现浇构件钢筋", "HRB400", "t", 12.5])
    ws.append(["合  计"])
    other = wb.create_sheet("总价措施项目清单")
    other.append(["序号", "项目编码", "项目名称", "计算基础", "费率"])
    other.append([1, "011707001001", "安全文明施工", "", ""])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_recognizes_items_sections_and_reports_uncertainty():
    r = recognize(workbook(), "清单.xlsx")
    items = r["items"]
    assert [i["code"] for i in items] == ["010401001001", "010401003001", "010502001001", "010502001001", "10515001001"]
    assert items[0] == {"section": "分部分项工程量清单 / 砌筑工程", "code": "010401001001", "name": "砖基础",
                        "features": "1.砖品种：实心砖\n2.砂浆：M5", "unit": "m3", "quantity": "100",
                        "source_ref": "分部分项工程量清单!B5", "anomalies": []}
    # 存储值比显示精度多：按存储值读取并提示
    assert items[1]["quantity"] == "50.456" and "显示 2 位" in items[1]["anomalies"][0]
    # 跨行特征：拼接并提示
    assert items[1]["features"].endswith("3.勾缝要求：原浆") and "跨行" in items[1]["anomalies"][1]
    assert items[2]["quantity"] == "1234.50" and items[2]["section"].endswith("混凝土工程")
    # 无法读成数字的工程量不猜测
    assert items[3]["quantity"] is None and "不是数字" in items[3]["anomalies"][0]
    assert any("重复" in a for a in items[3]["anomalies"])
    assert "前导 0" in items[4]["anomalies"][0]
    assert r["blocking_rows"] == 1 and r["anomaly_rows"] == 3
    used = {s["sheet"]: s for s in r["sheets"]}
    assert used["分部分项工程量清单"]["items"] == 5 and not used["总价措施项目清单"]["used"]


def test_rejects_unreadable_files():
    with pytest.raises(RecognitionError, match="xlsx"):
        recognize(b"x", "old.xls")
    with pytest.raises(RecognitionError):
        recognize(b"not an excel file", "a.xlsx")


def test_upload_preview_then_import_keeps_notes(ctx):  # noqa: F811
    uid = new_unit(ctx, fee_category="building", grade="III")["id"]
    resp = ctx.post(f"/api/units/{uid}/boq/recognize", params={"filename": "清单.xlsx"}, content=workbook())
    assert resp.status_code == 200, resp.text
    preview = resp.json()
    assert ctx.get(f"/api/units/{uid}/boq").status_code == 404  # 识别不入库
    good = [i for i in preview["items"] if i["quantity"] is not None]
    done = ctx.post(f"/api/units/{uid}/boq", json={"kind": "original", "source_file": preview["source_file"],
                                                    "items": good})
    assert done.status_code == 200, done.text
    boq = ctx.get(f"/api/units/{uid}/boq").json()
    assert len(boq["items"]) == 4 and boq["intact"] and "SHA-256" in boq["source_file"]
    assert "显示 2 位" in boq["items"][1]["anomalies"][0]
    unit = ctx.get(f"/api/units/{uid}").json()
    assert unit["reference"]["management"] == "23.27" and unit["reference"]["safety"][0]["floor"] == "3.49"
