import re
import os
import glob
from logai.utils import json_helper
import pandas as pd
from enum import Enum
from logai.utils.constants import (
    BASE_DIR, 
    MERGED_LOGS_DIR_NAME,
    TELEMETRY_PROFILES_DIR_NAME
)

class DML(str, Enum):
    TIME = ".Time"
    
    MEM_AVAILABLE = ".meminfoavailable_split"
    MEM_CACHED = ".cachedMem_split"
    MEM_FREE = ".flash_usage_nvram_free_split"
    
    # CPU
    CPU_TEMP = ".cpu_temp_split"
    CPU_USAGE = ".CPUUsage"

    # Device Info
    MAC_ADDRESS = ".mac"
    VER = ".Version"
    PROD_CLS = ".ProductClass"

    SERIAL_NUMBER = ".SerialNumber"
    SW_VERSION = ".Version"
    HW_VERSION = ".hardwareversion"
    MODEL_NAME = ".ModelName"
    MANUFACTURER = ".manufacturer"
    EROUTER = ".erouterIpv4"

    # device status
    WAN_MODE = ".wan_access_mode_split"
    RADIO1_EN = ".wifi_radio_1_enable"
    RADIO2_EN = ".wifi_radio_2_enable"
    AP1_EN = ".wifi_accesspoint_1_status"
    AP2_EN = ".wifi_accesspoint_2_status"
    SSID1 = ".wifi_ssid_1_ssid"
    SSID2 = ".wifi_ssid_2_ssid"
    AIETIES_EDGE = ".airties_edge_enable"
    
    # WAN Sts
    WAN_BYTES_RCVD = ".wan_bytesReceived"
    WAN_BYTES_SENT = ".wan_bytesSent"
    WAN_PKT_RCVD = ".wan_packetsReceived"
    WAN_PKT_SENT = ".wan_packetsSent"

    # SSID Stats
    SSID1_PKT_SENT = ".wifi_ssid_1_stats_packetssent"
    SSID1_PKT_RCVD = ".wifi_ssid_1_stats_packetsreceived"
    SSID1_BYTE_SENT = ".wifi_ssid_1_stats_bytessent"
    SSID1_BYTE_RCVD = ".wifi_ssid_1_stats_bytesreceived"
    SSID1_ERROR_SENT = ".wifi_ssid_1_stats_errorssent"
    SSID1_ERROR_RCVD = ".wifi_ssid_1_stats_errorsreceived"

    # Mem usage
    MESH_MEM_USAGE_SPLIT = ".mesh_memory_usage_split"
    CCSP_MEM_USAGE_SPLIT = ".ccsp_memory_usage_split"

