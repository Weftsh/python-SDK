# Changelog

## 0.1.0

First release.

- `Weft` and `AsyncWeft`: create, find, list, iterate, batch-create and
  batch-delete repositories; mirrors; tokens.
- `Repo` / `AsyncRepo`: commits through a builder
  (`create_commit().put().delete().send()`) with optimistic concurrency and
  an audit `context`; file, tree, history and diff reads with ETag caching;
  branches and tags; `reset` and `revert`; repository-scoped git remote URLs;
  webhooks; bundle export.
- `verify_webhook` for `X-Weft-Signature-256` deliveries.
- `WeftError` and `WeftConflictError` (with `current_tip`).
