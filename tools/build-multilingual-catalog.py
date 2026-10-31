"""Read the authorized workbook; write only a read-only JSON term catalog.

Usage: python tools/build-multilingual-catalog.py SOURCE.xlsx
The original spreadsheet is never edited or copied into the public repository.
"""
import argparse
import hashlib
import json
from pathlib import Path
import openpyxl

LANGUAGES = {'zh-CN': '中文', 'en-US': '英语', 'es-ES': '西班牙语',
             'fr-FR': '法语', 'ja-JP': '日语', 'ko': '韩语', 'pt': '葡萄牙语', 'ru-RU': '俄语'}


def build(source):
    workbook = openpyxl.load_workbook(source, read_only=True, data_only=True)
    entries, languages, seen = [], [], set()
    counts = {}
    source_rows = 0
    try:
        for sheet in workbook:
            sheet.reset_dimensions()
            rows = sheet.iter_rows(values_only=True)
            headers = [str(value or '').strip() for value in next(rows)]
            if any(code not in LANGUAGES for code in headers):
                raise ValueError('无法识别的语言列，请核对原表表头。')
            for code in headers:
                if code not in languages:
                    languages.append(code)
            for values in rows:
                terms = {code: str(value).strip() for code, value in zip(headers, values)
                         if value is not None and str(value).strip()}
                if not terms:
                    continue
                source_rows += 1
                token = json.dumps(terms, ensure_ascii=False, sort_keys=True)
                if token in seen:
                    continue
                seen.add(token)
                entries.append({'id': hashlib.sha256(token.encode()).hexdigest()[:20], 'terms': terms})
        for code in languages:
            counts[code] = sum(bool(row['terms'].get(code)) for row in entries)
    finally:
        workbook.close()
    return {'schema': 1, 'source': '公司官方多语言术语库',
            'sourceSha256': hashlib.sha256(Path(source).read_bytes()).hexdigest(),
            'readOnly': True, 'sourceRows': source_rows, 'duplicates': source_rows - len(entries),
            'languages': [{'code': code, 'name': LANGUAGES[code], 'count': counts[code]} for code in languages],
            'entries': entries}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1] / 'glossary/multilingual.json')
    args = parser.parse_args()
    result = build(args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: result[key] for key in ('sourceRows', 'duplicates', 'languages')}, ensure_ascii=False))
