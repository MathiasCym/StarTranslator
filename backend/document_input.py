"""Reject Office owner/lock files before attempting filesystem reads."""
import re


def validate_document_input(path):
    name = re.split(r'[\\/]', str(path))[-1]
    if name.startswith('~$'):
        raise ValueError('这是 Office 临时锁文件，请选择不带“~$”前缀的原始文档。')

