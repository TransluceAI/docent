---
title: Environment variables
---

## LLM calls

* `OPENAI_API_KEY`: OpenAI API key
* `ANTHROPIC_API_KEY`: Anthropic API key
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

## CORS

* `DOCENT_CORS_ORIGINS`: Comma-separated list of allowed frontend origins for CORS
    * Leave empty/unset for development (defaults to `localhost:*`)
    * Example for multiple domains: `DOCENT_CORS_ORIGINS=https://app.yourdomain.com,https://admin.yourdomain.com`
