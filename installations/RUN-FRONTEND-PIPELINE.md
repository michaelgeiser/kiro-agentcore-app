# Run Frontend Pipeline

Deploys **only the webapp** (static files) to S3 and invalidates CloudFront.

Use this when you've made changes to `webapp/` files (HTML, CSS, JS) and don't need to redeploy the backend.

---

## What It Does

1. Pulls latest code from `main` branch on GitHub
2. Runs `generate-frontend-config.sh` to populate `config.js` from CDK stack outputs
3. Syncs `webapp/` to the S3 CloudFront origin bucket (excluding test files, node_modules)
4. Creates a CloudFront invalidation on `/*` so users get the new version immediately

---

## Option A: Run from AWS Console

1. Open the CodePipeline console:
   ```
   https://us-east-1.console.aws.amazon.com/codesuite/codepipeline/pipelines?region=us-east-1
   ```

2. Click on **`prescoach-dev-kiro-frontend`**

3. Click the **"Release change"** button (top right, orange)

4. Confirm when prompted

5. Watch the stages turn green:
   - **Source** — Pulls from GitHub (30-60 seconds)
   - **Deploy** — Syncs to S3 and invalidates CloudFront (1-2 minutes)

6. Done. Visit `https://kiro.geiserai.com` to verify.

---

## Option B: Run from CLI (CloudShell or terminal)

```bash
aws codepipeline start-pipeline-execution \
  --name prescoach-dev-kiro-frontend \
  --region us-east-1
```

### Check status

```bash
# Get current pipeline state
aws codepipeline get-pipeline-state \
  --name prescoach-dev-kiro-frontend \
  --region us-east-1 \
  --query 'stageStates[*].{Stage:stageName,Status:latestExecution.status}' \
  --output table
```

### Watch logs in real time

```bash
# Find the latest build ID
BUILD_ID=$(aws codebuild list-builds-for-project \
  --project-name prescoach-dev-kiro-frontend-build \
  --query 'ids[0]' --output text)

# Tail the logs
aws codebuild batch-get-builds --ids $BUILD_ID \
  --query 'builds[0].logs.deepLink' --output text
```

Open the URL it prints to see full CloudWatch logs.

---

## Expected Duration

| Stage | Time |
|-------|------|
| Source (GitHub pull) | ~30 seconds |
| Deploy (S3 sync + CF invalidation) | ~1-2 minutes |
| **Total** | **~2 minutes** |

---

## Troubleshooting

### "No changes detected" in Source stage
The pipeline requires a newer commit than the last run. Push a commit (even empty) to trigger:
```bash
git commit --allow-empty -m "trigger frontend deploy"
git push origin main
```

### S3 sync fails with "Access Denied"
The CodeBuild role needs `s3:PutObject` and `s3:DeleteObject` on the target bucket. This was granted during CI/CD stack deployment. If missing, redeploy the CI/CD stack.

### CloudFront invalidation fails
Check that `CLOUDFRONT_DIST_ID` environment variable is set correctly in the CodeBuild project. Verify in CodeBuild → Environment variables.

### Config generation fails ("Stack not found")
The backend must be deployed first so the CloudFormation stack outputs exist. Run the backend pipeline first, or use the full-deploy pipeline.
