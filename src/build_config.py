"""Build-time configuration injected by the release workflow.

The public Sentry DSN is intentionally empty in source builds. Release builds
can replace it from a GitHub Actions secret without putting account-specific
configuration in the repository.
"""

SENTRY_DSN = ""
