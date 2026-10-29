# Fantasy Advisor staging on Streamlit Community Cloud

This guide deploys a separate staging app. Keep the existing fictional-data demo on the `main` branch and its current Streamlit URL unchanged.

## Prepare the staging branch

1. Create a `cloud-staging` branch from the repository's current `main` branch.
2. Add the complete contents of this project folder to the repository root on `cloud-staging`. Keep `app.py`, all Python modules, `requirements.txt`, `alembic.ini`, and the `migrations` folder together.
3. Do not add `.env`, `.streamlit/secrets.toml`, database files, or real ESPN cookies. The `.env.example` and `.streamlit/secrets.toml.example` files contain placeholders only.
4. Keep `render.yaml` and `render_start.py` out of the staging branch; they belong to the separate Render draft.

## Prepare the database and sign-in

1. Create a separate PostgreSQL database for staging. Do not point staging at a production database. The database must be reachable from Community Cloud and support TLS.
2. Configure an OIDC client in the identity provider. Community Cloud developers need admin access to the GitHub repository.
3. Choose an unused Streamlit app subdomain first. Set the OIDC callback to `https://<staging-subdomain>.streamlit.app/oauth2callback` in the identity provider.
4. Restrict the identity provider to the intended staging users. The app accepts any identity that the configured provider allows.
5. Generate a Fernet encryption key and a separate random OIDC cookie secret. Keep both outside GitHub. Back up the Fernet key securely; saved ESPN credentials cannot be decrypted if it is lost.

## Add Community Cloud secrets

In the staging app's Community Cloud **Advanced settings → Secrets**, add TOML like the following and replace every placeholder privately:

```toml
APP_ENV = "production"
ALLOW_SINGLE_USER_DEV = "0"
DATABASE_URL = "postgresql+psycopg://USER:PASSWORD@HOST:PORT/DATABASE?sslmode=require"
CREDENTIAL_ENCRYPTION_KEY = "<generated-fernet-key>"

[auth]
redirect_uri = "https://<staging-subdomain>.streamlit.app/oauth2callback"
cookie_secret = "<separate-random-cookie-secret>"
client_id = "<oidc-client-id>"
client_secret = "<oidc-client-secret>"
server_metadata_url = "<oidc-provider-metadata-url>"
```

Community Cloud exposes root-level secrets as environment variables; the app reads the `[auth]` section through `st.secrets`. Never paste secrets into this guide, chat, source code, or GitHub. The AI Analyst is temporarily disabled in this staging build.

## Deploy a separate app

1. In Streamlit Community Cloud, create a new app using the GitHub repository, the `cloud-staging` branch, and `app.py` as the entrypoint.
2. Choose a staging-only subdomain, enter the secrets above, and deploy.
3. Apply the initial database migration once against the staging database with `alembic upgrade head`. Do not use a production database.
4. Verify sign-in and run the two-account isolation checklist in `PROJECT_STATUS.md` using dedicated test identities and test leagues.
5. Leave the live demo and `main` branch unchanged while staging checks are incomplete.

## Staging limits

This staging build does not run an AI Analyst background worker. League data refreshes while the app is open; there is no scheduled background evidence collection. Free database plans can also pause or omit backups; confirm the provider's current limits and recovery options before storing real league data.

This guide does not indicate that a database, GitHub branch, or Community Cloud app has been created. The account-isolation and security checks remain incomplete.
