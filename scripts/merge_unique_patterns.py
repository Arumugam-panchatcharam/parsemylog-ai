#!/usr/bin/env python3
"""
Generic script to merge unique patterns from multiple Excel files.

Usage:
    python merge_unique_patterns.py file1.xlsx file2.xlsx file3.xlsx -o output.xlsx
    
The script will:
1. Read all input Excel files
2. For each sheet (except INDEX), combine patterns from all files
3. Remove duplicate patterns based on the 'Pattern' column
4. Create a merged Excel file with unique patterns
"""

import pandas as pd
import argparse
import sys
from pathlib import Path
from typing import List, Dict
import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill
from openpyxl.utils.dataframe import dataframe_to_rows


def read_excel_file(file_path: str) -> Dict[str, pd.DataFrame]:
    """
    Read an Excel file and return a dictionary of DataFrames.
    
    Args:
        file_path: Path to the Excel file
        
    Returns:
        Dictionary with sheet names as keys and DataFrames as values
    """
    print(f"Reading {file_path}...")
    excel_file = pd.ExcelFile(file_path)
    sheets = {}
    
    for sheet_name in excel_file.sheet_names:
        df = pd.read_excel(excel_file, sheet_name=sheet_name)
        sheets[sheet_name] = df
        print(f"  - Sheet '{sheet_name}': {len(df)} rows")
    
    return sheets


def merge_patterns(files: List[str], pattern_column: str = 'Pattern') -> Dict[str, pd.DataFrame]:
    """
    Merge patterns from multiple Excel files, keeping unique patterns with aggregated values.
    
    For duplicate patterns:
    - Frequency: comma-separated values from each file
    - CPE Count: comma-separated values from each file
    - Sample Log Lines: kept from first occurrence
    
    Args:
        files: List of Excel file paths
        pattern_column: Name of the column to use for uniqueness (default: 'Pattern')
        
    Returns:
        Dictionary with sheet names as keys and merged DataFrames as values
    """
    all_sheets = {}
    
    # Read all files
    for file_path in files:
        if not Path(file_path).exists():
            print(f"Warning: File not found: {file_path}")
            continue
            
        sheets = read_excel_file(file_path)
        
        for sheet_name, df in sheets.items():
            if sheet_name not in all_sheets:
                all_sheets[sheet_name] = []
            all_sheets[sheet_name].append(df)
    
    # Merge and deduplicate
    merged_sheets = {}
    print("\nMerging patterns...")
    
    for sheet_name, dfs in all_sheets.items():
        print(f"\nProcessing sheet '{sheet_name}'...")
        
        # Concatenate all DataFrames for this sheet
        combined_df = pd.concat(dfs, ignore_index=True)
        print(f"  - Total rows before deduplication: {len(combined_df)}")
        
        # For INDEX sheet, just keep as is (or handle differently)
        if sheet_name == 'INDEX':
            merged_sheets[sheet_name] = combined_df
            print(f"  - INDEX sheet kept as is")
            continue
        
        # Check if pattern column exists
        if pattern_column not in combined_df.columns:
            print(f"  - Warning: '{pattern_column}' column not found in sheet '{sheet_name}'")
            print(f"  - Available columns: {combined_df.columns.tolist()}")
            merged_sheets[sheet_name] = combined_df
            continue
        
        # Aggregate duplicate patterns with comma-separated values
        has_frequency = 'Frequency' in combined_df.columns
        has_cpe_count = 'CPE Count' in combined_df.columns
        has_sample_logs = 'Sample Log Lines' in combined_df.columns
        
        # Define aggregation functions
        agg_funcs = {}
        
        # For File Name, keep first
        if 'File Name' in combined_df.columns:
            agg_funcs['File Name'] = 'first'
        
        # For Pattern, keep first (this is our groupby key, but pandas needs it in agg)
        # We'll handle this after groupby
        
        # For Frequency, join with comma
        if has_frequency:
            agg_funcs['Frequency'] = lambda x: ', '.join(str(v) for v in x if pd.notna(v))
        
        # For CPE Count, join with comma
        if has_cpe_count:
            agg_funcs['CPE Count'] = lambda x: ', '.join(str(v) for v in x if pd.notna(v))
        
        # For Sample Log Lines, keep first
        if has_sample_logs:
            agg_funcs['Sample Log Lines'] = 'first'
        
        # Group by Pattern and aggregate
        if agg_funcs:
            unique_df = combined_df.groupby(pattern_column, as_index=False).agg(agg_funcs)
        else:
            # Fallback to simple deduplication
            unique_df = combined_df.drop_duplicates(subset=[pattern_column], keep='first')
        
        print(f"  - Unique rows after deduplication: {len(unique_df)}")
        print(f"  - Removed {len(combined_df) - len(unique_df)} duplicate patterns")
        
        if has_frequency and has_cpe_count:
            print(f"  - Aggregated Frequency and CPE Count as comma-separated values")
        
        # Sort by first Frequency value (extract first number from comma-separated string)
        if has_frequency:
            try:
                # Extract first frequency value for sorting
                unique_df['_sort_freq'] = unique_df['Frequency'].astype(str).str.split(',').str[0].str.strip()
                unique_df['_sort_freq'] = pd.to_numeric(unique_df['_sort_freq'], errors='coerce').fillna(0)
                unique_df = unique_df.sort_values('_sort_freq', ascending=False)
                unique_df = unique_df.drop(columns=['_sort_freq'])
                print(f"  - Sorted by first Frequency value (descending)")
            except Exception as e:
                print(f"  - Warning: Could not sort by Frequency: {e}")
        
        merged_sheets[sheet_name] = unique_df.reset_index(drop=True)
    
    return merged_sheets


