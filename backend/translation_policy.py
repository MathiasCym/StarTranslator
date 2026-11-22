"""Protect document literals, notation and paragraph structure during writeback."""
import re
from collections import Counter
from .text_integrity import command_literal, validate_identifiers


PARAGRAPH_INSTRUCTION = (
    '只翻译当前待译片段，邻段和参考资料只用来理解。'
    '不把其他段落的文字写进当前片段，也不新增原文没有的换行。'
)
_LINE_BREAK = re.compile(r'\r\n|[\r\n\v]')


class ParagraphBoundaryError(ValueError):
    message = '译文新增了原文没有的换行，需只按当前原文重译这一段。'

    def __init__(self):
        super().__init__(self.message)


def validate_paragraph_boundaries(source, target):
    if len(_LINE_BREAK.findall(target.strip())) > len(_LINE_BREAK.findall(source.strip())):
        raise ParagraphBoundaryError()


def validate_document_text(source, target, *, preserve_paragraph=False):
    from .parameter_notation import validate
    from .text_languages import INLINE_CODE
    if not isinstance(target,str) or not target.strip():
        raise ValueError('模型未返回有效译文。')
    if preserve_paragraph:
        validate_paragraph_boundaries(source,target)
    if ('```' in target and '```' not in source) or '\0' in target:
        raise ValueError('译文包含无法直接写入的包装或控制字符。')
    validate_identifiers(source,target)
    if command_literal(source) and source.strip()!=target.strip():
        raise ValueError('命令和搜索表达式必须原样保留。')
    if Counter(m[0] for m in INLINE_CODE.finditer(source)) != Counter(m[0] for m in INLINE_CODE.finditer(target)):
        raise ValueError('译文改变了行内代码，代码必须原样保留。')
    validate(source,target)
