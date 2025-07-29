# `docent_core` changelog

Not to be confused with the `docent` package, which contains our Python SDK and logging library.

## v0.1.0-alpha

Features:
- Chart visualization: Added bar, line, and table charts for flexible quantitative visualizations
- Rubrics: Replaced "search queries" with "rubrics", which have additional structure to improve accuracy
  - Rewrote rubric evaluation and clustering logic to improve performance and reliability

System improvements:
- Supported DB migrations with Alembic
- Refactored worker system to improve modularity and reliability
- Adopted RTK Query for frontend data fetching and caching
- Started modularizing application logic using service layers

Breaking changes:
- Search queries will no longer be rendered in the UI

## v0.0.1-alpha

Initial alpha release
