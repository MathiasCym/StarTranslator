"""术语表的读写（针对共享盘 / 云盘同步目录里的 Excel 或 CSV）。

设计约束（都是踩过的坑）：

1. **不碰内置词库。** 只允许编辑用户挂载的共享表；内置的
   led_glossary.json / overrides.json 由仓库分发，不在这里写。
2. **写入前先验指纹。** 用户可能是打开着编辑器在改，也可能别人刚改过、
   云盘刚同步下来。写之前比对打开时的指纹，变了就拒绝并让用户先刷新，
   避免把别人的改动默默盖掉。
3. **多工作表时拒绝写。** 加载端会读所有 sheet 合并，但写回只认第一张表，
   保持原样不动。如果原文件有多张表，直接说不支持，而不是写坏它。
4. **先备份再原子替换。** 写 .bak，再写临时文件后 os.replace，
   中途断电不会留下半截文件。
"""
import csv
import hashlib
import os
import re
import shutil
import tempfile

HEADER = ["中文", "英文", "备注", "正确别名", "机翻候选", "已确认错译", "确认状态", "来源", "分类"]
HEADER_FIELDS = ["zh", "en", "note", "variants", "machine_variants", "wrong_variants", "priority", "source", "category"]

# 那些一格存放多条、以换行分隔的字段。
LIST_FIELDS = ("variants", "machine_variants", "wrong_variants")

# 表头文案 → 字段名。含历史/别名写法，兼容旧表与部门 Excel。
FIELD_ALIASES = {
    "zh": {"中文", "中文术语", "名词（中文）", "名词(中文)", "zh", "chinese", "zh-cn", "zh_cn", "zh-hans", "zh-hans-cn"},
    "en": {"英文", "标准英文", "en", "english", "en-us", "en_us", "en-gb", "en_gb"},
    "note": {"备注", "解释", "说明", "note"},
    "variants": {"正确别名", "别名", "同义别名", "variants", "variant"},
    "machine_variants": {"机翻候选", "机翻变体", "机翻写法", "machine_variants", "machine variant"},
    "wrong_variants": {"已确认错译", "确认错译", "错译", "wrong_variants", "wrong variant"},
    "priority": {"确认状态", "确认", "状态", "priority"},
    "source": {"来源", "source"},
    "category": {"分类", "类别", "category"},
}
_ALIAS_TO_FIELD = {alias.casefold(): field
                   for field, aliases in FIELD_ALIASES.items()
                   for alias in aliases}


def file_fingerprint(path: str) -> str:
    """文件指纹：mtime + 大小 + 内容哈希。用来判断打开后有没有被改过。"""
    if not os.path.exists(path):
        return ""
    st = os.stat(path)
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return f"{int(st.st_mtime)}:{st.st_size}:{h.hexdigest()[:16]}"