class Telemetry2Parser:
    """
    Implementation of file data loader, reading log record objects from local files.
    """

    def __init__(self):
        self.log_prefix_pattern = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2} [^ ]+ T\d\.\w+ \[tid=\d+\] ?", re.MULTILINE)
        self.filename = "telemetry2_0"
        self.file_path = None
        self.telemetry_report = pd.DataFrame()
        self.telemetry_path = None
        
    def extract_telemetry_reports(self, project_path):
        if not os.path.exists(project_path):
            print(f"Merged Logs path '{project_path}' does not exist.")
            return
        
        self.telemetry_path = os.path.join(project_path, TELEMETRY_PROFILES_DIR_NAME)
        os.makedirs(self.telemetry_path, exist_ok=True)

        inside_json = False
        open_braces = 0
        json_buffer = ""
        json_blocks = []
        
        # Check for telemetry2_0 file
        merged_logs_path = os.path.join(project_path, MERGED_LOGS_DIR_NAME)
        for fname in os.listdir(merged_logs_path):
            if fname.startswith(self.filename):
                self.file_path = os.path.join(merged_logs_path, fname)
                break
        
        if self.file_path is None or not os.path.isfile(self.file_path):
            print(f"Telemetry file '{self.filename}' not found in '{merged_logs_path}'.")
            return
        
        with open(self.file_path, "r") as infile:
            for line in infile:
                # Remove log prefixes from line (works anywhere in the line)
                clean_line = self.log_prefix_pattern.sub("", line)
        
                # For every collected line, strip newlines and spaces immediately:
                stripped_line = clean_line.strip().replace('\n', '').replace('\r', '')
                if not inside_json:
                    brace_pos = stripped_line.find("{")
                    if brace_pos != -1:
                        inside_json = True
                        json_buffer = stripped_line[brace_pos:]
                        open_braces = json_buffer.count("{") - json_buffer.count("}")
                        if open_braces == 0:
                            json_blocks.append(json_buffer)
                            inside_json = False
                            json_buffer = ""
                else:
                    json_buffer += stripped_line
                    open_braces += stripped_line.count("{") - stripped_line.count("}")
                    if open_braces == 0:
                        json_blocks.append(json_buffer)
                        inside_json = False
                        json_buffer = ""
        
        for idx, json_str in enumerate(json_blocks, 1):
            # Remove everything after the last closing '}]}' (or '}}'), plus whitespace and percent
            # Prefer to anchor on '}]}' for your Report use case
            m = re.search(r'(.*\}\]\})', json_str, re.DOTALL)
            if m:
                json_str = m.group(1)
            else:
                # Fallback: Remove trailing percent and whitespace
                json_str = re.sub(r'[%\s]+$', '', json_str)
            outname = f"Telemetry2_report_{idx}.json"
            out_path = os.path.join(self.telemetry_path, outname)
            with open(out_path, "w", encoding="utf-8") as fout:
                fout.write(json_str)

    def get_timestamp(self):
        data = self.telemetry_report
        timestamp = pd.DataFrame()

        if data.empty:
            return False
        
        for col in data.columns:
            if col.endswith(DML.TIME):
                timestamp = self.telemetry_report[col]

        return timestamp
    
    def get_column_name(self, value):
        data = self.telemetry_report
        
        if self.telemetry_report.empty:
            print("Telemetry Report Empty!")
            return None
        else:
            matching_columns = [col for col in data.columns if col.endswith(value)]
            return matching_columns[0]

    def get_telemetry_col(self,value):
        data = self.telemetry_report

        if self.telemetry_report.empty:
            print("Telemetry Report Empty!")
            return None
        else:
            matching_columns = [col for col in data.columns if col.endswith(value)]
            if len(matching_columns):
                return data[matching_columns[0]]
            else:
                print("Column not Found!", value)
                return None

    def get_telemetry_value(self, value, index=0):
        data = self.telemetry_report
        
        if self.telemetry_report.empty:
            print("Telemetry Report Empty!")
            return None
        else:
            matching_columns = [col for col in data.columns if col.endswith(value)]
            #print(matching_columns)
            if len(matching_columns):
                latest = data.iloc[-1]
                return latest[matching_columns[index]]
            else:
                print("Column not Found!", value)
                return None
    
    def _key_value_split(self, raw_data, timestamp):
        process_entries = raw_data.strip().split(';')
        parsed_data = []
        
        for entry in process_entries:
            entry = entry.strip()
            if not entry:
                continue
            fields = entry.split('|')
            data = {}
            for field in fields:
                key, value = field.split('=')
                data[key.strip()] = value.strip()
                data['TimeStamp'] = timestamp
            parsed_data.append(data)
        
        df = pd.DataFrame(parsed_data)
        return df
    
    def extract_ccsp_mem_split_data(self, data=pd.DataFrame()):
        data = self.telemetry_report
        result_df = pd.DataFrame()
        if data.empty:
            return result_df

        time = self.get_timestamp()
        ccsp_mem_usage_raw = self.get_telemetry_col(DML.CCSP_MEM_USAGE_SPLIT)
        
        result_df = pd.DataFrame()
        for process_data, t in zip(ccsp_mem_usage_raw, time):
            if pd.isna(process_data):
                continue
            parsed_data = self._key_value_split(process_data, t)
            result_df = pd.concat([result_df, parsed_data], ignore_index=True)

        return result_df

    def start_processing(self):
        telemetry_report = pd.DataFrame()

        DATA_LIST = []
        # ---------- Load & prep once at start (or via Upload component) ----------
        for fname in glob.glob(self.telemetry_path + "/*.json"):
            RAW = json_helper.load_json(fname)
            if RAW is not None:
                data = json_helper.json_to_df(RAW)
                for col in data.columns:
                    if col.endswith(DML.TIME):
                        data[col] = pd.to_datetime(
                                    data[col],
                                    format="%Y-%m-%d %H:%M:%S",
                                )
                        #print("DataTime", data[col])
                        break
                DATA_LIST.append(data)

        if len(DATA_LIST) == 0:
            return
        
        combined_df = pd.concat(DATA_LIST, ignore_index=True)

        for col in combined_df.columns:
            if col.endswith(DML.TIME):
                telemetry_report = combined_df.sort_values(by=col, axis=0, ignore_index=True)
                break

        excel_path = os.path.join(self.telemetry_path, "Telemetry2_report.xlsx")
        try:
            with pd.ExcelWriter(excel_path) as writer:
                telemetry_report.to_excel(writer)
        except Exception as e:
            print("Excepton occured ", e)

        #print(telemetry_report.columns)
        self.telemetry_report = telemetry_report

    def get_telemetry_report(self):
        return self.telemetry_report