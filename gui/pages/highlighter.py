from dash import html
import re
class TextHighlighter:
    def __init__(self):
        self.patterns = [

            # === HIGH PRIORITY: FULL TIMESTAMPS (ISO, space, fractional, tz) ===
            # ISO 8601 timestamps: 2025-11-24T00:53:27.123Z or without Z
            (r'\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}'
            r'(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})?\b', 'timestamp'),

            # RFC822 / syslog style: "Nov 24 00:53:27"
            (r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)'
            r'\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\b', 'timestamp'),

            # HH:MM:SS (but **NOT inside MAC addresses**)
            (r'(?<![0-9A-Fa-f:])\b\d{2}:\d{2}:\d{2}'
            r'(?:\.\d{3})?\b(?![:0-9A-Fa-f])', 'timestamp'),

            # === MAC ADDRESSES ===
            (r'\b([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b', 'mac'),

            # === MODULE NAMES / IDENTIFIERS ===
            (r'\[([A-Za-z0-9_-]*[A-Za-z][A-Za-z0-9_-]*)\]', 'module'),

            # === IP ADDRESSES ===
            # IPv6 first (to avoid IPv4 submatching)
            (r'\b(?:[0-9A-Fa-f]{1,4}:){7}[0-9A-Fa-f]{1,4}\b', 'ip'),

            # IPv4
            (r'\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d?\d)\.){3}'
            r'(?:25[0-5]|2[0-4]\d|[01]?\d?\d)\b', 'ip'),

            # === FILESYSTEM PATHS ===
            # Unix paths
            (r'(?<!\S)/(?:[^\s/]+/)*[^\s/]+', 'path'),

            # Windows paths
            (r'\b[A-Za-z]:\\(?:[^\s\\]+\\)*[^\s\\]+\b', 'path'),

            # === CLI FLAGS ===
            (r'--[a-zA-Z][a-zA-Z0-9-]*(?:=[^\s]+)?', 'cli'),     # --flag=value
            (r'(?<!\w)-[a-zA-Z](?![a-zA-Z0-9])', 'cli'),         # -f

            # === KEYWORDS (ERRORS, WARNINGS, etc.) ===
            (r'\b(ERR|ERROR|FATAL|CRITICAL|FAIL|FAILED|EXCEPTION|CRASH|ABORT|PANIC)\b', 'error'),
            (r'\b(WARN|WARNING|WARN|DEPRECATED|CAUTION|ALERT)\b', 'warning'),
            (r'\b(INFO|INFORMATION|NOTICE|SUCCESS|OK|PASS|PASSED|COMPLETE|COMPLETED)\b', 'info'),
            (r'\b(OFF|DEBUG|TRACE|VERBOSE|DETAIL)\b', 'debug'),

            # === LOWEST PRIORITY: NUMBERS ===
            #(r'\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b', 'number'),
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
            'module': {'font-weight': 'bold', "padding": "1px 4px", "border-radius": "3px"},
        }
        self.module_colors = [
                {"color": "#e83e8c"},   # Pink
                {"color": "#0d6efd"},   # Blue
                {"color": "#20c997"},   # Teal
                {"color": "#fd7e14"},   # Orange
                {"color": "#6f42c1"},   # Purple
                {"color": "#198754"},   # Green
            ]
        self.module_color_map = {}    # dynamic mapping
        self.module_color_index = 0   # round-robin
    
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
            #components.append(html.Span(match_text, style=self.styles[style_name]))
            if style_name == "module":
                module_name = match_text.strip("[]")

                # assign color if new
                if module_name not in self.module_color_map:
                    self.module_color_map[module_name] = self.module_colors[self.module_color_index % len(self.module_colors)]
                    self.module_color_index += 1

                color_style = self.module_color_map[module_name]

                # merge base + color
                span_style = {**self.styles['module'], **color_style}
            else:
                span_style = self.styles.get(style_name, {})
                
            components.append(html.Span(match_text, style=span_style))

            last_end = end
        
        if last_end < len(line):
            components.append(line[last_end:])
        
        return components if components else [line]