#!/usr/bin/env python3
"""
ISO 20022 Structured Address (Libpostal) Convertor
Input:
Text file of one or more addresses (one per line)

Return/Output:
csv file of the original address, the parsed elements, the converted xml for
    a structured or hybrid address,
xsd validation result, any xsd validation errors, flags to show if the
    converted address has undergone character replacement or truncation.

Summary:
Reads a file of one or more addresses and converts to ISO 20022 PostalAddress24
stuctured address(es). Important to note that libpostal does not enrich the
address, only parses into individual elements which can then be mapped to the
PostalAddress24 elements.  If the source unstructured address is of insufficient
quality such as missing a discernable town/city or country, the libpostal
parsed address will likely also not have these fields and therefore it will be
unlikely a valid PostalAddress24, either strucutred or hybrid, can be produced.
To resolve, the deficient address should be corrected at source, however,
it may be possible to use geocoders to enrich the missing address elements,
if the source address has sufficient detail. The allow_geo_enrichment option
is for this purpose but it should be used with caution to avoid incorrect
data and regulatory issues.  The geocoder enrichment, if used, should be upgraded
to a production feature, as this code only uses the rate-limited APIs.

Each address is normalised after the libpostal parsing, to conform to the CBPR+
extended character set and each element truncated, if neccessary, to fit the
permitted field lengths.  Truncation will always be indicated with an appended
+ symbol at the end of the field.  Any address that is altered in these ways will be
flagged as is_replaced=True and/or is_truncated=True

Finally, the converted address is validated against the loaded xsds, either structured or hybrid.

Optionally, the following can be enabled:

allow_hybrid:  default is False.  If set to True, allows conversion to a hybrid address
if any strucutred address element exceeds the max length and would be truncated.
Essentially, it minimises truncation of structured address elements.  Hybrid address
is a limited-lifespan option, hence can be disabled to only allow structured address
conversion once the usage guidelines forid hybrid addresses.

allow_geo_enrichment:  default is False.  PostalAddress24 (structured and hybrid)
requires both a Town Name and Country Code. If these are not present, enabling this
option will invoke geocoders to attempt to enrich the address with the country code
and nearest town.
"""

import sys
import os
from pathlib import Path
from enum import Enum
import pandas as pd
from config import XSD_FILE_PATH_STRUCTURED, XSD_FILE_PATH_HYBRID
from address_parser import UnstructuredAddress
from log_config import AppLogger, get_logger
import address_converter

logger = get_logger()


class AddressType(Enum):
    """
    An enumeration representing the type of address data.  This can be extended with
    additional address types

    Attributes:
        UNSTRUCTURED: Indicates that the address is provided in an unstructured format.
    """

    UNSTRUCTURED = "unstructured"


