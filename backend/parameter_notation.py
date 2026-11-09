"""Protect pure numeric bit-parameter fields, not prose or the word bit itself."""
import re

PART=r'\d+(?:\.\d+)?[ \t]*-?[ \t]*bits?'
FIELD=re.compile(r'\s*'+PART+r'(?:\s*[/／,，;；]\s*'+PART+r')*\s*',re.I)
TOKEN=re.compile(r'(\d+(?:\.\d+)?)[ \t]*-?[ \t]*bits?',re.I)
INSTRUCTION=('参数表、公式中的 8bit、10bit / 12bit 等数值单位保留拉丁 bit（英文修饰语可为 8-bit），'
    '不能局部改成ビット、비트、位元。正文术语和解释正常翻译；bit/s、型号、代码及每通道/每像素的区别保持原样。')

def is_field(value):
    return isinstance(value,str) and FIELD.fullmatch(value) is not None

def validate(source,target):
    if not is_field(source):return
    if not is_field(target) or TOKEN.findall(source)!=TOKEN.findall(target):
        raise ValueError('位深参数字段应保留原数值和拉丁 bit 单位；不能部分改成其他语种或改为 byte。')
