"""
Config-based log parser for CPE logs.

Parses log files using regex patterns defined in a JSON config.
Generates PDF reports from parsed results.

Portable: config path is injectable via LogAIConfig.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from logai.config import LogAIConfig, default_config

logger = logging.getLogger(__name__)


@dataclass
class RegexPattern:
    type: str
    pattern: str
    description: str

@dataclass
class CPELog:
    FileName: str
    Regex: List[RegexPattern] = field(default_factory=list)

@dataclass
class Issue:
    Title: str
    Cause: str
    CPELogs: List[CPELog] = field(default_factory=list)

@dataclass
class IssueCategory:
    name: str
    Issues: List[Issue] = field(default_factory=list)

class LogParserConfig:
    """Config-based regex log parser. Portable: accepts LogAIConfig for path resolution."""

    def __init__(self, config: Optional[LogAIConfig] = None) -> None:
        self._config = config or default_config()
        self.config: Dict[str, Any] = self.load_config()
        self.lookup_cache: Optional[Dict[str, List[Dict[str, Any]]]] = None
        self.parser_results_path: Optional[str] = None

    # --------------------- Config Functions ---------------------
    def load_config(self) -> Dict[str, Any]:
        """Load parser config from JSON. Returns empty dict if not found."""
        config_path = self._config.resolve_parser_config_path()
        if not config_path.exists():
            logger.debug(f"[LogParserConfig] Config not found at {config_path}")
            return {}
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            logger.warning(f"[LogParserConfig] Invalid JSON in {config_path}: {e}")
            return {}
    
    def _load_config(self) -> List[IssueCategory]:
        if not self.config:
            return []
        raw = self.config
        categories = []
        for category_name, issue_list in raw.items():
            issues = []
            for issue_data in issue_list:
                cpe_logs = []
                for cpe in issue_data.get("CPELogs", []):
                    regex_objs = [RegexPattern(**r) for r in cpe.get("Regex", [])]
                    cpe_logs.append(CPELog(FileName=cpe.get("FileName", ""), Regex=regex_objs))
                issues.append(Issue(Title=issue_data.get("Title", ""),
                                    Cause=issue_data.get("Cause", ""),
                                    CPELogs=cpe_logs))
            categories.append(IssueCategory(name=category_name, Issues=issues))
        return categories

    def save_config(self, data: Dict[str, Any]) -> bool:
        """Save config to JSON. Returns True on success."""
        try:
            json.loads(json.dumps(data))
        except (TypeError, ValueError) as e:
            logger.error(f"[LogParserConfig] Error saving config: {e}")
            return False

        config_path = self._config.resolve_parser_config_path()
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
        self.config = data
        return True

    def delete_config_entry(
        self,
        category: Optional[str] = None,
        issue_title: Optional[str] = None,
        delete_category: bool = False,
    ) -> Tuple[bool, str]:
        """Delete an issue or entire category from config."""

        if delete_category:
            if category in self.config:
                del self.config[category]
            else:
                return False, f"Category '{category}' not found."
        else:
            if category not in self.config:
                return False, f"Category '{category}' not found."
            before = len(self.config[category])
            self.config[category] = [i for i in self.config[category] if i.get("Title") != issue_title]
            after = len(self.config[category])
            if before == after:
                return False, f"Issue '{issue_title}' not found in '{category}'."

        # Save back
        self.save_config(self.config)
        return True, "Deletion successful."

    # --------------------- Build Regex Cache ---------------------
    def build_lookup(self) -> Dict[str, List[Dict[str, Any]]]:
        """Builds and caches regex lookup table for all patterns in config."""
        lookup: Dict[str, List[Dict[str, Any]]] = {}
        if not self.config:
            return lookup
        config = self._load_config()
        pattern_map = {}
        for category in config:
            for issue in category.Issues:
                for cpe in issue.CPELogs:
                    fname = cpe.FileName.lower().strip()
                    for regex_obj in cpe.Regex:
                        entry = {
                            "Category": category.name,
                            "Title": issue.Title,
                            "Cause": issue.Cause,
                            "RegexType": regex_obj.type,
                            "Description": regex_obj.description,
                            "Pattern": regex_obj.pattern,
                            "RegexCompiled": re.compile(regex_obj.pattern),
                        }
                        pattern_map.setdefault(fname, []).append(entry)
        total = sum(len(v) for v in pattern_map.values())
        logger.info(f"[LogParserConfig] Regex lookup cache built: {total} patterns")
        return pattern_map

    def analyse_logs(
        self,
        project_dir: Path,
        files: List[Tuple[str, str, str, int, Any]],
    ) -> pd.DataFrame:
        if not self.lookup_cache:
            self.lookup_cache = self.build_lookup()
        return self._parse_logs(project_dir, files)
    
    # --------------------- Log Parser ---------------------
    def _parse_logs(
        self,
        project_dir: Path,
        files: List[Tuple[str, str, str, int, Any]],
    ) -> pd.DataFrame:
        if not project_dir:
            return pd.DataFrame()
        proj_path = Path(project_dir)

        self.parser_results_path = str(proj_path / "log_parser_results.parquet")

        results: List[Dict[str, Any]] = []
        if not files or not self.lookup_cache:
            return pd.DataFrame()

        for filename, file_path, original_name, _, _ in files:
            fpath = Path(file_path)
            if not fpath.exists():
                continue
            if fpath.stat().st_size == 0:
                continue
            
            filename = Path(original_name).stem.lower().strip()

            if filename not in self.lookup_cache:
                continue

            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            
            #print(f"Parsing file: {filename} with {len(lines)} lines.")
            for rule in self.lookup_cache[filename]:
                matches = []
                pattern = rule["RegexCompiled"]
                for line in lines:
                    if pattern.search(line):
                        matches.append(line)
                        if len(matches) >= 100:
                            break
                if matches:
                    results.append({
                        "Category": rule["Category"],
                        "Title": rule["Title"],
                        "Cause": rule["Cause"],
                        "Description": rule["Description"],
                        "Frequency": len(matches),
                        "SampleLogs": matches[:5],  # First 5 matches
                        "FileName": filename,
                    })

        if not results:
            return pd.DataFrame()

        df = pd.DataFrame(results)
        if self.parser_results_path:
            df.to_parquet(self.parser_results_path, index=False)
        return df

    # --------------------- PDF Report Generator ---------------------
    def generate_pdf(
        self, project_dir: Path, project_name: str
    ) -> Tuple[str, str]:
        """Generate PDF report from parsed results. Returns (pdf_path, pdf_name)."""
        results_path = Path(project_dir) / "log_parser_results.parquet"
        self.parser_results_path = str(results_path)

        if not results_path.exists():
            raise FileNotFoundError(
                f"No parser results found at {results_path} to generate report."
            )
        
        df = pd.read_parquet(self.parser_results_path)
        pdf_path, pdf_name = self._generate_pdf_report(df, project_name)
        return pdf_path, pdf_name
    
    def _generate_pdf_report(
        self, df: pd.DataFrame, project_name: str
    ) -> Tuple[str, str]:
        pdf_name = f"Static_Analysis_Report-{project_name}.pdf"
        pdf_path = os.path.join(os.path.dirname(self.parser_results_path), pdf_name)
        doc = SimpleDocTemplate(pdf_path, pagesize=letter)
        styles = getSampleStyleSheet()

        # Custom styles
        small_code_style = ParagraphStyle(
            "SmallCode",
            parent=styles["Code"],
            fontName="Courier",
            fontSize=6,
            leading=8,
            backColor=colors.whitesmoke,
            leftIndent=15,
            rightIndent=15,
            borderPadding=4,
        )

        body_text = styles["BodyText"]
        title_style = styles["Heading2"]
        header_style = styles["Heading3"]

        # Highlight style for high-frequency descriptions
        highlight_body_style = ParagraphStyle(
            "HighlightBody",
            parent=body_text,
            backColor=colors.lavenderblush,  # light red background
            borderPadding=4,
        )

        flow = [Paragraph("Log Analysis Report", styles["Title"]), Spacer(1, 12)]

        # Group by Category first, then within each Category, group by Title, Cause, Filename
        category_groups = df.groupby("Category", dropna=False)

        for category, cat_df in category_groups:
            # Print category once
            flow.append(Paragraph(f"<b>{category}</b>", title_style))
            flow.append(Spacer(1, 6))

            # Now group the rest
            issue_groups = (
                cat_df.groupby(["Title", "Cause", "FileName"], dropna=False)
                .apply(lambda x: x.to_dict("records"), include_groups=False)
                .to_dict()
            )

            for (title, cause, filename), records in issue_groups.items():
                flow.append(Paragraph(f"<b>{title}</b>", header_style))
                flow.append(Paragraph(f"<b>Cause:</b> {cause}", body_text))
                flow.append(Paragraph(f"<b>Filename:</b> {filename}", body_text))
                flow.append(Spacer(1, 6))

                for idx, rec in enumerate(records, 1):
                    freq = rec.get("Frequency", 0)
                    desc_style = highlight_body_style if freq > 10 else body_text

                    flow.append(
                        Paragraph(
                            f"{idx}. <b>{rec['Description']}</b> (Frequency: {rec['Frequency']})",
                            desc_style,
                        )
                    )
                    flow.append(Spacer(1, 6))

                    sample_logs = rec["SampleLogs"]
                    if not len(sample_logs):
                        continue

                    for log_line in sample_logs:
                        clean_line = log_line.strip().replace("\\n", "\n")
                        wrapped_log = Paragraph(
                            f"<font face='Courier' size='7'><pre>{clean_line}</pre></font>",
                            small_code_style,
                        )
                        flow.append(wrapped_log)
                        flow.append(Spacer(1, 6))

                flow.append(Spacer(1, 12))

            flow.append(Spacer(1, 18))  # Add extra space after category

        doc.build(flow)
        return pdf_path, pdf_name

