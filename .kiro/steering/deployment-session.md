---
inclusion: auto
---

# Deployment Session Reminder

## Context

When the upload-and-storage spec tasks are complete (all backend Lambda handlers, CDK infrastructure, Cognito setup, and frontend integration tasks finished), prompt the user to begin a collaborative IaC and deployment session.

## What to build in that session

- **Multi-environment CDK deployment** — The CDK stack must support deploying to dev, test, prod (or any custom environment names) within the same or different AWS accounts
- **Environment-aware configuration** — Environment-specific values (domain names, Cognito callback URLs, CORS origins, stack names) parameterized via CDK context, environment variables, or a config file per environment
- **Multi-account support** — Users should be able to deploy to separate AWS accounts for isolation (e.g., dev account, prod account) using CDK's `env` property with account/region
- **Public example code** — This project will be published as example/reference code. Other developers need to install it in their own environments. The deployment setup must be self-contained with clear instructions: clone → configure → deploy
- **Frontend + Backend as a logical unit** — The frontend SPA (S3/CloudFront) and the upload-and-storage backend (Lambda/API Gateway/DynamoDB/Cognito) are interdependent and should deploy together or have clear cross-stack references
- **Items to address:**
  - CDK context or config file for environment-specific values (account ID, region, domain, callback URLs)
  - Resource naming convention: `{appName}-{envName}-{instanceId}-{resourceName}` — already defined in the upload-and-storage spec (Requirement 11)
  - Multiple instances in a single account using instanceId (e.g., per-customer/tenant deployments)
  - Stack naming convention per environment (e.g., `prescoach-prod-acme123`)
  - CloudFront distribution + S3 bucket for frontend hosting (if not already covered)
  - Route 53 / custom domain setup (optional, configurable)
  - WAF association (optional, configurable)
  - CI/CD pipeline definition or at minimum deployment scripts
  - README with setup instructions for new users

## Trigger

When the user completes upload-and-storage tasks OR says they're ready for deployment, remind them:

> "The upload-and-storage implementation is complete. You mentioned wanting to collaboratively build the IaC and deployment code next — multi-environment, multi-account, designed for others to clone and deploy. Ready to start that session?"
