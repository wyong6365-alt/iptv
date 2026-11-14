"""Excel 工程量清单识别。

只读取、不修正：识别不确定的地方写成提示交给人工对照原件，不擅自改动内容。
"""
from __future__ import annotations

import io
import re
from decimal import Decimal, InvalidOperation

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

HEADER_SCAN_ROWS = 40
SKIP_WORDS = ("合计", "小计", "总计")


class RecognitionError(ValueError):
    pass


def _norm(value) -> str:
    return re.sub(r"\s+", "", "" if value is None else str(value))


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def _column_role(header: str) -> str | None:
    if "项目特征" in header:
        return "features"
    if "编码" in header or header in ("子目号", "细目号", "清单编号", "编号"):
        return "code"
    if header in ("项目名称", "子目名称", "细目名称", "名称", "清单项目名称"):
        return "name"
    if header in ("计量单位", "单位"):
        return "unit"
    if header in ("工程量", "工程数量", "数量", "清单工程量"):
        return "quantity"
    return None


def _find_header(rows: list[tuple]) -> tuple[int, dict[str, int]] | None:
    for idx, row in enumerate(rows[:HEADER_SCAN_ROWS]):
        roles: dict[str, int] = {}
        for col, cell in enumerate(row):
            role = _column_role(_norm(cell.value))
            if role and role not in roles:
                roles[role] = col
        if {"code", "name", "quantity"} <= roles.keys():
            # 合并表头：计量单位、工程量可能在下一行，已在同一行找到则直接使用
            return idx, roles
    return None


def _format_decimals(number_format: str) -> int | None:
    if not number_format or number_format == "General":
        return None
    m = re.search(r"0(?:\.(0+))?", number_format.split(";")[0])
    if not m:
        return None
    return len(m.group(1) or "")


def _quantity(cell) -> tuple[Decimal | None, list[str]]:
    value, notes = cell.value, []
    if value is None or _norm(value) == "":
        return None, ["工程量为空"]
    if isinstance(value, bool):
        return None, ["工程量不是数字"]
    if isinstance(value, (int, float)):
        qty = Decimal(repr(value))
        shown = _format_decimals(cell.number_format)
        stored = max(0, -qty.normalize().as_tuple().exponent)
        if shown is not None and stored > shown:
            notes.append(f"单元格存储值 {qty} 的小数位多于显示精度（显示 {shown} 位），已按存储值读取，请对照招标文件确认")
        return qty, notes
    raw = _norm(value).replace(",", "").replace("，", "")
    try:
        return Decimal(raw), notes
    except InvalidOperation:
        return None, [f"工程量不是数字：{value!r}"]


def recognize(content: bytes, filename: str) -> dict:
    if filename.lower().endswith(".xls"):
        raise RecognitionError("暂不支持旧版 .xls 格式，请用 Excel 另存为 .xlsx 后上传")
    try:
        wb = load_workbook(io.BytesIO(content), data_only=True)
    except Exception as exc:  # openpyxl 对损坏文件抛出多种异常
        raise RecognitionError(f"无法读取 Excel 文件：{exc}") from None

    items: list[dict] = []
    sheets: list[dict] = []
    for ws in wb.worksheets:
        if ws.sheet_state != "visible":
            sheets.append({"sheet": ws.title, "used": False, "reason": "隐藏工作表，未读取"})
            continue
        rows = list(ws.iter_rows())
        found = _find_header(rows)
        if not found:
            sheets.append({"sheet": ws.title, "used": False, "reason": "未找到含项目编码、项目名称、工程量的表头"})
            continue
        header_idx, roles = found
        header_sig = [_norm(c.value) for c in rows[header_idx]]
        section, count = "", 0
        for row in rows[header_idx + 1:]:
            def cell(role):
                col = roles.get(role)
                return row[col] if col is not None and col < len(row) else None

            if [_norm(c.value) for c in row] == header_sig:
                continue  # 分页重复的表头
            code = _text(cell("code").value) if cell("code") else ""
            name = _text(cell("name").value) if cell("name") else ""
            features = _text(cell("features").value) if cell("features") else ""
            unit = _text(cell("unit").value) if cell("unit") else ""
            qty_cell = cell("quantity")
            has_qty = qty_cell is not None and _norm(qty_cell.value) != ""
            joined = _norm(code + name)
            if not joined and not features and not unit and not has_qty:
                continue
            first = next((_norm(c.value) for c in row if _norm(c.value)), "")
            if len(first) <= 12 and any(w in first for w in SKIP_WORDS):
                continue  # 合计、小计行
            ref = f"{ws.title}!{get_column_letter(roles['code'] + 1)}{row[0].row}"
            if not code and not unit and not has_qty:
                if name:
                    section = name  # 分部标题行
                elif features and items and items[-1]["_sheet"] == ws.title:
                    items[-1]["features"] += "\n" + features
                    items[-1]["anomalies"].append(f"项目特征跨行（{ref}），已拼接，请对照原件核对")
                continue
            if not code and not name:
                continue  # 表尾说明等
            notes: list[str] = []
            quantity, qty_notes = _quantity(qty_cell) if qty_cell is not None else (None, ["工程量为空"])
            notes += qty_notes
            if cell("code") is not None and isinstance(cell("code").value, (int, float)):
                notes.append("项目编码单元格是数字格式，前导 0 可能丢失，请对照原件核对")
            if not code:
                notes.append("项目编码为空")
            if not name:
                notes.append("项目名称为空")
            if not unit:
                notes.append("计量单位为空")
            items.append({
                "section": f"{ws.title} / {section}" if section else ws.title, "code": code, "name": name,
                "features": features, "unit": unit, "quantity": None if quantity is None else str(quantity),
                "source_ref": ref, "anomalies": notes, "_sheet": ws.title,
            })
            count += 1
        sheets.append({"sheet": ws.title, "used": True, "items": count,
                       "columns": {role: get_column_letter(col + 1) for role, col in roles.items()}})

    seen: dict[str, str] = {}
    for it in items:
        del it["_sheet"]
        if it["code"]:
            if it["code"] in seen:
                it["anomalies"].append(f"项目编码与 {seen[it['code']]} 重复")
            else:
                seen[it["code"]] = it["source_ref"]
    blocking = sum(1 for it in items if it["quantity"] is None or not it["code"] or not it["name"] or not it["unit"])
    return {"items": items, "sheets": sheets, "blocking_rows": blocking,
            "anomaly_rows": sum(1 for it in items if it["anomalies"])}
