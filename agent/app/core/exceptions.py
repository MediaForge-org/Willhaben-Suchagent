class ProviderError(Exception):
    """Base class for expected provider failures."""


class NetworkError(ProviderError):
    pass


class RequestTimeoutError(NetworkError):
    pass


class ParseError(ProviderError):
    pass


class RateLimitedError(ProviderError):
    pass


class AccessDeniedError(ProviderError):
    pass


class ChallengeDetectedError(ProviderError):
    pass


class ProviderInternalError(ProviderError):
    pass
