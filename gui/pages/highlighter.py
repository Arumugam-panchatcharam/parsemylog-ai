from dash import html
import re
class TextHighlighter:
    def __init__(self):
        self.patterns = [
            (r'\d{4}-\d{2}-\w{5}:\d{2}:\d{2}', 'timestamp'),
            (r'\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d{3})?(?:Z|[+-]\d{2}:\d{2})?\b', 'timestamp'),
            (r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\b', 'timestamp'),
            (r'\b\d{2}:\d{2}:\d{2}(?:\.\d{3})?\b', 'timestamp'),
            (r'\b([0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}\b', 'mac'),
            (r'\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b', 'ip'),
            (r'\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b', 'ip'),
            (r'(?:/[^\s/]+)+(?:\.[^\s]*)?', 'path'),
            (r'[A-Za-z]:\\(?:[^\s\\]+\\)*[^\s\\]*', 'path'),
            (r'--[a-zA-Z][a-zA-Z0-9-]*(?:=[^\s]*)?', 'cli'),
            (r'(?<!\w)-[a-zA-Z](?![a-zA-Z0-9])', 'cli'),
            (r'\b0[xX][0-9a-fA-F]+\b', 'number'),
            (r'\b(ERROR|FATAL|CRITICAL|FAIL|FAILED|EXCEPTION|CRASH|ABORT|PANIC)\b', 'error'),
            (r'\b(WARNING|WARN|DEPRECATED|CAUTION|ALERT)\b', 'warning'),
            (r'\b(INFO|INFORMATION|NOTICE|SUCCESS|OK|PASS|PASSED|COMPLETE|COMPLETED)\b', 'info'),
            (r'\b(DEBUG|TRACE|VERBOSE|DETAIL)\b', 'debug'),
            (r'\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b', 'number'),
        ]
        
        self.styles = {
            'error': {'color': '#dc3545', 'font-weight': 'bold', 'background': 'rgba(220, 53, 69, 0.1)', 'padding': '1px 3px', 'border-radius': '3px'},
            'warning': {'color': '#fd7e14', 'font-weight': 'bold', 'background': 'rgba(253, 126, 20, 0.1)', 'padding': '1px 3px', 'border-radius': '3px'},
            'info': {'color': '#20c997', 'font-weight': 'bold', 'background': 'rgba(32, 201, 151, 0.1)', 'padding': '1px 3px', 'border-radius': '3px'},
            'debug': {'color': '#198754', 'font-weight': 'bold', 'background': 'rgba(25, 135, 84, 0.1)', 'padding': '1px 3px', 'border-radius': '3px'},
            'mac': {'color': '#e83e8c', 'font-weight': 'bold', 'background': 'rgba(232, 62, 140, 0.1)', 'padding': '1px 3px', 'border-radius': '3px'},
            'ip': {'color': '#6f42c1', 'font-weight': 'bold', 'background': 'rgba(111, 66, 193, 0.1)', 'padding': '1px 3px', 'border-radius': '3px'},
            'number': {'color': "#438badff", 'font-weight': '500'},
            'cli': {'color': '#0dcaf0', 'font-weight': '500', 'font-style': 'italic'},
            'timestamp': {'color': "#f4da5acd", 'font-weight': '500'},
            'path': {'color': '#d63384', 'text-decoration': 'underline'},
        }
    
    def highlight_chunk(self, text_lines):
        if not text_lines:
            return []
        
        result_components = []
        for line_idx, line in enumerate(text_lines):
            clean_line = line.rstrip("\r\n")  # remove newlines

            if not clean_line:  # empty line
                result_components.append(html.Br())
                continue

            highlighted_line = self._highlight_single_line(clean_line)
            result_components.extend(highlighted_line)

            # Only add <br> if it's not the last line
            if line_idx < len(text_lines) - 1:
                result_components.append(html.Br())
    
        return result_components
    
    def _highlight_single_line(self, line):
        if not line.strip():
            return [line]
        
        all_matches = []
        for pattern, style_name in self.patterns:
            try:
                for match in re.finditer(pattern, line, flags=re.IGNORECASE):
                    all_matches.append((match.start(), match.end(), match.group(), style_name))
            except Exception:
                continue
        
        all_matches.sort()
        non_overlapping_matches = []
        
        for start, end, text, style in all_matches:
            overlaps = False
            for existing_start, existing_end, _, _ in non_overlapping_matches:
                if not (end <= existing_start or start >= existing_end):
                    overlaps = True
                    break
            if not overlaps:
                non_overlapping_matches.append((start, end, text, style))
        
        components = []
        last_end = 0
        
        for start, end, match_text, style_name in non_overlapping_matches:
            if start > last_end:
                components.append(line[last_end:start])
            components.append(html.Span(match_text, style=self.styles[style_name]))
            last_end = end
        
        if last_end < len(line):
            components.append(line[last_end:])
        
        return components if components else [line]