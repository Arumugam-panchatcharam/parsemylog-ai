from logai.pattern import Pattern
from pathlib import Path
import os
from logai.utils.constants import UPLOAD_DIRECTORY
project_dir = Path(f'{UPLOAD_DIRECTORY}/sample_project')

file_path = os.path.join(project_dir, "sample.log")
print(file_path)
parser = Pattern(project_dir=project_dir)

result_df = parser.parse_logs(file_path)
print(result_df)