def detect_kind(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xlsm"):
        return "excel"
    if ext in (".csv", ".tsv"):
        return "csv"
    raise ValueError(f"术语表格式不支持：{ext}（支持 .xlsx/.xlsm/.csv/.tsv）")


def _row_from_cells(cells, width: int = 3) -> list[str]:
    out = []
    for c in cells[:width]:
        out.append("" if c is None else str(c).strip())
    while len(out) < width:
        out.append("")
    return out


def _split_list(cell: str) -> list[str]:
    """解析一格里存放的多条内容。

    优先按换行拆（与界面 textarea 的约定一致）；没有换行时再退回逗号/顿号，
    这样手工在 Excel 里用逗号分隔也能读。去重并保持顺序。
    """
    text = (cell or "").strip()
    if not text:
        return []
    if text.startswith('['):
        import json
        try:
            values=json.loads(text)
            if isinstance(values,list) and all(isinstance(v,str) for v in values):
                return list(dict.fromkeys(v.strip() for v in values if v.strip()))
        except ValueError:
            pass
    parts = text.split("\n") if "\n" in text else re.split(r"[,，、]", text)
    seen, out = set(), []
    for part in parts:
        value = part.strip()
        if value and value.casefold() not in seen:
            seen.add(value.casefold())
            out.append(value)
    return out


def _field_for(cell: str) -> str | None:
    return _ALIAS_TO_FIELD.get((cell or "").strip().casefold())


def header_for(columns: list[str]) -> list[str]:
    """把字段名列表反推成规范中文表头行（供写盘时使用）。"""
    canonical = {field: name for name, field in zip(HEADER, HEADER_FIELDS)}
    return [canonical.get(c, c or "") for c in columns]


def _header_map(row: list[str]) -> list[str | None] | None:
    """若 row 是表头行，返回「列位置 → 字段名」，否则 None。

    判据：至少有一格能识别成已知字段，且中文列与英文列都在。
    """
    fields = [_field_for(cell) for cell in row]
    if "zh" not in fields or "en" not in fields:
        return None
    if not any(fields):
        return None
    return fields


class TableTooComplex(Exception):
    """原文件结构超出本工具的处理范围（如多工作表）。"""


def _read_rows(path: str, kind: str) -> tuple[list[list[str]], str | None]:
    """读原始网格，返回 (rows, 表头行文本或无)。窄表按 3 列、带表头则按表头宽度。"""
    records: list[list] = []
    if kind == "excel":
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        if len(wb.worksheets) > 1:
            raise TableTooComplex(
                f"该表含 {len(wb.worksheets)} 个工作表，本工具只能编辑单表，"
                f"请在 Excel 里合并为一张表"
            )
        ws = wb.worksheets[0]
        records = [list(raw) for raw in ws.iter_rows(values_only=True)]
        wb.close()
    else:
        delim = "\t" if path.lower().endswith(".tsv") else ","
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            records = list(csv.reader(f, delimiter=delim))

    if records:
        first = [("" if c is None else str(c).strip()) for c in records[0]]
        if _header_map(first) is not None:
            width = len(first)
            return [_row_from_cells(r, width) for r in records[1:]], first
    # 无表头：保持旧的 3 列语义
    return [_row_from_cells(r, 3) for r in records], None


def load_table(path: str) -> dict:
    """读出术语表。

    返回 {"rows": [[...按列], ...], "columns": [...字段名], "header": [...],
          "fingerprint": "...", "kind": "excel|csv"}

    - 表头驱动：按首行的字段名映射列；无表头时回退 ["zh","en","note"]。
    - 列表字段已在行内用换行 join，界面按行编辑、写出时再拆。
    - rows 只含数据行（不含表头）；空行被跳过。
    """
    kind = detect_kind(path)
    if not os.path.exists(path):
        raise FileNotFoundError(path)

    records, header = _read_rows(path, kind)
    columns = _header_map(header) if header else None
    if columns is None:
        columns = ["zh", "en", "note"]
    width = len(columns)
    rows = [_row_from_cells(r, width) for r in records]
    rows = [r for r in rows if r[0] or r[1]]
    return {"rows": rows, "columns": columns,
            "header": header or HEADER[:width],
            "fingerprint": file_fingerprint(path), "kind": kind}


def _atomic_write_bytes(path: str, data: bytes) -> None:
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def save_table(path: str, rows: list[list[str]], expect_fingerprint: str | None,
               columns: list[str] | None = None, header: list[str] | None = None) -> dict:
    """把 rows 写回共享表。

    rows 的每一行按 columns 排列（与 load_table 返回的 columns 一致）；
    缺省时按 8 列标准布局写入。list 字段在写盘前用换行 join。

    expect_fingerprint 非空时，比对当前文件指纹，不一致 → 抛 FileChanged。
    返回 {"fingerprint": 新指纹, "count": 写入的数据行数}
    """
    if not os.path.exists(path):
        # 已有指纹说明调用方以为文件存在（打开后在写回）→ 报错；否则视为新建。
        if expect_fingerprint:
            raise FileNotFoundError(path)
    elif expect_fingerprint and file_fingerprint(path) != expect_fingerprint:
        raise FileChanged(
            "该表在你打开后被改动过（可能是同事刚编辑，或云盘刚同步下来）。"
            "请先刷新再改，以免覆盖别人的内容。"
        )

    kind = detect_kind(path)
    if not columns:
        # 保留文件原有列布局（旧 3 列表继续是 3 列），只有读不出时才用标准 8 列。
        try:
            existing = load_table(path)
            columns, header = existing["columns"], existing["header"]
        except Exception:
            columns, header = HEADER_FIELDS, HEADER
    elif not header:
        header = [next((h for h in HEADER if _field_for(h) == c), c or "") for c in columns]
    width = len(columns)
    clean = [_row_from_cells(r, width) for r in rows]
    clean = [r for r in clean if r[0] or r[1]]

    # 备份一次（覆盖同名 .bak），给误操作留后路
    try:
        shutil.copy2(path, path + ".bak")
    except OSError:
        pass

    if kind == "excel":
        from .excel_format import workbook
        wb = workbook(clean, columns, header, existing=path)
        # 写进内存再落盘，保证原子性
        d = os.path.dirname(os.path.abspath(path))
        fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
        os.close(fd)
        try:
            wb.save(tmp)
            os.replace(tmp, path)
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
        finally:
            wb.close()
    else:
        delim = "\t" if path.lower().endswith(".tsv") else ","
        import io
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=delim)
        w.writerow(header)
        w.writerows(clean)
        _atomic_write_bytes(path, buf.getvalue().encode("utf-8-sig"))

    return {"fingerprint": file_fingerprint(path), "count": len(clean)}


class FileChanged(Exception):
    """文件在打开之后被外部改动过，拒绝覆盖。"""
