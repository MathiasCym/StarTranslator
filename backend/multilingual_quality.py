"""Chinese/Japanese share Han characters; unchanged phrases need a judgment."""
import json
import re
import unicodedata
from functools import lru_cache
from .checkpoints import digest
from .text_integrity import HAN,prose


from .review_format import script_positions


class IncompleteLanguageReview(ValueError):
    pass

@lru_cache(maxsize=512)
def chinese_script(value,target):
    """Inventory glyph variants only; never replace the user's/model's text.

    Windows LCMapStringEx: https://learn.microsoft.com/windows/win32/api/winnls/nf-winnls-lcmapstringex
    Ambiguous variants and names remain decisions for the independent model.
    """
    import os
    if os.name!='nt':return None
    import ctypes
    function=ctypes.WinDLL('kernel32',use_last_error=True).LCMapStringEx
    function.argtypes=[ctypes.c_wchar_p,ctypes.c_ulong,ctypes.c_wchar_p,ctypes.c_int,ctypes.c_wchar_p,ctypes.c_int,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_ssize_t]
    function.restype=ctypes.c_int
    flag=0x04000000 if target=='zh-Hant-TW' else 0x02000000
    size=function(target,flag,value,-1,None,0,None,None,0)
    if not size:return None
    buffer=ctypes.create_unicode_buffer(size)
    if not function(target,flag,value,-1,buffer,size,None,None,0):return None
    return buffer.value


