"""
Utility functions for address field validation, normalization, and formatting
according to CBPR+ extended character set rules.
Modules:
    - re: Regular expressions for pattern matching.
Functions:
    - clean_whitespace_preserve_newlines(input_string: str) -> str:
        Cleans excessive whitespace and tabs from input string, preserving newlines.
"""
import re


def clean_whitespace_preserve_newlines(input_string: str) -> str:
    """
    Clean whitespace while preserving newlines.
    """
    # Split by lines first
    lines = input_string.splitlines()

    # Process each line separately
    cleaned_lines = []
    for line in lines:
        no_tabs = line.replace('\t', ' ')
        cleaned_line = re.sub(r'[^\S\n]{2,}', '  ', no_tabs)
        cleaned_lines.append(cleaned_line)

    # Join back with newlines
    return '\n'.join(cleaned_lines)