class AddressProcessor:
    """Class to handle address processing with libpostal"""

    def process_text_file(
        self,
        file_path: str,
        address_type: AddressType = AddressType.UNSTRUCTURED,
        start_row: int = 1,  # 1 assumes no header row
        allow_hybrid: bool = False,
        allow_geo_enrichment: bool = False,
    ) -> pd.DataFrame:
        """
        Process addresses from a Text file (one address per row) each line
        until end of line is reached

        Args:
            file_path: Path to the text file
            address_type: Enumerated value to state the type of address so the
                correct parsing can be called
            start_row: Row to start processing from (1-based, default: 1)
            allow_hybrid:  allows the fallback to a hybrid address to minimise truncation
            allow_geo_enrichment: if town name and country code are missing, allows
                these to be enriched using geocoders

        Returns:
            DataFrame with original addresses and parsed components
        """
        try:
            parsed_data = []

            # Read Text file
            print(f"Reading text file: {file_path}")
            logger.info("Reading text file: %s", file_path)

            expected_lengths = {AddressType.UNSTRUCTURED: 2000}  # Arbitrary long length

            trim_for_parsing = False  # Whether to trim whitespace for parsing

            # Open the file and process line by line
            with open(file_path, "r", encoding="utf-8") as file:
                # Skip to start_row (convert from 1-based to 0-based)
                for _ in range(start_row - 1):
                    next(file)

                # Process remaining lines
                for line_num, line in enumerate(file, start=start_row):

                    if not line.rstrip("\n"):  # Skip empty lines
                        logger.warning("Line %s is empty - skipped", line_num)
                        continue

                    try:
                        msg = f"Line {line_num} processing"
                        logger.info(msg)
                        print(msg)
                        # Preserve original for length check
                        original_line = line
                        # Only strip newline
                        actual_length = len(line.rstrip("\n"))

                        # Determine effective parser (this code only has UNSTRUCTURED defined)
                        effective_address_type = address_type
                        if address_type in expected_lengths:
                            expected_length = expected_lengths[address_type]
                            if actual_length > expected_length:
                                logger.warning(
                                    "TRUNCATION POSSIBLE: Line %s: Expected %s chars, got %s. "
                                    "This is truncated: %s",
                                    line_num,
                                    expected_length,
                                    actual_length,
                                    original_line[expected_length:]
                                )
                                original_line = original_line[:expected_length]

                        # Prepare line for parsing (conditional trim)
                        parse_line = original_line.rstrip("\n")
                        if trim_for_parsing:
                            parse_line = parse_line.strip()

                        # Parse using appropriate handler
                        if effective_address_type == AddressType.UNSTRUCTURED:
                            (
                                raw_fields,
                                optimised_libpostal_fields,
                                best_address_components,
                                city_enriched,
                                country_enriched,
                            ) = UnstructuredAddress.parse_address(
                                address_str=parse_line,
                                allow_geo_enrichment=allow_geo_enrichment,
                            )

                        entry = {
                            "address_type": effective_address_type.value,
                            "original_address_type": address_type.value,
                            "expected_length": expected_lengths.get(address_type),
                            "actual_length": actual_length,
                            "is_length_valid": actual_length
                            == expected_lengths.get(address_type, actual_length),
                            "allow_hybrid": allow_hybrid,
                            "allow_geo_enrichment": allow_geo_enrichment,
                            "raw_address": original_line.rstrip("\n"),
                        }

                        try:
                            if raw_fields is not None:
                                entry["raw_address_data"] = raw_fields
                            if optimised_libpostal_fields is not None:
                                entry["libpostal_data"] = optimised_libpostal_fields
                            if best_address_components is not None:
                                entry["best_address"] = best_address_components
                            if city_enriched is not None:
                                entry["city_enriched"] = city_enriched
                            if country_enriched is not None:
                                entry["country_enriched"] = country_enriched
                        except NameError as e:
                            logger.error("Fields missing: %s", e)

                        # Store the various results with metadata
                        parsed_data.append(entry)

                    except (ValueError, KeyError, TypeError) as e:
                        logger.error("Error parsing line %s: %s", line_num, str(e))
                        continue

        except (IOError, OSError, ValueError) as e:
            logger.error("Error: %s", str(e))
            return pd.DataFrame()  # Return empty DataFrame on error

        # Convert to DataFrame and expand the 'parsed_fields' dict into columns
        df = pd.json_normalize(parsed_data)

        return df


def get_wsl_path(windows_path):
    """
    Converts a Windows file path to its corresponding WSL (Windows Subsystem for Linux) path.

    Removes any surrounding quotes from the input path, and if the path starts
    with a common Windows drive letter (e.g., 'C:', 'D:', 'E:'),
    it converts the path to the WSL format (e.g., '/mnt/c/...').
    If the path does not match a known Windows drive letter, returns the path unchanged.

    Args:
        windows_path (str): The Windows file path to convert.

    Returns:
        str: The converted WSL path, or the original path if no conversion is necessary.
    """
    # Remove surrounding quotes if they exist
    windows_path = windows_path.strip().strip('"').strip("'")
    # For WSL, convert Windows path.  This provides cross-platform compatibility
    # (no Mac weirdos though)
    if windows_path.startswith(("C:", "D:", "E:")):  # Common drive letters
        drive = windows_path[0].lower()
        path = windows_path[2:].replace("\\", "/")
        return f"/mnt/{drive}{path}"
    return windows_path


