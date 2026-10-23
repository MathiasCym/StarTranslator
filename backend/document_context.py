"""Shared page context and conservative object/count bindings for both workflows."""
import json
import re
from .writing_policy import numeric_values


class DocumentContext:
    def __init__(self, segments):
        self.pages, self.positions, self.accepted, self.flows = {}, {}, {}, {}
        for segment in segments:
            key = (segment.file_path, segment.slide)
            self.positions[(segment.file_path, segment.id)] = len(self.pages.setdefault(key, []))
            self.pages[key].append(segment)

    def neighbors(self, segment):
        page = self.pages[(segment.file_path, segment.slide)]
        if segment.slide is not None: return page
        index = self.positions[(segment.file_path, segment.id)]
        return page[max(0, index - 8):index + 9]

    @staticmethod
    def frame(segment):
        if segment.slide is None: return re.sub(r'/span\d+$', '', segment.locator)
        return re.sub(r'/(?:p)?\d+$', '', segment.locator)

    def related(self, segment):
        """Same text frame/cell plus the closest vertically aligned boxes.

        Bounds remain in a common parent coordinate system, including groups.
        Proximity describes reading order, never a source/translation pairing.
        """
        key = (segment.file_path, segment.slide, self.frame(segment))
        if key in self.flows: return self.flows[key]
        page = self.pages[(segment.file_path, segment.slide)]
        frame = self.frame(segment)
        selected = [s for s in page if self.frame(s) == frame]
        box = segment.layout
        if segment.slide is not None and segment.source == 'text' and box:
            candidates = {}
            for other in page:
                b = other.layout
                if self.frame(other) == frame or other.source != 'text' or not b: continue
                if b['container'] != box['container']: continue
                if min(b['width'], box['width']) <= 0 or min(b['width'], box['width'])/max(b['width'], box['width']) < .85: continue
                if abs(b['x']-box['x']) > max(3, min(b['width'],box['width'])*.03): continue
                direction = 'after' if b['y'] >= box['y']+box['height']-.5 else 'before'
                gap = b['y']-(box['y']+box['height']) if direction == 'after' else box['y']-(b['y']+b['height'])
                if gap < -.5 or gap > min(12, min(b['height'],box['height'])*.4): continue
                previous = candidates.get(direction)
                if previous is None or gap < previous[0]: candidates[direction] = (gap, self.frame(other))
            frames = {value[1] for value in candidates.values()}
            selected += [s for s in page if self.frame(s) in frames]
            selected.sort(key=lambda s: (s.layout.get('y',box['y']), s.para or 0))
        self.flows[key] = selected
        return selected

    def duplicates_neighbor_number(self, segment, found, suggested):
        # Correcting an existing value is different from adding a duplicate.
        if segment.slide is None or numeric_values(found) - numeric_values(suggested): return False
        added = numeric_values(suggested) - numeric_values(found)
        if not added: return False
        neighbors = [s for s in self.related(segment) if s.id != segment.id]
        return any(value in numeric_values(s.text) for value in added for s in neighbors)

    def duplicates_neighbor_label(self, segment, found, suggested):
        from pathlib import Path
        if Path(segment.file_path or segment.file).suffix.lower()!='.pptx':return False
        from .pptx_content import validate_labels
        original='\n'.join(s.text for s in self.related(segment) if self.frame(s)==self.frame(segment))
        try:validate_labels(original,found,suggested)
        except ValueError:return True
        return False

    def report_context(self, segment):
        return '\n'.join(s.text for s in self.related(segment))

    def object_name(self, segment):
        text = segment.text
        if '块' not in text: return ''
        # Direct labels outweigh page-wide subject matter. Never turn cabinets
        # or modules into whole screens just because a display appears nearby.
        for source, noun in [('箱体', 'cabinet'), ('模组', 'module'), ('银幕', 'screen'), ('屏幕', 'screen'), ('显示屏', 'screen')]:
            if source in text: return noun
        page = '\n'.join(item.text for item in self.neighbors(segment))
        if not any(label in page for label in ('箱体', '模组')) and any(label in page for label in ('银幕', '屏幕', '显示屏', '影院')):
            return 'screen'
        return ''

    def cache_key(self, segment, piece):
        return (segment.file_path, segment.slide if segment.slide is not None else segment.para, self.object_name(segment), piece)

    def prompt(self, segment):
        page = self.neighbors(segment)
        lines = [f'{item.id} [{item.locator}]: {item.text}' for item in page]
        context = '\n'.join(lines)
        if len(context) > 14000:
            position = next((i for i, item in enumerate(page) if item.id == segment.id), 0)
            context = '\n'.join(lines[:3] + lines[max(3, position - 8):position + 9])[:14000]
        noun = self.object_name(segment)
        binding = f'本段“块”指 {noun}；独立量词用 {noun}s，数词搭配按单复数处理，不得在同一对象的统计中换成其他对象。' if noun else '按上下文确认被计数对象；“块”没有固定英文译法，不要把整屏、箱体或模组混用。'
        key = (segment.file_path, segment.slide)
        previous = self.accepted.get(key, [])[-24:]
        flow = '\n'.join(f'{"当前段落" if s.id == segment.id else "相邻段落"} [{s.locator}]: {s.text}' for s in self.related(segment))
        return '【当前文本框及紧邻且对齐的文字（按版面阅读顺序；仅供语境判断）】\n' + flow[:6000] + '\n标题、标签和下一行可以共同表达一条信息，不要求各段独立成句。不得将下一行已有的数值、单位或宾语再补进当前标题；不得合并改写这些段落。邻近关系不代表与参考原稿一一对应。\n【同页整体内容（理解语境，不是额外待译内容）】\n' + context + '\n【对象和量词】\n' + binding + (
            '\n【本页已经确定的译法，保持相同对象的一致性】\n' + json.dumps(previous, ensure_ascii=False)[-3500:] if previous else '')

    def remember(self, segment, source, translation):
        self.accepted.setdefault((segment.file_path, segment.slide), []).append({'source': source, 'translation': translation})

    def repair_quantity(self, segment, piece, translation):
        noun = self.object_name(segment)
        if not noun or '块' not in piece: return translation
        if piece.strip() == '块': return noun + 's'
        singular = bool(re.search(r'(?<!\d)(?:1|一)\s*块', piece))
        replacement = noun if singular else noun + 's'
        if '单位' in piece:
            return re.sub(r'([:：]\s*)(?:units?|cabinets?)(?![A-Za-z])', lambda m: m.group(1) + replacement, translation, flags=re.I)
        return re.sub(r'\b(?:units?|cabinets?)\b', replacement, translation, flags=re.I) if noun == 'screen' else translation
