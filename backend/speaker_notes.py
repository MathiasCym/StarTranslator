"""Task-local PPT speaker-note processing; original package data is preserved."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps

_ENABLED=ContextVar('star_include_ppt_notes',default=False)

def enabled():return _ENABLED.get()

@contextmanager
def processing(value):
    if type(value) is not bool:raise ValueError('处理演讲者备注选项应为开启或关闭。')
    token=_ENABLED.set(value)
    try:yield
    finally:_ENABLED.reset(token)

def option(function):
    @wraps(function)
    def call(*args,include_ppt_notes=None,**kwargs):
        with processing(enabled() if include_ppt_notes is None else include_ppt_notes):
            return function(*args,**kwargs)
    return call
