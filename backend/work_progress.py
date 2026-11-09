"""Report completed work within stage budgets, independent of elapsed time."""

BUDGETS = {
    'check': {'preparing': (0, 3), 'check': (3, 68), 'terminology': (71, 27), 'export': (98, 1)},
    'translate_review': {
        'preparing': (0, 2), 'translate': (2, 25), 'repair': (27, 6),
        'layout': (33, 2), 'image_text': (35, 4), 'consistency': (39, 1), 'output_check': (40, 5),
        'check': (45, 17), 'terminology': (62, 10), 'replace': (72, 4),
        'final_layout': (76, 2), 'write': (78, 1),
        'format_source': (79, 3), 'format_output': (82, 3), 'format_model_0': (85, 5),
        'format_adjust': (90, 1), 'format_rerender': (91, 2),
        'format_model_1': (93, 2), 'format_model_2': (95, 2),
        # PDF-to-Word has a separate final page audit instead of PPT inspection.
        'preflight_output': (79, 2), 'final_audit': (81, 16),
        'validate': (97, 1), 'publish': (98, 1), 'export': (98, 1),
    },
    'translate': {
        'preparing': (0, 2), 'translate': (2, 33), 'repair': (35, 10),
        'layout': (45, 5), 'image_text': (50, 10),
        'format_source': (60, 3), 'format_output': (63, 3), 'format_model_0': (66, 9),
        'format_adjust': (75, 1), 'format_rerender': (76, 3),
        'format_model_1': (79, 4), 'format_model_2': (83, 2),
        'consistency': (85, 2), 'output_check': (87, 10),
        'export': (97, 2), 'validate': (97, 1), 'publish': (98, 1),
    },
}

LABELS = {
    'terminology': '术语逐项复核', 'replace': '自动应用已校验修改',
    'format_source': '原稿页面渲染', 'format_output': '译稿页面渲染',
    'format_model_0': '逐页格式检查', 'format_adjust': '安全调整排版',
    'format_rerender': '调整后重新渲染', 'format_model_1': '第二轮格式复核',
    'format_model_2': '第三轮格式复核', 'validate': '输出完整性复查',
    'preflight_output': '输出结构复查', 'final_layout': '调整最终排版',
    'final_audit': '最终文件逐页复查', 'publish': '保存已验证文件',
}

UNITS = {'terminology': '组', 'replace': '处', 'image_text': '张', 'output_check': '页', 'final_audit': '页'}


class WorkProgress:
    def __init__(self, kind, paths):
        self.ranges = BUDGETS[kind]
        # Independent proofreading reports one aggregate segment count.
        self.file_count = 1 if kind == 'check' else max(1, len(paths))
        self.done = {}
        self.value = 0

    def update(self, index, phase, done, total, message=''):
        index = min(max(index, 0), self.file_count - 1)
        key = phase
        if phase in ('format', 'render'):
            key = 'format_model_0'
            if '原稿' in message:
                key = 'format_source'
            elif '重新渲染' in message:
                key = 'format_rerender'
            elif '渲染输出' in message or '实际页面' in message:
                key = 'format_output'
        start, span = self.ranges.get(key, (0, 0))
        fraction = min(1, max(0, done / total)) if total and total > 0 else None
        identity = (index, key)
        if fraction is not None:
            self.done[identity] = max(self.done.get(identity, 0), fraction)
        within = start + span * self.done.get(identity, 0)
        self.value = max(self.value, min(99.5, (100 * index + within) / self.file_count))
        return {
            'percent': self.value,
            'stage_percent': None if fraction is None else 100 * fraction,
            'stage_key': key,
            'phase_label': LABELS.get(key, ''),
            'stage_unit': '页' if key.startswith('format_') else UNITS.get(key, '段'),
        }


def emit(progress, done, total, message, stage='check'):
    if not progress:
        return
    handler = getattr(progress, 'stage', None)
    if handler:
        handler(stage, done, total, message)
    else:
        progress(done, total, message)


def format_callback(activity):
    if not activity:
        return None

    def report(message, done=0, total=0):
        activity('format', message, done, total)

    report.stage = activity
    return report
