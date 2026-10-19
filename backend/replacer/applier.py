"""按 locator 回找到 segment，执行替换，输出新文件。

统一原则：**绝不修改原文件**，always 另存。
"""
import os

from docx import Document
from pptx import Presentation

from ..models import Segment
from .run_utils import replace_in_runs


def _output_path(src_path: str, output_dir: str | None = None) -> str:
    """算出输出文件路径。

    output_dir 为空 → 原文件旁加 _checked 后缀（旧行为，向后兼容）。
    output_dir 非空 → 输出到该目录，同名冲突时 _checked(2) 递增。
    """
    base, ext = os.path.splitext(os.path.basename(src_path))
    from ..formats import output_extension
    ext = output_extension(src_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        folder = output_dir
    else:
        folder = os.path.dirname(src_path)
    stem = os.path.join(folder, f"{base}_checked")
    candidate = f"{stem}{ext}"
    n = 2
    while os.path.exists(candidate):
        candidate = f"{stem}({n}){ext}"
        n += 1
    return candidate


def _build_para_map_docx(path):
    from ..extract.office import open_office
    document, paragraphs, _ = open_office(path)
    return {locator: para for locator, para, *_ in paragraphs}, document


def _build_para_map_pptx(path):
    return _build_para_map_docx(path)


def apply_replacements(path: str, segments: list[Segment],
                       selected: dict[str, list[tuple[str, str]]],
                       output_dir: str | None = None) -> tuple[str, list, list]:
    """执行替换。

    selected: {segment_id: [(found, suggested), ...]}
    output_dir: 输出目录；为空则输出到原文件旁。

    返回 (新文件路径, 成功列表, 失败列表)
    """
    ext = os.path.splitext(path)[1].lower()
    is_docx = ext == ".docx"

    if is_docx:
        para_map, doc = _build_para_map_docx(path)
    else:
        para_map, prs = _build_para_map_pptx(path)

    by_id = {s.id: s for s in segments}
    succeeded, failed = [], []

    for seg_id, pairs in selected.items():
        seg = by_id.get(seg_id)
        if not seg:
            failed.append((seg_id, "找不到对应段落"))
            continue
        if not seg.editable:
            failed.append((seg_id, seg.not_editable_reason or "该处不可替换"))
            continue
        para = para_map.get(seg.locator)
        if para is None:
            failed.append((seg_id, f"定位失败：{seg.locator}"))
            continue
        from .text_runs import text_runs
        runs = text_runs(para)
        if not runs:
            failed.append((seg_id, "段落无可写入的 run"))
            continue

        for old, new in pairs:
            if replace_in_runs(runs, old, new):
                succeeded.append((seg_id, old, new))
            else:
                failed.append((seg_id, f"未找到文本：{old}"))

    out_path = _output_path(path, output_dir)
    if is_docx:
        from .pptx_package import save_office
        save_office(path, doc, out_path, list(para_map))
    else:
        prs.save(out_path)
    return out_path, succeeded, failed
