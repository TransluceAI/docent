---
title: Environment variables
---

## LLM calls

* `OPENAI_API_KEY`: OpenAI API key
* `ANTHROPIC_API_KEY`: Anthropic API key
* `GOOGLE_API_KEY`: Google API key
* `LLM_CACHE_PATH`: Path to the LLM cache

<Note>
You don't have to specify API keys for all providers; only ones that are used. See here for details on [adding new providers](./llm_providers_and_calls.md#provider-registry) and [customizing Docent's LLM API calls](./llm_providers_and_calls.md#selecting-models-for-docent-functions).
</Note>

## Postgres

We have provided reasonable defaults in `.env.template`, but you're welcome to customize these as needed.

* `DOCENT_PG_USER`: Postgres username
* `DOCENT_PG_PASSWORD`: Postgres password
* `DOCENT_PG_HOST`: Postgres host
* `DOCENT_PG_PORT`: Postgres port
* `DOCENT_PG_DATABASE`: Postgres database (not `postgres`)

## Redis

We have provided reasonable defaults in `.env.template`, but you're welcome to customize these as needed.

* `DOCENT_REDIS_HOST`: Redis host
* `DOCENT_REDIS_PORT`: Redis port
* `DOCENT_REDIS_USER`: Redis username (optional)
* `DOCENT_REDIS_PASSWORD`: Redis password (optional)

## CORS

* `DOCENT_CORS_ORIGINS`: CSV list of allowed frontend origins (optional)
    * Leave empty/unset for development (defaults to `localhost:*`)
    * Example for multiple domains: `DOCENT_CORS_ORIGINS=https://app.yourdomain.com,https://admin.yourdomain.com`

## Optional variables for deployed environments

* `DEPLOYMENT_ID`: ID of the deployment (unset for local)
* `SENTRY_DSN`: Sentry DSN
* `POSTHOG_API_KEY`: PostHog API key
* `POSTHOG_API_HOST`: PostHog API host (defaults to `https://us.i.posthog.com`)
