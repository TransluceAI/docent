import sentry_sdk


def init_sentry_or_raise(deployment_id: str | None, dsn: str | None) -> None:
    if not deployment_id:
        return
    if not dsn:
        raise ValueError(
            "SENTRY_DSN is required for any non-local deployment (i.e., deployment_id is not None), "
            f"but it isn't currently set for deployment_id={deployment_id}"
        )

    try:
        from sentry_sdk.integrations.openai import OpenAIIntegration

        disabled = [OpenAIIntegration]
    except Exception:
        disabled = []

    sentry_sdk.init(
        dsn=dsn,
        environment=deployment_id,
        send_default_pii=False,
        default_integrations=True,
        auto_enabling_integrations=True,
        disabled_integrations=disabled,
    )
