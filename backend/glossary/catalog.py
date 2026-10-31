"""Read-only multilingual reference, deliberately separate from matching/translation."""
import json
from pathlib import Path
from .loader import DEFAULT_PATH


def read():
    path = Path(DEFAULT_PATH).parent / 'multilingual.json'
    try:
        data = json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as error:
        raise ValueError('多语言术语资料暂时无法读取；中英词库仍可正常使用。请检查安装完整性。') from error
    if not isinstance(data, dict) or data.get('schema') != 1 or data.get('readOnly') is not True or not isinstance(data.get('entries'), list):
        raise ValueError('多语言术语资料格式不正确；中英词库仍可正常使用。')
    return data
