"""贯穿各层的统一数据结构。"""
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class RunInfo:
    """一个 OOXML run 的快照。替换时需要靠它还原格式。"""
    text: str
    index: int


@dataclass
class Segment:
    """提取层产出的最小文本单元。

    editable=False 的段落只进报告，不参与替换。
    needs_merge 标记跨 run 拆分的词——替换时须先合并 run 再写回。
    """
    id: str
    file: str
    text: str
    locator: str                      # 定位串：file 内的路径，供替换层回溯
    source: str = "text"              # text | table | notes | header | footer
    slide: int | None = None          # PPT 页号
    para: int | None = None           # DOCX 段落号
    runs: list[RunInfo] = field(default_factory=list)
    editable: bool = True
    needs_merge: bool = False
    not_editable_reason: str = ""
    file_path: str = ""
    layout: dict = field(default_factory=dict)  # PPT text-box bounds in parent coordinates, points.

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["runs"] = [asdict(r) for r in self.runs]
        return d


@dataclass
class GlossaryEntry:
    """一条术语。

    variants 是**召回用的别名**（同义说法、简称、常见异写），不是
    「已知错误清单」——这个区分是重构的关键。原实现把 variants 当判错
    依据，导致「COB screen 命中 COB LED display 的变体」被报成错误，
    而两者本来就同义。现在 variants 只帮检索器发现「这段可能涉及该术语」，
    是否算错交给判决器（judge.py）判断。
    """
    zh: str
    en: str
    variants: list[str] = field(default_factory=list)
    priority: int = 2                 # 1=已确认标准 2=待确认 3=参考
    note: str = ""
    source: str = ""
    machine_variants: list[str] = field(default_factory=list)
    wrong_variants: list[str] = field(default_factory=list)
    category: str = 'term'            # term=普通术语 person=人名

    def __post_init__(self):
        categories={'':'term','term':'term','术语':'term','普通术语':'term','person':'person','人名':'person'}
        if not isinstance(self.category,str) or self.category.strip().casefold() not in categories:
            raise ValueError('分类应为普通术语或人名。')
        self.category=categories[self.category.strip().casefold()]

    def all_forms(self) -> list[str]:
        seen, out = set(), []
        for form in [self.en, *self.variants, *self.machine_variants, *self.wrong_variants]:
            key = form.lower()
            if key not in seen:
                seen.add(key)
                out.append(form)
        return out

    def to_dict(self) -> dict[str, Any]:
        result=asdict(self)
        # Legacy ordinary terms keep their exact public/sync/cache identity.
        if self.category=='term':result.pop('category')
        return result


@dataclass
class Candidate:
    """匹配层给出的候选译法。"""
    en: str
    zh: str
    score: float
    reason: str
    priority: int = 2

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Finding:
    """一条检验发现——报告的基本单元。

    method 区分术语规则、全文一致性建议与模型审校；kind 区分问题类型，
    用于 UI 分类筛选。confidence 表示建议的确定度。
    """
    segment_id: str
    file: str
    slide: int | None
    para: int | None
    source: str
    found_text: str                   # 文档里实际出现的
    concept_zh: str = ""              # 对应的中文概念
    suggested: str = ""               # 建议替换为
    candidates: list[Candidate] = field(default_factory=list)
    confidence: str = "medium"        # high | medium | low（模型自述）
    method: str = "llm"               # 判决模式下恒为 llm
    kind: str = "term"                # term | typo | grammar
    reason: str = ""                  # 模型给出的一句话理由
    editable: bool = True
    not_editable_reason: str = ""
    context: str = ""                 # 所在句子的上下文，帮人判断
    file_path: str = ""
    occurrences: int = 1
    applied: bool = False             # 已由用户应用到原文件，无需再次复核
    numeric_addition_verified: bool = False  # Added numbers exist at an explicitly paired source position.

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["candidates"] = [c.to_dict() for c in self.candidates]
        return d
