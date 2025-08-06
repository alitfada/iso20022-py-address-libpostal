import re
import unicodedata
import pycountry
from geonamescache import GeonamesCache
from typing import Optional


# This is the pattern permitted for CBPR+ extended character set for address elements
# It is a pre-compiled regex pattern for validation of each element
VALID_ADDRESS_PATTERN = re.compile(
    r'^[0-9a-zA-Z/\-\?:\(\)\.,\'\+ !#$%&*=^_`\{\|\}~";<>@\[\\\]]+$'
)

# These are the maximum lengths for the 14 address elements.  
# The address line length is 70 only if used in a hybrid address
MAX_LENGTHS = {
    'Dept': 70,
    'SubDept': 70,
    'StrtNm': 70,
    'BldgNb': 16,
    'BldgNm': 35,
    'Flr': 70,
    'PstBx': 16,
    'Room': 70,
    'PstCd': 16,
    'TwnNm': 35,
    'TwnLctnNm': 35,
    'DstrctNm': 35,
    'CtrySubDvsn': 35,
    'Ctry': 2,
    'AdrLine': 70
    }


def normalise_and_validate_field(field: str) -> tuple[str, bool]:
    """
    Normalises and validates a field, replacing invalid/accented chars with '.'.
    Returns:
        tuple: (cleaned_field, was_modified)
    """
    was_modified = False
    cleaned_chars = []
    
    # Normalise Unicode (NFKD decomposes accents like 'é' → 'e' + '´')
    normalised = unicodedata.normalize('NFKD', field)

    for char in normalised:
        # Check if character is a combining mark (e.g., accent)
        if unicodedata.combining(char):
            was_modified = True  # Accent was stripped
            continue  # Skip adding the accent mark
        
        # Convert to ASCII (ignore remaining non-ASCII)
        ascii_char = char.encode('ascii', 'ignore').decode('ascii')
        if not ascii_char:
            was_modified = True  # Non-Latin character removed
            continue
        
        # Validate against pattern
        if VALID_ADDRESS_PATTERN.match(ascii_char):
            cleaned_chars.append(ascii_char)
        else:
            cleaned_chars.append('.')
            was_modified = True  # Invalid pattern character
    
    cleaned_field = ''.join(cleaned_chars).strip()
    return cleaned_field, was_modified


def get_country_name(country_code: str) -> str:
    try:
        country = pycountry.countries.get(alpha_2=country_code)
        return country.name
    except (AttributeError, LookupError):
        return country_code


def get_country_code_pycountry(country_name: str) -> Optional[str]:
    """
    Given a country name, this function uses the pycountry library to find
    the corresponding two-character ISO 3166-1 alpha-2 country code.

    The function performs a robust, case-insensitive search by checking common
    attributes and uses fuzzy searching as a fallback.

    Args:
        country_name: A string representing the name of a country.

    Returns:
        A string with the two-character country code if a match is found,
        otherwise None.
    """
    if not isinstance(country_name, str):
        return None
    
    normalized_name = country_name.strip().lower()

    # 1. Try to find an exact match first using various country name attributes.
    # This is more reliable than fuzzy search for known, clean inputs.
    try:
        # Check against 'name', 'official_name', and common names.
        for country in pycountry.countries:
            if normalized_name in [country.name.lower(), getattr(country, 'official_name', '').lower()]:
                return country.alpha_2
    except LookupError:
        # This part of the code is generally safe, but a LookupError could occur.
        pass

    # 2. As a fallback, use the robust `search_fuzzy` method.
    try:
        matches = pycountry.countries.search_fuzzy(country_name)
        if matches:
            # `search_fuzzy` returns a list. The most likely correct result is the first one.
            # We add a check to make sure the result has the `alpha_2` attribute.
            # This is the key fix for the `AttributeError`.
            first_match = matches[0]
            if hasattr(first_match, 'alpha_2'):
                return first_match.alpha_2
            
    except LookupError:
        # This exception is raised by `search_fuzzy` if no matches are found.
        pass
    
    # If no match is found after all attempts, return None.
    return None


class TownCountryValidator:
    def __init__(self):
        self.gc = GeonamesCache()
        self.towns = self.gc.get_cities()
        self.countries = self.gc.get_countries()

    
    def validate(self, town_name: str, country_code: str) -> bool:
        """Check if town/city exists in specified country"""
        country_code = country_code.upper()
        if country_code not in self.countries:
            return False
            
        return any(
            town['countrycode'] == country_code
            and town['name'].lower() == town_name.lower()
            for town in self.towns.values()
        )
    

    def get_country_code(self, town_name: str) -> Optional[str]:
        """Get country code for a town/city if known"""
        matches = [
            town['countrycode']
            for town in self.towns.values()
            if town['name'].lower() == town_name.lower()
        ]
        return matches[0] if matches else None
