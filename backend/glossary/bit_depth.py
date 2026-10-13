"""Merge the bit-depth convention once, retaining custom team translations."""
import copy,json
from . import store

VERSION='20261013-bit-depth'
NOTE='位深参数及数值修饰语统一使用 n-bit，如 8-bit、10-bit / 12-bit。描述比特数量可使用 8 bits；型号、代码、软件界面原名和 bit/s 不按此规则改写。每通道 8-bit 不等于整像素总共 8-bit；RGB 三通道合计为 24 bits per pixel。'
REFERENCE='NovaStar H5 Specifications V1.6.0 (Color Depth); Microsoft WIC Native Pixel Formats / 2026-10-13'
TERMS={'位深':'bit depth','色深':'color depth',**{str(n)+'bit':str(n)+'-bit' for n in [8,10,12,16,18,20,22,24,32]}}

def merge(entries):
    entries=copy.deepcopy(entries);changes=[]
    for zh,en in TERMS.items():
        current=next((e for e in entries if e['zh']==zh),None)
        if current and current['en'] not in (en,'bit' if zh=='位深' else en): continue
        if not current:
            current={'zh':zh,'en':en,'priority':1,'variants':[],'machine_variants':[],'wrong_variants':[],'note':'','source':''};entries.append(current)
            changes.append({'zh':zh,'new':en})
        current['en']=en;current['priority']=1
        if NOTE not in current.get('note',''):
            current['note']=(current.get('note','')+'\n'+NOTE).strip();changes.append({'zh':zh,'note':NOTE})
        if REFERENCE not in current.get('source',''): current['source']=(current.get('source','')+'\n'+REFERENCE).strip()
        if zh.endswith('bit') and zh not in current.get('machine_variants',[]): current.setdefault('machine_variants',[]).append(zh)
    return entries,changes

def upgrade_local(path):
    receipt=path.parent/('lexicon-'+VERSION+'.json')
    if receipt.exists(): return
    with store.edit_lock(path):
        raw=path.read_bytes();entries,changes=merge(store.validate(json.loads(raw.decode('utf-8-sig'))))
        if changes: store.atomic_json(path,store.validate(entries))
        store.atomic_json(receipt,{'id':VERSION,'changes':changes})
