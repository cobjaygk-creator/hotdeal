# Bright Data list collection

Set these Railway service variables to enable the integration:

```dotenv
BRIGHTDATA_ENABLED=1
BRIGHTDATA_API_KEY=<secret from your local .env.local>
BRIGHTDATA_ZONE=hotdeal
BRIGHTDATA_SOURCES=arca,quasarzone,fmkorea,coolenjoy
BRIGHTDATA_INTERVAL_MINUTES=60
BRIGHTDATA_MONTHLY_LIMIT=4500
PPOMPPU_PROXY_URL=
FMKOREA_PROXY_URL=
```

Never commit the API key. `.env.local` is for local tests and is not loaded by
the production application. Set credentials through Railway Variables.

Keep `DATA_DIR` on the existing persistent volume (or use
`RAILWAY_VOLUME_MOUNT_PATH`). `brightdata-budget.db` stores UTC-calendar-month
attempt counts and per-source cooldowns. The default is at most one request
per source per hour, including failed attempts. Existing scheduler ticks may
make the effective interval longer. Four sources use at most approximately
2,976 list requests in a 31-day month. Hourly collection can miss posts that
leave the first page between runs.

The cap applies to this deployment and counts outgoing API requests, not the
provider's credits or fees. It excludes manual probes and other applications.
Configure provider-side billing limits too; the integration does not promise
that every request type is included in a free allowance. Multiple replicas
must share the counter database. Do not delete it to restart the application.

FMKorea uses country `kr` and JavaScript rendering. Other sources use default
Web Unlocker requests. The integration only accepts the four hardcoded list
URLs. Details are disabled for these sources while enabled, including the
old proxy fallback, to keep costs bounded. Existing original-post links remain
available. No automatic retries occur; failed or empty results remain errors.

To roll back, set `BRIGHTDATA_ENABLED=0`. This restores the old source fetch
paths; keep the old paid-proxy variables empty if that service is unavailable.
