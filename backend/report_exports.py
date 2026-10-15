"""Bounded background exports; the original synchronous API remains compatible."""
import copy
import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from . import workflow, task_queue
from .llm.client import LLMClient

LOCK = threading.Lock()
EXPORTS = {}
POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix='star-export')


def read(export_id, report_id=None):
    with LOCK:
        value = EXPORTS.get(export_id)
        if value is None or report_id is not None and value['report_id'] != report_id:
            raise ValueError('保存任务不存在。')
        return copy.deepcopy(value)


def start(data):
    data = copy.deepcopy(data)
    with workflow.LOCK:
        if task_queue.MAINTENANCE: raise ValueError('正在校验安装文件，请稍后保存。')
        if data.get('report_id') not in workflow.REPORTS: raise ValueError('报告已过期，请重新校对。')
    client = LLMClient()  # Freeze the connection used for this export's format review.
    with LOCK:
        if sum(v['status'] in ('queued','running') for v in EXPORTS.values()) >= 8:
            raise ValueError('正在保存的任务较多，请稍后重试。')
        with workflow.LOCK:
            if task_queue.MAINTENANCE:raise ValueError('正在校验安装文件，请稍后保存。')
            if data.get('report_id') not in workflow.REPORTS:raise ValueError('报告已过期，请重新校对。')
            task_queue.ACTIVE_EXPORTS+=1  # Include queued exports in cleanup/maintenance guards.
        value = dict(id=uuid.uuid4().hex, report_id=data['report_id'], status='queued',
            phase='preparing',done=0,total=0,message='正在准备保存',result=None,error='')
        EXPORTS[value['id']] = value
        for key in list(EXPORTS):
            if len(EXPORTS) <= 30: break
            if EXPORTS[key]['status'] not in ('queued','running'): EXPORTS.pop(key)
    def progress(phase, done=0, total=0, message=''):
        with LOCK: value.update(phase=phase,done=done,total=total,message=message)
    def execute():
        with LOCK: value['status'] = 'running'
        try:
            result = workflow.apply_report(data,progress=progress,client=client)
            with LOCK: value.update(status='complete',phase='complete',done=1,total=1,message='文件已保存',result=result)
        except Exception as error:
            logging.getLogger(__name__).exception('Report export failed')
            with LOCK: value.update(status='failed',error=workflow.error_message(error),message='保存未完成')
        finally:
            with workflow.LOCK:task_queue.ACTIVE_EXPORTS-=1
    try:POOL.submit(execute)
    except Exception:
        with workflow.LOCK:task_queue.ACTIVE_EXPORTS-=1
        with LOCK:EXPORTS.pop(value['id'],None)
        raise
    return read(value['id'])
