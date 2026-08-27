---
inclusion: always
---

# Dependency Management

## Core Rule

Always use the **current/latest stable version** of any dependency when adding or updating packages. Never pin to an older version without explicitly asking the user for permission and receiving approval.

## When Adding Dependencies

- Look up the latest stable release on PyPI, npm, or the relevant registry
- Pin to that exact version (e.g., `weasyprint==69.0`, not `weasyprint>=62.3`)
- If a dependency has known compatibility constraints with other packages, resolve them using the latest compatible versions of both — do not downgrade

## When Fixing Dependency Issues

- If a version incompatibility is discovered, upgrade to the latest version that resolves the issue
- Do NOT pin to an older version as a fix unless:
  1. You explicitly inform the user that a downgrade is the proposed solution
  2. The user approves the downgrade
- Prefer upgrading the primary package over pinning transitive dependencies to old versions

## Rationale

Staying current avoids accumulating tech debt, ensures security patches are applied, and prevents cascading compatibility issues when other packages eventually require newer versions.