def get_input_parameters():
    """Captures user input for input processing parameters."""
    # Get input file path
    input_file_path = input("Enter Text file path: ").strip()
    input_file_path = (
        get_wsl_path(input_file_path)
        if sys.platform.startswith("linux")
        else input_file_path
    )
    if not input_file_path:
        print("Please enter a valid file path.")
        sys.exit(1)

    # Check if file exists
    if not os.path.exists(input_file_path):
        print(f"File not found: {input_file_path}")
        sys.exit(1)

    # Get output directory
    output_dir = input("Enter Output folder: ").strip()
    output_dir = (
        get_wsl_path(output_dir) if sys.platform.startswith("linux") else output_dir
    )
    if not output_dir:
        print("Please enter a valid folder.")
        sys.exit(1)

    # Check if file exists
    if not os.path.exists(output_dir):
        print(f"Folder not found: {output_dir}")
        sys.exit(1)

    # Display address type options
    print("\nAvailable address types:")
    for i, at in enumerate(AddressType, 1):
        print(f"{i}. {at.name} ({at.value})")

    # Get address type with validation
    while True:
        try:
            choice = int(input("Select address type of input file (1): "))
            address_type = list(AddressType)[choice - 1]
            break
        except (ValueError, IndexError):
            print("Invalid selection. Please enter a number between 1-1.")

    # Get start row with validation
    while True:
        try:
            start_row = int(
                input("Enter starting row number in file (default 1): ") or "1"
            )
            if start_row >= 0:
                break
            print("Row number must be 0 or positive.")
        except ValueError:
            print("Please enter a valid integer.")

    # Get allow_hybrid preference
    allow_hybrid_input = input("Allow hybrid address output? (y/N): ").lower()
    allow_hybrid = allow_hybrid_input in ("y", "yes")

    # Get allow_geo_enrichment preference
    allow_geo_enrichment_input = input(
        "Allow geo-enrichment if Town Name or Country missing? (y/N): "
    ).lower()
    allow_geo_enrichment = allow_geo_enrichment_input in ("y", "yes")

    return {
        "input_file_path": input_file_path,
        "output_dir": output_dir,
        "address_type": address_type,
        "start_row": start_row,
        "allow_hybrid": allow_hybrid,
        "allow_geo_enrichment": allow_geo_enrichment,
    }


if __name__ == "__main__":

    print("====== Capturing file processing parameters ======")
    params = get_input_parameters()

    # Initialise file logging
    output_directory = Path(params["output_dir"])
    # Initialise logger
    logger = get_logger()
    if not AppLogger().configure(output_directory):
        print("Failed to initialise logging - falling back to console only")

    logger.info("Logging initialised in %s", output_directory)

    processor = AddressProcessor()
    df_results = processor.process_text_file(
        params["input_file_path"],
        params["address_type"],
        params["start_row"],
        params["allow_hybrid"],
        params["allow_geo_enrichment"],
    )  # Process a text file of addresses

    # Load the structured and hybrid address schemas to build
    # the PostalAddress24 formats and to validate against
    STD_ADR_XSD_FILE_PATH = get_wsl_path(XSD_FILE_PATH_STRUCTURED)
    HYB_ADR_XSD_FILE_PATH = get_wsl_path(XSD_FILE_PATH_HYBRID)

    # Send the dataframe for conversion to PostalAddress24
    df_converted_results = address_converter.convert_addresses_to_xml(
        df=df_results,
        structured_xsd_path=STD_ADR_XSD_FILE_PATH,
        hybrid_xsd_path=HYB_ADR_XSD_FILE_PATH,
        allow_hybrid=params["allow_hybrid"],
    )

    # Save dataframe as csv
    # Append output file name to the directory
    OUTPUT_CSV_PATH = str(output_directory / "ConvertedPostalAddress24.csv")
    try:

        df_converted_results.to_csv(
        path_or_buf=OUTPUT_CSV_PATH, index=False, encoding="utf-8", sep=",", quoting=1
        )

        logger.info("CSV saved to: %s", OUTPUT_CSV_PATH)
        print(f"CSV saved to: {OUTPUT_CSV_PATH}")
        logger.info("Processing completed successfully")

    except PermissionError as e:
        # Error for "file in use" or permission issues
        logger.error("Cannot write to CSV file - file may be open in another program: %s", str(e))
        print(f"Error: Cannot write to {OUTPUT_CSV_PATH}")
        print("Please close the file if its open in Excel or another program, then try again.")
        sys.exit(1)

    except (IOError, OSError) as e:
        # General file I/O errors
        logger.error("File I/O error occurred: %s", str(e))
        print(f"File error: {str(e)}")
        sys.exit(1)