class LanguageReview:
    VERSION=1
    def __init__(self,source_language,target_language):
        self.src,self.dst=source_language,target_language
        self.approved=set()

    def candidates(self,source,target):
        if not isinstance(target,str):return []
        def readable(value):
            return re.sub(r'(`+).*?\1',lambda m:' '*len(m[0]),prose(value))
        original,translated=readable(source),readable(target)
        if self.dst=='ko':
            return sorted(set(re.findall('['+HAN+']+',translated)),key=lambda value:(-len(value),value))
        if self.dst in ('zh-CN','zh-Hant-TW'):
            values=[]
            for word in re.findall('['+HAN+']+',translated):
                mapped=chinese_script(word,self.dst)
                if mapped is None or mapped!=word:values.append(word)
            if unicodedata.normalize('NFKC',original).casefold()==unicodedata.normalize('NFKC',translated).casefold() and re.search('['+HAN+']',translated):values.append(translated.strip())
            return sorted(set(values),key=lambda value:(-len(value),value))
        if self.src not in ('zh-CN','zh-Hant-TW') or self.dst!='ja-JP':return []
        words=re.findall('['+HAN+']+',original)
        pairs={word[i:i+2] for word in words for i in range(len(word)-1)}
        values=[]
        for word in re.findall('['+HAN+']+',translated):
            start=None
            for i in range(len(word)):
                shared=i+1<len(word) and word[i:i+2] in pairs
                if shared and start is None:start=i
                if start is not None and not shared:
                    phrase=word[start:i+1]
                    values.extend([phrase] if phrase in original else [phrase[j:j+2] for j in range(len(phrase)-1)])
                    start=None
            if len(word)==1 and word==original.strip():values.append(word)
        # They are candidates, never a deterministic assertion of untranslated
        # Chinese. Japanese terms such as 使用率 must be allowed by the model.
        return sorted(set(values),key=lambda value:(-len(value),value))

    def payload(self,source,target):
        values=self.candidates(source,target)
        return {'待核对未变原文片段':values,'片段目标语言':self.dst} if values else {}

    def review_identical_formula(self,source,target):
        # Plain-text identity is normally a failure. An unchanged formula with
        # already-correct Japanese labels still requires explicit model review.
        if not isinstance(target,str):return False
        if self.dst in ('zh-CN','zh-Hant-TW') and self.src!=self.dst:
            return (unicodedata.normalize('NFKC',prose(source)).casefold()==unicodedata.normalize('NFKC',prose(target)).casefold()
                and bool(re.search('['+HAN+']',prose(target))))
        return (self.src in ('zh-CN','zh-Hant-TW') and self.dst=='ja-JP'
            and bool(re.search('[×÷=±]',source)) and not re.search('[。！？!?]',source)
            and bool(self.candidates(source,target)))

    def instructions(self):
        if self.dst=='ko':
            return ('逐项核对韩语译文中保留的汉字片段。中文句子或未译术语必须译成自然韩语，不能因整段有少量韩文就通过；'
                '有明确依据的专名、品牌或合法韩语汉字由你结合原文判断，不机械删除。发现错误时ok=false并返回完整corrected_translation。'
                'ok=true必须同时返回issues:[]和unchanged_source_spans，每个候选恰好一次：{"text":"候选片段","target_language":"ko","valid":true,"reason":"在当前韩语语境下可以保留的具体理由"}。')
        if self.dst in ('zh-CN','zh-Hant-TW'):
            name='台湾繁体中文' if self.dst=='zh-Hant-TW' else '简体中文'
            return (f'逐项检查待核对片段是否确属正确的{name}。简繁共用字、已经正确的公式标签可以相同，不能仅因译文相同就判漏译；'
                '但正文中应转换的简体／繁体字、原语句及英文句子不得遗漏。字形候选只用于定位，正常通用字、原样专名和合法型号由你结合语境判断，不机械改写。'
                '全部位置都要核对。发现错误时ok=false并给出完整corrected_translation，不把错误字形认证为正确。'
                f'ok=true时必须同时返回issues:[]和unchanged_source_spans数组，每个候选恰好一次：{{"text":"候选片段","target_language":"{self.dst}","valid":true,"reason":"在当前语境中正确且无需转换的具体理由"}}。')
        return ('若有待核对未变原文片段，逐处判断它在当前句子中是否确属自然、正确的日语。'
            '日语与中文共用汉字，使用率、温度等正确日语可以原样保留；不得因字形相同一律报漏译。'
            '但含中文语法的句子、中文术语、中文简化字不能因为整段有少量假名就放过。'
            '每个候选片段的所有出现位置都必须核对。未译中文必须ok=false并给出完整corrected_translation。'
            'ok=true时另返回unchanged_source_spans数组，逐个包含'
            '{"text":"候选原词","target_language":"ja-JP","valid":true,"reason":"当前语境下为何是正确日语"}。'
            '不得仅声称是汉字、型号或品牌而忽略它的实际语义；无候选时不要求该字段。')

    def validate_review(self,source,target,answer):
        expected=self.candidates(source,target)
        if not expected or not isinstance(answer,dict) or answer.get('ok') is not True:return
        rows=answer.get('unchanged_source_spans')
        if not isinstance(rows,list) or len(rows)!=len(expected):
            raise IncompleteLanguageReview('未逐项确认候选片段是否为正确的目标语言。')
        approved=[]
        for row in rows:
            if (not isinstance(row,dict) or row.get('valid') is not True or row.get('target_language')!=self.dst
                or not isinstance(row.get('text'),str) or not isinstance(row.get('reason'),str) or not row['reason'].strip()):
                raise IncompleteLanguageReview('未取得候选片段的明确目标语言判断。')
            approved.append(row['text'])
        if set(approved)!=set(expected) or len(set(approved))!=len(approved):
            raise IncompleteLanguageReview('目标语言检查没有覆盖全部候选片段。')
        self.approved.update(approved)

    def proof(self,source,target):
        values=self.candidates(source,target)
        if not set(values)<=self.approved:return None
        return {'version':self.VERSION,'binding':digest([self.src,self.dst,source,target]),'approved':values}

    def reusable(self,source,target,proof):
        values=self.candidates(source,target)
        if not values:return True
        return (isinstance(proof,dict) and proof.get('version')==self.VERSION
            and proof.get('binding')==digest([self.src,self.dst,source,target])
            and isinstance(proof.get('approved'),list) and proof['approved']==values)

    def review_existing(self,client,source,target,cancel,terms):
        """Upgrade old ambiguous checkpoints without regenerating good text."""
        from .translation import check_cancel
        payload={'原文':source,'译文':target,**({'相关术语':terms} if terms is not None else {}),**self.payload(source,target)}
        error=''
        for _ in range(2):
            check_cancel(cancel)
            answer=client.chat_json(json.dumps({**payload,'上次检查':error},ensure_ascii=False),
                system=f'独立对照原文检查{self.dst}译文是否完整、事实正确且没有保留未译原语。'
                '数字、否定、单位、条件、型号、网址及人名品牌不可改变。'+self.instructions()+
                '只返回 {"ok":true,"issues":[],"unchanged_source_spans":[]} 或'
                ' {"ok":false,"issues":["确定的问题"]}，不能改写当前译文。',max_tokens=3000)
            if not isinstance(answer,dict) or answer.get('ok') is not True or answer.get('issues')!=[]:return False
            try:self.validate_review(source,target,answer)
            except IncompleteLanguageReview as exc:error=str(exc)
            else:return True
        return False
