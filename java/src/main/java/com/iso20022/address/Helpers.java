package com.iso20022.address;

import java.util.regex.Pattern;

/**
 * General helper functions (equivalent to Python helpers.py).
 */
public final class Helpers {

    private static final Pattern CONSECUTIVE_WHITESPACE = Pattern.compile("[^\\S\\n]{2,}");
    private static final Pattern CONSECUTIVE_COMMAS = Pattern.compile(",\\s*,+");
    private static final Pattern PUNCTUATION_CHARS = Pattern.compile("[,.!?]");

    private Helpers() {
    }

    /**
     * Clean whitespace while preserving newlines and remove consecutive commas.
     *
     * @param input the string to clean
     * @return cleaned string with normalized whitespace and single commas only
     */
    public static String cleanWhitespacePreserveNewlines(String input) {
        if (input == null || input.isEmpty()) {
            return input;
        }

        String[] lines = input.split("\\r?\\n", -1);
        StringBuilder result = new StringBuilder();

        for (int i = 0; i < lines.length; i++) {
            String line = lines[i];

            // Replace tabs with spaces
            String noTabs = line.replace('\t', ' ');

            // Normalize whitespace (2 or more consecutive non-newline whitespace -> 2 spaces)
            String cleaned = CONSECUTIVE_WHITESPACE.matcher(noTabs).replaceAll("  ");

            // Remove consecutive commas (2 or more commas -> single comma)
            cleaned = CONSECUTIVE_COMMAS.matcher(cleaned).replaceAll(",");

            result.append(cleaned);
            if (i < lines.length - 1) {
                result.append('\n');
            }
        }

        return result.toString();
    }

    /**
     * Remove all commas, periods, exclamation marks, and question marks from a string.
     *
     * @param input the string to clean
     * @return string with punctuation removed
     */
    public static String removeCharsRegex(String input) {
        if (input == null || input.isEmpty()) {
            return input;
        }
        return PUNCTUATION_CHARS.matcher(input).replaceAll("");
    }
}
