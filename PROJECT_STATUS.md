# Project status

The working copy now has the first owner-scoped application path for the hosted fantasy advisor. It still supports only ESPN fantasy basketball; ESPN football, Yahoo, and Sleeper remain future work.

## Implemented in the working copy

- OIDC sign-in derives a stable account key from the identity provider and subject. A separate local-only development flag supports one local profile.
- Any authenticated identity accepted by the configured OIDC provider can sign in; the app has no separate email allowlist.
- Users can validate ESPN basketball cookies in a password form. The app encrypts them before storing them with that user's provider connection.
- Leagues, private history, forecasts, decisions, and analyst evidence are stored under both the signed-in owner and league.
- OpenAI analysis now requires a saved, per-league opt-in. The background briefing and question paths check consent before making external requests; local evidence collection and deterministic summaries still work without it.
- Private calculation caches include the owner, league, connection, and browser session. Public schedule and news caches remain shared.
- The background evidence worker is keyed by owner and league, reads only that user's saved connection, and stops on sign-out or disconnect.
- ESPN cookies are no longer read from global environment variables. The incorrect fantasy-app role activity panel was removed; consulting role activity belongs on the AI Consulting Team Page.
- Streamlit OIDC dependencies and an Alembic environment with an initial owner-scoped account schema migration are included. The migration is not applied to any database.

## Remaining before hosted multi-user use

- Streamlit Community Cloud is the current hosting path under evaluation. It can run `app.py` from GitHub, but it does not provide this app's persistent shared PostgreSQL database; a separate database provider is required. The full source must be committed to the chosen GitHub repository and branch. The published sample-only demo is separate and should not be replaced before review.
- Community Cloud sleeps after 12 hours without traffic. The background worker currently runs inside the app process, so it pauses when the app sleeps. Do not rely on it for time-critical continuous refreshes; replace it with durable background jobs before that requirement or a multi-instance deployment.
- The Community Cloud secrets configuration, external database, OIDC provider callback, and account access policy are not configured. The initial migration matches the current SQLAlchemy owner-scoped table definitions; it has not been applied or validated against a live database.
- Owner isolation, live OIDC sign-in, encrypted credential storage, consent revocation, and disconnect behavior have not been tested end to end. Do not deploy this package for multiple users yet.
- The uploaded source files, `.env`, local databases, and generated schedule cache remain excluded from this clean copy. No real credentials are included.

## Next step

Choose an external persistent PostgreSQL provider and confirm the GitHub repository and branch that should hold the full source. Then configure the Community Cloud secrets and OIDC callback, provision the database, and review the migration before running it. Complete two-account isolation, sign-in, connection refresh, consent-revocation, and disconnect checks before multi-user launch. Keep the app single-instance and restrict allowed accounts in the OIDC provider until those checks pass. No GitHub source update, cloud resource, database migration, or deployment has been performed.
