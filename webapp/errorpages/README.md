# Error Pages - CloudFront Custom Error Responses

Generic error handling for geisersoft.com using CloudFront's built-in custom error response feature.
Zero cost, no additional Lambda invocations.

## Files

| File | Purpose |
|------|---------|
| `error.html` | Generic error page handling all HTTP error codes. Reads the status from a query param, looks up a friendly message, and shows a hidden debug panel. |
| `404.html` | Legacy standalone 404 page (kept as fallback). |

## How It Works

1. A request hits CloudFront → S3 returns an error (e.g., 404)
2. CloudFront's custom error response config intercepts the error
3. CloudFront serves `/errorpages/error.html?status=404` (preserving or overriding the HTTP status)
4. The page reads `?status=XXX` from the query string
5. JavaScript looks up the error title, description, and typical S3 error code from a local array
6. A "Show debug info" link reveals debug details (status, S3 code/message, key, URL, timestamp, user agent)

## CloudFront Configuration

In your CloudFront distribution, configure **Custom Error Responses** for each error code:

| HTTP Error Code | Response Page Path | HTTP Response Code | Error Caching TTL |
|---|---|---|---|
| 400 | `/errorpages/error.html?status=400` | 400 | 10 |
| 403 | `/errorpages/error.html?status=403` | 403 | 10 |
| 404 | `/errorpages/error.html?status=404` | 404 | 10 |
| 405 | `/errorpages/error.html?status=405` | 405 | 10 |
| 414 | `/errorpages/error.html?status=414` | 414 | 10 |
| 416 | `/errorpages/error.html?status=416` | 416 | 10 |
| 500 | `/errorpages/error.html?status=500` | 500 | 5 |
| 501 | `/errorpages/error.html?status=501` | 501 | 5 |
| 502 | `/errorpages/error.html?status=502` | 502 | 5 |
| 503 | `/errorpages/error.html?status=503` | 503 | 5 |
| 504 | `/errorpages/error.html?status=504` | 504 | 5 |

### Via AWS Console

1. Go to CloudFront → Distributions → `E38F17UQPVUDDG` → **Error pages** tab
2. Click **Create custom error response** for each error code above
3. Set:
   - **HTTP error code**: (the code from the table)
   - **Customize error response**: Yes
   - **Response page path**: `/errorpages/error.html?status=XXX`
   - **HTTP response code**: (same as the error code — preserves original status)
   - **Error caching minimum TTL**: 10 (or 5 for 5xx errors)

### Via AWS CLI

```bash
aws cloudfront get-distribution-config --id E38F17UQPVUDDG > dist-config.json
# Edit dist-config.json to add CustomErrorResponses (see below), then:
aws cloudfront update-distribution --id E38F17UQPVUDDG --distribution-config file://dist-config.json --if-match <ETag>
```

Example CustomErrorResponses snippet for the distribution config:

```json
"CustomErrorResponses": {
  "Quantity": 11,
  "Items": [
    { "ErrorCode": 400, "ResponsePagePath": "/errorpages/error.html?status=400", "ResponseCode": "400", "ErrorCachingMinTTL": 10 },
    { "ErrorCode": 403, "ResponsePagePath": "/errorpages/error.html?status=403", "ResponseCode": "403", "ErrorCachingMinTTL": 10 },
    { "ErrorCode": 404, "ResponsePagePath": "/errorpages/error.html?status=404", "ResponseCode": "404", "ErrorCachingMinTTL": 10 },
    { "ErrorCode": 405, "ResponsePagePath": "/errorpages/error.html?status=405", "ResponseCode": "405", "ErrorCachingMinTTL": 10 },
    { "ErrorCode": 414, "ResponsePagePath": "/errorpages/error.html?status=414", "ResponseCode": "414", "ErrorCachingMinTTL": 10 },
    { "ErrorCode": 416, "ResponsePagePath": "/errorpages/error.html?status=416", "ResponseCode": "416", "ErrorCachingMinTTL": 10 },
    { "ErrorCode": 500, "ResponsePagePath": "/errorpages/error.html?status=500", "ResponseCode": "500", "ErrorCachingMinTTL": 5 },
    { "ErrorCode": 501, "ResponsePagePath": "/errorpages/error.html?status=501", "ResponseCode": "501", "ErrorCachingMinTTL": 5 },
    { "ErrorCode": 502, "ResponsePagePath": "/errorpages/error.html?status=502", "ResponseCode": "502", "ErrorCachingMinTTL": 5 },
    { "ErrorCode": 503, "ResponsePagePath": "/errorpages/error.html?status=503", "ResponseCode": "503", "ErrorCachingMinTTL": 5 },
    { "ErrorCode": 504, "ResponsePagePath": "/errorpages/error.html?status=504", "ResponseCode": "504", "ErrorCachingMinTTL": 5 }
  ]
}
```

## Limitations

- No access to S3 RequestId or HostId (those are in the XML response body that CloudFront discards)
- S3 error Code/Message in the debug panel are based on typical mappings, not the actual response
- If you need full AWS error details for support tickets, see `/errorpagesalt/` for the Lambda@Edge alternative

## Excluding from deployment

Add `errorpages/README.md` to the buildspec exclude list if you don't want it deployed to S3.
