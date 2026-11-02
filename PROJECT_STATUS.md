# Project status

The working copy has owner-scoped account and ESPN connection paths. It supports sport-specific ESPN basketball and football HUDs, plus a read-only Sleeper NFL adapter that uses the NFL HUD.

## Implemented in the working copy

- OIDC sign-in derives a stable account key from the identity provider and subject. A separate local-only development flag supports one local profile.
- Any authenticated identity accepted by the configured OIDC provider can sign in; the app has no separate email allowlist.
- Users can validate ESPN basketball cookies in a password form. The app encrypts them before storing them with that user's provider connection.
- Users can validate ESPN football cookies and save an owner-scoped NFL league. Selecting that league switches the HUD to football-specific navigation and NFL analysis.
- NFL pages cover weekly lineups, matchup and opponent breakdowns, injuries, ESPN free agents, roster value, move scenarios, transaction activity, weekly recaps, power rankings, league scouting, draft review, playoff planning, bye-week checks, league scoring, decision history, and forecast accuracy.
- NFL lineup recommendations maximize ESPN weekly projections across the current starter-slot mix and ESPN player eligibility. They remain advisory and require a final review in ESPN.
- Sleeper NFL users can find their public leagues by username and connect one to the same NFL HUD without entering cookies or an API key. The adapter uses Sleeper roster, matchup, injury, standings, draft, transactions, and trending-add data.
- Sleeper does not publish player projections through this adapter. NFL lineup, waiver, roster-value, and move-planning screens can use a recency-weighted baseline from up to four weeks of actual league scoring; the app labels it as a baseline, not an official projection. Per-player schedules are not included.
- Leagues, private history, forecasts, decisions, and analyst evidence are stored under both the signed-in owner and league.
- The AI Analyst is temporarily disabled in the app. No background evidence collection or OpenAI requests are started; existing analyst records are retained and not displayed.
- Private calculation caches include the owner, league, connection, and browser session. Public schedule and news caches remain shared.
- ESPN cookies are no longer read from global environment variables. The incorrect fantasy-app role activity panel was removed; consulting role activity belongs on the AI Consulting Team Page.
- Streamlit OIDC dependencies and an Alembic environment with an initial owner-scoped account schema migration are included. The migration is not applied to any database.

## Remaining before hosted multi-user use

- Yahoo is not connected yet. The Yahoo Fantasy API supports football and basketball, but a connector still needs an OAuth app, client credentials, registered callback, and implementation of the read-only league/player data path.
- Sleeper's public league discovery API currently documents NFL leagues only; do not advertise it as an NBA provider. Its API is described as free for non-commercial use; confirm licensing before commercial or broader hosted use.
- NFL news currently shows ESPN injury designations only; an independent NFL news feed and richer injury context remain future work.
- Some NBA capabilities are intentionally sport-specific: NBA schedule streaming and daily lineup optimization are not copied to NFL. NFL uses weekly starters, bye weeks, playoff-week schedules, and NFL scoring settings instead.

- Streamlit Community Cloud is the current hosting path under evaluation. It can run `app.py` from GitHub, but it does not provide this app's persistent shared PostgreSQL database; a separate database provider is required. The full source must be committed to the chosen GitHub repository and branch. The published sample-only demo is separate and should not be replaced before review.
- The AI Analyst background worker is disabled in this build. League data refreshes while the app is open; there is no scheduled background evidence collection.
- The Community Cloud secrets configuration, external database, OIDC provider callback, and account access policy are not configured. The initial migration matches the current SQLAlchemy owner-scoped table definitions; it has not been applied or validated against a live database.
- Owner isolation, live OIDC sign-in, encrypted credential storage, consent revocation, and disconnect behavior have not been tested end to end. Do not deploy this package for multiple users yet.
- The uploaded source files, `.env`, local databases, and generated schedule cache remain excluded from this clean copy. No real credentials are included.

## Next step

Continue product work by adding Yahoo's approved OAuth read-only connector once the application credentials and callback are available, then extend NFL analysis for non-ESPN data. After provider coverage is complete, provision and validate the staging database and OIDC configuration, then complete two-account isolation and credential-lifecycle checks before any multi-user launch. Keep the app single-instance and restrict allowed accounts until those checks pass. No GitHub source update, cloud resource, database migration, or deployment has been performed.
