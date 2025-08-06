from helpers import TownCountryValidator
from postal.parser import parse_address
from postal.expand import expand_address
from typing import Dict, Tuple, List
from collections import defaultdict
from log_config import get_logger
from helpers import get_country_code_pycountry


logger = get_logger()


class UnstructuredAddress:
    @staticmethod
    def _optimise_libpostal_components(components: List[Tuple[str, str]]) -> Dict[str, str]:
        """
        Processes libpostal components to handle repeating fields optimally.
        Returns the most complete version of each component which is the longest
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
    def _prepare_for_libpostal(raw_fields: Dict[str, str]) -> str:
        """
        Prepares UnstructuredAddress fields in optimal order/format for libpostal parsing.
        """
        # Build components in recommended order for unknown countries
        components = [
            raw_fields['address_line']
        ]

        # Filter out empty components and join with commas
        address_to_parse = ", ".join(filter(None, components))
    
        if len(address_to_parse) < 25:
            logger.warning("Address is too short for libpostal to reliably parse")

        return address_to_parse
    

    @staticmethod
    def parse_address(address_str: str, allow_hybrid: bool) -> tuple[dict, dict]:
        """
        Parses any unstructured addresss string into structured or hybrid address components.
        
        Args:
            address_str: The input string containing the address data
            allow_hybrid: if True, dwill fallback to hybrid address to avoid fields being truncated.
             If false, with truncate fields to fit into structured fields
        Returns:
            raw_fields
        """
        if len(address_str) < 25:
            logger.error("Input string too short for UnstructuredAddress format")
            raise ValueError("Input string too short for UnstructuredAddress format")

        raw_fields = {
            'address_line': address_str[0:].strip()
        }

        libpostal_input = UnstructuredAddress._prepare_for_libpostal(raw_fields)
        libpostal_parsed = parse_address(libpostal_input)
        optimised_components = UnstructuredAddress._optimise_libpostal_components(libpostal_parsed)
        optimised_components['libpostal_parsed_data'] = libpostal_parsed
        
        # Check for a libpostal country exists
        if 'country' in optimised_components:
            optimised_components['libpostal_country_exists'] = True
            # Check to ensure it is a 2 char code
            if len(optimised_components['country']) != 2:
                optimised_components['country'] = get_country_code_pycountry(optimised_components['country'])
                # TODO insert either a failure here or a country lookup code based on the address we do have
                optimised_components['libpostal_country_exists'] = False
        else:
            optimised_components['libpostal_country_exists'] = False            

        # Set libpostal city existence flag
        if 'city' in optimised_components:
            optimised_components['libpostal_city_exists'] = True
        else:
            optimised_components['libpostal_city_exists'] = False
        
        return raw_fields, optimised_components
