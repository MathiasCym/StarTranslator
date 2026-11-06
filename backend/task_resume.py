"""An explicit resume owns its task checkpoints; a new task gets a new scope."""
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

_CURRENT=ContextVar('star_task_checkpoints',default=(None,None))


@contextmanager
def activate(session,observer=None):
    token=_CURRENT.set((session,observer))
    try:yield
    finally:_CURRENT.reset(token)


def checkpoint_identity(identity):
    session,observer=_CURRENT.get()
    from .speaker_notes import enabled
    if str(identity.get('source','')).lower().endswith('.pptx') and not enabled():
        identity={**identity,'include_ppt_notes':False}
    return ({**identity,'task_session':session} if session is not None else identity),observer


def model_identity(client):
    return {key:getattr(client,key,'') for key in ('provider','base_url','model','api_format')}


def context(data,glossary,references,client):
    from .checkpoints import context_identity,digest
    from .glossary.store import fingerprint
    identity=context_identity(glossary,references,client)
    files=[]
    for path in data['paths']:
        try:value=fingerprint(path)
        except OSError:value='unavailable'
        files.append((str(Path(path).resolve()),value))
    value={'files':digest(files),'model':identity['model'],'glossary':identity['glossary'],
        'references':digest(identity['references']),'pairing':digest(identity['pairing']),
        'direction':data.get('direction','zh-en'),'mode':data.get('translation_mode','faithful')}
    if any(str(p).lower().endswith('.pptx') for p in data['paths']):value['include_ppt_notes']=data.get('include_ppt_notes',False)
    from .document_languages import extended,reference_identity
    if extended(value['direction']):value['multilingual']=reference_identity()
    return value


def guard(previous,current):
    labels={'files':'原稿内容或位置','model':'模型连接','glossary':'术语库','references':'参考资料',
        'pairing':'原文对照配对','direction':'翻译方向','mode':'翻译模式','multilingual':'官方多语言词库'}
    changed=[label for key,label in labels.items() if previous.get(key)!=current.get(key)]
    if previous.get('include_ppt_notes',True)!=current.get('include_ppt_notes',True):changed.append('演讲者备注处理范围')
    if changed:
        model=previous.get('model',{}).get('model','')
        raise ValueError('无法按原断点继续：'+ '、'.join(changed)+'已变化。'+
            (f'原任务模型为 {model}。' if '模型连接' in changed and model else '')+
            '请恢复原任务设置后继续；需要使用新设置时，请开始新任务。已完成断点和输出仍保留。')


def guard_legacy(data,glossary,references,client):
    """Old tasks lack a run context. Probe exact bound translation identities.

    Never guess a cache based on file name or import another model's results.
    The read-only probes may explain a mismatch but cannot make model requests.
    """
    import os,sqlite3
    from contextlib import closing
    from types import SimpleNamespace
    from .checkpoints import Checkpoint,context_identity
    from .glossary.store import data_dir,fingerprint
    if data['kind'] not in ('translate','translate_review'):return ''
    db_path=data_dir()/'task-checkpoints.sqlite3'
    if not db_path.is_file():return '原任务没有已保存的翻译断点，将处理尚未完成的内容。'
    direction=data.get('direction','zh-en');stage='translation-zh' if direction=='en-zh' else 'translation'
    inputs=[]
    for path in data['paths']:
        item={'source':os.path.abspath(path) if direction=='en-zh' else os.path.normcase(os.path.abspath(path)),
            'fingerprint':fingerprint(path),'mode':data.get('translation_mode','faithful') if direction!='en-zh' or Path(path).suffix.lower()=='.pptx' else 'faithful'}
        if direction=='en-zh':item['direction']=direction
        inputs.append(item)
    def matches(candidate):
        shared=context_identity(glossary,references,candidate)
        return any(Checkpoint(stage,{**shared,**item},read_only=True).values for item in inputs)
    if matches(client):return '正在校验并恢复早期任务的已完成断点。'
    from .model_profiles import _load
    names=set()
    for profile in _load()['profiles']:
        candidate=SimpleNamespace(**{key:profile.get(key,'openai' if key=='api_format' else '') for key in ('provider','base_url','model','api_format')})
        if matches(candidate):names.add(candidate.model)
    if names:
        raise ValueError('无法按原断点继续：旧断点属于模型 '+ '、'.join(sorted(names))+
            '，当前模型为 '+str(getattr(client,'model',''))+'。请切回原模型后继续；使用当前模型重新处理，请开始新任务。')
    with closing(sqlite3.connect(db_path)) as db:
        existing=any(db.execute('SELECT 1 FROM checkpoints c JOIN checkpoint_scopes s ON s.scope=c.scope WHERE c.stage=? AND s.origin=? LIMIT 1',
            (stage,item['source'])).fetchone() for item in inputs)
    if existing:
        raise ValueError('找到早期任务断点，但原稿、术语库、参考资料、模型或翻译模式与当前设置不匹配，无法安全复用。请恢复原任务设置后继续，或开始新任务；旧断点仍保留。')
    return '原任务没有已保存的翻译断点，将处理尚未完成的内容。'
