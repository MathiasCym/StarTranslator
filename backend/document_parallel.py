"""Shared bounded page/block execution; only callers write document objects."""
import threading
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextvars import copy_context

def ordered_groups(groups,work,workers,cancel):
    from .translation import check_cancel
    if type(workers) is not int or workers<1:raise ValueError('并发数量必须为正整数。')
    groups=list(groups);count=min(workers,3)
    if count==1 or len(groups)<2:
        for group in groups:
            check_cancel(cancel);yield work(group)
        return
    pool=ThreadPoolExecutor(max_workers=count,thread_name_prefix='star-document')
    iterator=iter(enumerate(groups));pending={};ready={}
    def submit():
        task=next(iterator,None)
        if task is not None:
            index,group=task
            pending[pool.submit(copy_context().run,work,group)]=index
    try:
        for _ in range(count):submit()
        for index in range(len(groups)):
            while index not in ready:
                check_cancel(cancel)
                completed,_=wait(pending,timeout=.1,return_when=FIRST_COMPLETED)
                for future in completed:
                    ready[pending.pop(future)]=future
                    submit()
            check_cancel(cancel)
            yield ready.pop(index).result()
    finally:
        for future in pending:future.cancel()
        pool.shutdown(wait=True,cancel_futures=True)

def ordered_pages(items,work,workers,cancel,segment):
    from .translation import check_cancel
    pages={}
    for index,item in enumerate(items):
        current=segment(item)
        key=(current.file_path,current.slide if current.slide is not None else ('block',index//12))
        pages.setdefault(key,[]).append(item)
    def page_work(page):
        values=[]
        for item in page:check_cancel(cancel);values.append(work(item))
        return values
    for values in ordered_groups(pages.values(),page_work,workers,cancel):yield from values


class Activity:
    def __init__(self, total, notify=None, progress=None):
        self.total, self.notify, self.progress = total, notify, progress
        self.done, self.active = 0, {}
        self.lock = threading.RLock()

    def update(self, identity, message):
        with self.lock:
            self.active[identity] = message
            self.emit()

    def finish(self, identity, count=1):
        with self.lock:
            self.active.pop(identity, None)
            self.done += count
            if self.progress:
                self.progress(self.done, self.total)
            self.emit()

    def emit(self):
        if self.notify:
            counts = Counter(self.active.values())
            self.notify('；'.join(f'{message} {count} 处' for message, count in counts.items())
                        or '正在整理已验证结果', self.done, self.total)
