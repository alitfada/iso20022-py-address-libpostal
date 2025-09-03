import re


def clean_whitespace_preserve_newlines(input_string: str) -> str:
    """
    Clean whitespace while preserving newlines and remove consecutive commas.
    
    Args:
        input_string: The string to clean
        
    Returns:
        Cleaned string with normalized whitespace and single commas only
        
    Examples:
        >>> clean_whitespace_preserve_newlines("12 Great Street, Highbury,, London")
        "12 Great Street, Highbury, London"
        >>> clean_whitespace_preserve_newlines("Name:   John,,, Doe\nAddress:  123  Main St,, Apt 4")
        "Name:  John, Doe\nAddress:  123  Main St, Apt 4"
    """
    # Split by lines first
    lines = input_string.splitlines()

    # Process each line separately
    cleaned_lines = []
    for line in lines:
        # Replace tabs with spaces
        no_tabs = line.replace('\t', ' ')

        # Normalize whitespace (2 or more consecutive non-newline whitespace -> 2 spaces)
        cleaned_line = re.sub(r'[^\S\n]{2,}', '  ', no_tabs)

        # Remove consecutive commas (2 or more commas -> single comma)
        # Also handles whitespace around commas to avoid "word,, word" -> "word, word"
        cleaned_line = re.sub(r',\s*,+', ',', cleaned_line)

        cleaned_lines.append(cleaned_line)

    # Join back with newlines
    return '\n'.join(cleaned_lines)


def remove_chars_regex(input_string: str) -> str:
    """
    Remove all commas and periods from a string using regex.
    
    Args:
        input_string: The string to clean
        
    Returns:
        String with all commas and periods removed
        
    Examples:
        >>> remove_chars_regex("Hello, world. How are you?")
        "Hello world How are you?"
        >>> remove_commas_and_periods_regex("Dr. Digby, Ph.D., lives in China.")
        "Dr Digby PhD lives in China"
    """
    # Remove all commas and periods using regex
    cleaned_string = re.sub(r'[,.!?]', '', input_string)
    
    return cleaned_string
