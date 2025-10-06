import re
import os
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
from dateutil import parser as dateparser

from drain3 import TemplateMiner
from drain3.template_miner_config import TemplateMinerConfig
from drain3.file_persistence import FilePersistence

# ---------------------
# Drain3 Parser Wrapper
# ---------------------
"""
Drain3 returns a dictionary like this when you call add_log_message(line)
{
  "change_type": "cluster_created",
  "cluster_id": 1,
  "template_mined": "User <NUM> logged in at <DATETIME>",
  "parameter_list": ["123", "2025-10-01 12:34:56,789"]
}
"""
class Pattern:
    def __init__(self, project_dir=None, sim_th=None, depth=None):
        config = TemplateMinerConfig()
        config.load("drain3.ini")  # load from external ini file
        self.preprocess_regex = re.compile(
                r"^(?P<timestamp>("
                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"          # 2023-10-02T12:34:56
                r"|\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}"         # 2023-10-02-12-34-56
                r"|\d{6}-\d{2}:\d{2}:\d{2}\.\d+"                # 230102-12:34:56.123
                r"|[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}" # Sep  3 00:28:37
                r"|\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2}"        # 2023-10-02 12:34:56
                r"|\d+\.\d+"                                    # 175383.097855
                r"))[:\s]+(?P<loglines>.*)$"
            )
        self.headers = ["timestamp", "loglines"]
        persistence = FilePersistence(f"{project_dir}/drain3_state.json") if project_dir and os.path.exists(project_dir) else None
        self.template_miner = TemplateMiner(persistence,config=config)
        #self.template_miner = TemplateMiner(config=config)
        self.log_df = pd.DataFrame()
        self.results = pd.DataFrame()

    def parse_logs(self, fpath):
        # Check if already parsed file exists
        result_file_path = Path(fpath + ".parquet")
        tmp_result_file_path = Path(fpath + ".parquet.tmp")
        
        #print(f"Result file path: {result_file_path}")
        if os.path.exists(result_file_path):
            return pd.read_parquet(result_file_path), result_file_path

        self.log_df = self._read_logs(fpath)
        if self.log_df.empty:
            return pd.DataFrame(), None
        
        self.results = pd.DataFrame()

        def extract_template_and_args(logline):
            # Step 1: Get the template from the logline
            """
            dict returned by add_log_message():
            {
                "change_type": "cluster_created",
                "cluster_id": 1,
                "template_mined": "<DATETIME> <THREADID> error"
            }
            """
            result = self.template_miner.add_log_message(logline)
            
            template = result["template_mined"]
            # Step 2: Extract parameters from logline based on the template
            params = self.template_miner.get_parameter_list(template, logline)
   
            return template, params

        # Apply to DataFrame
        self.log_df[["template", "parameter_list"]] = self.log_df["loglines"].apply(
                lambda x: pd.Series(list(extract_template_and_args(x)))
            )
        
        self.results = self.log_df[['timestamp', 'loglines', 'template', 'parameter_list']].copy()
        self.results.to_parquet(tmp_result_file_path, index=False)
        os.replace(str(tmp_result_file_path), str(result_file_path))

        try:
            self.template_miner.save_state()
        except Exception:
            pass
        
        return self.results, result_file_path
    
    def _read_logs(self, fpath):
        try:
            with open(fpath, "r", encoding='utf-8', errors='ignore') as fin:
                lines = fin.readlines()
                logdf = self._logs_to_dataframe(lines)
            return logdf
        except Exception as e:
            print("Read log file failed. Exception {}.".format(e))
            return pd.DataFrame()

    def _logs_to_dataframe(self, log_lines):
        # Step 1: Extract timestamp and logline using regex
        matches = [self.preprocess_regex.match(log) for log in log_lines]
        data = []
        for i, m in enumerate(matches):
            if m:
                data.append((m.group("timestamp"), m.group("loglines")))
            else:
                data.append((None, log_lines[i]))
        
        df = pd.DataFrame(data, columns=["raw_timestamp", "loglines"])

        # Step 2: Parse standard & non-standard datetimes
        def try_parse(ts):
            if pd.isna(ts):
                return pd.NaT
            try:
                # Hostapd uptime float will fail here
                return dateparser.parse(ts)
            except Exception:
                return pd.NaT

        df["timestamp"] = df["raw_timestamp"].apply(try_parse)

        # Step 3: Determine base time for hostapd timestamps
        real_times = df["timestamp"].dropna()
        base_time = real_times.min() if not real_times.empty else datetime.now()

        # Step 4: Handle hostapd-style uptime floats
        def convert_hostapd(ts, base):
            if ts is None:
                return pd.NaT
            if re.match(r"^\d+\.\d+$", ts):
                return base + timedelta(seconds=float(ts))
            return pd.NaT  # already parsed in step 2

        hostapd_mask = df["timestamp"].isna() & df["raw_timestamp"].notna()
        df.loc[hostapd_mask, "timestamp"] = df.loc[hostapd_mask, "raw_timestamp"].apply(lambda x: convert_hostapd(x, base_time))

        # Step 5: Optionally, inject current year for syslog-style timestamps without year
        syslog_mask = df["timestamp"].dt.year == 1900
        current_year = base_time.year
        df.loc[syslog_mask, "timestamp"] = df.loc[syslog_mask, "timestamp"].apply(
            lambda dt: dt.replace(year=current_year)
        )

        # Step 6: Sort by timestamp
        df = df.sort_values("timestamp").reset_index(drop=True)
        
        return df

    def _normalize_timestamp(ts_str, base_time=None):
        """
        Try to parse timestamp string into datetime.
        - If it's a float-like uptime (e.g. 175383.097855), convert to base_time + timedelta
        - Else, use dateutil.parser
        """
        try:
            # hostapd uptime style
            if re.match(r"^\d+\.\d+$", ts_str):
                if base_time is None:
                    # Default base: UNIX epoch (1970-01-01)
                    base_time = datetime(1970, 1, 1)
                seconds = float(ts_str)
                return base_time + timedelta(seconds=seconds)
            
            # try parsing standard datetime formats
            return dateparser.parse(ts_str)
        except Exception:
            return None

