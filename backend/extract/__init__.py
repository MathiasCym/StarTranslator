"""提取层入口：按扩展名分派。"""
import os
import hashlib

from ..models import Segment
from .docx_extract import extract_docx
from .pptx_extract import extract_pptx
from .office import extract_office
from ..document_input import validate_document_input

SUPPORTED = {".docx", ".pptx"}


def extract(path: str) -> list[Segment]:
    validate_document_input(path)
    ext = os.path.splitext(path)[1].lower()
    if ext in SUPPORTED:
        segments = extract_office(path)
    else:
        raise ValueError(f"不支持的格式：{ext}。当前支持 {'、'.join(sorted(SUPPORTED))}")
    absolute = os.path.normcase(os.path.abspath(path))
    prefix = hashlib.sha256(absolute.encode('utf-8')).hexdigest()[:16]
    for segment in segments:
        segment.id = f"{prefix}:{segment.id}"
        segment.file_path = os.path.abspath(path)
    return segments
