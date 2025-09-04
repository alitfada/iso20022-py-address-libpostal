"""
Address parsing and enrichment module using libpostal labels, pycountry, and Nominatim.

Dependencies:
pip install pycountry geopy requests
"""
import time
import re
from typing import Dict, Set, Tuple, Optional, Any, List
from dataclasses import dataclass
import requests
import pycountry
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
from helpers import remove_chars_regex
from log_config import get_logger

# Set up logging
logger = get_logger()


@dataclass
class AddressComponents:
    """Structure to hold parsed address components"""
    house_number: Optional[str] = None
    street_name: Optional[str] = None
    neighborhood: Optional[str] = None
    city: Optional[str] = None
    subregion: Optional[str] = None  # District/County
    region: Optional[str] = None     # State/Province
    postal_code: Optional[str] = None
    country_code: Optional[str] = None
    country_name: Optional[str] = None
    formatted_address: Optional[str] = None
    location: Optional[dict[str, float]] = None  # lat, lng
    score: Optional[float] = None


class AddressEnricher:
    """
    Address enrichment class using Nominatim geocoding and pycountry for standardization.
    """

    def __init__(self, user_agent: str = "affinis_address_enricher",
                 timeout: int = 10, delay: float = 1.0, prefer_latin: bool = True,
                 base_url: str = "https://nominatim.openstreetmap.org"):
        """
        Initialize the address enricher.
        
        Args:
            user_agent: User agent string for Nominatim requests
            timeout: Timeout for geocoding requests in seconds
            delay: Delay between requests to respect rate limits
            prefer_latin: Whether to prefer Latin/English names in results
        """
        self.geolocator = Nominatim(user_agent=user_agent, timeout=timeout)
        self.delay = delay
        self.prefer_latin = prefer_latin
        self._last_request_time = 0
        self.base_url = base_url
        self.user_agent = user_agent
        # Get valid ISO 3166-1 alpha-2 country codes from pycountry
        self.valid_country_codes: Set[str] = {
            country.alpha_2 for country in pycountry.countries
        }


    def _rate_limit(self):
        """Implement basic rate limiting for Nominatim requests."""
        current_time = time.time()
        time_since_last = current_time - self._last_request_time
        if time_since_last < self.delay:
            time.sleep(self.delay - time_since_last)
        self._last_request_time = time.time()


    def parse_and_enrich_address(self,
                                address: str,
                                country_hint: Optional[str] = None,
                                return_all_candidates: bool = False) -> List[AddressComponents]:
        """
        Parse and enrich an address string using Nominatim geocoding
        
        Args:
            address: Input address string
            country_hint: Optional country code to bias results (2-letter ISO code)
            return_all_candidates: Return all candidates or just the best match
            
        Returns:
            List of AddressComponents objects (single item if return_all_candidates=False)
        """

        # Respect rate limiting (max 1 request per second)
        self._rate_limit()

        params = {
            'q': address,
            'format': 'json',
            'addressdetails': '1',  # Include detailed address components
            'limit': '10' if return_all_candidates else '5',
            'extratags': '1',  # Include extra tags
            'namedetails': '1'  # Include name details
        }

        # Only add countrycodes if country_hint is provided
        if country_hint is not None:
            params['countrycodes'] = country_hint.lower()[:2]  # Use 2-letter code

        headers = {
            'User-Agent': self.user_agent
        }

        try:
            print(f"Searching Nominatim for: {address}")
            response = requests.get(f"{self.base_url}/search",
                                  params=params,
                                  headers=headers,
                                  timeout=10)
            response.raise_for_status()
            data = response.json()

            if not data:
                print(f"No results found for: {address}")
                # Try without country restriction
                return self._try_fallback_search(address, return_all_candidates)

            print(f"Found {len(data)} candidates")

            candidates = []
            for i, result in enumerate(data):
                components = self._extract_components(result)
                candidates.append(components)
                print(f"Candidate {i+1}: {components.formatted_address} (score: {components.score:.1f})")

            return candidates if return_all_candidates else [candidates[0]] if candidates else []

        except requests.exceptions.RequestException as e:
            print(f"Error with Nominatim request: {e}")
            return []
        except json.JSONDecodeError as e:
            print(f"Error parsing Nominatim response: {e}")
            return []


    def _try_fallback_search(
            self, address: str,
            return_all_candidates: bool)-> List[AddressComponents]:
        """Try search without country restriction if initial search fails"""

        self._rate_limit()

        params = {
            'q': address,
            'format': 'json',
            'addressdetails': '1',
            'limit': '5',
            'extratags': '1',
            'namedetails': '1'
        }

        headers = {'User-Agent': self.user_agent}

        try:
            logger.info("Trying fallback search without country restriction...")
            response = requests.get(f"{self.base_url}/search",
                                  params=params,
                                  headers=headers,
                                  timeout=10)
            response.raise_for_status()
            data = response.json()

            if data:
                logger.info("Fallback found %s candidates", len(data))
                candidates = []
                for result in data:
                    components = self._extract_components(result)
                    candidates.append(components)

                return candidates if return_all_candidates else [candidates[0]] if candidates else []

        except Exception as e:
            logger.error("Fallback search failed: %s", str(e))
            print(f"Fallback search failed: {e}")

        return []


    def _extract_components(self, result: dict) -> AddressComponents:
        """
        Extract address components from Nominatim response
        
        Args:
            result: Single result from Nominatim response
            
        Returns:
            AddressComponents object with parsed data
        """
        address_parts = result.get('address', {})

        # Print available address fields for debugging
        print(f"Available address fields: {list(address_parts.keys())}")

        return AddressComponents(
            house_number=address_parts.get('house_number'),
            street_name=address_parts.get('road'),
            neighborhood=self._get_neighborhood(address_parts),
            city=self._get_city(address_parts),
            subregion=self._get_subregion(address_parts),
            region=address_parts.get('state'),
            postal_code=address_parts.get('postcode'),
            country_code=address_parts.get('country_code', '').upper(),
            country_name=address_parts.get('country'),
            formatted_address=result.get('display_name'),
            location={
                'lat': float(result['lat']) if result.get('lat') else None,
                'lng': float(result['lon']) if result.get('lon') else None
            },
            score=self._calculate_score(result)
        )


    def _get_neighborhood(self, address_parts: dict) -> Optional[str]:
        """Extract neighborhood/suburb from various possible fields"""
        neighborhood_fields = ['neighbourhood', 'suburb', 'quarter', 'residential']
        for field in neighborhood_fields:
            if address_parts.get(field):
                return address_parts[field]
        return None


    def _get_city(self, address_parts: dict) -> Optional[str]:
        """Extract city from various possible fields"""
        city_fields = ['city', 'town', 'village', 'municipality']
        for field in city_fields:
            if address_parts.get(field):
                return address_parts[field]
        return None


    def _get_subregion(self, address_parts: dict) -> Optional[str]:
        """Extract subregion (county/district) from various possible fields"""
        subregion_fields = ['county', 'state_district', 'region']
        for field in subregion_fields:
            if address_parts.get(field):
                return address_parts[field]
        return None


    def _calculate_score(self, result: dict) -> float:
        """Calculate a relevance score for the result"""
        importance = result.get('importance', 0)
        # Convert importance (0-1) to percentage-like score
        return float(importance) * 100 if importance else 50.0


    def get_detailed_components(self, address: str, country_hint: Optional[str] = None) -> dict:
        """
        Get all available address components in a detailed dictionary format
        
        Args:
            address: Input address string
            country_hint: Country code to bias results
            
        Returns:
            Dictionary with all parsed components and metadata
        """
        results = self.parse_and_enrich_address(address, country_hint)

        if not results:
            return {
                'input_address': address,
                'parsed_components': {},
                'formatted_address': None,
                'coordinates': None,
                'match_score': None,
                'enriched_elements': [],
                'success': False,
                'message': 'No results found'
            }

        best_result = results[0]  # Take the first (best) result

        return {
            'input_address': address,
            'parsed_components': {
                'house_number': best_result.house_number,
                'street_name': best_result.street_name,
                'neighborhood': best_result.neighborhood,
                'city': best_result.city,
                'district_county': best_result.subregion,
                'state_province': best_result.region,
                'postal_code': best_result.postal_code,
                'country_code': best_result.country_code,
                'country_name': best_result.country_name,
            },
            'formatted_address': best_result.formatted_address,
            'coordinates': best_result.location,
            'match_score': best_result.score,
            'enriched_elements': self._identify_enriched_elements(address, best_result),
            'success': True,
            'total_candidates': len(results)
        }


    def _identify_enriched_elements(
            self, original: str,
            components: AddressComponents) -> List[str]:
        """Identify which elements were enriched/added by geocoding"""
        enriched = []
        original_lower = original.lower()

        # Check for enriched country code
        if components.country_code and components.country_code.lower() not in original_lower:
            enriched.append(f"country_code: {components.country_code}")

        # Check for enriched city
        if components.city and components.city.lower() not in original_lower:
            enriched.append(f"city: {components.city}")

        # Check for enriched postal code
        if components.postal_code and str(components.postal_code) not in original:
            enriched.append(f"postal_code: {components.postal_code}")

        # Check for enriched neighborhood
        if components.neighborhood and components.neighborhood.lower() not in original_lower:
            enriched.append(f"neighborhood: {components.neighborhood}")

        return enriched


    def _get_country_code_from_name(self, name: str) -> Optional[str]:
        """
        Given a name (country or city, in the case of a city/state such as Singapore),
        this function uses the pycountry library to find
        the corresponding two-character ISO 3166-1 alpha-2 country code.

        The function performs a case-insensitive search by checking common
        attributes and uses fuzzy searching as a fallback.

        Args:
            country_name: A string representing the name of a country.

        Returns:
            A string with the two-character country code if a match is found,
            otherwise None.
        """
        if not isinstance(name, str):
            return None

        normalised_name = name.strip().lower()

         # If it's already a 2-char code, validate and return
        if len(normalised_name) == 2:
            try:
                country = pycountry.countries.get(alpha_2=normalised_name.upper())
                return country.alpha_2 if country else None
            except Exception:
                pass

        # Try by alpha_3 code
        if len(normalised_name) == 3:
            country = pycountry.countries.get(alpha_3=normalised_name.upper())
            if country:
                return country.alpha_2

        # 1. Try to find an exact match first using various country name attributes.
        # This is more reliable than fuzzy search for known, clean inputs.
        try:
            # Check against 'name'.
            for country in pycountry.countries:
                if normalised_name in [country.name.lower(), getattr(country, 'name', '').lower()]:
                    return country.alpha_2
        except LookupError:
            # This part of the code is generally safe, but a LookupError could occur.
            pass

        try:
            # Check against 'name', 'official_name'.
            for country in pycountry.countries:
                if normalised_name in [country.name.lower(), getattr(country, 'official_name', '').lower()]:
                    return country.alpha_2
        except LookupError:
            # This part of the code is generally safe, but a LookupError could occur.
            pass

        try:
            # Check against 'name', 'common_name'.
            for country in pycountry.countries:
                if normalised_name in [country.name.lower(), getattr(country, 'common_name', '').lower()]:
                    return country.alpha_2
        except LookupError:
            # This part of the code is generally safe, but a LookupError could occur.
            pass

        # Check is a multi-label country, i.e. name and code (e.g. Italy IT)
        try:
            found_code = self._extract_country_code_from_multilabel(normalised_name)
            if found_code:
                return found_code
        except Exception:
            pass

        # 2. As a fallback, use the robust `search_fuzzy` method.
        try:
            matches = pycountry.countries.search_fuzzy(normalised_name)
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
        logger.info("No country code found for '%s'", name)

        return None


    def _extract_country_code_from_multilabel(self, text: str) -> Optional[str]:
        """
        Extract a 2-character country code from a text string.
        Handles both 2-letter (ISO alpha-2) and 3-letter (ISO alpha-3) country codes,
        always returning the 2-letter equivalent.
        
        Args:
            text (str): Input string containing multi labels 
            such as country name and code (e.g. spain es, spain esp)
            
        Returns:
            Optional[str]: The 2-character country code in uppercase, or None if not found
        """
        text = text.strip().upper()

        # Look for both 2-char and 3-char codes at word boundaries
        # Priority: 2-char codes first, then 3-char codes
        patterns = [
            (r'\b([A-Z]{2})\b', lambda x: x if x in self.valid_country_codes else None),
            (r'\b([A-Z]{3})\b', lambda x: self._convert_alpha3_to_alpha2(x))
        ]

        for pattern, validator in patterns:
            matches = re.findall(pattern, text)
            for match in reversed(matches):  # Check from end first
                result = validator(match)
                if result:
                    return result

        # Check end of string patterns
        end_patterns = [
            (r'([A-Z]{2})$', lambda x: x if x in self.valid_country_codes else None),
            (r'([A-Z]{3})$', lambda x: self._convert_alpha3_to_alpha2(x))
        ]
        
        for pattern, validator in end_patterns:
            match = re.search(pattern, text)
            if match:
                result = validator(match.group(1))
                if result:
                    return result
        
        return None


    def _convert_alpha3_to_alpha2(self, alpha3_code: str) -> Optional[str]:
        """Helper method to convert 3-letter country code to 2-letter code."""
        try:
            country = pycountry.countries.get(alpha_3=alpha3_code)
            if country and country.alpha_2 in self.valid_country_codes:
                return country.alpha_2
        except (AttributeError, KeyError):
            pass
        return None


    def _build_search_query(self, address_dict: Dict[str, str], exclude_keys: set = None) -> str:
        """
        Build a search query from available address components.
        
        Args:
            address_dict: Dictionary of libpostal labels and values
            exclude_keys: Keys to exclude from the search query
            
        Returns:
            Formatted search string for geocoding
        """
        if exclude_keys is None:
            exclude_keys = set()

        # Priority order for address components
        priority_order = [
            'house_number', 'house', 'unit', 'road',
            'suburb', 'city_district', 'neighbourhood', 
            'city', 'town', 'village',
            'state_district', 'state', 'po_box', 
            'postcode', 'country'
        ]

        query_parts = []

        # Add components in priority order
        for key in priority_order:
            if key in address_dict and key not in exclude_keys and address_dict[key]:
                query_parts.append(address_dict[key].strip())

        # Add any remaining components not in priority list
        for key, value in address_dict.items():
            if key not in priority_order and key not in exclude_keys and value:
                query_parts.append(value.strip())

        return ', '.join(query_parts)


    def _geocode_with_retry(self, query: str, max_retries: int = 2) -> Optional[Any]:
        """
        Perform geocoding with retry logic for network errors only
        
        Args:
            query: Search query string
            max_retries: Maximum number of retry attempts
            
        Returns:
            Geocoding result or None if failed
        """
        for attempt in range(max_retries):
            try:
                self._rate_limit()
                logger.info("Geocoding query: %s", query)

                # Set language preference for Latin characters if enabled
                if self.prefer_latin:
                    result = self.geolocator.geocode(
                        query,
                        exactly_one=True,
                        addressdetails=True,
                        language='en'
                    )
                else:
                    result = self.geolocator.geocode(
                        query,
                        exactly_one=True,
                        addressdetails=True
                    )

                # If we get a result (even if it's None), don't retry
                # None means the address wasn't found, which won't change on retry
                return result

            except (GeocoderTimedOut, GeocoderServiceError) as e:
                logger.warning(
                    "Geocoding attempt %s failed due to network/service error: %s",
                     attempt + 1,
                     str(e))
                if attempt < max_retries - 1:
                    time.sleep(1.5 ** attempt)  # Reduced retry delay
                else:
                    logger.error("All geocoding attempts failed for query: %s", query)
            except Exception as e:
                # For other exceptions (like address parsing issues), don't retry
                logger.warning("Geocoding failed with non-retryable error: %s", str(e))
                return None

        return None


    def _extract_country_from_geocode(self, result: Any) -> Optional[str]:
        """Extract country code from geocoding result."""
        try:
            if hasattr(result, 'raw') and 'address' in result.raw:
                address = result.raw['address']
                return address.get('country_code', '').upper()
        except (AttributeError, KeyError) as e:
            logger.warning("Error extracting country from geocode result: %s", e)
        return None


    def _extract_city_from_geocode(self, result: Any) -> Optional[str]:
        """Extract village/suburb/town/city from geocoding result."""
        try:
            if hasattr(result, 'raw') and 'address' in result.raw:
                address = result.raw['address']
                # Try different city-level components in order of preference
                for key in ['village', 'suburb', 'town', 'city', 'municipality', 'county']:
                    if key in address and address[key]:
                        return address[key]
        except Exception as e:
            logger.warning("Error extracting city from geocode result: %s", e)
        return None


    def address_to_coordinates_nominatim(self, address: str) -> Optional[Tuple[float, float]]:
        """
        Convert address to lat/lng coordinates using Nominatim
        
        Args:
            address: Address string
            
        Returns:
            Tuple of (latitude, longitude) or None
        """
        try:
            self._rate_limit()

            url = f"{self.base_url.rstrip('/')}/search"
            params = {
                'q': address,
                'format': 'json',
                'limit': 1
            }
            headers = {
                'User-Agent': self.user_agent
            }

            response = requests.get(url, params=params, headers=headers, timeout=10)
            response.raise_for_status()

            data = response.json()
            if data and len(data) > 0:
                result = data[0]
                lat = float(result.get('lat', 0))
                lon = float(result.get('lon', 0))
                if lat != 0 and lon != 0:
                    logger.info("Found coordinates: %s, %s for address: %s", lat, lon, address)
                    return (lat, lon)

            logger.warning("No coordinates found for address: %s", address)
            return None

        except Exception as e:
            logger.error("Error getting coordinates: %s", str(e))
            return None


    def coordinates_to_country_nominatim(self, lat: float, lon: float) -> Optional[str]:
        """
        Reverse geocode coordinates to get country using Nominatim
        
        Args:
            lat: Latitude
            lon: Longitude
            
        Returns:
            ISO 3166-1 alpha-2 country code or None
        """
        try:
            self._rate_limit()

            url = f"{self.base_url.rstrip('/')}/reverse"
            params = {
                'lat': lat,
                'lon': lon,
                'format': 'json',
                'addressdetails': 1,
                'zoom': 10  # Country level
            }
            headers = {
                'User-Agent': self.user_agent
            }

            response = requests.get(url, params=params, headers=headers, timeout=10)
            response.raise_for_status()

            data = response.json()
            address_details = data.get('address', {})
            country_code = address_details.get('country_code', '').upper()

            if country_code:
                logger.info("Reverse geocoding found country: %s for coordinates: %s, %s", country_code, lat, lon)
                return country_code
            else:
                logger.warning("No country found for coordinates: %s, %s", lat, lon)
                return None

        except Exception as e:
            logger.error("Error reverse geocoding coordinates %s, %s: %s", lat, lon, str (e))
            return None


    def address_to_coordinates_progressive(self, address: str) -> Optional[Tuple[float, float]]:
        """
        Try progressively simpler versions of address to get coordinates
        """
        # Create variations of the address
        variations = [address]

        if ', ' in address:
            parts = [part.strip() for part in address.split(', ')]

            # Try without business name (if multiple parts)
            if len(parts) > 2:
                variations.append(', '.join(parts[1:]))

            # Try just postcode + city (last 2 parts)
            if len(parts) >= 2:
                variations.append(', '.join(parts[-2:]))

            # Try just the last part (usually city)
            variations.append(parts[-1])

        # Try each variation
        for variation in variations:
            logger.info("Trying coordinate lookup for: %s", variation)
            coords = self.address_to_coordinates_nominatim(variation)
            if coords:
                return coords

        return None


    def get_country_via_coordinates(self, address: str) -> Optional[str]:
        """
        Main method: Convert address to coordinates, then to country
        
        Args:
            address: Address string
            
        Returns:
            ISO 3166-1 alpha-2 country code or None
        """
        logger.info("Starting coordinate-based country detection for: %s", address)

        # Step 1: Get coordinates
        coordinates = self.address_to_coordinates_progressive(address)
        if not coordinates:
            logger.warning("Could not get coordinates for address: %s", address)
            return None

        lat, lon = coordinates

        # Step 2: Reverse geocode to get country
        country = self.coordinates_to_country_nominatim(lat, lon)
        if country:
            logger.info("Successfully determined country %s via coordinates for address: %s", country, address)
        else:
            logger.warning("Could not determine country from coordinates %s, %s", lat, lon)

        return country


    def get_coordinates_and_country(
            self, address: str) -> Tuple[Optional[Tuple[float, float]], Optional[str]]:
        """
        Get both coordinates and country for an address
        
        Returns:
            Tuple of ((lat, lon), country_code) where either can be None
        """
        coordinates = self.address_to_coordinates_progressive(address)
        country = None

        if coordinates:
            lat, lon = coordinates
            country = self.coordinates_to_country_nominatim(lat, lon)

        return coordinates, country


