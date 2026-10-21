"""术语库的加载、保存与索引。

术语库是一个 JSON 数组，每条一个 GlossaryEntry。
变体索引用于确定匹配——把每个术语的所有形式映射回它所属的条目。
"""
import json
import os

from ..models import GlossaryEntry
from ..document_input import validate_document_input

DEFAULT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "glossary", "led_glossary.json",
)


class Glossary:
    def __init__(self, entries: list[GlossaryEntry] | None = None):
        self.entries: list[GlossaryEntry] = entries or []
        self._index: dict[str, list[GlossaryEntry]] = {}
        self._rebuild_index()

    def _rebuild_index(self) -> None:
        self._index = {}
        for entry in self.entries:
            for form in entry.all_forms():
                key = form.strip().lower()
                if key:
                    self._index.setdefault(key, []).append(entry)

    def lookup_exact(self, text: str) -> list[GlossaryEntry]:
        """精确（忽略大小写）查找某个英文形式属于哪些术语条目。"""
        return self._index.get(text.strip().lower(), [])

    def all_terms(self) -> list[GlossaryEntry]:
        return self.entries

    def add(self, entry: GlossaryEntry) -> None:
        self.entries.append(entry)
        self._rebuild_index()

    def merge(self, other: "Glossary") -> None:
        seen = {(e.zh, e.en.lower()): e for e in self.entries}
        for e in other.entries:
            if (e.zh, e.en.lower()) not in seen:
                self.entries.append(e)
                seen[(e.zh, e.en.lower())] = e
            else:
                current = seen[(e.zh, e.en.lower())]
                if e.category=='person':current.category='person'
                for field in ('source', 'note'):
                    value = getattr(e, field)
                    if value and value not in getattr(current, field):
                        setattr(current, field, (getattr(current, field) + '\n' + value).strip())
        self._rebuild_index()

    def save(self, path: str = DEFAULT_PATH) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump([e.to_dict() for e in self.entries], f,
                      ensure_ascii=False, indent=2)

    def apply_overrides(self, overrides_path: str) -> None:
        """人工修正表覆盖自动抽取的结果。

        priority=1 的条目视为已确认标准，让确定匹配优先命中它们。
        """
        if not os.path.exists(overrides_path):
            return
        with open(overrides_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        by_zh = {e.zh: e for e in self.entries}
        for item in raw:
            entry = GlossaryEntry(
                zh=item["zh"], en=item["en"],
                variants=item.get("variants", []),
                machine_variants=item.get("machine_variants", []),
                wrong_variants=item.get("wrong_variants", []),
                priority=item.get("priority", 1),
                note=item.get("note", ""),
                source=item.get("source", "人工修正"),
                category=item.get('category','term'),
            )
            by_zh[entry.zh] = entry
        self.entries = list(by_zh.values())
        self._rebuild_index()

    @classmethod
    def load(cls, path: str = DEFAULT_PATH) -> "Glossary":
        if not os.path.exists(path):
            return cls([])
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        entries = [
            GlossaryEntry(
                zh=item["zh"], en=item["en"],
                variants=item.get("variants", []),
                priority=item.get("priority", 2),
                machine_variants=item.get("machine_variants", []),
                wrong_variants=item.get("wrong_variants", []),
                note=item.get("note", ""),
                source=item.get("source", ""),
                category=item.get('category','term'),
            )
            for item in raw
        ]
        g = cls(entries)
        # 人工修正表始终生效
        if os.path.basename(path) == 'led_glossary.json':
            g.apply_overrides(os.path.join(os.path.dirname(path), "overrides.json"))
        if os.path.abspath(path) == os.path.abspath(DEFAULT_PATH):
            extra = os.path.join(os.path.dirname(path), 'department.json')
            if os.path.exists(extra):
                g.merge(cls.load(extra))
        return g

    @classmethod
    def load_with_imports(cls, path: str = DEFAULT_PATH,
                          imports: list[str] | None = None) -> "Glossary":
        """加载主术语库，并合并用户导入的额外术语表（JSON 或 Excel）。"""
        g = cls.load(path)
        for extra in imports or []:
            g.merge(_load_any(extra))
        return g


def _load_any(path: str) -> "Glossary":
    validate_document_input(path)
    ext = os.path.splitext(path)[1].lower()
    if ext == ".json":
        return Glossary.load(path)
    if ext in (".xlsx", ".xlsm"):
        return _load_excel(path)
    if ext in (".csv", ".tsv"):
        return _load_csv(path, "\t" if ext == ".tsv" else ",")
    raise ValueError(f"术语表格式不支持：{ext}（支持 .json/.xlsx/.csv/.tsv）")


def _rows_to_entries(rows) -> list[GlossaryEntry]:
    """把表格行转成术语条目。

    两种模式：
    - **表头驱动**（新）：首行含可识别的字段名时，按各列映射填充 zh/en/note/
      variants/machine_variants/wrong_variants/priority/source，富字段不丢。
      列表列用换行分隔（与界面对齐），另以逗号/顿号容错。
    - **位置回退**（旧）：无表头时按 [中文, 英文, 备注] 三列读取，priority=1。

    注意：这里只负责「读出」，不判断对错；priority 的默认值在两种模式下
    都是保守的（旧模式 1、新模式缺列时 2），不改变判决层逻辑。
    """
    from .writer import _split_list, _field_for, HEADER_FIELDS

    materialized = [[(str(c).strip() if c is not None else "") for c in row] for row in rows]
    if not materialized:
        return []

    header_fields = [_field_for(cell) for cell in materialized[0]]
    if 'zh' in header_fields and 'en' in header_fields:
        index_of = {field: pos for pos, field in enumerate(header_fields) if field}
        entries = []
        for row in materialized[1:]:
            def get(field: str) -> str:
                pos = index_of.get(field, -1)
                return row[pos] if 0 <= pos < len(row) else ""
            zh, en = get('zh'), get('en')
            if not zh or not en:
                continue
            raw_priority = get('priority').strip()
            try:
                priority = int(raw_priority) if raw_priority else 2
            except ValueError:
                priority = 2
            if priority not in (1, 2, 3):
                priority = 2
            entries.append(GlossaryEntry(
                zh=zh, en=en, note=get('note'),
                variants=_split_list(get('variants')),
                machine_variants=_split_list(get('machine_variants')),
                wrong_variants=_split_list(get('wrong_variants')),
                priority=priority, source=get('source') if 'source' in index_of else "用户导入",
                category=get('category') or 'term'))
        return entries

    # 位置回退：旧的三列语义
    entries = []
    columns = (0, 1, 2)
    for i, cells in enumerate(materialized):
        while len(cells) < 3:
            cells.append("")
        if any(c in ('中文', '名词（中文）', '中文术语', 'zh') for c in cells):
            z = next((j for j,c in enumerate(cells) if c in ('中文', '名词（中文）', '中文术语', 'zh')), 0)
            e = next((j for j,c in enumerate(cells) if c in ('英文', '标准英文', 'en')), 1)
            n = next((j for j,c in enumerate(cells) if c in ('备注', '解释', 'note')), -1)
            columns = (z, e, n)
            continue
        z,e,n = columns
        zh, en = cells[z] if z < len(cells) else '', cells[e] if e < len(cells) else ''
        note = cells[n] if 0 <= n < len(cells) else ''
        if not zh or not en:
            continue
        if i == 0 and zh.lower() in ("中文", "zh", "chinese", "中文术语"):
            continue
        entries.append(GlossaryEntry(zh=zh, en=en, note=note,
                                     priority=1, source="用户导入"))
    return entries


def _load_excel(path: str) -> "Glossary":
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    entries: list[GlossaryEntry] = []
    for ws in wb.worksheets:
        ws.reset_dimensions()
        entries.extend(_rows_to_entries(ws.iter_rows(values_only=True)))
    wb.close()
    return Glossary(entries)


def _load_csv(path: str, delim: str) -> "Glossary":
    import csv
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f, delimiter=delim))
    return Glossary(_rows_to_entries(rows))
