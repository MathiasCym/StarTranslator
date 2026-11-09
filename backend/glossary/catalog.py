"""Read-only multilingual reference; free text can use its supplied language pairs.

It remains independent of the editable bilingual glossary and document writers.
"""
import json
from pathlib import Path
from .loader import DEFAULT_PATH


def effective():
    """Local maintained standards for proofreading/free text only."""
    from .language_pairs import overlay
    return overlay(reference())


def reference():
    from .technical_usage import compose
    return compose(read())


def read():
    path = Path(DEFAULT_PATH).parent / 'multilingual.json'
    try:
        data = json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as error:
        raise ValueError('多语言术语资料暂时无法读取；中英词库仍可正常使用。请检查安装完整性。') from error
    if not isinstance(data, dict) or data.get('schema') != 1 or data.get('readOnly') is not True or not isinstance(data.get('entries'), list):
        raise ValueError('多语言术语资料格式不正确；中英词库仍可正常使用。')
    return data
