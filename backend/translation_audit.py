"""Inspect the saved artifact, rather than trusting only in-memory paragraphs."""
from collections import Counter
from pathlib import Path
from zipfile import ZipFile
from lxml import etree
from .text_integrity import CHINESE, contains_chinese, prose


def saved_residuals(path):
    from .extract import extract
    segments = extract(str(path))
    remaining = [dict(slide=s.slide, para=s.para, locator=s.locator, text=s.text,
        source=s.source, editable=s.editable, reason=s.not_editable_reason)
        for s in segments if s.source != 'image' and contains_chinese(s.text)]
    if Path(path).suffix.lower() != '.docx': return remaining
    # An independent XML inventory catches omissions in the Word traversal.
    # Inspect text nodes only: relationship targets, field instructions, paths,
    # author metadata and document properties are never translation candidates.
    from docx import Document
    reachable = {str(p.partname).lstrip('/') for p in Document(path).part.package.parts}
    covered = Counter(c for s in segments if s.source != 'image' for c in CHINESE.findall(prose(s.text)))
    w = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    a = 'http://schemas.openxmlformats.org/drawingml/2006/main'
    c = 'http://schemas.openxmlformats.org/drawingml/2006/chart'
    m = 'http://schemas.openxmlformats.org/officeDocument/2006/math'
    tags = {'{'+w+'}t', '{'+a+'}t', '{'+m+'}t'}
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    with ZipFile(path) as archive:
        for name in archive.namelist():
            if name not in reachable or not name.startswith('word/') or not name.endswith('.xml'): continue
            root = etree.fromstring(archive.read(name), parser)
            buckets = {}
            for node in root.iter():
                if node.tag not in tags and not (node.tag == '{'+c+'}v' and
                        any(p.tag in {'{'+c+'}strCache', '{'+c+'}strLit', '{'+c+'}tx'} for p in node.iterancestors())): continue
                if any(p.tag in {'{'+w+'}del', '{'+w+'}moveFrom'} for p in node.iterancestors()): continue
                parent = next((p for p in node.iterancestors() if p.tag in {'{'+w+'}p','{'+a+'}p'}), node)
                buckets.setdefault(parent, []).append(node.text or '')
            for index, values in enumerate(buckets.values()):
                text = ''.join(values)
                tokens = Counter(CHINESE.findall(prose(text)))
                missing = tokens-covered
                covered.subtract(tokens & covered)
                if missing:
                    remaining.append(dict(slide=None, para=None, locator=f'package:{name}/{index}', text=text,
                        source='package_text', editable=False,
                        reason='保存后的文件仍含未覆盖的可见中文，已保留原结构；不能视为完整英文。'))
    return remaining
