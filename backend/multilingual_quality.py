"""Chinese/Japanese share Han characters; unchanged phrases need a judgment."""
import json
import re
from .checkpoints import digest
from .text_integrity import HAN,prose


def script_positions(groups):
    """Expose genuine superscript/subscript semantics without touching XML."""
    result=[];offset=0
    for group in groups:
        def find(node):
            if not isinstance(node,(tuple,list)) or len(node)!=4:return None
            tag,attributes,_,children=node
            if not isinstance(tag,str):return None
            attributes=dict(attributes)
            if 'baseline' in attributes and int(attributes['baseline']):return {'baseline':attributes['baseline']}
            if tag.rsplit('}',1)[-1]=='vertAlign':
                return {'vertical_align':next(iter(attributes.values()),'')}
            return next((value for child in children if (value:=find(child))),None)
        position=find(group.get('key'))
        if position:result.append({'start':offset,'end':offset+len(group['text']),'text':group['text'],**position})
        offset+=len(group['text'])
    return result


class IncompleteLanguageReview(ValueError):
    pass


class LanguageReview:
    VERSION=1
    def __init__(self,source_language,target_language):
        self.src,self.dst=source_language,target_language
        self.approved=set()

    def candidates(self,source,target):
        if self.src not in ('zh-CN','zh-Hant-TW') or self.dst!='ja-JP':return []
        def readable(value):
            return re.sub(r'(`+).*?\1',lambda m:' '*len(m[0]),prose(value))
        original,translated=readable(source),readable(target)
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
        return {'待核对未变原文片段':values} if values else {}

    def review_identical_formula(self,source,target):
        # Plain-text identity is normally a failure. An unchanged formula with
        # already-correct Japanese labels still requires explicit model review.
        return (self.src in ('zh-CN','zh-Hant-TW') and self.dst=='ja-JP'
            and bool(re.search('[×÷=±]',source)) and not re.search('[。！？!?]',source)
            and bool(self.candidates(source,target)))

    @staticmethod
    def instructions():
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
            raise IncompleteLanguageReview('未逐项确认原样保留的中文片段是否为正确日语。')
        approved=[]
        for row in rows:
            if (not isinstance(row,dict) or row.get('valid') is not True or row.get('target_language')!='ja-JP'
                or not isinstance(row.get('text'),str) or not isinstance(row.get('reason'),str) or not row['reason'].strip()):
                raise IncompleteLanguageReview('未取得原样保留片段的明确日语判断。')
            approved.append(row['text'])
        if set(approved)!=set(expected) or len(set(approved))!=len(approved):
            raise IncompleteLanguageReview('日语残留检查没有覆盖全部候选片段。')
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
                system='独立对照原文检查日语译文是否完整、事实正确且没有保留未译中文。'
                '数字、否定、单位、条件、型号、网址及人名品牌不可改变。'+self.instructions()+
                '只返回 {"ok":true,"issues":[],"unchanged_source_spans":[]} 或'
                ' {"ok":false,"issues":["确定的问题"]}，不能改写当前译文。',max_tokens=3000)
            if not isinstance(answer,dict) or answer.get('ok') is not True or answer.get('issues')!=[]:return False
            try:self.validate_review(source,target,answer)
            except IncompleteLanguageReview as exc:error=str(exc)
            else:return True
        return False
