import re
import os
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta, timezone
from dateutil import parser as dateparser

from drain3 import TemplateMiner
from drain3.template_miner_config import TemplateMinerConfig
from drain3.file_persistence import FilePersistence
import time

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
        result_file_path = Path(str(fpath) + ".parquet")
        tmp_result_file_path = Path(str(fpath) + ".parquet.tmp")
        
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
        logdf = pd.DataFrame()
        try:
            with open(fpath, "r", encoding='utf-8', errors='ignore') as fin:
                lines = fin.readlines()
                start = time.perf_counter()
                logdf = self._logs_to_dataframe(lines)
                end = time.perf_counter()
                print(f"Execution time: {end - start:.4f} seconds")
        except Exception as e:
            print("Read log file failed. Exception {} filename {}".format(e, fpath))
        #print(logdf)
        return logdf


    def _logs_to_dataframe(self, log_lines):
        if not log_lines:
            return pd.DataFrame()

        # Step 1: Extract timestamp + logline using your regex
        matches = [self.preprocess_regex.match(log) for log in log_lines]
        data = [
            (m.group("timestamp"), m.group("loglines")) if m else (None, log)
            for log, m in zip(log_lines, matches)
        ]
        df = pd.DataFrame(data, columns=["raw_timestamp", "loglines"])

        # Step 2: Parse timestamps robustly (does NOT touch hostapd float uptimes)
        def try_parse(ts):
            if pd.isna(ts) or not isinstance(ts, str) or not ts.strip():
                return pd.NaT

            ts = ts.strip()

            # Skip pure uptime floats here; convert later using base_time
            if re.match(r"^\d+\.\d+$", ts):
                return pd.NaT

            # YYYY-MM-DD-HH-MM-SS fallback
            if re.match(r"^\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}$", ts):
                try:
                    return datetime.strptime(ts, "%Y-%m-%d-%H-%M-%S")
                except Exception:
                    return pd.NaT

            # short ISO like 230102-12:34:56.123 -> parse manually
            if re.match(r"^\d{6}-\d{2}:\d{2}:\d{2}\.\d+", ts):
                try:
                    # take YYMMDD-HH:MM:SS (first 15 chars)
                    return datetime.strptime(ts[:15], "%y%m%d-%H:%M:%S")
                except Exception:
                    pass

            # syslog style (e.g. "Sep  3 00:28:37") - dateparser will default year=1900
            if re.match(r"^[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}$", ts):
                dt = dateparser.parse(ts)
                if dt:
                    # Inject current year later (use base_time year)
                    return dt

            # fallback to dateparser for everything else
            dt = dateparser.parse(ts)
            if dt is None:
                return pd.NaT

            # If aware, normalize to UTC-naive
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)

            return dt

        df["timestamp"] = df["raw_timestamp"].apply(try_parse)

        # Quick diagnostic
        parsed_count = df["timestamp"].notna().sum()
        print(f"Parsed timestamps: {parsed_count}/{len(df)}")

        # Step 3: Determine base_time using only parsed timestamps (no forward-fill yet)
        real_times = df["timestamp"].dropna()
        if not real_times.empty:
            # use min parsed time as base
            base_time = real_times.min()
        else:
            base_time = datetime.now()
        #print(f"Base time for hostapd timestamps: {base_time}")

        # Step 4: Convert hostapd uptime floats (raw_timestamp matches float pattern)
        def convert_hostapd_value(ts, base):
            try:
                if isinstance(ts, str) and re.match(r"^\d+\.\d+$", ts):
                    return base + timedelta(seconds=float(ts))
            except Exception:
                pass
            return pd.NaT

        hostapd_mask = df["timestamp"].isna() & df["raw_timestamp"].notna() & df["raw_timestamp"].astype(str).str.match(r"^\d+\.\d+$")
        if hostapd_mask.any():
            df.loc[hostapd_mask, "timestamp"] = df.loc[hostapd_mask, "raw_timestamp"].apply(lambda x: convert_hostapd_value(x, base_time))

        # Step 5: Forward-fill timestamps for continuation / non-timestamped lines
        # Naive forward-fill example (may over-fill in some cases):
        df["timestamp"] = df["timestamp"].ffill()

        # Step 6: Syslog-style year injection (only operate where timestamp exists and year==1900)
        try:
            syslog_mask = df["timestamp"].notna() & (df["timestamp"].dt.year == 1900)
            if syslog_mask.any():
                current_year = base_time.year
                df.loc[syslog_mask, "timestamp"] = df.loc[syslog_mask, "timestamp"].apply(lambda dt: dt.replace(year=current_year))
        except Exception as e:
            print("Syslog year injection failed:", e)

        # Step 7: Final normalization: ensure dtype is datetime64[ns] and tz-naive
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce").dt.tz_localize(None)

        # Step 8: Sort (NaT will be placed last)
        df = df.sort_values("timestamp", na_position="last").reset_index(drop=True)

        remaining_nat = df["timestamp"].isna().sum()
        if remaining_nat:
            print(f"Remaining NaT timestamps after processing: {remaining_nat}")

        # Step 9: Cleanup loglines (strip, remove empty lines)
        df = self.cleanup_loglines(df)
        return df

    def cleanup_loglines(self, df):
        df["loglines"] = df["loglines"].astype(str).str.strip()
        df = df[df["loglines"].ne("")]   # keep non-empty rows only
        df = df[~df["loglines"].eq("\\n")]  # drop literal "\n" if any
        df = df[~df["loglines"].eq("\n")]   # drop actual newline-only lines
        df = df.reset_index(drop=True)
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

