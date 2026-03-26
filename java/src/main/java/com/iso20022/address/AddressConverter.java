package com.iso20022.address;

import org.slf4j.Logger;
import org.w3c.dom.Document;
import org.w3c.dom.Element;
import org.w3c.dom.Node;
import org.w3c.dom.NodeList;
import org.xml.sax.SAXException;

import javax.xml.parsers.DocumentBuilder;
import javax.xml.parsers.DocumentBuilderFactory;
import javax.xml.transform.OutputKeys;
import javax.xml.transform.Transformer;
import javax.xml.transform.TransformerFactory;
import javax.xml.transform.dom.DOMSource;
import javax.xml.transform.stream.StreamResult;
import javax.xml.transform.stream.StreamSource;
import javax.xml.validation.Schema;
import javax.xml.validation.SchemaFactory;
import javax.xml.validation.Validator;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.text.Normalizer;
import java.util.*;
import java.util.regex.Pattern;

/**
 * Address Converter Module (equivalent to Python address_converter.py).
 *
 * Converts parsed/enriched addresses to ISO 20022 PostalAddress24 structured
 * or hybrid address format with XML schema validation.
 */
public class AddressConverter {

    private static final Logger logger = AppLogger.getLogger();

    /** CBPR+ allowed character pattern */
    private static final Pattern CBPR_PATTERN = Pattern.compile(
            "[0-9a-zA-Z/\\-?:().,'+\\s!#$%&*=^_`{|}~\";<>@\\[\\\\\\]]"
    );

    /** Max lengths for each PostalAddress24 field */
    private static final Map<String, Integer> MAX_LENGTHS = Map.ofEntries(
            Map.entry("Dept", 70),
            Map.entry("SubDept", 70),
            Map.entry("StrtNm", 70),
            Map.entry("BldgNb", 16),
            Map.entry("BldgNm", 35),
            Map.entry("Flr", 70),
            Map.entry("PstBx", 16),
            Map.entry("Room", 70),
            Map.entry("PstCd", 16),
            Map.entry("TwnNm", 35),
            Map.entry("TwnLctnNm", 35),
            Map.entry("DstrctNm", 35),
            Map.entry("CtrySubDvsn", 35),
            Map.entry("Ctry", 2),
            Map.entry("AdrLine", 70)
    );

    /** Field order for structured XML format */
    private static final List<String> FIELD_ORDER = List.of(
            "Dept", "SubDept", "StrtNm", "BldgNb", "BldgNm", "Flr",
            "PstBx", "Room", "PstCd", "TwnNm", "TwnLctnNm", "DstrctNm",
            "CtrySubDvsn", "Ctry"
    );

    /** Optional field mappings from libpostal components to PostalAddress24 */
    private static final Map<String, String> OPTIONAL_MAPPINGS = new LinkedHashMap<>();
    static {
        OPTIONAL_MAPPINGS.put("department", "Dept");
        OPTIONAL_MAPPINGS.put("sub_department", "SubDept");
        OPTIONAL_MAPPINGS.put("road", "StrtNm");
        OPTIONAL_MAPPINGS.put("house_number", "BldgNb");
        OPTIONAL_MAPPINGS.put("house", "BldgNm");
        OPTIONAL_MAPPINGS.put("level", "Flr");
        OPTIONAL_MAPPINGS.put("po_box", "PstBx");
        OPTIONAL_MAPPINGS.put("unit", "Room");
        OPTIONAL_MAPPINGS.put("postcode", "PstCd");
        OPTIONAL_MAPPINGS.put("suburb", "TwnLctnNm");
        OPTIONAL_MAPPINGS.put("city_district", "DstrctNm");
    }

