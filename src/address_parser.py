"""
Address Parser Module.

This module provides functionality for parsing the source address 
based on the type of address.  For this Unstructured address type
(the only type configured) it uses libpostal and if necessary, 
and allowed, geocoders for enrichment of Town Name and Country.
"""
from typing import Tuple, List
from collections import defaultdict
import libpostal_config     #do not delete, must be imported before the postal.parser below
from postal.parser import parse_address
#from postal.expand import expand_address
from log_config import get_logger
from helpers import clean_whitespace_preserve_newlines
from config import MIN_VIABLE_ADDRESS_LENGTH
from address_enricher import enrich_address


logger = get_logger()


class UnstructuredAddress:
    """
    Handles parsing and enrichment of unstructured address strings using
    libpostal and optional geo-enrichment.
    """

    @staticmethod
    def _optimise_libpostal_components(components: List[Tuple[str, str]]) -> dict[str, str]:
        """
        Processes libpostal components to handle repeating fields optimally.
        Returns the most complete version of each component (we have set to being the longest)
        """
        component_map = defaultdict(list)

        # Group all components by their type
        for value, component_type in components:
            component_map[component_type].append(value)

        optimised = {}

        # For each component type, select the most complete version
        for comp_type, values in component_map.items():
            if len(values) == 1:
                optimised[comp_type] = values[0]
            else:
                # For multiple values, use the longest that contains meaningful info
                sorted_values = sorted(values, key=lambda x: (-len(x), x))
                optimised[comp_type] = next(
                    (v for v in sorted_values if v.strip()),
                    sorted_values[0]  # fallback
                )

        return optimised


    @staticmethod
    def _prepare_for_libpostal(raw_fields: dict[str, str]) -> str:
        """
        Prepares UnstructuredAddress fields in optimal order/format for libpostal parsing.
        Nothing to do for this single string address but could be expanded if more 
        structured fields were present
        """
        # Adjust any prepartory code to apply to this type of address here.
        # In this example we'll simply strip out any tab characters and
        # any series of 2 or more whitespace characters but you could
        # customise much more depending on the type of address
        # e.g. you could parse individual elements such as a
        # country code and re-order components in recommended order for given
        # countries for better libpostal parsing
        prepared_address_line = clean_whitespace_preserve_newlines(raw_fields['address_line'])
        raw_fields['address_line'] = prepared_address_line

        components = [
            raw_fields['address_line']
        ]

        # Filter out empty components and join with commas
        address_to_parse = ", ".join(filter(None, components))

        if len(address_to_parse) < MIN_VIABLE_ADDRESS_LENGTH:
            logger.warning(
                "Address is too short for libpostal to reliably parse: %s", address_to_parse)

        return address_to_parse


    @staticmethod
    def parse_address(
        address_str: str,
        allow_geo_enrichment: bool) -> tuple[dict, dict, dict, bool, bool]:
        """
        Parses any unstructured address string into structured or hybrid address components.
        
        Args:
            address_str: The input string containing the address data
            allow_geo_enrichment: if True, will attempt to geo enrich if missing 
                Town Name and Country Code plus postcode and neighborhood (city_district)
                If false, will parse as is and return only libpostal fields
        Returns:
            raw_fields
            optimised_fields (from libpostal parsing)
        """

        if len(address_str) < MIN_VIABLE_ADDRESS_LENGTH:
            logger.error("Input string too short for reliable conversion")
            raise ValueError("Input string too short for reliable conversion")

        # Parse the raw address
        raw_fields = {'address_line': address_str.strip()}

        libpostal_input = UnstructuredAddress._prepare_for_libpostal(raw_fields)
        libpostal_parsed = parse_address(libpostal_input)
        optimised_components = UnstructuredAddress._optimise_libpostal_components(libpostal_parsed)

        country_code = optimised_components.get('country')

        best_address_components, city_enriched, country_enriched = enrich_address(
            address_dict=optimised_components,
            country_code=country_code.upper() if country_code and len(country_code) == 2 else None,
            allow_geo_enrichment=allow_geo_enrichment,
            prefer_latin_names=True)

        optimised_components['libpostal_parsed_data'] = libpostal_parsed

        return (
            raw_fields,
            optimised_components,
            best_address_components,
            city_enriched,
            country_enriched
            )


    @staticmethod
    def _apply_geo_enrichment(
        optimised_components: dict,
        geo_data: tuple | None,
        country_code: str | None
        ) -> None:
        """Apply geo-enrichment data to optimised components for missing fields only."""
        # Set city existence flag
        optimised_components['libpostal_city_exists'] = (
            "true" if 'city' in optimised_components else "false")

        if geo_data is None:
            return

        enriched_country, enriched_city, enriched_postcode, enriched_neighborhood, is_geo_enriched = geo_data

        # Apply country if missing
        if 'country' not in optimised_components:
            if enriched_country:
                optimised_components['country'] = enriched_country
                optimised_components['is_geo_enriched_country'] = str(is_geo_enriched)
        elif country_code:
            # Use the processed country code from libpostal
            optimised_components['country'] = country_code
            optimised_components['is_geo_enriched_country'] = "false"

        # Apply other fields if missing
        field_mappings = [
            ('city', enriched_city),
            ('postcode', enriched_postcode),
            ('city_district', enriched_neighborhood)
        ]

        for field_name, enriched_value in field_mappings:
            if field_name not in optimised_components and enriched_value:
                optimised_components[field_name] = enriched_value
