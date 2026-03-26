package com.iso20022.address;

/**
 * Application configuration constants.
 * Edit these values to match your environment.
 */
public final class Config {

    private Config() {
    }

    /** Path to the structured address XSD schema file */
    public static final String XSD_FILE_PATH_STRUCTURED = "PostalAddress24Structured.xsd";

    /** Path to the hybrid address XSD schema file */
    public static final String XSD_FILE_PATH_HYBRID = "PostalAddress24Hybrid.xsd";

    /** Minimum character length for reliable libpostal parsing */
    public static final int MIN_VIABLE_ADDRESS_LENGTH = 25;

    /** Default libpostal data directory */
    public static final String LIBPOSTAL_DATA_DIR = "/usr/local/share/libpostal";
}
