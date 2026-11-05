"""Bounded model work; callers alone apply Office XML and collect findings."""
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from contextvars import copy_context


def ordered_pages(items, work, workers, cancel, segment):
    from .translation import check_cancel
    if type(workers) is not int or workers < 1:
        raise ValueError('并发数量必须为正整数。')
    count = min(workers, 3)
    pages = {}
    for index, item in enumerate(items):
        current = segment(item)
        key = (current.file_path, current.slide if current.slide is not None else ('block', index // 12))
        pages.setdefault(key, []).append(item)

    def page_work(page):
        values = []
        for item in page:
            check_cancel(cancel)
            values.append(work(item))
        return values

    if count == 1 or len(pages) < 2:
        for page in pages.values():
            yield from page_work(page)
        return
    pool = ThreadPoolExecutor(max_workers=count, thread_name_prefix='star-multilingual')
    iterator = iter(pages.values())
    pending = []

    def submit():
        page = next(iterator, None)
        if page is not None:
            # Each page gets its own Context, including the explicit resume
            # session. Never enter the same Context concurrently.
            context = copy_context()
            pending.append(pool.submit(context.run, page_work, page))

    try:
        for _ in range(count):
            submit()
        while pending:
            check_cancel(cancel)
            future = pending[0]
            try:
                values = future.result(timeout=.1)
            except TimeoutError:
                if future.done():raise
                continue
            pending.pop(0)
            check_cancel(cancel)
            yield from values
            submit()
    finally:
        for future in pending:
            future.cancel()
        # Let running calls finish their cancellation/verified-checkpoint path;
        # no work may outlive its task and silently update recovery state.
        pool.shutdown(wait=True, cancel_futures=True)


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
