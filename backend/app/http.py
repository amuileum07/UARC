"""HTTPS trust that also works without the build machine's OpenSSL CA paths."""

import ssl

import certifi


def https_context() -> ssl.SSLContext:
    """Retain system/custom roots and add the CA bundle shipped with the app."""
    context = ssl.create_default_context()
    context.load_verify_locations(cafile=certifi.where())
    return context
