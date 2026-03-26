package com.iso20022.address;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.neovisionaries.i18n.CountryCode;
import org.slf4j.Logger;

import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.*;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Address enrichment using Nominatim geocoding and country code standardization.
 * Equivalent to Python address_enricher.py.
 */
public class AddressEnricher {

    private static final Logger logger = AppLogger.getLogger();
    private static final ObjectMapper objectMapper = new ObjectMapper();

    private final HttpClient httpClient;
    private final String userAgent;
    private final long delayMs;
    private final boolean preferLatin;
    private final String baseUrl;
    private final Set<String> validCountryCodes;
    private long lastRequestTime = 0;

    public AddressEnricher() {
        this("affinis_address_enricher", 10, 1000, true, "https://nominatim.openstreetmap.org");
    }

    public AddressEnricher(boolean preferLatin) {
        this("affinis_address_enricher", 10, 1000, preferLatin, "https://nominatim.openstreetmap.org");
    }

    public AddressEnricher(String userAgent, int timeoutSec, long delayMs,
                           boolean preferLatin, String baseUrl) {
        this.userAgent = userAgent;
        this.delayMs = delayMs;
        this.preferLatin = preferLatin;
        this.baseUrl = baseUrl;
        this.httpClient = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(timeoutSec))
                .build();

