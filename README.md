# Fantasy Advisor — staging

A separate staging copy of the read-only ESPN fantasy advisor. It keeps the existing fictional NBA/NFL demo untouched.

## What is in this staging build

- ESPN fantasy basketball connection and analysis for NBA leagues.
- OIDC sign-in, owner-scoped PostgreSQL storage, encrypted ESPN credentials, and disconnect controls.
- The AI Analyst is temporarily disabled; the app makes no OpenAI requests.
- Streamlit Community Cloud deployment notes in `STREAMLIT_CLOUD_STAGING.md`.

## Current limits

- This full advisor currently supports ESPN basketball only. The NFL view shown in the public demo uses fictional sample data; live ESPN NFL support is not implemented in this build.
- Yahoo and Sleeper are future integrations.
- Account isolation, OIDC, database migration, and security behavior still need staging verification. Do not use production ESPN credentials or real users yet.
- This staging build does not start a background evidence worker. League data refreshes while the app is open; there is no scheduled background collection.

## Deploy

Follow `STREAMLIT_CLOUD_STAGING.md`. Deploy from a separate `cloud-staging` branch and use a separate Community Cloud app URL. Do not overwrite the existing demo or commit real secrets.
