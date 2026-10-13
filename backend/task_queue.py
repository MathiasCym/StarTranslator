"""Bounded background work; request slots are shared by all local/LAN jobs."""
import asyncio
import threading
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor

POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix='star-task')
REQUEST_SLOTS = threading.BoundedSemaphore(4)
MAX_ACTIVE = 32
MAX_RETAINED = 100
MAINTENANCE = False  # protected by workflow.LOCK
ACTIVE_EXPORTS = 0


@contextmanager
def request_slot(cancel=None):
    from .llm.client import LLMUnavailable
    while not REQUEST_SLOTS.acquire(timeout=.25):
        if cancel and cancel.is_set(): raise LLMUnavailable('任务已取消。')
    try:
        if cancel and cancel.is_set(): raise LLMUnavailable('任务已取消。')
        yield
    finally: REQUEST_SLOTS.release()


async def wait(job_id, interval=.25):
    """Async integration entry point; does not block the caller's event loop."""
    from . import workflow
    while True:
        with workflow.LOCK:
            job = workflow.JOBS.get(job_id)
            if not job:
                raise ValueError('任务不存在')
            value = workflow.snapshot(job)
        if value['status'] not in ('queued', 'running'):
            return value
        await asyncio.sleep(interval)


async def submit(data):
    from . import workflow
    return await asyncio.to_thread(workflow.start, data)