def geo_enrich_with_nominatim_parsing(
        address_string: str,
        country_code_hint: str | None) -> Tuple[str | None, str | None, str | None, str | None]:
    """
    Nominatim address parsing and enrichment 
    
    Args:
        address_string:  single string containing the inout address to parse
    
    Returns:
        Tuple of strings - enriched elements str or None 
         (country_code, city, postcode, neighborhood)
    """
    country_code = None
    city = None
    postcode = None
    neighborhood = None

    if not address_string:
        return None, None, None, None

    # Initialize parser
    parser = AddressEnricher(user_agent="affinis_address_enricher")

    logger.info("Geocoder enrichment begins for: {address_string}")

    # Get detailed address components
    result = parser.get_detailed_components(address=address_string, country_hint=country_code_hint)

    if result['success']:
        logger.info("Parsed components: %s", result['parsed_components'])

        if result['enriched_elements']:
            logger.info("Available enriched elements: %s", result['enriched_elements'])
            for item in result['enriched_elements']:
                # Split key / value pair
                key, value = item.split(':', 1)

                if key == 'country_code':
                    country_code = value.strip()
                elif key == 'city':
                    city = value.strip()
                elif key == 'postal_code':
                    postcode = value.strip()
                elif key == 'neighborhood':
                    neighborhood = value.strip()

    else:
        logger.info(
            "Failed to enrich: %s, trying reverse geocoding",
            result.get('message', 'Unknown error'))

    return country_code, city, postcode, neighborhood


