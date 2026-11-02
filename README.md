# Fantasy Advisor — staging

A separate staging copy of the read-only fantasy advisor. It keeps the existing fictional NBA/NFL demo untouched.

## What is in this staging build

- ESPN fantasy basketball connection and analysis for NBA leagues.
- ESPN fantasy football connection with a dedicated football HUD. The active league controls the navigation: NBA leagues show the basketball sections; NFL leagues show football equivalents and football-only tools.
- Sleeper NFL username lookup and read-only league connection, using the same NFL HUD.
- NFL views for matchup and opponent breakdowns, lineup planning, player forecasts, injuries, waivers, roster value, move scenarios, league rankings, draft review, playoff planning, and bye-week checks. ESPN leagues use ESPN projections; Sleeper leagues use a clearly labeled recent-score baseline when history is available.
- Shared account-scoped decision history and projection accuracy views for both sports.
- OIDC sign-in, owner-scoped PostgreSQL storage, encrypted ESPN credentials, and disconnect controls.
- The AI Analyst is temporarily disabled; the app makes no OpenAI requests.
- Streamlit Community Cloud deployment notes in `STREAMLIT_CLOUD_STAGING.md`.

## Current limits

- NFL projections and availability come from ESPN. The NFL News and Injuries page uses ESPN injury designations; a separate NFL news feed and automated live lineup changes are not included.
- NFL multi-week move scenarios hold this week's projection difference constant. NFL lineup suggestions are projection-based; verify late injury news, flex rules, and final lineup locks in ESPN.
- Sleeper does not publish player projections through this adapter. Sleeper NFL planning uses a recency-weighted baseline from up to four weeks of actual league scoring; it is not an official projection or future-performance guarantee. Sleeper player-by-player schedules are not included.
- Sleeper's public league-list API currently documents NFL only. Yahoo supports NBA and NFL, but the Yahoo Fantasy Sports API application must be approved and OAuth credentials configured before a Yahoo connector can be completed.
- Account isolation, OIDC, database migration, and security behavior still need staging verification. Do not use production ESPN credentials or real users yet.
- This staging build does not start a background evidence worker. League data refreshes while the app is open; there is no scheduled background collection.

## Deploy

Follow `STREAMLIT_CLOUD_STAGING.md`. Deploy from a separate `cloud-staging` branch and use a separate Community Cloud app URL. Do not overwrite the existing demo or commit real secrets.