    /**
     * Normalize text to CBPR+ compliant format.
     *
     * @return [normalizedText, isAltered]
     */
    public static Object[] normalizeText(String text) {
        if (text == null || text.isEmpty()) {
            return new Object[]{"", false};
        }

        String original = text;
        boolean isAltered = false;
        boolean patternReplaced = false;

        // Replace special chars before NFKD normalization
        text = text.replace("\u0153", "oe"); // œ
        text = text.replace("\u00e6", "ae"); // æ
        text = text.replace("\u00df", "ss"); // ß
        text = text.replace("\u0133", "ij"); // ĳ

        // Normalize unicode to ASCII
        try {
            String normalized = Normalizer.normalize(text, Normalizer.Form.NFKD);
            // Remove non-ASCII characters
            StringBuilder asciiBuilder = new StringBuilder();
            for (char c : normalized.toCharArray()) {
                if (c < 128) {
                    asciiBuilder.append(c);
                }
            }
            String asciiText = asciiBuilder.toString();
            if (!asciiText.equals(original)) {
                isAltered = true;
                logger.warn("DATA REPLACED (ASCII): Original - {} | Normalised - {}", original, asciiText);
                text = asciiText;
            }
        } catch (Exception e) {
            logger.error("Unicode error trying to replace: {}", text);
        }

        // Replace non-CBPR+ characters with "."
        StringBuilder normalizedChars = new StringBuilder();
        for (char c : text.toCharArray()) {
            if (CBPR_PATTERN.matcher(String.valueOf(c)).matches()) {
                normalizedChars.append(c);
            } else {
                normalizedChars.append('.');
                isAltered = true;
                patternReplaced = true;
            }
        }

        String normalizedText = normalizedChars.toString();
        if (patternReplaced) {
            logger.warn("DATA REPLACED (PATTERN): Original - {} | Normalised - {}", original, normalizedText);
        }

        return new Object[]{normalizedText, isAltered || !normalizedText.equals(original)};
    }

    /**
     * Truncate text to maximum length -1 plus "+" to indicate truncation.
     *
     * @return [truncatedText, isTruncated]
     */
    public static Object[] truncateField(String text, int maxLength) {
        if (text == null || text.isEmpty()) {
            return new Object[]{"", false};
        }
        if (text.length() > maxLength) {
            return new Object[]{text.substring(0, maxLength - 1) + "+", true};
        }
        return new Object[]{text, false};
    }

    public static int getFieldLength(String fieldName) {
        if (fieldName == null || fieldName.isEmpty()) return 0;
        return MAX_LENGTHS.getOrDefault(fieldName, 0);
    }

    /**
     * Split an address line if it exceeds the max permitted length.
     *
     * @return [line1, line2OrNull, isTruncated]
     */
    public static Object[] splitAddressLine(String addressLine, int maxLength) {
        if (addressLine.length() <= maxLength) {
            return new Object[]{addressLine, null, false};
        }
        String line1 = addressLine.substring(0, maxLength);
        String line2 = addressLine.substring(maxLength);
        Object[] truncResult = truncateField(line2, MAX_LENGTHS.get("AdrLine"));
        return new Object[]{line1, truncResult[0], truncResult[1]};
    }

    /**
     * Extract address components from a row (map of column->value).
     */
    public static Map<String, String> extractAddressComponents(Map<String, String> row) {
        Map<String, String> components = new LinkedHashMap<>();

        List<String> fieldNames = List.of(
                "department", "sub_department", "house", "house_number", "road",
                "unit", "level", "staircase", "entrance", "po_box", "postcode",
                "suburb", "city_district", "city", "island", "state_district",
                "state", "country_region", "country", "world_region"
        );

        for (String field : fieldNames) {
            String key = "best_address." + field;
            String value = row.get(key);
            if (value != null && !value.isBlank()) {
                components.put(field, value.strip());
            }
        }

        return components;
    }

