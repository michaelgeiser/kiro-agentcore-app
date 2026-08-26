# Fix: CloudFront Reverse Proxy for Cognito (SChannel TLS Fix)

## Problem

Windows clients using SChannel encounter TLS handshake failures when connecting directly to the Cognito Hosted UI endpoint (`prescoach-dev-local01.auth.<region>.amazoncognito.com`). This is an uncontrollable endpoint — AWS manages its TLS configuration. The fix is to route Cognito traffic through our existing CloudFront distribution (`E38F17UQPVUDDG` / `kiro.geiserai.com`), which uses configurable TLS settings that work with SChannel.

## Current Architecture

- CloudFront distribution `E38F17UQPVUDDG` serves the SPA from S3
- Distribution is **not managed by CDK** — it exists externally (console/CLI created)
- Cognito domain: `https://prescoach-dev-local01.auth.<region>.amazoncognito.com`
- SPA auth code in `webapp/js/auth.js` calls Cognito directly at endpoints:
  - `{cognitoDomain}/oauth2/authorize` (login redirect)
  - `{cognitoDomain}/oauth2/token` (token exchange)
  - `{cognitoDomain}/logout` (logout redirect)
- `webapp/js/config.js` holds the `cognitoDomain` value, generated at deploy time by `upload-service/scripts/generate-frontend-config.sh`

## Solution Overview

Add a `/cognito/*` behavior on the existing CloudFront distribution that proxies requests to the Cognito Hosted UI origin. Update the SPA to use `https://kiro.geiserai.com/cognito` instead of the direct Cognito domain.

---

## Step 1: Add a Cognito Origin to CloudFront

**Who:** You (manual, via AWS Console — no IaC exists for this distribution yet)

**Where:** AWS Console → CloudFront → Distribution `E38F17UQPVUDDG` → Origins tab → Create origin

**Settings:**

| Field | Value |
|-------|-------|
| Origin domain | `prescoach-dev-local01.auth.<region>.amazoncognito.com` |
| Origin name | `cognito-hosted-ui` |
| Protocol | HTTPS only |
| HTTPS port | 443 |
| Minimum origin SSL protocol | TLSv1.2 |
| Origin path | *(leave empty)* |

**Do NOT add any custom headers.** The Cognito Hosted UI needs to see the original request headers (especially `Host` from the origin, not the viewer).

---

## Step 2: Create a CloudFront Cache Behavior for `/cognito/*`

**Who:** You (manual, via AWS Console)

**Where:** AWS Console → CloudFront → Distribution `E38F17UQPVUDDG` → Behaviors tab → Create behavior

**Settings:**

| Field | Value |
|-------|-------|
| Path pattern | `/cognito/*` |
| Origin | `cognito-hosted-ui` (created in Step 1) |
| Viewer protocol policy | HTTPS only |
| Allowed HTTP methods | GET, HEAD, OPTIONS, PUT, POST, PATCH, DELETE |
| Cache policy | `CachingDisabled` (managed policy) |
| Origin request policy | `AllViewerExceptHostHeader` (managed policy ID: `b689b0a8-53d0-40ab-baf2-68738e2966ac`) |

**Why `AllViewerExceptHostHeader`:** CloudFront must send `Host: prescoach-dev-local01.auth.<region>.amazoncognito.com` to the origin (not `Host: kiro.geiserai.com`). The `AllViewerExceptHostHeader` policy forwards all viewer headers except `Host`, which lets CloudFront substitute the origin's hostname. This is critical — Cognito rejects requests with an incorrect `Host` header.

**Why `CachingDisabled`:** Every Cognito request is session-specific. Caching would break auth flows.

---

## Step 3: Create a CloudFront Function to Strip the `/cognito` Prefix

**Who:** You (manual, via AWS Console)

**Where:** AWS Console → CloudFront → Functions → Create function

**Function name:** `cognito-path-rewrite`

**Function code:**

```javascript
function handler(event) {
    var request = event.request;
    // Strip /cognito prefix so Cognito receives /oauth2/token, /oauth2/authorize, /logout etc.
    request.uri = request.uri.replace(/^\/cognito/, '') || '/';
    return request;
}
```

**After creating, publish the function, then associate it:**

1. Go back to Distribution `E38F17UQPVUDDG` → Behaviors → Edit the `/cognito/*` behavior
2. Under "Function associations" → Viewer request → Select `cognito-path-rewrite`
3. Save changes

**Why this is needed:** The SPA will send requests to `/cognito/oauth2/token`, but Cognito expects `/oauth2/token`. This function strips the prefix before the request reaches the origin.

---

## Step 4: Update `webapp/js/config.js` — Change `cognitoDomain`

**Who:** Kiro (code change)

**What changes:** The `cognitoDomain` value changes from the direct Cognito URL to the CloudFront proxy path.

**File:** `webapp/js/config.js`

