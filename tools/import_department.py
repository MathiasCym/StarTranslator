"""Read supplied department sources without modifying them; build attributed JSON seeds."""
import json
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.models import GlossaryEntry

# Translations of Chinese-only slide concepts are proposals, not source quotations.
PPT_CONCEPTS = {
    2: ('LED模组', 'LED module'), 3: ('灯珠', 'LED lamp'),
    4: ('行驱动管', 'row driver transistor'), 5: ('列驱动芯片', 'column driver IC'),
    6: ('直插式', 'through-hole (DIP)'), 7: ('箱体', 'cabinet'),
    8: ('开关电源', 'switching power supply'), 9: ('灯板', 'lamp board'),
    10: ('封装', 'packaging'),
    11: ('像素', 'pixel'), 12: ('动态子像素', 'dynamic subpixel'),
    13: ('点间距', 'pixel pitch'), 14: ('分辨率', 'resolution'),
    15: ('像素密度', 'pixel density'), 16: ('水平视角', 'horizontal viewing angle'),
    17: ('垂直视角', 'vertical viewing angle'), 18: ('光通量', 'luminous flux'),
    19: ('照度', 'illuminance'), 20: ('光强度', 'luminous intensity'),
    21: ('灰度等级', 'grayscale level'),
    22: ('Gamma校准', 'gamma calibration'), 23: ('亮度', 'luminance'),
    26: ('对比度', 'contrast ratio'),
    27: ('饱和度', 'saturation'), 28: ('色温', 'color temperature'),
    29: ('色域', 'color gamut'), 30: ('波长', 'wavelength'),
    31: ('白平衡', 'white balance'), 32: ('帧频', 'frame rate'),
    33: ('刷新率', 'refresh rate'),
    34: ('视觉刷新率', 'visual refresh rate'), 35: ('余晖', 'ghosting'),
    36: ('摩尔纹', 'moiré pattern'), 37: ('全灰阶校正', 'full-grayscale calibration'),
}
SUSPECT = {'steper exposure', 'fusion', 'bounding machine', 'die bounding',
           'bining', 'briading', 'passive mactive'}

# 已确认的机翻错译（脚本层自动改正的依据）。只收录人工确认、语义无歧义的
# 常见机翻写法；绝不自动生成——把合法别名误当错译会造成大量假阳性。
WRONG_VARIANTS = {
    '点间距': ['dot spacing', 'point spacing', 'point distance'],
    '接收卡': ['receive card', 'receiving board card'],
    '发送卡': ['send card', 'transmission board card'],
    '刷新率': ['refreshing ratio'],
    '驱动IC': ['driving integrated circuit chip'],
    '灰度等级': ['gray scale grade'],
    '对比度': ['comparison degree'],
    '灯珠': ['lamp bead', 'light bead'],
}


def main(xlsx, pptx):
    entries, sources, incomplete = [], [], []
    wb = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
    for ws in wb:
        ws.reset_dimensions()  # The supplied first sheet declares only column A.
        count = 0
        for rowno, raw in enumerate(ws.iter_rows(values_only=True), 1):
            cells = ['' if c is None else str(c).strip() for c in raw]
            cells += [''] * max(0, 4 - len(cells))
            _, zh, en, note = cells[:4]
            if zh in ('名词（中文）', '中文') or not (zh or en):
                continue
            source = f'{Path(xlsx).name} / {ws.title} / 第{rowno}行'
            if not zh or not en:
                incomplete.append({'zh': zh, 'en': en, 'source': source})
                continue
            # Retain alternative translations verbatim rather than arbitrarily
            # turning one of the slash-separated alternatives into an error.
            flagged = en.casefold() in SUSPECT or zh in ('虚拟纸片', '虚拟射拍摄')
            note = '' if note == '-' else note
            if flagged:
                note = '待确认：源表疑似拼写或对应关系有误；保留原值。' + note
            entries.append(GlossaryEntry(zh=zh, en=en, priority=2,
                note=note, source=source).to_dict())
            count += 1
        sources.append({'sheet': ws.title, 'pairs': count})
    wb.close()
    ns = {'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}
    reference = []
    with zipfile.ZipFile(pptx) as archive:
        slides = sorted((s for s in archive.namelist() if re.fullmatch(r'ppt/slides/slide\d+\.xml', s)),
                        key=lambda s: int(re.search(r'slide(\d+)', s).group(1)))
        for name in slides:
            number = int(re.search(r'slide(\d+)', name).group(1))
            xml = ET.fromstring(archive.read(name))
            paragraphs = [''.join(p.findall('.//a:t', ns)[i].text or ''
                           for i in range(len(p.findall('.//a:t', ns))))
                          for p in xml.findall('.//a:p', ns)]
            text = '\n'.join(p for p in paragraphs if p.strip())
            source = f'{Path(pptx).name} / 第{number}页'
            reference.append({'source': source, 'text': text})
            if number in PPT_CONCEPTS:
                zh, en = PPT_CONCEPTS[number]
                entries.append(GlossaryEntry(zh=zh, en=en, priority=2, source=source,
                    note='中文定义来自课件；英文为补充建议，待确认。\n' + text[:1600]).to_dict())
    # Deduplicate identical pairs while retaining every source and definition.
    merged = {}
    for entry in entries:
        key = (entry['zh'], entry['en'].casefold())
        if key in merged:
            merged[key]['source'] += '\n' + entry['source']
            if entry['note'] and entry['note'] not in merged[key]['note']:
                merged[key]['note'] += '\n' + entry['note']
        else:
            merged[key] = entry
    # 人工确认的机翻错译：仅在语义无歧义时挂到对应条目上，供脚本层自动改正。
    for entry in merged.values():
        wrongs = WRONG_VARIANTS.get(entry['zh'])
        if not wrongs:
            continue
        accepted = {entry['en'].casefold()} | {v.casefold() for v in entry['variants']}
        entry['wrong_variants'] = [w for w in wrongs if w.casefold() not in accepted]
    (ROOT/'glossary/department.json').write_text(json.dumps(list(merged.values()), ensure_ascii=False, indent=2), encoding='utf-8')
    (ROOT/'glossary/department_reference.json').write_text(json.dumps(reference, ensure_ascii=False, indent=2), encoding='utf-8')
    manifest = {'workbook': Path(xlsx).name, 'sheets': sources, 'workbook_pairs': sum(s['pairs'] for s in sources),
                'slides': len(reference), 'slide_concepts': len(PPT_CONCEPTS), 'unique_pairs': len(merged),
                'incomplete_rows': incomplete, 'policy': '保留源值；新增材料默认为待确认，不触发自动替换。'}
    (ROOT/'glossary/department_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in manifest.items() if k not in ('sheets','incomplete_rows','policy')}, ensure_ascii=True))


if __name__ == '__main__':
    main(*sys.argv[1:3])
