"""
Address Converter Module.

This module provides functionality for converting address data 
from the parsed and/or enriched source address to either an ISO 20022
strucutred or hybrid address format.  It includes XML schema validation
and transformation using predefined, loaded schemas.

Key features:
- XML schema validation for structured and hybrid addresses (PostalAddress24)
- Address format conversion and normalization
- CSV output generation with proper formatting

Example usage:
    from address_converter import convert_addresses
    result = convert_addresses(input_data, output_dir)
"""
import xml.etree.ElementTree as ET
from xml.dom import minidom
import re
import unicodedata
from typing import Optional
import pandas as pd
from lxml import etree
from log_config import get_logger

logger = get_logger()


class AddressConverter:
    """
    Converts libpostal parsed addresses to PostalAddress24 formats (Structured/Hybrid)
    """

    def __init__(self):
        # CBPR+ allowed character pattern (without length restrictions)
        self.cbpr_pattern = re.compile(
            r"[0-9a-zA-Z/\-\?:\(\)\.,'\+ !#$%&\*=^_`\{\|\}~\";<>@\[\\\]]+"
        )

        # Field mapping from libpostal to PostalAddress24
        self.field_mappings = {
            # department and sub_department are extensions to Libposal model
            # and for future use if needed in a strategy
            "department": ["Dept"],
            "sub_department": ["SubDept"],
            "house": ["BldgNm"],
            "house_number": ["BldgNb"],
            "level": ["Flr"],
            "po_box": ["PstBx"],
            "unit": ["Room"],
            "road": ["StrtNm"],
            "suburb": ["TwnLctnNm", "DstrctNm"],
            "city": ["TwnNm"],
            "postcode": ["PstCd"],
            "country": ["Ctry"],
            "state_district": ["CtrySubDvsn"],
        }

        # Max lengths for each field
        self.max_lengths = {
            "Dept": 70,
            "SubDept": 70,
            "StrtNm": 70,
            "BldgNb": 16,
            "BldgNm": 35,
            "Flr": 70,
            "PstBx": 16,
            "Room": 70,
            "PstCd": 16,
            "TwnNm": 35,
            "TwnLctnNm": 35,
            "DstrctNm": 35,
            "CtrySubDvsn": 35,
            "Ctry": 2,
            "AdrLine": 70,
        }


    def normalize_text(self, text: str) -> tuple[str, bool]:
        """
        Normalize text to CBPR+ compliant format
        Returns: (normalized_text, is_altered)
        """
        if not text:
            return "", False

        original_text = text
        is_altered = False
        pattern_replaced = False

        # Remove accents and normalize to ASCII
        try:
            # Unicodedata doens't replace "œ", "æ", "ß" etc so replace first before NFKD
            text = text.replace("œ", "oe")
            text = text.replace("æ", "ae")
            text = text.replace("ß", "ss")
            text = text.replace("ĳ", "ij")
            # Normalise unicode characters
            normalised = unicodedata.normalize("NFKD", text)
            ascii_text = normalised.encode("ascii", "ignore").decode("ascii")
            if ascii_text != original_text:
                is_altered = True
                logger.warning(
                    "DATA REPLACED (ASCII): Original - %s | Normalised - %s",
                    original_text,
                    ascii_text,
                )
                text = ascii_text
        except UnicodeError:
            logger.error("Unicode error trying to replace: %s", text)

        # Replace CBPR+ extended char set non-conforming characters with "."
        normalised_chars = []
        for char in text:
            if self.cbpr_pattern.match(char):
                normalised_chars.append(char)
            else:
                normalised_chars.append(".")
                is_altered = True
                pattern_replaced = True

        normalised_text = "".join(normalised_chars)
        if pattern_replaced:
            logger.warning(
                "DATA REPLACED (PATTERN): Original - %s | Normalised - %s",
                original_text,
                normalised_text,
            )

        return normalised_text, is_altered or (normalised_text != original_text)


    def truncate_field(self, text: str, max_length: int) -> tuple[str, bool]:
        """
        Truncate text to maximum length -1 plus + char to show truncation
        Returns: (truncated_text, is_altered)
        """
        if not text:
            return "", False

        if len(text) > max_length:
            return text[: max_length - 1] + "+", True

        return text, False


    def get_field_length(self, field_name: str) -> int:
        """
        Gets the max length for the given PostalAddress field name
        Returns: int
        """
        if not field_name:
            return 0

        max_len = self.max_lengths.get(field_name)

        if max_len:
            return max_len
        else:
            return 0


    def split_address_line(
        self, address_line: str,
        max_length: int) -> tuple[str, str | None, bool]:
        """
        Splits an address line if it exceeds the max permitted length characters.

        Args:
            address_line: The address string to potentially split
            max_length: The max length of the string to decide whether to split

        Returns:
            - The original string if length <= max length and truncation flag False
            - A tuple of (address_line_1_first_70_chars, address_line_2_remainder) 
                if length > 70 and truncation flag (True or False)
        """
        if len(address_line) <= max_length:
            return (address_line, None, False)  # False i.e. not truncated

        address_line_1 = address_line[:max_length]
        address_line_2 = address_line[max_length:]
        truncated_address_line2, truncated = self.truncate_field(
            address_line_2, self.max_lengths["AdrLine"]
        )
        return (address_line_1, truncated_address_line2, truncated)


    def extract_address_components(self, row: pd.Series) -> dict[str, str]:
        """
        Extract address components from DataFrame row
        """
        components = {}

        field_mappings = {
            "department": "department",
            "sub_department": "sub_department",
            "house": "house",
            "house_number": "house_number",
            "road": "road",
            "unit": "unit",
            "level": "level",
            "staircase": "staircase",
            "entrance": "entrance",
            "po_box": "po_box",
            "postcode": "postcode",
            "suburb": "suburb",
            "city_district": "city_district",
            "city": "city",
            "island": "island",
            "state_district": "state_district",
            "state": "state",
            "country_region": "country_region",
            "country": "country",
            "world_region": "world_region",
        }

        # Extract from best_address columns
        for libpostal_field, component in field_mappings.items():
            field_name = f"best_address.{libpostal_field}"
            if field_name in row.index and pd.notna(row[field_name]):
                components[component] = str(row[field_name]).strip()

        return components


    def build_structured_address(
        self, components: dict[str, str]
    ) -> tuple[dict[str, str], dict[str, str], bool, bool, bool]:
        """
        Build PostalAddress24 structured format
        Returns: (address_fields_trunc (truncated to fit structured),
            address_fields_no_trunc, is_replaced, is_truncated, use_hybrid)
        """
        address_fields_trunc = {}
        address_fields_no_trunc = {}  # For use as fallback hybrid address
        total_is_replaced = False
        total_is_truncated = False
        # Flag to determine if the fallback to hybrid is required
        # (based on any truncated field except TwnNm)
        use_hybrid = False

        # Required fields
        # =========Town Name================
        # Use suburb if city is not present
        # (should only be possible if allow_geo_enrichment is False)
        town_name = components.get("city", "")
        if not town_name:
            town_name = components.get("suburb", "")

        if town_name:
            normalized_town, replaced = self.normalize_text(town_name)
            truncated_town, truncated = self.truncate_field(
                normalized_town, self.max_lengths["TwnNm"]
            )
            address_fields_trunc["TwnNm"] = truncated_town.upper()
            # TwnNm is the no truncation exception
            address_fields_no_trunc["TwnNm"] = address_fields_trunc["TwnNm"]
            total_is_replaced = total_is_replaced or replaced
            total_is_truncated = total_is_truncated or truncated

        # ========Country Code===============
        country = components.get("country", "")
        address_fields_trunc["Ctry"] = country.upper()
        address_fields_no_trunc["Ctry"] = address_fields_trunc["Ctry"]

        # Optional fields
        optional_mappings = {
            "department": "Dept",
            "sub_department": "SubDept",
            "road": "StrtNm",
            "house_number": "BldgNb",
            "house": "BldgNm",
            "level": "Flr",
            "po_box": "PstBx",
            "unit": "Room",
            "postcode": "PstCd",
            "suburb": "TwnLctnNm",
            "city_district": "DstrctNm",
        }

        # Handle many to one field mapping, for state and state_district to CtrySubDvsn
        priority_mappings = {
            # Priority is state_district then state if both present
            "CtrySubDvsn": ["state_district", "state"]
        }

        for component_key, field_name in optional_mappings.items():
            if component_key in components and components[component_key]:
                # Skip suburb if it was used for TwnNm
                if field_name == "TwnLctnNm" and components[component_key] == town_name:
                    continue

                normalized_text, replaced = self.normalize_text(
                    components[component_key]
                )
                address_fields_no_trunc[field_name] = normalized_text.upper()
                truncated_text, truncated = self.truncate_field(
                    normalized_text, self.max_lengths[field_name]
                )
                # Set use_hybrid to whether this field was truncated
                use_hybrid = use_hybrid or truncated
                total_is_replaced = total_is_replaced or replaced
                if truncated_text:
                    address_fields_trunc[field_name] = truncated_text.upper()
                    total_is_truncated = total_is_truncated or truncated

        # Process priority mappings (multiple source fields to one target field)
        for target_field, source_fields in priority_mappings.items():
            # Find the first available source field in priority order
            for source_field in source_fields:
                if source_field in components and components[source_field]:
                    normalized_text, replaced = self.normalize_text(
                        components[source_field]
                    )
                    address_fields_no_trunc[target_field] = normalized_text.upper()
                    truncated_text, truncated = self.truncate_field(
                        normalized_text, self.max_lengths[target_field]
                    )
                    # Set use_hybrid to whether this field was truncated
                    use_hybrid = use_hybrid or truncated
                    total_is_replaced = total_is_replaced or replaced
                    if truncated_text:
                        address_fields_trunc[target_field] = truncated_text.upper()
                        total_is_truncated = total_is_truncated or truncated
                    break  # Stop after finding first match

        return (
            address_fields_trunc,
            address_fields_no_trunc,
            total_is_replaced,
            total_is_truncated,
            use_hybrid,
        )

    def build_hybrid_address(
        self,
        address_fields_no_trunc: dict[str, str],
        structured_replaced: bool
    ) -> tuple[dict[str, str], bool, bool]:
        """
        Build PostalAddress24 hybrid format (with AdrLine fields)
        Returns: (address_fields, is_replaced, is_truncated)
        """
        is_replaced = False
        is_truncated = False

        # Assumes this is libpostal structured address conversion that failed proper structure rules

        is_replaced = is_replaced or structured_replaced

        # Add up to 2 AdrLine fields for additional address info
        addr_lines = []

        # Find elements that exceed max length
        exceeding_elements = [
            element
            for element, value in address_fields_no_trunc.items()
            if len(value) > self.get_field_length(element)
        ]

        # Process exceeding elements
        for element in exceeding_elements:
            value = address_fields_no_trunc[element]
            addr_lines.append(value)
            logger.info(
                "Structured to hybrid change: %s moved to AdrLine: %s", element, value
            )

        # Remove exceeding elements from original dict (this uses dict comprehension)
        address_fields_no_trunc = {
            k: v
            for k, v in address_fields_no_trunc.items()
            if k not in exceeding_elements
        }

        # Add AdrLine fields
        for i, addr_line in enumerate(addr_lines):
            address_fields_no_trunc[f"AdrLine{i+1}"] = addr_line

        # Aggregate all AdrLines and split into max 2 occurences, correctly truncated
        address_line = " ".join(addr_lines)

        if address_line:
            # Check if more than one address line length and split into 2 if req.
            address_line_1, address_line_2, truncated = self.split_address_line(
                address_line=address_line,
                max_length=self.max_lengths["AdrLine"],
            )
            address_fields_no_trunc["AdrLine1"] = address_line_1.upper()
            if address_line_2:
                address_fields_no_trunc["AdrLine2"] = address_line_2.upper()
            #is_replaced = is_replaced or replaced
            is_truncated = is_truncated or truncated

        return address_fields_no_trunc, is_replaced, is_truncated


    def remove_duplicate_elements(
        self, xml_element, protected_tags: Optional[list[str]] = None
    ) -> etree._Element:
        """
        Remove duplicate elements from XML while protecting certain tags from being removed,
        TwnNm and Ctry

        Args:
            xml_element: The XML root element to process
            protected_tags: List of element tags that should never be removed when duplicates exist

        Returns:
            The processed XML tree with duplicates removed (except protected tags)
        """
        if protected_tags is None:
            protected_tags = ["TwnNm", "Ctry"]

        seen_values: set[str] = set()
        elements_to_remove = []

        # First pass: Record values from protected tags
        for elem in xml_element.iter():
            if (
                elem.tag in protected_tags
                and elem.text
                and (value := elem.text.strip())
            ):
                seen_values.add(value)

        # Second pass: Identify elements to remove
        parent_map = {
            c: p for p in xml_element.iter() for c in p
        }  # Works for both implementations

        # Create list to avoid modification during iteration
        for elem in list(xml_element.iter()):
            if elem.tag in protected_tags:
                continue

            if elem.text and (value := elem.text.strip()):
                if value in seen_values:
                    elements_to_remove.append(elem)
                else:
                    seen_values.add(value)

        # Remove elements (works for both implementations)
        for elem in elements_to_remove:
            parent = parent_map.get(elem)
            if parent is not None:
                # Different removal methods for different implementations
                if hasattr(parent, "remove"):  # lxml
                    parent.remove(elem)
                else:  # xml.etree
                    parent[:] = [c for c in parent if c != elem]

        return xml_element


    def create_xml_element(
        self, address_fields: dict[str, str], allow_hybrid: bool = False
    ) -> ET.Element:
        """
        Create XML element for the address
        """
        root = ET.Element("PstlAdr")

        # Field order for structured format
        field_order = [
            "Dept",
            "SubDept",
            "StrtNm",
            "BldgNb",
            "BldgNm",
            "Flr",
            "PstBx",
            "Room",
            "PstCd",
            "TwnNm",
            "TwnLctnNm",
            "DstrctNm",
            "CtrySubDvsn",
            "Ctry",
        ]

        # Add fields in order
        for field in field_order:
            if field in address_fields and address_fields[field]:
                elem = ET.SubElement(root, field)
                elem.text = address_fields[field]

        # Add AdrLine fields for hybrid format
        if allow_hybrid:
            for i in range(1, 3):  # AdrLine1, AdrLine2
                field_name = f"AdrLine{i}"
                if field_name in address_fields and address_fields[field_name]:
                    elem = ET.SubElement(root, "AdrLine")
                    elem.text = address_fields[field_name]

        return root

    def validate_xml_against_xsd(
        self, xml_element: ET.Element, xsd_content: str
    ) -> tuple[bool, list[str]]:
        """
        Validate XML against XSD schema
        Returns: (is_valid, error_messages)
        """
        try:
            # Parse XSD
            xsd_doc = etree.fromstring(xsd_content.encode())
            schema = etree.XMLSchema(xsd_doc)

            # Convert ET.Element to lxml element
            xml_string = ET.tostring(xml_element, encoding="unicode")
            xml_doc = etree.fromstring(xml_string.encode())

            # Validate
            is_valid = schema.validate(xml_doc)

            if not is_valid:
                error_messages = [str(error) for error in schema.error_log]
                return False, error_messages

            return True, []

        except (etree.XMLSchemaError, etree.XMLSyntaxError, ValueError) as e:
            error_msg = f"Validation error: {str(e)}"
            logger.error(error_msg)
            return False, [error_msg]


    def xml_to_string(self, xml_element: ET.Element) -> str:
        """
        Convert XML element to formatted string
        """
        rough_string = ET.tostring(xml_element, encoding="unicode")
        reparsed = minidom.parseString(rough_string)
        # Remove XML declaration
        return reparsed.toprettyxml(indent="  ").split("\n", 1)[1]


    def convert_addresses(
        self, df: pd.DataFrame, structured_xsd: str, hybrid_xsd: str, allow_hybrid: bool
    ) -> pd.DataFrame:
        """
        Convert all addresses in DataFrame to PostalAddress24 formats with metadata
        allow_hybrid: allows fallback to hybrid to avoid truncation
        """
        # Create new columns for results
        result_columns = [
            "xml_address_structured",
            "xml_address_hybrid",
            "xml_address_final",
            "address_format_used",
            "is_valid_structured",
            "is_valid_hybrid",
            "is_valid_final",
            "validation_errors_structured",
            "validation_errors_hybrid",
            "validation_errors_final",
            "is_replaced",
            "is_truncated",
        ]

        for col in result_columns:
            df[col] = None

        # Convert each row
        for idx, row in df.iterrows():
            try:
                # Extract address components
                components = self.extract_address_components(row=row)

                # Try structured format first
                result = self.build_structured_address(components)
                structured_fields = result[0]
                structured_fields_no_trunc = result[1]
                is_replaced_structured = result[2]
                is_truncated_structured = result[3]
                use_hybrid = result[4]

                # No fields were truncated or if allow_hybrid is False,
                # continue to try the convert to fully structured address
                if not (use_hybrid and allow_hybrid):
                    # Check if we have minimum required fields for structured format
                    has_required_structured = (
                        "TwnNm" in structured_fields and "Ctry" in structured_fields
                    )

                    if (
                        has_required_structured
                        and structured_fields["TwnNm"]
                        and structured_fields["Ctry"]
                    ):
                        # Create structured XML
                        xml_structured = self.create_xml_element(
                            structured_fields, allow_hybrid=allow_hybrid
                        )

                        # Remove duplicates
                        deduped_xml_structured = self.remove_duplicate_elements(
                            xml_element=xml_structured
                        )
                        deduped_xml_structured_str = self.xml_to_string(
                            deduped_xml_structured
                        )

                        # Validate structured format
                        is_valid_structured, errors_structured = (
                            self.validate_xml_against_xsd(
                                deduped_xml_structured, structured_xsd
                            )
                        )

                        df.at[idx, "xml_address_structured"] = (
                            deduped_xml_structured_str
                        )
                        df.at[idx, "is_valid_structured"] = is_valid_structured
                        df.at[idx, "validation_errors_structured"] = (
                            "; ".join(errors_structured) if errors_structured else ""
                        )

                        if is_valid_structured:
                            # Use structured format
                            df.at[idx, "xml_address_final"] = deduped_xml_structured_str
                            df.at[idx, "address_format_used"] = "structured"
                            df.at[idx, "is_valid_final"] = True
                            df.at[idx, "validation_errors_final"] = ""
                            df.at[idx, "is_replaced"] = is_replaced_structured
                            df.at[idx, "is_truncated"] = is_truncated_structured
                            continue

                # Fields were truncated therefore fallback to hybrid address
                else:
                    # Try hybrid format
                    hybrid_fields, is_replaced_hybrid, is_truncated_hybrid = (
                        self.build_hybrid_address(
                            address_fields_no_trunc=structured_fields_no_trunc,
                            structured_replaced=is_replaced_structured
                        )
                    )

                    # Check if we have minimum required fields for hybrid format
                    has_required_hybrid = (
                        "TwnNm" in hybrid_fields and "Ctry" in hybrid_fields
                    )

                    if (
                        has_required_hybrid
                        and hybrid_fields["TwnNm"]
                        and hybrid_fields["Ctry"]
                    ):
                        # Create hybrid XML
                        xml_hybrid = self.create_xml_element(
                            hybrid_fields, allow_hybrid=True
                        )

                        # Remove duplicates
                        deduped_xml_hybrid = self.remove_duplicate_elements(
                            xml_element=xml_hybrid
                        )
                        deduped_xml_hybrid_str = self.xml_to_string(deduped_xml_hybrid)

                        # Validate hybrid format
                        is_valid_hybrid, errors_hybrid = self.validate_xml_against_xsd(
                            deduped_xml_hybrid, hybrid_xsd
                        )

                        df.at[idx, "xml_address_hybrid"] = deduped_xml_hybrid_str
                        df.at[idx, "is_valid_hybrid"] = is_valid_hybrid
                        df.at[idx, "validation_errors_hybrid"] = (
                            "; ".join(errors_hybrid) if errors_hybrid else ""
                        )

                        if is_valid_hybrid:
                            # Use hybrid format
                            df.at[idx, "xml_address_final"] = deduped_xml_hybrid_str
                            df.at[idx, "address_format_used"] = "hybrid"
                            df.at[idx, "is_valid_final"] = True
                            df.at[idx, "validation_errors_final"] = ""
                            df.at[idx, "is_replaced"] = is_replaced_hybrid
                            df.at[idx, "is_truncated"] = is_truncated_hybrid
                        else:
                            # Neither format is valid
                            df.at[idx, "xml_address_final"] = deduped_xml_hybrid_str
                            df.at[idx, "address_format_used"] = "hybrid"
                            df.at[idx, "is_valid_final"] = False
                            df.at[idx, "validation_errors_final"] = "; ".join(
                                errors_hybrid
                            )
                            df.at[idx, "is_replaced"] = is_replaced_hybrid
                            df.at[idx, "is_truncated"] = is_truncated_hybrid
                    else:
                        # No valid format possible
                        df.at[idx, "xml_address_final"] = ""
                        df.at[idx, "address_format_used"] = "none"
                        df.at[idx, "is_valid_final"] = False
                        df.at[idx, "validation_errors_final"] = (
                            "Insufficient address data"
                        )
                        df.at[idx, "is_replaced"] = False
                        df.at[idx, "is_truncated"] = False

            except (ValueError, KeyError, TypeError) as e:
                # Handle conversion errors
                df.at[idx, "xml_address_final"] = ""
                df.at[idx, "address_format_used"] = "error"
                df.at[idx, "is_valid_final"] = False
                df.at[idx, "validation_errors_final"] = f"Conversion error: {str(e)}"
                df.at[idx, "is_replaced"] = False
                df.at[idx, "is_truncated"] = False
                logger.error("Conversion error: %s", str(e))

        return df


def convert_addresses_to_xml(
    df: pd.DataFrame, structured_xsd_path: str, hybrid_xsd_path: str, allow_hybrid: bool
) -> pd.DataFrame:
    """
    Main function to convert libpostal addresses to PostalAddress24 formats

    Args:
        df: DataFrame with libpostal parsed address data
        structured_xsd_path: Path to PostalAddress24Structured.xsd
        hybrid_xsd_path: Path to PostalAddress24Hybrid.xsd
        force_hybid: straight to hybrid
    Returns:
        DataFrame with converted addresses and validation results
    """
    # Load XSD schemas
    with open(structured_xsd_path, "r", encoding="utf-8") as f:
        structured_xsd = f.read()

    with open(hybrid_xsd_path, "r", encoding="utf-8") as f:
        hybrid_xsd = f.read()

    # Create converter and process addresses
    converter = AddressConverter()
    result_df = converter.convert_addresses(
        df, structured_xsd, hybrid_xsd, allow_hybrid
    )

    return result_df
