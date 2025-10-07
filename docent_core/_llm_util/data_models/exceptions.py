class LLMException(Exception):
    error_type_id = "other"
    user_message = "The model failed to respond. Please try again later."


class CompletionTooLongException(LLMException):
    error_type_id = "completion_too_long"
    user_message = "Completion too long."


class RateLimitException(LLMException):
    error_type_id = "rate_limit"
    user_message = "Rate limited by the model provider. Please wait and try again."


class ContextWindowException(LLMException):
    error_type_id = "context_window"
    user_message = "Context window exceeded."


class NoResponseException(LLMException):
    error_type_id = "no_response"
    user_message = "The model returned an empty response. Please try again later."


class DocentUsageLimitException(LLMException):
    error_type_id = "docent_usage_limit"
    user_message = "Free daily usage limit reached. Add your own API key in settings or contact us for increased limits."


class ValidationFailedException(LLMException):
    error_type_id = "validation_failed"
    user_message = "The model returned invalid output that failed validation."

    def __init__(self, message: str = "", failed_output: str | None = None):
        super().__init__(message)
        self.failed_output = failed_output


LLM_ERROR_TYPES: list[type[LLMException]] = [
    LLMException,
    CompletionTooLongException,
    RateLimitException,
    ContextWindowException,
    NoResponseException,
    DocentUsageLimitException,
    ValidationFailedException,
]
