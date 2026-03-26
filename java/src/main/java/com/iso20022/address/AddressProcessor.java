package com.iso20022.address;

import org.slf4j.Logger;

import java.io.BufferedReader;
import java.io.FileInputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.*;

/**
 * Processes addresses from text files (equivalent to Python AddressProcessor class in main.py).
 */
public class AddressProcessor {

    private static final Logger logger = AppLogger.getLogger();

    /**
     * Process addresses from a text file (one address per row).
     *
     * @param filePath            path to the text file
     * @param addressType         type of address
     * @param startRow            1-based row to start processing from
     * @param allowHybrid         allow fallback to hybrid address
     * @param allowGeoEnrichment  allow geocoder enrichment for missing fields
     * @param logInterval         interval for progress logging
     * @return list of maps representing parsed address data (each map = one row)
     */
    public List<Map<String, String>> processTextFile(
            String filePath,
            AddressType addressType,
            int startRow,
            boolean allowHybrid,
            boolean allowGeoEnrichment,
            int logInterval) {

        List<Map<String, String>> parsedData = new ArrayList<>();

        Map<AddressType, Integer> expectedLengths = Map.of(
                AddressType.UNSTRUCTURED, 2000
        );

        int expectedLength = expectedLengths.getOrDefault(addressType, 2000);
        String addressTypeValue = addressType.getValue();

        try {
            System.out.println("Reading Text file: " + filePath);
            logger.info("Reading Text file: {}", filePath);

            try (BufferedReader reader = new BufferedReader(
                    new InputStreamReader(new FileInputStream(filePath), StandardCharsets.UTF_8))) {

                // Skip to start_row (1-based)
                for (int i = 1; i < startRow; i++) {
                    if (reader.readLine() == null) break;
                }

                String line;
                int lineNum = startRow;

                while ((line = reader.readLine()) != null) {
                    String strippedLine = line.stripTrailing();

                    if (strippedLine.isEmpty()) {
                        logger.warn("Line {} is empty - skipped", lineNum);
                        lineNum++;
                        continue;
                    }

                    // Batch logging for performance
                    if (lineNum % logInterval == 0) {
                        System.out.println("Processed " + lineNum + " lines...");
                        logger.info("Processed {} lines", lineNum);
                    }

                    try {
                        int actualLength = strippedLine.length();
                        String originalLine = strippedLine;

                        // Handle truncation if needed
                        if (actualLength > expectedLength) {
                            logger.warn(
                                    "TRUNCATION POSSIBLE: Line {}: Expected {} chars, got {}. Truncated: {}",
                                    lineNum, expectedLength, actualLength,
                                    originalLine.substring(expectedLength));
                            originalLine = originalLine.substring(0, expectedLength);
                        }

                        // Parse address based on type
                        AddressParser.ParseResult result = AddressParser.parseAddress(
                                originalLine, allowGeoEnrichment);

                        // Build entry map (flat structure for CSV output)
                        Map<String, String> entry = new LinkedHashMap<>();
                        entry.put("address_type", addressTypeValue);
                        entry.put("original_address_type", addressTypeValue);
                        entry.put("expected_length", String.valueOf(expectedLength));
                        entry.put("actual_length", String.valueOf(actualLength));
                        entry.put("is_length_valid", String.valueOf(actualLength == expectedLength));
                        entry.put("allow_hybrid", String.valueOf(allowHybrid));
                        entry.put("allow_geo_enrichment", String.valueOf(allowGeoEnrichment));
                        entry.put("raw_address", strippedLine);

                        // Add raw fields
                        if (result.rawFields() != null) {
                            for (Map.Entry<String, String> e : result.rawFields().entrySet()) {
                                entry.put("raw_address_data." + e.getKey(), e.getValue());
                            }
                        }

                        // Add libpostal fields
                        if (result.optimisedFields() != null) {
                            for (Map.Entry<String, String> e : result.optimisedFields().entrySet()) {
                                entry.put("libpostal_data." + e.getKey(), e.getValue());
                            }
                        }

                        // Add best address components
                        if (result.bestAddressComponents() != null) {
                            for (Map.Entry<String, String> e : result.bestAddressComponents().entrySet()) {
                                entry.put("best_address." + e.getKey(), e.getValue());
                            }
                        }

                        entry.put("city_enriched", String.valueOf(result.cityEnriched()));
                        entry.put("country_enriched", String.valueOf(result.countryEnriched()));

                        parsedData.add(entry);

                    } catch (IllegalArgumentException | ClassCastException e) {
                        logger.error("Error parsing line {}: {}", lineNum, e.getMessage());
                    }

                    lineNum++;
                }
            }

        } catch (Exception e) {
            logger.error("Error: {}", e.getMessage());
            return new ArrayList<>();
        }

        System.out.println("Completed processing " + parsedData.size() + " lines");
        logger.info("Completed processing {} lines", parsedData.size());

        return parsedData;
    }

    public List<Map<String, String>> processTextFile(
            String filePath, AddressType addressType, int startRow,
            boolean allowHybrid, boolean allowGeoEnrichment) {
        return processTextFile(filePath, addressType, startRow, allowHybrid, allowGeoEnrichment, 1000);
    }
}
