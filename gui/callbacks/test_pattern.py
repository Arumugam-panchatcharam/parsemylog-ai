from logai.pattern import Pattern
from pathlib import Path

project_dir = "user_uploads/sample_project"
file_path = Path(project_dir) / "sample.log"
parser = Pattern(project_dir=project_dir)

result_df = parser.parse_logs(file_path)
print(result_df)