    /**
     * Build PostalAddress24 structured format.
     *
     * @return StructuredResult with truncated/untruncated fields and flags
     */
    public static StructuredResult buildStructuredAddress(Map<String, String> components) {
        Map<String, String> fieldsTrunc = new LinkedHashMap<>();
        Map<String, String> fieldsNoTrunc = new LinkedHashMap<>();
        boolean totalIsReplaced = false;
        boolean totalIsTruncated = false;
        boolean useHybrid = false;

        // === Town Name ===
        String townName = components.getOrDefault("city", "");
        if (townName.isEmpty()) {
            townName = components.getOrDefault("suburb", "");
        }

        if (!townName.isEmpty()) {
            Object[] normResult = normalizeText(townName);
            String normalized = (String) normResult[0];
            boolean replaced = (boolean) normResult[1];

            Object[] truncResult = truncateField(normalized, MAX_LENGTHS.get("TwnNm"));
            String truncated = (String) truncResult[0];
            boolean wasTruncated = (boolean) truncResult[1];

            fieldsTrunc.put("TwnNm", truncated.toUpperCase());
            fieldsNoTrunc.put("TwnNm", fieldsTrunc.get("TwnNm")); // TwnNm exception
            totalIsReplaced = totalIsReplaced || replaced;
            totalIsTruncated = totalIsTruncated || wasTruncated;
        }

        // === Country Code ===
        String country = components.getOrDefault("country", "");
        fieldsTrunc.put("Ctry", country.toUpperCase());
        fieldsNoTrunc.put("Ctry", fieldsTrunc.get("Ctry"));

        // === Optional fields ===
        for (Map.Entry<String, String> mapping : OPTIONAL_MAPPINGS.entrySet()) {
            String componentKey = mapping.getKey();
            String fieldName = mapping.getValue();

            String value = components.get(componentKey);
            if (value != null && !value.isEmpty()) {
                // Skip suburb if it was used for TwnNm
                if ("TwnLctnNm".equals(fieldName) && value.equals(townName)) {
                    continue;
                }

                Object[] normResult = normalizeText(value);
                String normalized = (String) normResult[0];
                boolean replaced = (boolean) normResult[1];

                fieldsNoTrunc.put(fieldName, normalized.toUpperCase());

                Object[] truncResult = truncateField(normalized, MAX_LENGTHS.get(fieldName));
                String truncated = (String) truncResult[0];
                boolean wasTruncated = (boolean) truncResult[1];

                useHybrid = useHybrid || wasTruncated;
                totalIsReplaced = totalIsReplaced || replaced;

                if (!truncated.isEmpty()) {
                    fieldsTrunc.put(fieldName, truncated.toUpperCase());
                    totalIsTruncated = totalIsTruncated || wasTruncated;
                }
            }
        }

        // === Priority mappings (state_district, state -> CtrySubDvsn) ===
        Map<String, List<String>> priorityMappings = Map.of(
                "CtrySubDvsn", List.of("state_district", "state")
        );

        for (Map.Entry<String, List<String>> entry : priorityMappings.entrySet()) {
            String targetField = entry.getKey();
            for (String sourceField : entry.getValue()) {
                String value = components.get(sourceField);
                if (value != null && !value.isEmpty()) {
                    Object[] normResult = normalizeText(value);
                    String normalized = (String) normResult[0];
                    boolean replaced = (boolean) normResult[1];

                    fieldsNoTrunc.put(targetField, normalized.toUpperCase());

                    Object[] truncResult = truncateField(normalized, MAX_LENGTHS.get(targetField));
                    String truncated = (String) truncResult[0];
                    boolean wasTruncated = (boolean) truncResult[1];

                    useHybrid = useHybrid || wasTruncated;
                    totalIsReplaced = totalIsReplaced || replaced;

                    if (!truncated.isEmpty()) {
                        fieldsTrunc.put(targetField, truncated.toUpperCase());
                        totalIsTruncated = totalIsTruncated || wasTruncated;
                    }
                    break; // Stop after first match
                }
            }
        }

        return new StructuredResult(fieldsTrunc, fieldsNoTrunc, totalIsReplaced, totalIsTruncated, useHybrid);
    }

