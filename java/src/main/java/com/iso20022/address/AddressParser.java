package com.iso20022.address;

import com.mapzen.jpostal.AddressExpander;
import com.mapzen.jpostal.AddressParserResponse;
import org.slf4j.Logger;

import java.util.*;

/**
 * Address Parser Module (equivalent to Python address_parser.py).
 *
 * Provides functionality for parsing unstructured addresses using libpostal
 * and optional geocoding enrichment.
 */
public class AddressParser {

    private static final Logger logger = AppLogger.getLogger();

    private AddressParser() {
    }

    /**
     * Processes libpostal components to handle repeating fields optimally.
     * Returns the most complete version of each component (longest value).
     */
    static Map<String, String> optimiseLibpostalComponents(AddressParserResponse response) {
        if (response == null) {
            return Map.of();
        }

        String[] labels = response.getLabels();
        String[] values = response.getValues();

        if (labels == null || values == null || labels.length == 0) {
            return Map.of();
        }

        Map<String, String> optimised = new LinkedHashMap<>();

        for (int i = 0; i < labels.length; i++) {
            String componentType = labels[i];
            String value = values[i];

            if (!optimised.containsKey(componentType)) {
                optimised.put(componentType, value);
            } else {
                String existing = optimised.get(componentType);

                // Quick length comparison first (most common case)
                if (value.length() > existing.length()) {
                    optimised.put(componentType, value);
                } else if (value.length() == existing.length()) {
                    // Same length - prefer non-empty stripped version
                    String valueStripped = value.strip();
                    String existingStripped = existing.strip();

                    if (valueStripped.length() > existingStripped.length()) {
                        optimised.put(componentType, value);
                    } else if (valueStripped.length() == existingStripped.length()
                            && value.compareTo(existing) < 0) {
                        // Lexicographic tie-breaker for consistency
                        optimised.put(componentType, value);
                    }
                }
            }
        }
        return optimised;
    }

    /**
     * Converts libpostal response to a list of label-value pairs for storage.
     */
    static List<Map.Entry<String, String>> responseToList(AddressParserResponse response) {
        if (response == null) return List.of();
        String[] labels = response.getLabels();
        String[] values = response.getValues();
        List<Map.Entry<String, String>> result = new ArrayList<>();
        for (int i = 0; i < labels.length; i++) {
            result.add(Map.entry(values[i], labels[i]));
        }
        return result;
    }

    /**
     * Prepares unstructured address fields for libpostal parsing.
     */
    static String prepareForLibpostal(Map<String, String> rawFields) {
        String addressLine = rawFields.getOrDefault("address_line", "");
        String prepared = Helpers.cleanWhitespacePreserveNewlines(addressLine);
        rawFields.put("address_line", prepared);

        String component = prepared.isBlank() ? null : prepared;
        String addressToParse = component != null ? component : "";

        if (addressToParse.length() < Config.MIN_VIABLE_ADDRESS_LENGTH) {
            logger.warn("Address is too short for libpostal to reliably parse: {}", addressToParse);
        }

        return addressToParse;
    }

    /**
     * Parses an unstructured address string into structured components.
     *
     * @param addressStr           the input address string
     * @param allowGeoEnrichment   whether to attempt geo-enrichment for missing fields
     * @return ParseResult containing all parsed data and enrichment flags
     */
    public static ParseResult parseAddress(String addressStr, boolean allowGeoEnrichment) {
        if (addressStr.length() < Config.MIN_VIABLE_ADDRESS_LENGTH) {
            logger.error("Input string too short for reliable conversion");
            throw new IllegalArgumentException("Input string too short for reliable conversion");
        }

        // Parse the raw address
        Map<String, String> rawFields = new LinkedHashMap<>();
        rawFields.put("address_line", addressStr.strip());

        String libpostalInput = prepareForLibpostal(rawFields);

        // Configure and call libpostal
        LibpostalConfig.configure();
        com.mapzen.jpostal.AddressParser parser = com.mapzen.jpostal.AddressParser.getInstance();
        AddressParserResponse libpostalParsed = parser.parseAddress(libpostalInput);

        Map<String, String> optimisedComponents = optimiseLibpostalComponents(libpostalParsed);

        String countryCode = optimisedComponents.get("country");
        if (countryCode != null && countryCode.length() == 2) {
            countryCode = countryCode.toUpperCase();
        } else {
            countryCode = null;
        }

        AddressEnricher.EnrichmentResult enrichmentResult = AddressEnricher.enrichAddress(
                optimisedComponents,
                countryCode,
                allowGeoEnrichment,
                true // prefer latin names
        );

        // Store original libpostal parsed data
        optimisedComponents.put("libpostal_parsed_data", responseToList(libpostalParsed).toString());

        return new ParseResult(
                rawFields,
                optimisedComponents,
                enrichmentResult.enrichedAddress(),
                enrichmentResult.cityEnriched(),
                enrichmentResult.countryEnriched()
        );
    }

    /**
     * Container for address parsing results.
     */
    public record ParseResult(
            Map<String, String> rawFields,
            Map<String, String> optimisedFields,
            Map<String, String> bestAddressComponents,
            boolean cityEnriched,
            boolean countryEnriched
    ) {
    }
}