        // Build valid country codes set from nv-i18n
        this.validCountryCodes = new HashSet<>();
        for (CountryCode cc : CountryCode.values()) {
            if (cc != CountryCode.UNDEFINED) {
                validCountryCodes.add(cc.getAlpha2());
            }
        }
    }

    private void rateLimit() {
        long currentTime = System.currentTimeMillis();
        long timeSinceLast = currentTime - lastRequestTime;
        if (timeSinceLast < delayMs) {
            try {
                Thread.sleep(delayMs - timeSinceLast);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
        }
        lastRequestTime = System.currentTimeMillis();
    }

    /**
     * Parse and enrich an address string using Nominatim geocoding.
     */
    public List<AddressComponents> parseAndEnrichAddress(String address, String countryHint,
                                                          boolean returnAllCandidates) {
        rateLimit();

        StringBuilder urlBuilder = new StringBuilder(baseUrl).append("/search?");
        urlBuilder.append("q=").append(URLEncoder.encode(address, StandardCharsets.UTF_8));
        urlBuilder.append("&format=json&addressdetails=1");
        urlBuilder.append("&limit=").append(returnAllCandidates ? "10" : "5");
        urlBuilder.append("&extratags=1&namedetails=1");

        if (countryHint != null && !countryHint.isEmpty()) {
            urlBuilder.append("&countrycodes=")
                    .append(countryHint.toLowerCase().substring(0, Math.min(2, countryHint.length())));
        }

        try {
            System.out.println("Searching Nominatim for: " + address);
            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create(urlBuilder.toString()))
                    .header("User-Agent", userAgent)
                    .timeout(Duration.ofSeconds(10))
                    .GET()
                    .build();

            HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
            JsonNode data = objectMapper.readTree(response.body());

            if (!data.isArray() || data.isEmpty()) {
                System.out.println("No results found for: " + address);
                return tryFallbackSearch(address, returnAllCandidates);
            }

            System.out.println("Found " + data.size() + " candidates");
            List<AddressComponents> candidates = new ArrayList<>();
            for (int i = 0; i < data.size(); i++) {
                AddressComponents components = extractComponents(data.get(i));
                candidates.add(components);
                System.out.printf("Candidate %d: %s (score: %.1f)%n",
                        i + 1, components.getFormattedAddress(), components.getScore());
            }

            if (returnAllCandidates) {
                return candidates;
            }
            return candidates.isEmpty() ? List.of() : List.of(candidates.get(0));

        } catch (Exception e) {
            System.out.println("Error with Nominatim request: " + e.getMessage());
            return List.of();
        }
    }

    private List<AddressComponents> tryFallbackSearch(String address, boolean returnAllCandidates) {
        rateLimit();

        String url = baseUrl + "/search?q=" + URLEncoder.encode(address, StandardCharsets.UTF_8)
                + "&format=json&addressdetails=1&limit=5&extratags=1&namedetails=1";

        try {
            logger.info("Trying fallback search without country restriction...");
            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create(url))
                    .header("User-Agent", userAgent)
                    .timeout(Duration.ofSeconds(10))
                    .GET()
                    .build();

            HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
            JsonNode data = objectMapper.readTree(response.body());

            if (data.isArray() && !data.isEmpty()) {
                logger.info("Fallback found {} candidates", data.size());
                List<AddressComponents> candidates = new ArrayList<>();
                for (JsonNode result : data) {
                    candidates.add(extractComponents(result));
                }
                if (returnAllCandidates) {
                    return candidates;
                }
                return candidates.isEmpty() ? List.of() : List.of(candidates.get(0));
            }
        } catch (Exception e) {
            logger.error("Fallback search failed: {}", e.getMessage());
            System.out.println("Fallback search failed: " + e.getMessage());
        }
        return List.of();
    }

    private AddressComponents extractComponents(JsonNode result) {
        JsonNode addressParts = result.path("address");

        System.out.println("Available address fields: " + iteratorToList(addressParts.fieldNames()));

        AddressComponents components = new AddressComponents();
        components.setHouseNumber(getTextOrNull(addressParts, "house_number"));
        components.setStreetName(getTextOrNull(addressParts, "road"));
        components.setNeighborhood(getNeighborhood(addressParts));
        components.setCity(getCity(addressParts));
        components.setSubregion(getSubregion(addressParts));
        components.setRegion(getTextOrNull(addressParts, "state"));
        components.setPostalCode(getTextOrNull(addressParts, "postcode"));

        String cc = getTextOrNull(addressParts, "country_code");
        components.setCountryCode(cc != null ? cc.toUpperCase() : null);
        components.setCountryName(getTextOrNull(addressParts, "country"));
        components.setFormattedAddress(getTextOrNull(result, "display_name"));

        // Location
        String latStr = getTextOrNull(result, "lat");
        String lonStr = getTextOrNull(result, "lon");
        if (latStr != null && lonStr != null) {
            try {
                double lat = Double.parseDouble(latStr);
                double lng = Double.parseDouble(lonStr);
                components.setLocation(Map.of("lat", lat, "lng", lng));
            } catch (NumberFormatException ignored) {
            }
        }

        components.setScore(calculateScore(result));
        return components;
    }

    private String getNeighborhood(JsonNode addressParts) {
        for (String field : List.of("neighbourhood", "suburb", "quarter", "residential")) {
            String val = getTextOrNull(addressParts, field);
            if (val != null) return val;
        }
        return null;
    }

    private String getCity(JsonNode addressParts) {
        for (String field : List.of("city", "town", "village", "municipality")) {
            String val = getTextOrNull(addressParts, field);
            if (val != null) return val;
        }
        return null;
    }

    private String getSubregion(JsonNode addressParts) {
        for (String field : List.of("county", "state_district", "region")) {
            String val = getTextOrNull(addressParts, field);
            if (val != null) return val;
        }
        return null;
    }

    private double calculateScore(JsonNode result) {
        JsonNode importance = result.get("importance");
        if (importance != null && importance.isNumber()) {
            return importance.asDouble() * 100;
        }
        return 50.0;
    }

    /**
     * Get all available address components in a detailed format.
     */
    public Map<String, Object> getDetailedComponents(String address, String countryHint) {
        List<AddressComponents> results = parseAndEnrichAddress(address, countryHint, false);

        Map<String, Object> output = new LinkedHashMap<>();
        output.put("input_address", address);

        if (results.isEmpty()) {
            output.put("parsed_components", Map.of());
            output.put("formatted_address", null);
            output.put("coordinates", null);
            output.put("match_score", null);
            output.put("enriched_elements", List.of());
            output.put("success", false);
            output.put("message", "No results found");
            return output;
        }

        AddressComponents best = results.get(0);

        Map<String, String> parsed = new LinkedHashMap<>();
        parsed.put("house_number", best.getHouseNumber());
        parsed.put("street_name", best.getStreetName());
        parsed.put("neighborhood", best.getNeighborhood());
        parsed.put("city", best.getCity());
        parsed.put("district_county", best.getSubregion());
        parsed.put("state_province", best.getRegion());
        parsed.put("postal_code", best.getPostalCode());
        parsed.put("country_code", best.getCountryCode());
        parsed.put("country_name", best.getCountryName());

        output.put("parsed_components", parsed);
        output.put("formatted_address", best.getFormattedAddress());
        output.put("coordinates", best.getLocation());
        output.put("match_score", best.getScore());
        output.put("enriched_elements", identifyEnrichedElements(address, best));
        output.put("success", true);
        output.put("total_candidates", results.size());

        return output;
    }

    private List<String> identifyEnrichedElements(String original, AddressComponents components) {
        List<String> enriched = new ArrayList<>();
        String originalLower = original.toLowerCase();

        if (components.getCountryCode() != null
                && !originalLower.contains(components.getCountryCode().toLowerCase())) {
            enriched.add("country_code: " + components.getCountryCode());
        }
        if (components.getCity() != null
                && !originalLower.contains(components.getCity().toLowerCase())) {
            enriched.add("city: " + components.getCity());
        }
        if (components.getPostalCode() != null
                && !original.contains(components.getPostalCode())) {
            enriched.add("postal_code: " + components.getPostalCode());
        }
        if (components.getNeighborhood() != null
                && !originalLower.contains(components.getNeighborhood().toLowerCase())) {
            enriched.add("neighborhood: " + components.getNeighborhood());
        }
        return enriched;
    }

    /**
     * Get country code from a country name using nv-i18n library.
     */
    public String getCountryCodeFromName(String name) {
        if (name == null || name.isBlank()) {
            return null;
        }

        String normalized = name.strip().toLowerCase();

        // If it's already a 2-char code, validate and return
        if (normalized.length() == 2) {
            CountryCode cc = CountryCode.getByCodeIgnoreCase(normalized);
            if (cc != null && cc != CountryCode.UNDEFINED) {
                return cc.getAlpha2();
            }
        }

        // Try by alpha-3 code
        if (normalized.length() == 3) {
            CountryCode cc = CountryCode.getByCodeIgnoreCase(normalized);
            if (cc != null && cc != CountryCode.UNDEFINED) {
                return cc.getAlpha2();
            }
        }

        // Try exact name match
        for (CountryCode cc : CountryCode.values()) {
            if (cc == CountryCode.UNDEFINED) continue;
            if (cc.getName().equalsIgnoreCase(normalized)) {
                return cc.getAlpha2();
            }
        }

        // Try Locale-based lookup
        for (Locale locale : Locale.getAvailableLocales()) {
            String country = locale.getCountry();
            if (country.length() == 2) {
                Locale countryLocale = Locale.of("", country);
                if (countryLocale.getDisplayCountry(Locale.ENGLISH).equalsIgnoreCase(normalized)) {
                    return country;
                }
            }
        }

        // Check multi-label country (e.g. "Italy IT")
        String fromMultiLabel = extractCountryCodeFromMultiLabel(normalized.toUpperCase());
        if (fromMultiLabel != null) {
            return fromMultiLabel;
        }

        // Fuzzy search: find by partial name match
        CountryCode bestMatch = CountryCode.findByName("(?i).*" + Pattern.quote(normalized) + ".*")
                .stream().findFirst().orElse(null);
        if (bestMatch != null && bestMatch != CountryCode.UNDEFINED) {
            return bestMatch.getAlpha2();
        }

        logger.info("No country code found for '{}'", name);
        return null;
    }

    private String extractCountryCodeFromMultiLabel(String text) {
        text = text.strip();

        // Look for 2-char codes at word boundaries
        Pattern alpha2Pattern = Pattern.compile("\\b([A-Z]{2})\\b");
        Matcher matcher = alpha2Pattern.matcher(text);
        List<String> matches = new ArrayList<>();
        while (matcher.find()) {
            matches.add(matcher.group(1));
        }
        // Check from end first
        for (int i = matches.size() - 1; i >= 0; i--) {
            if (validCountryCodes.contains(matches.get(i))) {
                return matches.get(i);
            }
        }

        // Look for 3-char codes
        Pattern alpha3Pattern = Pattern.compile("\\b([A-Z]{3})\\b");
        matcher = alpha3Pattern.matcher(text);
        matches.clear();
        while (matcher.find()) {
            matches.add(matcher.group(1));
        }
        for (int i = matches.size() - 1; i >= 0; i--) {
            String converted = convertAlpha3ToAlpha2(matches.get(i));
            if (converted != null) {
                return converted;
            }
        }

        return null;
    }

    private String convertAlpha3ToAlpha2(String alpha3Code) {
        try {
            CountryCode cc = CountryCode.getByCode(alpha3Code);
            if (cc != null && cc != CountryCode.UNDEFINED && validCountryCodes.contains(cc.getAlpha2())) {
                return cc.getAlpha2();
            }
        } catch (Exception ignored) {
        }
        return null;
    }

    /**
     * Build a search query from available address components.
     */
    public String buildSearchQuery(Map<String, String> addressDict, Set<String> excludeKeys) {
        if (excludeKeys == null) {
            excludeKeys = Set.of();
        }

        List<String> priorityOrder = List.of(
                "house_number", "house", "unit", "road",
                "suburb", "city_district", "neighbourhood",
                "city", "town", "village",
                "state_district", "state", "po_box",
                "postcode", "country"
        );

        List<String> queryParts = new ArrayList<>();
        Set<String> addedKeys = new HashSet<>();

        // Add components in priority order
        for (String key : priorityOrder) {
            if (addressDict.containsKey(key) && !excludeKeys.contains(key)) {
                String value = addressDict.get(key);
                if (value != null && !value.isBlank()) {
                    queryParts.add(value.strip());
                    addedKeys.add(key);
                }
            }
        }

        // Add remaining components not in priority list
        for (Map.Entry<String, String> entry : addressDict.entrySet()) {
            if (!addedKeys.contains(entry.getKey()) && !excludeKeys.contains(entry.getKey())) {
                String value = entry.getValue();
                if (value != null && !value.isBlank()) {
                    queryParts.add(value.strip());
                }
            }
        }

        return String.join(", ", queryParts);
    }

    /**
     * Perform geocoding with retry logic for network errors.
     */
    public JsonNode geocodeWithRetry(String query, int maxRetries) {
        for (int attempt = 0; attempt < maxRetries; attempt++) {
            try {
                rateLimit();
                logger.info("Geocoding query: {}", query);

                StringBuilder urlBuilder = new StringBuilder(baseUrl).append("/search?");
                urlBuilder.append("q=").append(URLEncoder.encode(query, StandardCharsets.UTF_8));
                urlBuilder.append("&format=json&addressdetails=1&limit=1");
                if (preferLatin) {
                    urlBuilder.append("&accept-language=en");
                }

                HttpRequest request = HttpRequest.newBuilder()
                        .uri(URI.create(urlBuilder.toString()))
                        .header("User-Agent", userAgent)
                        .timeout(Duration.ofSeconds(10))
                        .GET()
                        .build();

                HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
                JsonNode data = objectMapper.readTree(response.body());

                if (data.isArray() && !data.isEmpty()) {
                    return data.get(0);
                }
                return null; // No results, don't retry

            } catch (java.net.http.HttpTimeoutException e) {
                logger.warn("Geocoding attempt {} failed due to timeout: {}", attempt + 1, e.getMessage());
                if (attempt < maxRetries - 1) {
                    try {
                        Thread.sleep((long) Math.pow(1.5, attempt) * 1000);
                    } catch (InterruptedException ie) {
                        Thread.currentThread().interrupt();
                        return null;
                    }
                } else {
                    logger.error("All geocoding attempts failed for query: {}", query);
                }
            } catch (Exception e) {
                logger.warn("Geocoding failed with non-retryable error: {}", e.getMessage());
                return null;
            }
        }
        return null;
    }

    public JsonNode geocodeWithRetry(String query) {
        return geocodeWithRetry(query, 2);
    }

    /**
     * Extract country code from geocoding result.
     */
    public String extractCountryFromGeocode(JsonNode result) {
        try {
            JsonNode address = result.path("address");
            String cc = getTextOrNull(address, "country_code");
            return cc != null ? cc.toUpperCase() : null;
        } catch (Exception e) {
            logger.warn("Error extracting country from geocode result: {}", e.getMessage());
            return null;
        }
    }

    /**
     * Extract city from geocoding result.
     */
    public String extractCityFromGeocode(JsonNode result) {
        try {
            JsonNode address = result.path("address");
            for (String key : List.of("village", "suburb", "town", "city", "municipality", "county")) {
                String val = getTextOrNull(address, key);
                if (val != null) return val;
            }
        } catch (Exception e) {
            logger.warn("Error extracting city from geocode result: {}", e.getMessage());
        }
        return null;
    }

    /**
     * Convert address to lat/lng coordinates using Nominatim.
     */
    public double[] addressToCoordinatesNominatim(String address) {
        try {
            rateLimit();

            String url = baseUrl + "/search?q=" + URLEncoder.encode(address, StandardCharsets.UTF_8)
                    + "&format=json&limit=1";

            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create(url))
                    .header("User-Agent", userAgent)
                    .timeout(Duration.ofSeconds(10))
                    .GET()
                    .build();

            HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
            JsonNode data = objectMapper.readTree(response.body());

            if (data.isArray() && !data.isEmpty()) {
                JsonNode first = data.get(0);
                double lat = first.path("lat").asDouble(0);
                double lon = first.path("lon").asDouble(0);
                if (lat != 0 && lon != 0) {
                    logger.info("Found coordinates: {}, {} for address: {}", lat, lon, address);
                    return new double[]{lat, lon};
                }
            }

            logger.warn("No coordinates found for address: {}", address);
            return null;

        } catch (Exception e) {
            logger.error("Error getting coordinates: {}", e.getMessage());
            return null;
        }
    }

    /**
     * Reverse geocode coordinates to get country using Nominatim.
     */
    public String coordinatesToCountryNominatim(double lat, double lon) {
        try {
            rateLimit();

            String url = baseUrl + "/reverse?lat=" + lat + "&lon=" + lon
                    + "&format=json&addressdetails=1&zoom=10";

            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create(url))
                    .header("User-Agent", userAgent)
                    .timeout(Duration.ofSeconds(10))
                    .GET()
                    .build();

            HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
            JsonNode data = objectMapper.readTree(response.body());

            String cc = getTextOrNull(data.path("address"), "country_code");
            if (cc != null && !cc.isEmpty()) {
                String upper = cc.toUpperCase();
                logger.info("Reverse geocoding found country: {} for coordinates: {}, {}", upper, lat, lon);
                return upper;
            } else {
                logger.warn("No country found for coordinates: {}, {}", lat, lon);
                return null;
            }
        } catch (Exception e) {
            logger.error("Error reverse geocoding coordinates {}, {}: {}", lat, lon, e.getMessage());
            return null;
        }
    }

    /**
     * Try progressively simpler versions of address to get coordinates.
     */
    public double[] addressToCoordinatesProgressive(String address) {
        List<String> variations = new ArrayList<>();
        variations.add(address);

        if (address.contains(", ")) {
            String[] parts = address.split(", ");
            if (parts.length > 2) {
                variations.add(String.join(", ", Arrays.copyOfRange(parts, 1, parts.length)));
            }
            if (parts.length >= 2) {
                variations.add(String.join(", ", Arrays.copyOfRange(parts, parts.length - 2, parts.length)));
            }
            variations.add(parts[parts.length - 1].trim());
        }

        for (String variation : variations) {
            logger.info("Trying coordinate lookup for: {}", variation);
            double[] coords = addressToCoordinatesNominatim(variation);
            if (coords != null) {
                return coords;
            }
        }
        return null;
    }

    /**
     * Get country via coordinates (forward + reverse geocoding).
     */
    public String getCountryViaCoordinates(String address) {
        logger.info("Starting coordinate-based country detection for: {}", address);
        double[] coordinates = addressToCoordinatesProgressive(address);
        if (coordinates == null) {
            logger.warn("Could not get coordinates for address: {}", address);
            return null;
        }
        String country = coordinatesToCountryNominatim(coordinates[0], coordinates[1]);
        if (country != null) {
            logger.info("Successfully determined country {} via coordinates for address: {}", country, address);
        } else {
            logger.warn("Could not determine country from coordinates {}, {}", coordinates[0], coordinates[1]);
        }
        return country;
    }

    /**
     * Get both coordinates and country for an address.
     *
     * @return [0] = coordinates (double[2] or null), [1] = country code (String or null)
     */
    public Object[] getCoordinatesAndCountry(String address) {
        double[] coordinates = addressToCoordinatesProgressive(address);
        String country = null;
        if (coordinates != null) {
            country = coordinatesToCountryNominatim(coordinates[0], coordinates[1]);
        }
        return new Object[]{coordinates, country};
    }

    // ======================== Static enrichment methods ========================

    /**
     * Nominatim address parsing and enrichment.
     *
     * @return [countryCode, city, postcode, neighborhood] (any may be null)
     */
    @SuppressWarnings("unchecked")
    public static String[] geoEnrichWithNominatimParsing(String addressString, String countryCodeHint) {
        if (addressString == null || addressString.isBlank()) {
            return new String[]{null, null, null, null};
        }

        AddressEnricher parser = new AddressEnricher();
        logger.info("Geocoder enrichment begins for: {}", addressString);

        Map<String, Object> result = parser.getDetailedComponents(addressString, countryCodeHint);

        String countryCode = null;
        String city = null;
        String postcode = null;
        String neighborhood = null;

        if (Boolean.TRUE.equals(result.get("success"))) {
            logger.info("Parsed components: {}", result.get("parsed_components"));

            List<String> enrichedElements = (List<String>) result.get("enriched_elements");
            if (enrichedElements != null && !enrichedElements.isEmpty()) {
                logger.info("Available enriched elements: {}", enrichedElements);
                for (String item : enrichedElements) {
                    int colonIdx = item.indexOf(':');
                    if (colonIdx < 0) continue;
                    String key = item.substring(0, colonIdx).strip();
                    String value = item.substring(colonIdx + 1).strip();

                    switch (key) {
                        case "country_code" -> countryCode = value;
                        case "city" -> city = value;
                        case "postal_code" -> postcode = value;
                        case "neighborhood" -> neighborhood = value;
                    }
                }
            }
        } else {
            logger.info("Failed to enrich: {}, trying reverse geocoding",
                    result.getOrDefault("message", "Unknown error"));
        }

        return new String[]{countryCode, city, postcode, neighborhood};
    }

    /**
     * Enrich an address dictionary with missing country and city information.
     *
     * @return EnrichmentResult with enriched address, city_enriched, country_enriched flags
     */
    public static EnrichmentResult enrichAddress(Map<String, String> addressDict,
                                                  String countryCode,
                                                  boolean allowGeoEnrichment,
                                                  boolean preferLatinNames) {
        Map<String, String> enriched = new LinkedHashMap<>(addressDict);
        boolean cityEnriched = false;
        boolean countryEnriched = false;

        // Use provided country_code if available
        if (countryCode != null && countryCode.length() == 2) {
            String existing = enriched.getOrDefault("country", "").strip();
            if (existing.isEmpty()) {
                enriched.put("country", countryCode.toUpperCase());
                countryEnriched = true;
            }
        }

        AddressEnricher enricher = new AddressEnricher(preferLatinNames);
        String currentCountry = enriched.getOrDefault("country", "").strip();

        // Clean up country by removing punctuation
        if (currentCountry != null && !currentCountry.isEmpty()) {
            currentCountry = Helpers.removeCharsRegex(currentCountry);
            enriched.put("country", currentCountry);
            countryEnriched = true;
        }

        if (currentCountry != null && !currentCountry.isEmpty() && currentCountry.length() != 2) {
            String codeFromName = enricher.getCountryCodeFromName(currentCountry);
            if (codeFromName != null) {
                enriched.put("country", codeFromName);
                countryEnriched = true;
                logger.info("Converted country '{}' to code '{}'", currentCountry, codeFromName);
                currentCountry = codeFromName;
            }
        }

        // Check if city name is also a country (e.g., Singapore, Monaco)
        if (currentCountry == null || currentCountry.isEmpty() || currentCountry.length() != 2) {
            String cityValue = enriched.get("city");
            if (cityValue != null && !cityValue.isEmpty()) {
                String cityAsCountry = enricher.getCountryCodeFromName(cityValue);
                if (cityAsCountry != null) {
                    enriched.put("country", cityAsCountry);
                    currentCountry = cityAsCountry;
                }
            }
        }

        // Early return if geo enrichment is not allowed
        if (!allowGeoEnrichment) {
            return new EnrichmentResult(enriched, cityEnriched, countryEnriched);
        }

        // Update current country after potential conversion
        currentCountry = enriched.getOrDefault("country", "").strip();

        // Handle remaining country enrichment via geocoding
        if (currentCountry == null || currentCountry.isEmpty()) {
            String searchQuery = enricher.buildSearchQuery(enriched, Set.of("country"));
            if (searchQuery != null && !searchQuery.isEmpty()) {
                JsonNode geocodeResult = enricher.geocodeWithRetry(searchQuery);
                if (geocodeResult != null) {
                    String countryFromGeo = enricher.extractCountryFromGeocode(geocodeResult);
                    if (countryFromGeo != null) {
                        enriched.put("country", countryFromGeo);
                        countryEnriched = true;
                        logger.info("Enriched missing country with '{}'", countryFromGeo);
                    } else {
                        Object[] coordsAndCountry = enricher.getCoordinatesAndCountry(searchQuery);
                        String reverseCountry = (String) coordsAndCountry[1];
                        if (reverseCountry != null) {
                            enriched.put("country", reverseCountry.toUpperCase());
                            countryEnriched = true;
                            logger.info("Enriched missing country with reverse geocoding '{}'", reverseCountry);
                        }
                    }
                } else {
                    Object[] coordsAndCountry = enricher.getCoordinatesAndCountry(searchQuery);
                    String reverseCountry = (String) coordsAndCountry[1];
                    if (reverseCountry != null) {
                        enriched.put("country", reverseCountry);
                        countryEnriched = true;
                        logger.info("Enriched missing country with reverse geocoding '{}'", reverseCountry);
                    }
                }
            }
        }

        // Handle city enrichment
        String cityValue = enriched.getOrDefault("city", "").strip();
        if (cityValue.isEmpty()) {
            String searchQuery = enricher.buildSearchQuery(enriched, Set.of("city"));
            String countryHint = enriched.get("country");
            String[] enrichResult = geoEnrichWithNominatimParsing(searchQuery, countryHint);

            if (enrichResult[1] != null) {
                enriched.put("city", enrichResult[1].strip());
                cityEnriched = true;
                logger.info("Enriched missing city with geocoding '{}'", enrichResult[1].strip());
            }
        }

        return new EnrichmentResult(enriched, cityEnriched, countryEnriched);
    }

    // ======================== Utility ========================

    private static String getTextOrNull(JsonNode node, String field) {
        JsonNode child = node.get(field);
        if (child != null && !child.isNull() && child.isTextual()) {
            String text = child.asText();
            return text.isEmpty() ? null : text;
        }
        if (child != null && !child.isNull()) {
            String text = child.asText();
            return (text == null || text.isEmpty()) ? null : text;
        }
        return null;
    }

    private static List<String> iteratorToList(Iterator<String> iterator) {
        List<String> list = new ArrayList<>();
        iterator.forEachRemaining(list::add);
        return list;
    }

    /** Result container for enrichment operations. */
    public record EnrichmentResult(Map<String, String> enrichedAddress, boolean cityEnriched,
                                   boolean countryEnriched) {
    }
}
