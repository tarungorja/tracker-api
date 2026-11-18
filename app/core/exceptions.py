class AppError(Exception):
    """Base class for errors that map to a client-facing HTTP response."""

    status_code = 400

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class BadRequestError(AppError):
    status_code = 400


class UnauthorizedError(AppError):
    status_code = 401


class NotFoundError(AppError):
    status_code = 404


class ConflictError(AppError):
    status_code = 409


class TooManyRequestsError(AppError):
    status_code = 429


class BadGatewayError(AppError):
    status_code = 502


class ServiceUnavailableError(AppError):
    status_code = 503
