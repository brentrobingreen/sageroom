---
name: local-dev
description: "How to start the local dev server, credentials locations, and service details"
metadata: 
  node_type: memory
  type: reference
  originSessionId: 6ce57e75-8de0-4a30-a5d5-29ee8ec7095b
---

## Starting the server

```bash
cd /Users/brentgreen/sageroom
PATH="$PATH:/Users/brentgreen/Library/Python/3.9/bin" && set -a && source .env && set +a && uvicorn web.main:app --reload --port 8000
```

Also start Stripe webhook listener in a separate process:
```bash
stripe listen --forward-to http://localhost:8000/webhooks/stripe
```

App runs at: http://localhost:8000

## Credentials

All in `/Users/brentgreen/sageroom/.env` (gitignored — do not commit).

- **Anthropic key**: also in `/Users/brentgreen/brain_builder/.env`
- **Supabase project**: `pdaudcjbckgmlsmzqrll` (Sydney region), org `pkyqilnygyaysqwuxdxa`
- **Supabase access token**: stored locally only — get from supabase.com/dashboard/account/tokens (token name: sageroom-local, no expiry)
- **Stripe account**: `acct_1I3BfEKWgsaTpD3g` (gyroflip.com.au), test mode
- **Stripe product**: `prod_UcIF7k3wi3B2EW` (Sageroom), price `price_1Td3fqKWgsaTpD3gtWPX4Qdn` ($20 AUD/month)
- **Stripe CLI**: logged in, stored at `~/.config/stripe/config.toml`

## Test user

- Email: `brentrobin.green@gmail.com`
- Supabase user ID: `13129c94-6417-4535-8021-0c696f9011f4`
- Subscription record ID: `833fa62e-d11f-4ca9-8cc2-aaecbd22b778`
- Subscription manually set to `active` for testing (expires 2026-12-31)

## Stripe test card

`4242 4242 4242 4242` — any future expiry, any CVC, any postcode

## Services

- **Supabase dashboard**: https://supabase.com/dashboard/project/pdaudcjbckgmlsmzqrll
- **Stripe dashboard**: https://dashboard.stripe.com (test mode)
- **GitHub**: https://github.com/brentrobingreen/sageroom
- **Railway**: https://railway.app (prod deploy — not yet configured for this session)

## Brain files

Located at `/Users/brentgreen/sageroom/brains/` — tony_robbins, warren_buffett, robin_sharma all have brain.md + system_prompt.md. Steve Jobs directory exists but has no brain.md (deferred to v1.1).
