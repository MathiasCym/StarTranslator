"""PowerPoint-only guards against borrowing an adjacent English label.

Slides often split an advertising heading across manual line breaks with
different styles. Those labels supply context, never extra translation text.
Do not deduplicate legitimate repeats in the source or alter the written runs.
"""
import re
from collections import Counter
from .text_integrity import contains_chinese


def label_pattern(label):
    return re.compile(r'(?<![A-Za-z0-9])' + r'\s+'.join(re.escape(w) for w in label.split())
                      + r'(?![A-Za-z0-9])', re.I)


def _identifier_label(label):
    # Keep this gate narrow. An ordinary bilingual heading ("Meeting Minutes"
    # followed by its Chinese equivalent) may legitimately translate twice.
    # Compact mixed-case names, model IDs and LED brand headings are retained
    # identifiers, rather than English prose that needs semantic guessing.
    words=label.split()
    if len(words)==1:
        return bool(re.fullmatch(r'[A-Za-z0-9]+',label) and (
            re.search(r'[a-z][A-Z]',label) or re.search(r'[A-Za-z]\d|\d[A-Za-z]',label)
            or (label.isupper() and label.endswith('LED'))))
    return bool(2<=len(words)<=3 and re.fullmatch(r'[A-Z]{4,}',words[0])
                and all(re.fullmatch(r'[A-Z0-9]{1,3}',word) for word in words[1:]))


def validate_labels(original, piece, target):
    for line in re.split(r'[\n\v]', original):
        label = line.strip()
        # Entire source-only English headings, not fragments from mixed prose
        # or common short tokens such as LED, UK, or a page number.
        if (not label or contains_chinese(label) or len(label.split()) > 6
                or len(re.sub('[^A-Za-z]', '', label)) < 4
                or not re.fullmatch(r'[A-Za-z0-9 &+./™®©–—-]+', label)
                or not _identifier_label(label)):
            continue
        pattern = label_pattern(label)
        if len(pattern.findall(target)) > len(pattern.findall(piece)):
            raise ValueError('译文重复补入了当前待译文字之外的独立标题“' + label
                             + '”。该标题已保留在原来的位置；只翻译当前待译文字，不得再次补入。'
                             + '保留当前文字中的全部动作、事实、条件和修饰，不能为消除重复而删除含义；'
                             + '当前文字是接在上一行标题后的谓语或补充信息时，只译这部分。')


def cross_line_repetitions(original,target):
    """Suspicions for a model check, never automatic deletion of prose."""
    lines=[line.strip() for line in re.split(r'[\n\v]',original) if line.strip()]
    if len(lines)<2:return []
    found=Counter()
    for line in re.split(r'[\n\v]',target):
        words=re.findall(r'[A-Za-z0-9]+',line.lower())
        found.update(set(tuple(words[i:i+2]) for i in range(len(words)-1)
                         if sum(len(w) for w in words[i:i+2])>=8 and any(len(w)>=4 for w in words[i:i+2])))
    repeats=[]
    for words,count in found.items():
        phrase=' '.join(words)
        if count>max(len(label_pattern(phrase).findall(original)),max(Counter(lines).values(),default=0)):
            repeats.append(phrase)
    return repeats
