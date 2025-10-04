import os
import base64
import shutil
import tarfile
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from dash import html
from urllib.parse import quote as urlquote

from logai.utils.constants import (
    BASE_DIR, 
    MERGED_LOGS_DIR_NAME,
    MERGED_LOGS_ARCHIVE_NAME,
    TELEMETRY_PROFILES_DIR_NAME
)

from typing import List, Optional, Tuple, Dict, Any

from  logai.telemetry_parser import Telemetry2Parser

@dataclass
class ConfigEntry:
    name: str
    supported_config: str
    supported_files: List[str]

@dataclass
class ConfigIndex:
    supported_files: List[ConfigEntry]

    @staticmethod
    def load_from_file(index_path: str) -> 'ConfigIndex':
        with open(index_path, 'r') as f:
            raw_data = json.load(f)
        entries = [ConfigEntry(**entry) for entry in raw_data.get("supported_files", [])]
        return ConfigIndex(supported_files=entries)

    def find_config_for_file(self, filename: str) -> str:
        filename_base = os.path.basename(filename)

        for entry in self.supported_files:
            for supported_name in entry.supported_files:
                if supported_name.lower() in filename_base.lower():
                    return entry.supported_config
        raise ValueError(f"No config found for file: {filename}")

class FileManager:
    """Processor for handling uploaded files in the application."""
    def __init__(self):
        self.directory = None
        self.merged_logs_path = None

        #os.makedirs(self.directory, exist_ok=True)
        #os.makedirs(self.merged_logs_path, exist_ok=True)

    # === Save uploaded file to local folder ===
    def save_file(self, name, content):
        content_type, content_string = content.split(',')
        decoded = base64.b64decode(content_string)
        file_path = os.path.join(self.directory, name)
        with open(file_path, "wb") as f:
            f.write(decoded)
    """
    def save_file(self, name, content):
        data = content.encode("utf8").split(b";base64,")[1]
        with open(os.path.join(self.directory, name), "wb") as fp:
            fp.write(base64.decodebytes(data))
    """ 
    def uploaded_files(self):
        files = []
        for filename in os.listdir(self.directory):
            path = os.path.join(self.directory, filename)
            if os.path.isfile(path):
                files.append(filename)
        return files
    
    def create_merged_logs_archive(self, project_name, project_path, merged_logs_path, telemetry_path):
        if not os.listdir(merged_logs_path):
            return
        if os.path.exists(telemetry_path) and len(os.listdir(telemetry_path)) > 0:
            # Copy the first telemetry profile to the merged logs directory
            telemetry_report_path = os.path.join(telemetry_path, "Telemetry2_report.xlsx")
            copyto_path = os.path.join(merged_logs_path, "Telemetry2_report.xlsx")
            if os.path.exists(os.path.join(telemetry_path, "Telemetry2_report.xlsx")):
                shutil.copyfile(telemetry_report_path, copyto_path)
            else:
                print("Telemetry2_report.xlsx not found in TELEMETRY_PROFILES.")

        archive = MERGED_LOGS_ARCHIVE_NAME + "-" + str(project_name)
        # Create a zip file of the merged logs directory
        shutil.make_archive(os.path.join(project_path, archive), 'zip', os.path.join(merged_logs_path))

    def file_download_link(self, filename):
        location = "/download/{}".format(urlquote(filename))
        return html.A(filename, href=location)
    
    def process_uploaded_files(self, project_path, project_name):
        """Process uploaded files by extracting and merging logs."""
        self.directory = project_path
        if not os.path.exists(self.directory):
            raise FileNotFoundError(f"Upload directory '{self.directory}' does not exist.")
        
        self.merged_logs_path = os.path.join(self.directory, MERGED_LOGS_DIR_NAME)
        self.telemetry_path = os.path.join(self.directory, TELEMETRY_PROFILES_DIR_NAME)
        os.makedirs(self.merged_logs_path, exist_ok=True)

        print(f"Processing uploaded files in {self.directory} ...")
        
        # Create a temporary directory for extraction
        temp_dir = os.path.join(self.directory, "temp")
        os.makedirs(temp_dir, exist_ok=True)
        for file in os.listdir(self.directory):
            if os.path.isdir(os.path.join(self.directory,file)):
                continue
            filename = file.lower()
            if filename.endswith(".tgz") or filename.endswith(".tar.gz"):
                src_file = os.path.join(self.directory, file)
                base = file.rsplit('.', 2)[0]
                dest = os.path.join(temp_dir, base)
                os.makedirs(dest, exist_ok=True)
                with tarfile.open(src_file, "r:gz") as tar:
                    tar.extractall(path=dest)
            else:
                shutil.move(os.path.join(self.directory, file), os.path.join(self.merged_logs_path, file))
        
        self._merge_files(temp_dir, output_dir=self.merged_logs_path)
        self.clean_temp_files()
        # remove temporary directory
        shutil.rmtree(temp_dir)

        # Extract Telemetry Profiles
        temp_telemetry_parser = Telemetry2Parser()
        temp_telemetry_parser.extract_telemetry_reports(project_path=self.directory)
        temp_telemetry_parser.start_processing()

        self.create_merged_logs_archive(project_name=project_name,
                                        project_path=self.directory, 
                                        merged_logs_path=self.merged_logs_path, 
                                        telemetry_path=self.telemetry_path)
        
        print("Process uploaded files done")

    def _merge_files(self, temp_dir, output_dir="./merged_logs"):
        # Check if directory empty
        if not os.listdir(temp_dir):
            return
        
        folder_path = temp_dir
        folders = os.listdir(folder_path)
        folders.sort()
 
        # ----------- Stage 1: Initial merge by normalized name -----------
        for dirname in folders:
            content = os.path.join(folder_path, dirname)
            dirs = os.listdir(content)
            if len(dirs) == 1:
                in_path = os.path.join(content, dirs[0])
            else:
                in_path = content
 
            for in_filename in os.listdir(in_path):
                if "2023" not in in_filename and "2024" not in in_filename and "2025" not in in_filename:
                    out_filename = in_filename
                else:
                    out_filename = in_filename[19:]
                    if "024-" in out_filename:
                        out_filename = in_filename[37:]
                    if "1_" in out_filename:
                        out_filename = out_filename[2:]
                    if out_filename and out_filename[0] in "0123456789_":
                        out_filename = out_filename[1:]
 
                out_file = os.path.join(output_dir, out_filename)
                in_file = os.path.join(in_path, in_filename)
 
                with open(in_file, "rb") as rd, open(out_file, "ab") as wr:
                    shutil.copyfileobj(rd, wr)
 
        # ----------- Stage 2: Merge rotated logs and delete originals -----------
        merged_files = os.listdir(output_dir)
        base_map = defaultdict(list)
 
        for filename in merged_files:
            match = re.match(r"(.+?)(?:\.(\d+))?$", filename)
            if match:
                base_name = match.group(1)
                base_map[base_name].append(filename)
 
        for base_name, versions in base_map.items():
            if len(versions) <= 1:
                continue
 
            def suffix_key(f):
                m = re.search(r"\.(\d+)$", f)
                return int(m.group(1)) if m else -1
 
            versions.sort(key=suffix_key)
            merged_path = os.path.join(output_dir, base_name + "_final_merged.log")
 
            with open(merged_path, "wb") as wr:
                for version in versions:
                    full_path = os.path.join(output_dir, version)
                    with open(full_path, "rb") as rd:
                        shutil.copyfileobj(rd, wr)
                    os.remove(full_path)
 
            #print(f"Merged and cleaned: {versions} -> {merged_path}")
 
        # ----------- Stage 3: Sort _final_merged.log files by timestamp string -----------
        for filename in os.listdir(output_dir):
            if filename.endswith("_final_merged.log"):
                file_path = os.path.join(output_dir, filename)
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()
 
                    def extract_ts_str(line: str):
                        parts = line.split()
                        return parts[0] if parts else ""
 
                    lines.sort(key=extract_ts_str)
 
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.writelines(lines)
 
                    #print(f"Sorted by timestamp string: {filename}")
                except Exception as e:
                    print(f"Error sorting {filename}: {e}")

        for filename in os.listdir(output_dir):
            if filename.endswith("_final_merged.log"):
                file_path = os.path.join(output_dir, filename)
                base_fname = os.path.basename(file_path)
                remove_tag = base_fname.replace("_final_merged.log", "")
                new_file_name = os.path.join(output_dir, remove_tag)
                #print("file {} rename to {} \n".format(file_path, new_file_name))
                os.rename(file_path, new_file_name)
    
    def clean_temp_files(self):
        for name in os.listdir(self.directory):
            full_path = os.path.join(self.directory, name)
            if not os.path.isdir(full_path):
                os.remove(full_path)
        #os.rmdir(input_dir)
        #print(f"Cleaned all contents from {input_dir}")

    def list_uploaded_files(self):
        """List all files saved in the uploads folder."""
        try:
            return sorted(os.listdir(self.directory))
        except FileNotFoundError:
            return []
        
    def load_config(self, filename):

        root_dir = os.path.dirname(os.path.abspath(__file__))
        config_list_path = os.path.join(root_dir, "../configs", "config_list.json")

        if os.path.exists(config_list_path):
            #print(f"Loading config from {config_list_path}")
            self.config_index = ConfigIndex.load_from_file(config_list_path)
            if self.config_index:
                file_config = self.config_index.find_config_for_file(filename)
                self.config_path = os.path.join(root_dir, "../configs", file_config)
                #print("config {}, path {}".format(file_config, self.config_path))
                if os.path.exists(self.config_path):
                    try:
                         with open(self.config_path, 'r') as f:
                            raw_data = json.load(f)
                            return raw_data
                    except json.JSONDecodeError as e:
                        print(f"Error decoding invalid JSON: {e}\n")
                    except Exception as e:
                        print(f"An unexpected error occurred: {e}\n")