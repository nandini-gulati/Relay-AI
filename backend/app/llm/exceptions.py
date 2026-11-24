"""Domain exceptions for LLM Gateway operations."""


class AllProvidersUnavailableException(Exception):
    """Raised when every key in the key pool has failed."""

    def __init__(self, message: str = "all providers unavailable"):
        super().__init__(message)
        self.detail = message
