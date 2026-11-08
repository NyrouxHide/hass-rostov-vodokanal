"""Stable errors; never include cookies, tokens, or portal HTML."""


class VodokanalError(Exception):
    """Base portal error."""


class CannotConnect(VodokanalError):
    """Network or server failure."""


class InvalidAccount(VodokanalError):
    """Account does not exist or is not accessible anonymously."""


class PortalChanged(VodokanalError):
    """Expected forms or fields are missing; fail instead of guessing."""


class ReadingRejected(VodokanalError):
    """Reading is invalid, already sent today, or rejected by the portal."""


class StaleReading(VodokanalError):
    """Cancellation target no longer matches the portal's current reading."""


class MutationUncertain(VodokanalError):
    """A write may have succeeded. Do not automatically retry it."""
