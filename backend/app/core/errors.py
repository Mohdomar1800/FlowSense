"""Domain errors raised by the service layer.

Services never import FastAPI. They raise these, and app.main maps them to HTTP responses,
so business logic stays usable outside a web request (scheduler jobs, scripts, tests).
"""


class AppError(Exception):
    status_code = 400
    error_type = "bad_request"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class BadRequestError(AppError):
    status_code = 400
    error_type = "bad_request"


class UnauthorizedError(AppError):
    status_code = 401
    error_type = "unauthorized"


class NotFoundError(AppError):
    status_code = 404
    error_type = "not_found"


class ConflictError(AppError):
    status_code = 409
    error_type = "conflict"


class TooManyRequestsError(AppError):
    status_code = 429
    error_type = "too_many_requests"

    def __init__(self, message: str, retry_after: int) -> None:
        super().__init__(message)
        self.retry_after = retry_after
