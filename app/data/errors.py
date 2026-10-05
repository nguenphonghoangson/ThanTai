class DataFetchError(RuntimeError):
    """The data source could not be reached or returned an unusable response."""


class MalformedDataError(DataFetchError):
    """The response was received but contains no usable draw records."""