    /**
     * Build PostalAddress24 hybrid format (with AdrLine fields).
     */
    public static HybridResult buildHybridAddress(Map<String, String> fieldsNoTrunc, boolean structuredReplaced) {
        boolean isReplaced = structuredReplaced;
        boolean isTruncated = false;

        List<String> addrLines = new ArrayList<>();

        // Find elements that exceed max length
        List<String> exceeding = new ArrayList<>();
        for (Map.Entry<String, String> entry : fieldsNoTrunc.entrySet()) {
            int maxLen = getFieldLength(entry.getKey());
            if (maxLen > 0 && entry.getValue().length() > maxLen) {
                exceeding.add(entry.getKey());
            }
        }

        for (String element : exceeding) {
            String value = fieldsNoTrunc.get(element);
            addrLines.add(value);
            logger.info("Structured to hybrid change: {} moved to AdrLine: {}", element, value);
        }

        // Remove exceeding elements
        Map<String, String> hybridFields = new LinkedHashMap<>();
        for (Map.Entry<String, String> entry : fieldsNoTrunc.entrySet()) {
            if (!exceeding.contains(entry.getKey())) {
                hybridFields.put(entry.getKey(), entry.getValue());
            }
        }

        // Aggregate all AdrLines and split into max 2 occurrences
        String addressLine = String.join(" ", addrLines);

        if (!addressLine.isEmpty()) {
            Object[] splitResult = splitAddressLine(addressLine, MAX_LENGTHS.get("AdrLine"));
            hybridFields.put("AdrLine1", ((String) splitResult[0]).toUpperCase());
            if (splitResult[1] != null) {
                hybridFields.put("AdrLine2", ((String) splitResult[1]).toUpperCase());
            }
            isTruncated = isTruncated || (boolean) splitResult[2];
        }

        return new HybridResult(hybridFields, isReplaced, isTruncated);
    }

    /**
     * Create XML string for the address.
     */
    public static String createXmlElement(Map<String, String> addressFields, boolean allowHybrid) {
        try {
            DocumentBuilderFactory factory = DocumentBuilderFactory.newInstance();
            DocumentBuilder builder = factory.newDocumentBuilder();
            Document doc = builder.newDocument();

            Element root = doc.createElement("PstlAdr");
            doc.appendChild(root);

            // Add fields in order
            for (String field : FIELD_ORDER) {
                String value = addressFields.get(field);
                if (value != null && !value.isEmpty()) {
                    Element elem = doc.createElement(field);
                    elem.setTextContent(value);
                    root.appendChild(elem);
                }
            }

            // Add AdrLine fields for hybrid format
            if (allowHybrid) {
                for (int i = 1; i <= 2; i++) {
                    String value = addressFields.get("AdrLine" + i);
                    if (value != null && !value.isEmpty()) {
                        Element elem = doc.createElement("AdrLine");
                        elem.setTextContent(value);
                        root.appendChild(elem);
                    }
                }
            }

            return xmlToString(doc);

        } catch (Exception e) {
            logger.error("Error creating XML element: {}", e.getMessage());
            return "";
        }
    }

    /**
     * Remove duplicate elements from XML while protecting TwnNm and Ctry.
     */
    public static String removeDuplicateElements(String xmlString, Set<String> protectedTags) {
        if (protectedTags == null) {
            protectedTags = Set.of("TwnNm", "Ctry");
        }

        try {
            DocumentBuilderFactory factory = DocumentBuilderFactory.newInstance();
            DocumentBuilder docBuilder = factory.newDocumentBuilder();
            Document doc = docBuilder.parse(new ByteArrayInputStream(xmlString.getBytes(StandardCharsets.UTF_8)));

            Element root = doc.getDocumentElement();
            Set<String> seenValues = new HashSet<>();

            // First pass: Record values from protected tags
            for (String tag : protectedTags) {
                NodeList nodes = root.getElementsByTagName(tag);
                for (int i = 0; i < nodes.getLength(); i++) {
                    String text = nodes.item(i).getTextContent();
                    if (text != null && !text.strip().isEmpty()) {
                        seenValues.add(text.strip());
                    }
                }
            }

            // Second pass: Identify elements to remove
            List<Node> toRemove = new ArrayList<>();
            NodeList children = root.getChildNodes();
            for (int i = 0; i < children.getLength(); i++) {
                Node child = children.item(i);
                if (child.getNodeType() != Node.ELEMENT_NODE) continue;
                if (protectedTags.contains(child.getNodeName())) continue;

                String text = child.getTextContent();
                if (text != null && !text.strip().isEmpty()) {
                    String value = text.strip();
                    if (seenValues.contains(value)) {
                        toRemove.add(child);
                    } else {
                        seenValues.add(value);
                    }
                }
            }

            for (Node node : toRemove) {
                root.removeChild(node);
            }

            return xmlToString(doc);

        } catch (Exception e) {
            logger.error("Error removing duplicates: {}", e.getMessage());
            return xmlString;
        }
    }