**Before:**
```javascript
cognitoDomain: 'https://your-prefix.auth.us-east-1.amazoncognito.com',
```

**After:**
```javascript
cognitoDomain: 'https://kiro.geiserai.com/cognito',
```

This single change makes all auth calls in `auth.js` route through CloudFront automatically because `auth.js` builds URLs like `${AUTH_CONFIG.cognitoDomain}/oauth2/authorize`.

---

## Step 5: Update `upload-service/scripts/generate-frontend-config.sh`

**Who:** Kiro (code change)

**What changes:** The script currently pulls `CognitoDomain` directly from the CDK stack output (the raw Cognito URL). It needs to output the CloudFront proxy URL instead.

**File:** `upload-service/scripts/generate-frontend-config.sh`

**Change:** Replace the `cognitoDomain` value in the generated config with the CloudFront-proxied path. The CloudFront domain is already known (`kiro.geiserai.com`) or can be derived from the S3 bucket name / distribution. The simplest approach:

**Before (line in the heredoc):**
```bash
  cognitoDomain: '${COGNITO_DOMAIN}',
```

**After:**
```bash
  cognitoDomain: 'https://kiro.geiserai.com/cognito',
```

Alternatively, if you want this to be dynamic (for multiple environments), add a `CLOUDFRONT_DOMAIN` variable:

```bash
CLOUDFRONT_DOMAIN="${CLOUDFRONT_DOMAIN:-kiro.geiserai.com}"
```

And use:
```bash
  cognitoDomain: 'https://${CLOUDFRONT_DOMAIN}/cognito',
```

---

## Step 6: Update Cognito App Client Callback/Logout URLs (if needed)

**Who:** You (verify) — likely no change needed

The OAuth `redirect_uri` in auth.js is `window.location.origin` → `https://kiro.geiserai.com`. This is already in the Cognito App Client's allowed callback URLs (see `cognito_construct.py` line with `callback_urls`). No change needed here because:

- The browser still lands on `https://kiro.geiserai.com` after login
- The `redirect_uri` param sent to Cognito is still `https://kiro.geiserai.com`
- Only the *path to reach Cognito* changed, not the callback destination

**Verify:** In the AWS Console → Cognito → User Pool → App Client → check that `https://kiro.geiserai.com` is still listed in both Callback URLs and Sign-out URLs. It should already be there.

---

## Step 7: Invalidate CloudFront Cache and Test

**Who:** You (manual)

After Steps 1-3 are done in the console and Steps 4-5 are deployed:

```bash
aws cloudfront create-invalidation --distribution-id E38F17UQPVUDDG --paths "/*"
```

**Test procedure:**

1. Open `https://kiro.geiserai.com` in a browser on the affected Windows machine
2. Click Login — you should be redirected to `https://kiro.geiserai.com/cognito/oauth2/authorize?...`
3. Cognito Hosted UI should load (the browser shows your CloudFront domain in the address bar during the OAuth flow... **wait** — see Important Note below)

---

## Important Note: Hosted UI Redirects

The Cognito `/oauth2/authorize` endpoint returns a **302 redirect** to the Hosted UI login page. That redirect's `Location` header will point to `https://prescoach-dev-local01.auth.<region>.amazoncognito.com/login?...` — this takes the browser directly to Cognito again, bypassing the proxy.

**This means:** The proxy approach works perfectly for the **token endpoint** (`/oauth2/token`) and **logout** — which are backend API calls made via `fetch()` from your SPA. But the initial login redirect (which is a browser navigation) will still hit Cognito directly for the Hosted UI page.

**If the SChannel issue is on the `/oauth2/token` call (most likely):** You're done. The `fetch()` calls to `/oauth2/token` and `/oauth2/revoke` go through CloudFront. The browser navigation to the Hosted UI login page uses the browser's TLS stack which may handle it differently.

**If the SChannel issue is also on the Hosted UI page itself:** You'd need to switch to a **custom login UI** that collects credentials and calls the Cognito API (InitiateAuth/RespondToAuthChallenge) through the CloudFront proxy instead of using the Hosted UI. This is a larger change.

---

## Summary of Changes

| Step | Who | What |
|------|-----|------|
| 1 | You (Console) | Add Cognito origin to CloudFront |
| 2 | You (Console) | Add `/cognito/*` cache behavior |
| 3 | You (Console) | Create and attach CloudFront Function for path rewrite |
| 4 | Kiro | Update `webapp/js/config.js` |
| 5 | Kiro | Update `generate-frontend-config.sh` |
| 6 | You (Verify) | Confirm Cognito callback URLs are correct |
| 7 | You (CLI) | Invalidate CloudFront + test |

---

## Rollback

If something breaks:
1. Change `cognitoDomain` in `webapp/js/config.js` back to the direct Cognito URL
2. Deploy/sync to S3
3. Invalidate CloudFront
4. The `/cognito/*` behavior in CloudFront can stay — it won't receive traffic if the SPA doesn't send requests there
