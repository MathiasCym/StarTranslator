"""Paragraph text offsets include soft breaks; fields remain protected."""
from copy import deepcopy
from pptx.oxml.xmlchemy import OxmlElement


class BreakRun:
    def __init__(self, element, paragraph):
        self._r, self._parent = element, paragraph

    @property
    def text(self):
        return '\v'

    @text.setter
    def text(self, value):
        parent = self._r.getparent()
        position = parent.index(self._r)
        parent.remove(self._r)
        if value:
            from pptx.text.text import _Run
            element = OxmlElement('a:r')
            rpr = self._r.find('{http://schemas.openxmlformats.org/drawingml/2006/main}rPr')
            if rpr is not None:
                element.append(deepcopy(rpr))
            element.append(OxmlElement('a:t'))
            parent.insert(position, element)
            _Run(element, self._parent).text = value


def text_runs(paragraph):
    if getattr(paragraph,'_star_xml_runs',False):return list(paragraph.runs)
    if paragraph._p.tag.rsplit('}', 1)[-1] != 'p' or 'drawingml' not in paragraph._p.tag:
        return list(paragraph.runs)
    from pptx.text.text import _Run
    return [_Run(node, paragraph) if node.tag.rsplit('}', 1)[-1] == 'r' else BreakRun(node, paragraph)
            for node in paragraph._p if node.tag.rsplit('}', 1)[-1] in {'r', 'br'}]


def editable_paragraph(paragraph):
    runs = text_runs(paragraph)
    return bool(runs) and ''.join(r.text for r in runs) == paragraph.text