    /**
     * Validate XML string against XSD schema content.
     *
     * @return ValidationResult with validity flag and error messages
     */
    public static ValidationResult validateXmlAgainstXsd(String xmlString, String xsdContent) {
        try {
            SchemaFactory schemaFactory = SchemaFactory.newInstance("http://www.w3.org/2001/XMLSchema");
            Schema schema = schemaFactory.newSchema(new StreamSource(new StringReader(xsdContent)));
            Validator validator = schema.newValidator();

            List<String> errors = new ArrayList<>();
            validator.setErrorHandler(new org.xml.sax.ErrorHandler() {
                @Override
                public void warning(SAXException e) {
                    errors.add(e.getMessage());
                }

                @Override
                public void error(SAXException e) {
                    errors.add(e.getMessage());
                }

                @Override
                public void fatalError(SAXException e) {
                    errors.add(e.getMessage());
                }
            });

            validator.validate(new StreamSource(new StringReader(xmlString)));
            return new ValidationResult(errors.isEmpty(), errors);

        } catch (SAXException e) {
            String msg = "Validation error: " + e.getMessage();
            logger.error(msg);
            return new ValidationResult(false, List.of(msg));
        } catch (Exception e) {
            String msg = "Validation error: " + e.getMessage();
            logger.error(msg);
            return new ValidationResult(false, List.of(msg));
        }
    }

    private static String xmlToString(Document doc) {
        try {
            TransformerFactory tf = TransformerFactory.newInstance();
            Transformer transformer = tf.newTransformer();
            transformer.setOutputProperty(OutputKeys.OMIT_XML_DECLARATION, "yes");
            transformer.setOutputProperty(OutputKeys.INDENT, "yes");
            transformer.setOutputProperty("{http://xml.apache.org/xslt}indent-amount", "2");

            StringWriter writer = new StringWriter();
            transformer.transform(new DOMSource(doc), new StreamResult(writer));
            return writer.toString();
        } catch (Exception e) {
            logger.error("Error converting XML to string: {}", e.getMessage());
            return "";
        }
    }