def create_index_sheet(merged_sheets: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """
    Create an enhanced INDEX sheet with domain grouping and hyperlinks.
    
    Args:
        merged_sheets: Dictionary with sheet names and DataFrames
        
    Returns:
        DataFrame for INDEX sheet with DOMAIN and FILES columns
    """
    # Define domain mapping (common log file categories)
    domain_mapping = {
        'Platform': ['kernel', 'systemdLog.txt', 'system_eventlog', 'BootTime.log', 'critlog'],
        'Network': ['ETHAGENTLog.txt', 'WANMANAGERLog.txt', 'PPPManagerLog.txt', 'dibbler-server.log', 'zebra.log', 'GponManagerLog.txt'],
        'WiFi': ['WiFilog.txt', 'wifi_vendor_apps.log', 'wifi_vendor_hal.log', 'wifihealth.txt', 'airties.log'],
        'Management': ['LM.txt', 'PAMlog.txt', 'WEBPAlog.txt', 'OnBoardingLog.txt', 'EnrolmentAgentLog.txt', 'xconf.txt'],
        'Voice': ['TELCOVOICEMANAGERLog.txt', 'TDMlog.txt'],
        'System Logs': ['Consolelog.txt', 'ArmConsolelog.txt', 'syslog.txt', 'messages', 'user', 'local7notice'],
        'Security': ['FirewallDebug.txt', 'CUJOAGENT.log', 'CCSPCUJOAGENTLog.txt'],
        'Services': ['PARODUSlog.txt', 'NOTIFYLog.txt', 'PSMlog.txt', 'STATEINFOMANAGERLog.txt', 'ntpLog.log', 'lighttpd.error.log'],
        'Other': []  # Catch-all for unmapped files
    }
    
    # Get all sheet names except INDEX
    all_sheets = sorted([s for s in merged_sheets.keys() if s != 'INDEX'])
    
    # Create reverse mapping for quick lookup
    file_to_domain = {}
    for domain, files in domain_mapping.items():
        for file in files:
            file_to_domain[file] = domain
    
    # Build INDEX data
    index_data = []
    
    # Group by domain
    for domain in ['Platform', 'Network', 'WiFi', 'Management', 'Voice', 'System Logs', 'Security', 'Services']:
        domain_files = [f for f in all_sheets if file_to_domain.get(f) == domain]
        
        if domain_files:
            for i, file in enumerate(domain_files):
                index_data.append({
                    'DOMAIN': domain if i == 0 else '',
                    'FILES': file
                })
    
    # Add any unmapped files to 'Other'
    unmapped_files = [f for f in all_sheets if f not in file_to_domain]
    if unmapped_files:
        for i, file in enumerate(unmapped_files):
            index_data.append({
                'DOMAIN': 'Other' if i == 0 else '',
                'FILES': file
            })
    
    return pd.DataFrame(index_data)


def write_excel_with_formatting(merged_sheets: Dict[str, pd.DataFrame], output_file: str):
    """
    Write merged sheets to Excel with formatting similar to source files.
    
    Args:
        merged_sheets: Dictionary with sheet names and DataFrames
        output_file: Output Excel file path
    """
    print(f"\nWriting output to {output_file}...")
    
    # Create a new workbook
    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # Remove default sheet
    
    # Define styles
    header_font = Font(bold=True, size=11)
    header_fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
    header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    
    # Create enhanced INDEX sheet
    index_df = create_index_sheet(merged_sheets)
    
    # Write INDEX sheet first
    sheet_order = ['INDEX']
    
    # Add all other sheets in alphabetical order
    other_sheets = sorted([s for s in merged_sheets.keys() if s != 'INDEX'])
    sheet_order.extend(other_sheets)
    
    for sheet_name in sheet_order:
        # Use enhanced INDEX sheet instead of merged version
        if sheet_name == 'INDEX':
            df = index_df
        else:
            df = merged_sheets[sheet_name]
        
        # Create worksheet
        ws = wb.create_sheet(title=sheet_name)
        
        # Identify Sample Log Lines column index
        sample_log_col_idx = None
        if sheet_name != 'INDEX' and 'Sample Log Lines' in df.columns:
            sample_log_col_idx = df.columns.get_loc('Sample Log Lines') + 1  # +1 for Excel 1-based indexing
        
        # Write data
        for r_idx, row in enumerate(dataframe_to_rows(df, index=False, header=True), 1):
            for c_idx, value in enumerate(row, 1):
                cell = ws.cell(row=r_idx, column=c_idx, value=value)
                
                # Apply header formatting
                if r_idx == 1:
                    cell.font = header_font
                    cell.fill = header_fill
                    cell.alignment = header_alignment
                
                # Apply wrap text alignment for Sample Log Lines column
                elif r_idx > 1 and sample_log_col_idx and c_idx == sample_log_col_idx:
                    cell.alignment = Alignment(wrap_text=True, vertical='top')
                
                # Add hyperlinks for INDEX sheet FILES column
                if sheet_name == 'INDEX' and r_idx > 1 and c_idx == 2 and value:  # Column B (FILES), skip header
                    # Check if the sheet exists
                    if value in other_sheets:
                        # Create hyperlink to the sheet
                        cell.hyperlink = f"#'{value}'!A1"
                        cell.font = Font(color="0563C1", underline="single")  # Blue underlined text
                        cell.style = "Hyperlink"
        
        # Adjust column widths and set row heights for pattern sheets
        for column in ws.columns:
            max_length = 0
            column_letter = column[0].column_letter
            
            for cell in column:
                try:
                    if cell.value:
                        max_length = max(max_length, len(str(cell.value)))
                except:
                    pass
            
            # Special handling for Sample Log Lines column (make it wider)
            if sample_log_col_idx and column[0].column == sample_log_col_idx:
                adjusted_width = min(max(max_length + 2, 80), 120)  # Min 80, max 120
            else:
                adjusted_width = min(max_length + 2, 100)  # Cap at 100
            
            ws.column_dimensions[column_letter].width = adjusted_width
        
        # Set row heights for data rows (to show wrapped text better)
        if sheet_name != 'INDEX' and sample_log_col_idx:
            for row_idx in range(2, ws.max_row + 1):  # Skip header
                ws.row_dimensions[row_idx].height = 60  # Set height to show ~3-4 lines
        
        # Freeze first row
        ws.freeze_panes = 'A2'
        
        # Enable AutoFilter on header row
        if ws.max_row > 0:  # Only if there's data
            ws.auto_filter.ref = ws.dimensions
        
        print(f"  - Created sheet '{sheet_name}' with {len(df)} rows")
    
    # Save workbook
    wb.save(output_file)
    print(f"\n✓ Successfully created {output_file}")


def generate_output_filename(input_files: List[str]) -> str:
    """
    Generate an output filename based on input files.
    
    Args:
        input_files: List of input file paths
        
    Returns:
        Suggested output filename
    """
    # Extract base name from first file
    first_file = Path(input_files[0])
    base_name = first_file.stem
    
    # Try to identify pattern numbers (e.g., -1-, -2-, -15-)
    import re
    numbers = []
    for file in input_files:
        match = re.search(r'-(\d+)-', Path(file).stem)
        if match:
            numbers.append(match.group(1))
    
    if numbers:
        # Create combined number part
        number_part = '-'.join(numbers)
        # Replace the number in base name with combined numbers
        output_name = re.sub(r'-\d+-', f'-{number_part}-', base_name)
    else:
        output_name = f"{base_name}-merged"
    
    return f"{output_name}.xlsx"


def main():
    parser = argparse.ArgumentParser(
        description='Merge unique patterns from multiple Excel files',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Merge three files with auto-generated output name
  python merge_unique_patterns.py file1.xlsx file2.xlsx file3.xlsx
  
  # Merge files with custom output name
  python merge_unique_patterns.py file1.xlsx file2.xlsx -o merged_output.xlsx
  
  # Use different column for uniqueness
  python merge_unique_patterns.py file1.xlsx file2.xlsx --pattern-column "Log Pattern"
        """
    )
    
    parser.add_argument(
        'files',
        nargs='+',
        help='Excel files to merge (minimum 2 files)'
    )
    
    parser.add_argument(
        '-o', '--output',
        help='Output Excel file name (auto-generated if not specified)',
        default=None
    )
    
    parser.add_argument(
        '-p', '--pattern-column',
        help='Column name to use for identifying unique patterns (default: Pattern)',
        default='Pattern'
    )
    
    args = parser.parse_args()
    
    # Validate inputs
    if len(args.files) < 2:
        print("Error: Please provide at least 2 Excel files to merge")
        sys.exit(1)
    
    # Check if files exist
    valid_files = []
    for file_path in args.files:
        if Path(file_path).exists():
            valid_files.append(file_path)
        else:
            print(f"Warning: File not found: {file_path}")
    
    if len(valid_files) < 2:
        print("Error: Need at least 2 valid files to merge")
        sys.exit(1)
    
    # Generate output filename if not provided
    output_file = args.output
    if not output_file:
        output_file = generate_output_filename(valid_files)
    
    print("="*70)
    print("Excel Pattern Merger")
    print("="*70)
    print(f"\nInput files ({len(valid_files)}):")
    for i, file in enumerate(valid_files, 1):
        print(f"  {i}. {file}")
    print(f"\nOutput file: {output_file}")
    print(f"Pattern column: {args.pattern_column}")
    print("="*70)
    
    # Merge patterns
    try:
        merged_sheets = merge_patterns(valid_files, args.pattern_column)
        
        # Write output
        write_excel_with_formatting(merged_sheets, output_file)
        
        print("\n" + "="*70)
        print("Summary:")
        print("="*70)
        total_rows = sum(len(df) for df in merged_sheets.values())
        print(f"Total sheets: {len(merged_sheets)}")
        print(f"Total unique patterns: {total_rows}")
        print(f"Output file: {output_file}")
        print("="*70)
        
    except Exception as e:
        print(f"\nError: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
