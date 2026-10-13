"""Bounded retries for transient Windows locks, retaining original-change guards."""
import os
import time


def replace_checked(temporary,target,guard):
    for attempt in range(5):
        guard()
        try:
            os.replace(temporary,target)
            return
        except PermissionError as error:
            if getattr(error,'winerror',None) not in (5,32,33):raise
            if attempt==4:
                raise PermissionError('原文件正在被占用或没有写入权限，本次内容尚未覆盖。请关闭正在使用该文件的软件，或选择另存。') from error
            time.sleep(.1*(attempt+1))
