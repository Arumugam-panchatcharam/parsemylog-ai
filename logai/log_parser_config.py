import re
import os
import json
import pandas as pd
from pathlib import Path

from dataclasses import dataclass, field
from typing import List

from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table as PlatypusTable, TableStyle, Preformatted
)
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

from sqlalchemy import Table
from logai.utils.constants import (
    PARSER_CONFIG_PATH,
)

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
    def __init__(self):
        self.config = self.load_config()
        self.lookup_cache = None
        self.parser_results_path = None

    # --------------------- Config Functions ---------------------
    def load_config(self):
        if not os.path.exists(PARSER_CONFIG_PATH):
            return {}
        try:
            with open(PARSER_CONFIG_PATH, "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
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

    def save_config(self, data):
        try:
            json.loads(json.dumps(data))
        except (TypeError, ValueError) as e:
            print(f"⚠️ Error saving config: {e}")
            return

        with open(PARSER_CONFIG_PATH, "w") as f:
            json.dump(data, f, indent=4)
        self.config = data

    def delete_config_entry(self, category=None, issue_title=None, delete_category=False):
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
    def build_lookup(self):
        """Builds and caches regex lookup table for all patterns in config"""
        lookup = {}
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
        print(f"Regex lookup cache built: {sum(len(v) for v in pattern_map.values())} patterns.")
        return pattern_map

    def analyse_logs(self, project_dir, files):
        if not self.lookup_cache:
            self.lookup_cache = self.build_lookup()
        return self._parse_logs(project_dir, files)
    
    # --------------------- Log Parser ---------------------
    def _parse_logs(self, project_dir, files):
        if not project_dir:
            return pd.DataFrame()
        
        self.parser_results_path = os.path.join(project_dir, "log_parser_results.parquet")
        
        results = []
        if not files or not self.lookup_cache:
            return pd.DataFrame()
        
        """         
        if os.path.exists(self.parser_results_path):
            try:
                df = pd.read_parquet(self.parser_results_path)
                return df
            except Exception as e:
                print(f"⚠️ Error loading cached results: {e}")
                self.lookup_cache = None  # Rebuild cache if error 
        """

        for filename, file_path, original_name, _, _ in files:
            if not os.path.exists(file_path):
                continue

            if not os.path.getsize(file_path):
                continue
            
            filename = Path(original_name).stem.lower().strip()

            if filename not in self.lookup_cache:
                continue

            with open(file_path, "r", errors="ignore") as f:
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
    def generate_pdf(self, project_dir):
        self.parser_results_path = os.path.join(project_dir, "log_parser_results.parquet")

        if not os.path.exists(self.parser_results_path):
            raise FileNotFoundError("No parser results found to generate report.")
        
        df = pd.read_parquet(self.parser_results_path)
        pdf_path, pdf_name = self._generate_pdf_report(df)
        return pdf_path, pdf_name
    
    def _generate_pdf_report(self, df):
        pdf_name = f"Static_Analysis_Report.pdf"
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

        flow = [Paragraph("Log Analysis Report", styles["Title"]), Spacer(1, 12)]

        grouped = (
            df.groupby(["Category", "Title", "Cause", "FileName"], dropna=False)
            .apply(lambda x: x.to_dict("records"), include_groups=False)
            .to_dict()
        )

        for (category, title, cause, filename), records in grouped.items():
            flow.append(Paragraph(f"<b>{category}</b>", title_style))
            flow.append(Paragraph(f"<b>{title}</b>", header_style))
            flow.append(Paragraph(f"<b>Cause:</b> {cause}", body_text))
            flow.append(Paragraph(f"<b>Filename:</b> {filename}", body_text))
            flow.append(Spacer(1, 6))

            for idx, rec in enumerate(records, 1):
                flow.append(
                    Paragraph(f"{idx}. <b>{rec['Description']}</b> (Frequency: {rec['Frequency']})", body_text)
                )
                flow.append(Spacer(1, 6))
                sample_logs = rec["SampleLogs"]
                if not len(sample_logs):
                    continue

                # Clean up each log and ensure proper wrapping
                for log_line in sample_logs:
                    clean_line = log_line.strip().replace("\\n", "\n")
                    #print(f"Adding log line to PDF: {clean_line}")
                    wrapped_log = Paragraph(
                        f"<font face='Courier' size='7'><pre>{clean_line}</pre></font>",
                        small_code_style
                    )
                    flow.append(wrapped_log)
                    flow.append(Spacer(1, 6))

                flow.append(Spacer(1, 6))

            flow.append(Spacer(1, 12))

        doc.build(flow)
        return pdf_path, pdf_name

