#!/usr/bin/env python3

"""
Fix script for the scanner.py syntax error
"""
import sys
import re

# Path to the scanner.py file
scanner_file = "scanner.py"

# Read current content
with open(scanner_file, "r") as f:
    content = f.read()

# Find and fix the issue
# The problem is around the "candidates = []" line
pattern = r"(\s+except Exception as e:\n\s+logger\.error\(f\"Error in parallel processing of earnings data: \{e\}\"\)\n\s+)\n(candidates = \[\])"
replacement = r"\1\n        \2"

# Apply the fix
fixed_content = re.sub(pattern, replacement, content)

# Check if changes were made
if fixed_content != content:
    print("Syntax error fixed! Writing changes...")
    # Write the fixed content back
    with open(scanner_file, "w") as f:
        f.write(fixed_content)
    print("Done! The file has been fixed.")
    sys.exit(0)
else:
    print("No changes made - couldn't find the pattern to fix.")
    sys.exit(1)