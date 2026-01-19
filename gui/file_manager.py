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
from log_merger import LogMerger
from typing import List

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
        # Merge log files
        merger = LogMerger(self.directory, self.merged_logs_path)
        merger.merge_logs()

        # Extract Telemetry Profiles
        temp_telemetry_parser = Telemetry2Parser()
        temp_telemetry_parser.extract_telemetry_reports(project_path=self.directory)
        temp_telemetry_parser.start_processing()

        self.create_merged_logs_archive(project_name=project_name,
                                        project_path=self.directory, 
                                        merged_logs_path=self.merged_logs_path, 
                                        telemetry_path=self.telemetry_path)
        
        print("Process uploaded files done")

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