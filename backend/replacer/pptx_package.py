"""Preserve untouched Office package parts byte-for-byte, including extensions."""
from pathlib import Path
import re
from zipfile import ZipFile
def save_office(source, document, destination, changed):
    if Path(source).suffix.lower() != '.pptx':
        document.save(str(destination))
        return
    parts = {}
    for locator in changed:
        if locator.startswith('part:'):
            continue
        match = re.match(r'^slide(\d+)/(.*)', locator)
        if not match:
            raise ValueError('幻灯片文字位置无效，未导出。')
        slide = document.slides[int(match[1])-1]
        part = slide.notes_slide.part if match[2].startswith('notes/') else slide.part
        parts[str(part.partname).lstrip('/')] = part
    with ZipFile(source, 'r') as original, ZipFile(destination, 'w') as output:
        from ..extract.pptx_extra import changed_extra_parts
        extras = changed_extra_parts(document, changed, original)
        output.comment = original.comment
        for info in original.infolist():
            data = extras.get(info.filename) if info.filename in extras else parts[info.filename].blob if info.filename in parts else original.read(info.filename)
            output.writestr(info, data)
