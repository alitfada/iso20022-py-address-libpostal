package com.iso20022.address;

import org.apache.commons.csv.CSVFormat;
import org.apache.commons.csv.CSVPrinter;
import org.slf4j.Logger;

import java.io.FileWriter;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.*;

/**
 * ISO 20022 Structured Address (Libpostal) Converter - Main entry point.
 *
 * Reads a file of one or more addresses and converts to ISO 20022 PostalAddress24
 * structured address(es). Uses libpostal for parsing and optional Nominatim
 * geocoding for enrichment of missing Town Name and Country Code.
 */
public class Main {

    private static final Logger logger = AppLogger.getLogger();

    /**
     * Converts a Windows file path to its corresponding WSL path.
     */
    static String getWslPath(String windowsPath) {
        windowsPath = windowsPath.strip().replace("\"", "").replace("'", "");
        if (windowsPath.startsWith("C:") || windowsPath.startsWith("D:") || windowsPath.startsWith("E:")) {
            char drive = Character.toLowerCase(windowsPath.charAt(0));
            String path = windowsPath.substring(2).replace("\\", "/");
            return "/mnt/" + drive + path;
        }
        return windowsPath;
    }

    /**
     * Captures user input for processing parameters.
     */
    static Map<String, Object> getInputParameters() {
        Scanner scanner = new Scanner(System.in);

        // Get input file path
        System.out.print("Enter Text file path: ");
        String inputFilePath = scanner.nextLine().strip();
        String os = System.getProperty("os.name", "").toLowerCase();
        if (os.contains("linux")) {
            inputFilePath = getWslPath(inputFilePath);
        }
        if (inputFilePath.isEmpty()) {
            System.out.println("Please enter a valid file path.");
            System.exit(1);
        }
        if (!Files.exists(Paths.get(inputFilePath))) {
            System.out.println("File not found: " + inputFilePath);
            System.exit(1);
        }

        // Get output directory
        System.out.print("Enter Output folder: ");
        String outputDir = scanner.nextLine().strip();
        if (os.contains("linux")) {
            outputDir = getWslPath(outputDir);
        }
        if (outputDir.isEmpty()) {
            System.out.println("Please enter a valid folder.");
            System.exit(1);
        }
        if (!Files.exists(Paths.get(outputDir))) {
            System.out.println("Folder not found: " + outputDir);
            System.exit(1);
        }

        // Display address type options
        System.out.println("\nAvailable address types:");
        AddressType[] types = AddressType.values();
        for (int i = 0; i < types.length; i++) {
            System.out.printf("%d. %s (%s)%n", i + 1, types[i].name(), types[i].getValue());
        }

        // Get address type
        AddressType addressType = null;
        while (addressType == null) {
            try {
                System.out.print("Select address type of input file (1): ");
                String input = scanner.nextLine().strip();
                int choice = input.isEmpty() ? 1 : Integer.parseInt(input);
                addressType = types[choice - 1];
            } catch (Exception e) {
                System.out.println("Invalid selection. Please enter a number between 1-" + types.length + ".");
            }
        }

        // Get start row
        int startRow = 1;
        while (true) {
            try {
                System.out.print("Enter starting row number in file (default 1): ");
                String input = scanner.nextLine().strip();
                startRow = input.isEmpty() ? 1 : Integer.parseInt(input);
                if (startRow >= 0) break;
                System.out.println("Row number must be 0 or positive.");
            } catch (NumberFormatException e) {
                System.out.println("Please enter a valid integer.");
            }
        }

        // Get allow_hybrid preference
        System.out.print("Allow hybrid address output? (y/N): ");
        String hybridInput = scanner.nextLine().strip().toLowerCase();
        boolean allowHybrid = hybridInput.equals("y") || hybridInput.equals("yes");

        // Get allow_geo_enrichment preference
        System.out.print("Allow geo-enrichment if Town Name or Country missing? (y/N): ");
        String geoInput = scanner.nextLine().strip().toLowerCase();
        boolean allowGeoEnrichment = geoInput.equals("y") || geoInput.equals("yes");

        Map<String, Object> params = new LinkedHashMap<>();
        params.put("input_file_path", inputFilePath);
        params.put("output_dir", outputDir);
        params.put("address_type", addressType);
        params.put("start_row", startRow);
        params.put("allow_hybrid", allowHybrid);
        params.put("allow_geo_enrichment", allowGeoEnrichment);
        return params;
    }

    public static void main(String[] args) {
        System.out.println("====== Capturing file processing parameters ======");
        Map<String, Object> params = getInputParameters();

        // Initialise file logging
        Path outputDirectory = Paths.get((String) params.get("output_dir"));
        if (!AppLogger.getInstance().configure(outputDirectory)) {
            System.out.println("Failed to initialise logging - falling back to console only");
        }
        logger.info("Logging initialised in {}", outputDirectory);

        // Process addresses
        AddressProcessor processor = new AddressProcessor();
        List<Map<String, String>> results = processor.processTextFile(
                (String) params.get("input_file_path"),
                (AddressType) params.get("address_type"),
                (int) params.get("start_row"),
                (boolean) params.get("allow_hybrid"),
                (boolean) params.get("allow_geo_enrichment")
        );

        // Load XSD schema paths
        String structuredXsdPath = getWslPath(Config.XSD_FILE_PATH_STRUCTURED);
        String hybridXsdPath = getWslPath(Config.XSD_FILE_PATH_HYBRID);

        // Convert addresses to PostalAddress24
        try {
            List<Map<String, String>> convertedResults = AddressConverter.convertAddressesToXml(
                    results, structuredXsdPath, hybridXsdPath, (boolean) params.get("allow_hybrid"));

            // Save as CSV
            Path outputCsvPath = outputDirectory.resolve("ConvertedPostalAddress24.csv");
            writeCsv(convertedResults, outputCsvPath);

            logger.info("CSV saved to: {}", outputCsvPath);
            System.out.println("CSV saved to: " + outputCsvPath);
            logger.info("Processing completed successfully");

        } catch (IOException e) {
            if (e.getMessage() != null && e.getMessage().contains("Permission")) {
                logger.error("Cannot write to CSV file - file may be open in another program: {}", e.getMessage());
                System.out.println("Error: Cannot write to output file");
                System.out.println("Please close the file if it's open in Excel or another program, then try again.");
            } else {
                logger.error("File I/O error occurred: {}", e.getMessage());
                System.out.println("File error: " + e.getMessage());
            }
            System.exit(1);
        }
    }

    /**
     * Write list of maps to CSV file, collecting all unique keys as headers.
     */
    private static void writeCsv(List<Map<String, String>> rows, Path outputPath) throws IOException {
        if (rows.isEmpty()) {
            logger.warn("No data to write to CSV");
            return;
        }

        // Collect all unique column headers in order
        Set<String> headerSet = new LinkedHashSet<>();
        for (Map<String, String> row : rows) {
            headerSet.addAll(row.keySet());
        }
        String[] headers = headerSet.toArray(new String[0]);

        try (FileWriter writer = new FileWriter(outputPath.toFile());
             CSVPrinter csvPrinter = new CSVPrinter(writer,
                     CSVFormat.DEFAULT.builder()
                             .setHeader(headers)
                             .setQuoteMode(org.apache.commons.csv.QuoteMode.ALL)
                             .build())) {

            for (Map<String, String> row : rows) {
                List<String> values = new ArrayList<>();
                for (String header : headers) {
                    values.add(row.getOrDefault(header, ""));
                }
                csvPrinter.printRecord(values);
            }
        }
    }
}