def enrich_address(
    address_dict: Dict[str, str],
    country_code: Optional[str] = None,
    allow_geo_enrichment: bool = True,
    prefer_latin_names: bool = True
) -> Tuple[Dict[str, str], bool, bool]:
    """
    Enrich an address dictionary with missing country and city information.
    If country cannot be enriched, call a reverse geocoder as the final attempt.
    
    Args:
        address_dict: Dictionary with libpostal labels as keys and address components as values
        country_code: Optional 2-character country code
        allow_geo_enrichment: Whether to allow geocoding-based enrichment
        prefer_latin_names: Whether to prefer Latin/English names from geocoding results
        
    Returns:
        Tuple of (enriched_address_dict, city_enriched, country_enriched)
    """
    # Create a copy to avoid modifying the original
    enriched_address = address_dict.copy()
    city_enriched = False
    country_enriched = False

    # Use provided country_code if available
    if country_code and len(country_code) == 2:
        if 'country' not in enriched_address or not enriched_address['country']:
            enriched_address['country'] = country_code.upper()
            country_enriched = True

    # Handle country code conversion first (doesn't require geo enrichment)
    enricher = AddressEnricher(prefer_latin=prefer_latin_names)
    current_country = enriched_address.get('country', '').strip()
    # Check and clean up current_country by removing non-letters
    if current_country:
        current_country = remove_chars_regex(current_country) # Remove any commas, periods
        enriched_address['country'] = current_country
        country_enriched = True

    if current_country and len(current_country) != 2:
        # If country exists but is not a 2-char code, convert it (no geo enrichment needed)
        country_code_from_name = enricher._get_country_code_from_name(current_country)
        if country_code_from_name:
            current_country = country_code_from_name
            enriched_address['country'] = country_code_from_name
            country_enriched = True
            logger.info("Converted country '%s' to code '%s'", current_country,
                        country_code_from_name)

    # Recheck if country_code is now 2 chars
    if current_country and len(current_country) != 2:
        # Check for city / state, i.e if no country code but city is Singapore or Monaco
        # then return the country code relavent to this (doesn't require geoenrichment)
        if country_code := enricher._get_country_code_from_name(enriched_address['city']):
            enriched_address['country'] = country_code

    # Early return if geo enrichment is not allowed
    if not allow_geo_enrichment:
        return enriched_address, city_enriched, country_enriched

    # Update current_country after potential conversion
    current_country = enriched_address.get('country', '').strip()

    # Handle remaining country enrichment (requires geo enrichment)
    if not current_country:
        # Country is missing, try to get it via geocoding
        search_query = enricher._build_search_query(enriched_address, exclude_keys={'country'})
        if search_query:
            geocode_result = enricher._geocode_with_retry(search_query)
            if geocode_result:
                country_from_geo = enricher._extract_country_from_geocode(geocode_result)
                if country_from_geo:
                    enriched_address['country'] = country_from_geo
                    country_enriched = True
                    logger.info("Enriched missing country with '%s'", country_from_geo)
                # Still no country, so try reverse geocodering using lat, long
                else:
                    # Get both coordinates and country
                    coordinates, country_from_reverse_geo = enricher.get_coordinates_and_country(search_query)
                    if country_from_reverse_geo:
                        enriched_address['country'] = country_from_reverse_geo.upper()
                        country_enriched = True
                        logger.info(
                            "Enriched missing country with reverse geocoding '%s'",
                            country_from_reverse_geo)

            else:
                coordinates, country_from_reverse_geo = enricher.get_coordinates_and_country(search_query)
                if country_from_reverse_geo:
                    enriched_address['country'] = country_from_reverse_geo
                    country_enriched = True
                    logger.info(
                        "Enriched missing country with reverse geocoding '%s'",
                        country_from_reverse_geo)


    # Handle city enrichment (only if geo enrichment is allowed
    # and we have sufficient location data)
    city_keys = ['city']
    has_city = any(enriched_address.get(key, '').strip() for key in city_keys)

    if not has_city:
        # City is missing so try to get it via geocoding using all available addresses elements
        search_query = enricher._build_search_query(
            enriched_address,
            exclude_keys=set(city_keys)
            )
        country_code_hint = enriched_address['country']
        enriched_country_code, enriched_city, enriched_postcode, enriched_neighborhood = geo_enrich_with_nominatim_parsing(address_string=search_query, country_code_hint=country_code_hint)

        if enriched_city:
            enriched_address['city'] = enriched_city.strip()
            city_enriched = True
            logger.info("Enriched missing city with geocoding '%s'", enriched_city.strip())

    return enriched_address, city_enriched, country_enriched
