#!/usr/bin/env python3
"""
Database Migration: Add project_type column to projects table

This script adds the 'project_type' column to existing projects.
All existing projects will default to 'normal' type.
"""

import sqlite3
import sys
from pathlib import Path

# Get database path from command line or use default
DB_PATH = sys.argv[1] if len(sys.argv) > 1 else "data/logai_users.db"

def migrate():
    """Add project_type column to projects table"""
    
    if not Path(DB_PATH).exists():
        print(f"❌ Database not found at: {DB_PATH}")
        print("Usage: python3 migrate_project_type.py [path/to/logai_users.db]")
        return False
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Check if column already exists
        cursor.execute("PRAGMA table_info(projects)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if "project_type" in columns:
            print("✅ Column 'project_type' already exists in projects table")
            conn.close()
            return True
        
        # Add the column
        print("📝 Adding 'project_type' column to projects table...")
        cursor.execute("""
            ALTER TABLE projects 
            ADD COLUMN project_type VARCHAR(20) DEFAULT 'normal'
        """)
        
        # Update all existing projects to 'normal'
        cursor.execute("""
            UPDATE projects 
            SET project_type = 'normal' 
            WHERE project_type IS NULL
        """)
        
        conn.commit()
        
        # Verify the change
        cursor.execute("SELECT COUNT(*) FROM projects WHERE project_type = 'normal'")
        count = cursor.fetchone()[0]
        
        print(f"✅ Migration successful!")
        print(f"   - Added 'project_type' column")
        print(f"   - Updated {count} existing project(s) to 'normal' type")
        
        conn.close()
        return True
        
    except sqlite3.Error as e:
        print(f"❌ Database error: {e}")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == "__main__":
    print("🔄 Project Type Migration")
    print("=" * 50)
    print(f"Database: {DB_PATH}")
    print()
    
    if migrate():
        print()
        print("✅ Migration complete!")
        sys.exit(0)
    else:
        print()
        print("❌ Migration failed!")
        sys.exit(1)
