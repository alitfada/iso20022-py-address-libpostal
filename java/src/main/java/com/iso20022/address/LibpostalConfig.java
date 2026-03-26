package com.iso20022.address;

/**
 * Centralized libpostal configuration.
 * Call {@link #configure()} before using any libpostal functions.
 */
public final class LibpostalConfig {

    private static boolean configured = false;

    private LibpostalConfig() {
    }

    /**
     * Configure libpostal environment if not already set.
     * Sets the LIBPOSTAL_DATA_DIR system property if not present.
     */
    public static synchronized void configure() {
        if (!configured) {
            String dataDir = System.getenv("LIBPOSTAL_DATA_DIR");
            if (dataDir == null || dataDir.isEmpty()) {
                // Set system property as fallback; the JNI binding reads from env
                System.setProperty("LIBPOSTAL_DATA_DIR", Config.LIBPOSTAL_DATA_DIR);
            }
            configured = true;
        }
    }
}
