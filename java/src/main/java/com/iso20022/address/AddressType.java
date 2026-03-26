package com.iso20022.address;

/**
 * Enumeration representing the type of address data.
 * Can be extended with additional address types.
 */
public enum AddressType {

    UNSTRUCTURED("unstructured");

    private final String value;

    AddressType(String value) {
        this.value = value;
    }

    public String getValue() {
        return value;
    }
}
