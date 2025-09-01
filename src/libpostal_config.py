#!/usr/bin/env python3
"""
Centralized libpostal configuration module.
Import this module before importing any postal modules to ensure proper configuration.
"""
import os


def configure_libpostal():
    """Configure libpostal environment if not already set"""
    if 'LIBPOSTAL_DATA_DIR' not in os.environ:
        os.environ['LIBPOSTAL_DATA_DIR'] = '/usr/local/share/libpostal'


# Configure automatically when this module is imported
configure_libpostal()
