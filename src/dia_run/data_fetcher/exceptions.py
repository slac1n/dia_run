class CareLinkDataStaleError(Exception):
    """Raised when the latest CareLink CGM reading is too far behind current server time."""