    /**
     * Convert all addresses to PostalAddress24 formats.
     * Processes each row in the data list and adds conversion results.
     *
     * @param rows             list of address data maps (each map = one row)
     * @param structuredXsd    content of structured XSD schema
     * @param hybridXsd        content of hybrid XSD schema
     * @param allowHybrid      whether to allow fallback to hybrid format
     * @return the same list with conversion result columns added
     */
    public static List<Map<String, String>> convertAddresses(
            List<Map<String, String>> rows,
            String structuredXsd,
            String hybridXsd,
            boolean allowHybrid) {

        for (Map<String, String> row : rows) {
            try {
                Map<String, String> components = extractAddressComponents(row);

                StructuredResult structured = buildStructuredAddress(components);

                if (!(structured.useHybrid && allowHybrid)) {
                    // Try structured format
                    boolean hasRequired = structured.fieldsTrunc.containsKey("TwnNm")
                            && structured.fieldsTrunc.containsKey("Ctry");
                    String twnNm = structured.fieldsTrunc.getOrDefault("TwnNm", "");
                    String ctry = structured.fieldsTrunc.getOrDefault("Ctry", "");

                    if (hasRequired && !twnNm.isEmpty() && !ctry.isEmpty()) {
                        String xml = createXmlElement(structured.fieldsTrunc, allowHybrid);
                        String deduped = removeDuplicateElements(xml, null);

                        ValidationResult validation = validateXmlAgainstXsd(deduped, structuredXsd);

                        row.put("xml_address_structured", deduped);
                        row.put("is_valid_structured", String.valueOf(validation.isValid));
                        row.put("validation_errors_structured",
                                validation.isValid ? "" : String.join("; ", validation.errors));

                        if (validation.isValid) {
                            row.put("xml_address_final", deduped);
                            row.put("address_format_used", "structured");
                            row.put("is_valid_final", "true");
                            row.put("validation_errors_final", "");
                            row.put("is_replaced", String.valueOf(structured.isReplaced));
                            row.put("is_truncated", String.valueOf(structured.isTruncated));
                            continue;
                        }
                    }
                } else {
                    // Fallback to hybrid
                    HybridResult hybrid = buildHybridAddress(
                            structured.fieldsNoTrunc, structured.isReplaced);

                    boolean hasRequired = hybrid.fields.containsKey("TwnNm")
                            && hybrid.fields.containsKey("Ctry");
                    String twnNm = hybrid.fields.getOrDefault("TwnNm", "");
                    String ctry = hybrid.fields.getOrDefault("Ctry", "");

                    if (hasRequired && !twnNm.isEmpty() && !ctry.isEmpty()) {
                        String xml = createXmlElement(hybrid.fields, true);
                        String deduped = removeDuplicateElements(xml, null);

                        ValidationResult validation = validateXmlAgainstXsd(deduped, hybridXsd);

                        row.put("xml_address_hybrid", deduped);
                        row.put("is_valid_hybrid", String.valueOf(validation.isValid));
                        row.put("validation_errors_hybrid",
                                validation.isValid ? "" : String.join("; ", validation.errors));

                        if (validation.isValid) {
                            row.put("xml_address_final", deduped);
                            row.put("address_format_used", "hybrid");
                            row.put("is_valid_final", "true");
                            row.put("validation_errors_final", "");
                        } else {
                            row.put("xml_address_final", deduped);
                            row.put("address_format_used", "hybrid");
                            row.put("is_valid_final", "false");
                            row.put("validation_errors_final", String.join("; ", validation.errors));
                        }
                        row.put("is_replaced", String.valueOf(hybrid.isReplaced));
                        row.put("is_truncated", String.valueOf(hybrid.isTruncated));
                    } else {
                        row.put("xml_address_final", "");
                        row.put("address_format_used", "none");
                        row.put("is_valid_final", "false");
                        row.put("validation_errors_final", "Insufficient address data");
                        row.put("is_replaced", "false");
                        row.put("is_truncated", "false");
                    }
                }

            } catch (Exception e) {
                row.put("xml_address_final", "");
                row.put("address_format_used", "error");
                row.put("is_valid_final", "false");
                row.put("validation_errors_final", "Conversion error: " + e.getMessage());
                row.put("is_replaced", "false");
                row.put("is_truncated", "false");
                logger.error("Conversion error: {}", e.getMessage());
            }
        }

        return rows;
    }

    /**
     * Main function to convert addresses to PostalAddress24 formats.
     *
     * @param rows               address data rows
     * @param structuredXsdPath  path to structured XSD file
     * @param hybridXsdPath      path to hybrid XSD file
     * @param allowHybrid        whether to allow hybrid format
     * @return processed rows with XML conversion results
     */
    public static List<Map<String, String>> convertAddressesToXml(
            List<Map<String, String>> rows,
            String structuredXsdPath,
            String hybridXsdPath,
            boolean allowHybrid) throws IOException {

        String structuredXsd = new String(
                new FileInputStream(structuredXsdPath).readAllBytes(), StandardCharsets.UTF_8);
        String hybridXsd = new String(
                new FileInputStream(hybridXsdPath).readAllBytes(), StandardCharsets.UTF_8);

        return convertAddresses(rows, structuredXsd, hybridXsd, allowHybrid);
    }

    // ======================== Result records ========================

    public record StructuredResult(
            Map<String, String> fieldsTrunc,
            Map<String, String> fieldsNoTrunc,
            boolean isReplaced,
            boolean isTruncated,
            boolean useHybrid
    ) {
    }

    public record HybridResult(
            Map<String, String> fields,
            boolean isReplaced,
            boolean isTruncated
    ) {
    }

    public record ValidationResult(
            boolean isValid,
            List<String> errors
    ) {
    }
}
