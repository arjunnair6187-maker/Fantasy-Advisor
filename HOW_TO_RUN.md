# How to Run Fantasy Basketball Advisor

> **Development status:** The app now requires an authenticated account, stores ESPN connections encrypted, and scopes private records and caches by owner and league. Local development can use one explicitly enabled local profile. This is still a pre-release build: Community Cloud is under evaluation, the production schema must be provisioned, and account isolation has not been tested. Do not deploy it to multiple users yet.

This site is read-only. It never changes lineups, submits waiver claims, or proposes trades on ESPN.

## One-time local setup

1. Copy `.env.example` to `.env` in the project folder.
2. Keep `APP_ENV="development"` and `ALLOW_SINGLE_USER_DEV="1"` for localhost use only. These settings create a single local profile; never use them on a hosted app.
3. Keep the example `DATABASE_URL` for local SQLite storage.
4. Install the packages with the command under **Install or repair packages**.
5. Generate a credential encryption key in the local terminal:

   ```bat
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

6. Paste that value into `CREDENTIAL_ENCRYPTION_KEY` in `.env`. Keep it private; losing it makes saved ESPN cookies unreadable.
7. Start the site. Use **Connect an ESPN basketball league** in the sidebar to add a league.

For hosted use, set up OIDC in the identity provider and Streamlit secrets, use a shared SQL database, set `APP_ENV="production"`, and turn off the local profile. The app accepts any authenticated identity from the configured OIDC provider and has no separate email allowlist; configure the provider to accept the accounts you intend to support. Before starting the app, configure `DATABASE_URL` and run `alembic upgrade head` from this project folder to create the account schema. This migration has not been applied to a hosted database; deployment and multi-account isolation still require approval and review.

## Streamlit Community Cloud setup draft (not deployed)

The full advisor can use `app.py` as its Community Cloud entrypoint. Community Cloud deploys from a GitHub repository, so the complete working source and `requirements.txt` must be in the selected repository and branch. The currently published sample-only demo is separate; do not replace it with this full app until its database, sign-in, and account-isolation checks are complete. Community Cloud runs from the repository root even when the entrypoint is in a subfolder.

The app needs an external persistent PostgreSQL database; Community Cloud does not provide the shared application database this project needs. Create that database with a provider you choose, then configure the connection string in the app's Community Cloud **Secrets** settings. Also set root-level secrets for `APP_ENV = "production"`, `ALLOW_SINGLE_USER_DEV = "0"`, `DATABASE_URL`, and a stable, private `CREDENTIAL_ENCRYPTION_KEY`. Put the OIDC values in an `[auth]` section: `redirect_uri`, `cookie_secret`, `client_id`, `client_secret`, and `server_metadata_url`. Community Cloud root-level secrets are exposed to the app as environment variables, while `[auth]` is read through `st.secrets`. The AI Analyst is temporarily disabled and needs no API key.

Choose the final Community Cloud app subdomain before configuring OIDC, then register `https://<chosen-subdomain>.streamlit.app/oauth2callback` as the provider callback URL. Restrict allowed identities in the OIDC provider: this app has no separate email allowlist. A Community Cloud developer needs admin permission to the GitHub repository. Never commit a real `.streamlit/secrets.toml` or credentials.

Before any multi-user launch, provision the external database, run `alembic upgrade head` once against that database, and complete the two-account isolation, sign-in, credential encryption, consent-revocation, and disconnect checks. The AI Analyst worker is disabled in this build; league data refreshes while the app is open, with no scheduled background evidence collection.

The existing `render.yaml` and `render_start.py` are for the separate Render hosting draft. Community Cloud does not use them. No cloud database has been provisioned and no migration or deployment has been run.

## Start the site each morning

1. Open Visual Studio Code.
2. Click **File → Open Folder**.
3. Open **Desktop → fantasy-basketball-advisor**.
4. Click **Terminal → New Terminal**.
5. If the terminal is PowerShell, click the down arrow beside the terminal's **+** button and select **Command Prompt**.
6. Type:

   ```bat
   .venv\Scripts\activate.bat
   ```

7. Confirm the terminal begins with `(.venv)`.
8. Type:

   ```bat
   python -m streamlit run app.py
   ```

9. If the browser does not open, visit http://localhost:8501.

## Stop the site

1. Click inside the VS Code terminal running the site.
2. Press **Ctrl + C** once.
3. Wait for the normal command prompt to return.
4. If it stays on `Stopping...` for more than 20 seconds, press **Ctrl + C** again or click the terminal trash-can icon.

## Update expired ESPN cookies

Never paste cookies into chat, screenshots, source code, or `.env`.

1. Sign in to ESPN in your normal browser.
2. Open your fantasy basketball league page.
3. Press **F12**.
4. Open **Application**. Click `>>` if the tab is hidden.
5. Under **Storage**, expand **Cookies**.
6. Select `https://fantasy.espn.com`.
7. Find `espn_s2` and `SWID`.
8. Copy each cookie's **Value** without sharing it.
9. In the app sidebar, open **Update ESPN cookies**.
10. Paste both updated values into the password fields and choose **Validate and replace cookies**. The app checks the connection before replacing the encrypted saved values.

## Install or repair packages

With `(.venv)` visible in Command Prompt, type:

```bat
python -m pip install -r requirements.txt
```

## AI Analyst status

The AI Analyst is temporarily removed from the app. No analyst worker or OpenAI API calls run; existing saved analyst records are retained.

## Daily routine

1. Open **Home** for the morning summary.
2. Open **Strategy Board** for the four-week forecast and current priorities.
3. Open **Weekly Lineup**, click each day, and review every injury warning.
4. Make lineup changes yourself on ESPN.
5. Open **Waivers** for recommendations, then **My Moves** to verify pending claims. Place, reorder, or cancel claims yourself in ESPN.
6. Check **News** again shortly before games begin.

The open website automatically refreshes live ESPN league data and news approximately every 2.5 minutes. Interacting with a control can briefly delay the next refresh so your click is not interrupted.
Current matchup scores use ESPN's detailed live box-score feed because its simpler scoreboard feed can lag or temporarily return zeros.
The **Players → My Moves** page reads pending and recent waiver activity from ESPN. It cannot submit, reorder, or cancel a claim.
Canceled claims are reconciled against ESPN's linked cancellation records so an older stale “pending” row does not continue affecting strategy.
The **Waivers** page rereads ESPN on every refresh. Use **Refresh waiver wire now** when you want an immediate update instead of waiting for the automatic 2.5-minute refresh.
Players already named as the drop side of an active claim are excluded from further drop and trade recommendations until that claim is canceled, fails, or processes.
On the Waivers page, active claims appear in their own **Active claims already counted** table. The main waiver table contains only players still eligible as a next move.
Live partial games are excluded from player-value averages. Early-season completed results are blended gradually with ESPN and last-season projections so one small sample cannot create an obviously incorrect drop recommendation.
The Strategy Board treats the highest-priority non-conflicting pending claims as provisional roster moves, recalculates the remaining positional weaknesses, and recommends the next best improvement instead of repeating a player you already claimed.
The Strategy Board also separates short-term needs from rest-of-season needs. Injured long-term targets are labeled as watch/stash candidates, and return timing is shown only when fetched news supports it.
Strategy is divided into 1-week, 2-week, 4-week, and season views. Each view automatically recalculates from recent player performance, pending claims, injuries, upcoming opponents, completed matchup results, and changing power rankings.
The **Strategy → Move Simulator** page compares an add/drop against the current roster across 1-week, 2-week, 4-week, and season horizons. It uses legal daily lineup slots and warns about schedule congestion, missing position coverage, and the four-center limit. It is read-only.
Use **Save this scenario** to put a simulated move into **Strategy → Decision Tracker**. There you can mark it Pending, Followed, or Skipped and add private notes. The history is stored under the signed-in account and selected league in `DATABASE_URL`.
The **Strategy → Streaming Planner** tests combinations across upcoming weeks, counts only games that fit legal daily lineup slots, protects active-claim drops, and proposes a possible week-one move followed by a week-two pivot. Its completed calculation is reused for 2.5 minutes so returning to the page is fast; it then recalculates with fresh ESPN data. Recalculate before acting because availability and injuries change.

The site uses a Sleeper-inspired five-part product shell: **Roster**, **Matchup**, **Players**, **League**, and **GM Hub**. Start each morning on **Roster → Championship Dashboard**, use Matchup for the current opponent and lineups, Players for waivers and news, League for league-wide intelligence, and GM Hub for simulations and long-term planning. Team and data-source controls are inside the collapsed **League Settings** sidebar.

The **Live win probability** card appears on the Championship Dashboard and Matchup Center. It combines ESPN's current matchup score with projected points from legal lineup games that remain. Scheduled games count fully, games marked live count as an estimated half-game remaining, and finished games are not counted again. The confidence label rises as fewer projected points remain. It is an estimate, not a guarantee.

Use **Market → Roster Value** to see value over replacement player (VORP). Each roster player's custom rating is compared with the strongest healthy ESPN free agent who can cover one of the same positions. Active waiver targets are excluded from replacement level. Positive VORP indicates value above waivers; a negative number marks a player who may be replaceable, not an automatic instruction to drop them.

Use **Front Office → Playoff Planner** to compare the NBA schedule across your two-week semifinal and two-week championship matchup. The app derives the start from ESPN's regular-season matchup count when available and visibly warns when it must use the final four schedule weeks as a fallback. Long-range projected points assume current roles and health, so treat them as acquisition planning rather than a guaranteed lineup total.

Use **Front Office → Transaction Portfolio** to organize active claims, one primary next claim, a same-drop fallback if that player is unavailable, and an independent pivot targeting a different roster spot. Active ESPN claims are treated as work already in progress. The page is read-only; submit and prioritize every claim yourself in ESPN.

Use **Matchup → Injury Contingencies** to see an if/then plan for every current roster injury designation. Roster replacements must be healthy bench players who share an eligible position and play today. Waiver fallbacks must also be healthy, position-compatible, available after active claims, and playing today. Verify official status near tipoff and make every lineup or transaction change yourself in ESPN.

Use **Matchup → Opponent Gameplan** to see the opponent's largest projected threats, your most dangerous and most favorable days, daily legal-starter projections, opponent injury flags, and waiver moves ranked by their estimated lift to the current live win probability. The lift assumes the claim succeeds and the opponent makes no counter-move, so treat it as decision support rather than certainty.

At the start of a new fantasy week, the site reconciles ESPN's reported matchup period with the dated NBA schedule. If ESPN still reports the completed period, the site advances the local read-only view during the one-week regular season, archives the previous final score in the signed-in account's database, loads the new opponent and schedule, and saves the new week's first projection. The Championship Dashboard shows a rollover banner with the completed result and prior forecast error. This local reconciliation never changes anything on ESPN and does not override ESPN's two-week playoff periods.

Use **Front Office → Accuracy Lab** to compare the earliest saved forecast for each matchup with the archived final result. It reports score error, margin error, winner accuracy, probability error, and whether the model has been systematically high or low. The evidence label stays cautious during the first few completed weeks and becomes more useful as the sample grows.

Power Rankings, Strategy Board, League Scout, and Draft Review share one league-intelligence calculation for the active fantasy week. It refreshes every 2.5 minutes while the site is open and is keyed to the reconciled matchup period, so a new week immediately creates a new calculation. Completed scoreboard results rebuild records, points per week, opponent-adjusted ratings, and weekly power movement even when ESPN's summary record fields are briefly delayed. Opening any of these intelligence pages saves or updates that week's power snapshot for later movement charts.

Use **League → Weekly Recap** to review any completed fantasy week. It ranks all teams by official ESPN matchup score, shows results and margins, compares each team with the league average and its own prior-week baseline, and provides a plain-English interpretation. The player table separately totals custom-scoring production from dated NBA box scores; it includes production even when a player was on a fantasy bench, while the team table remains the official matchup result.

## New analysis pages

- **Strategy Board** shows your strengths, weaknesses, action plan, four-week matchup forecast, and measured projection accuracy.
- Its **Weak-spot repair plan** quantifies each positional gap and lists waiver add/drop options with estimated FP/G and current-week gains. It also lists realistic trade targets, possible outgoing players, and estimated net lineup improvement.
- **Power Rankings** combine roster quality with opponent-adjusted wins, losses, and scoring margins. Real results gain more weight each week.
- **Draft Recap** regrades every draft pick from 1–10 as the season changes.
- **Boom or Bust** shows projection ranges and volatility. Low-confidence estimates are labeled rather than presented as certain.
- The interface uses a navy, teal, and slate sports-dashboard design inspired by the supplied references while remaining a distinct local website.
- Pages are opened from the Sleeper-style tabs across the top. Choose a main section first, then use the smaller second row when that section contains multiple pages. The sidebar is reserved for team and data-source settings.

## Data and accuracy notes

- The preseason baseline blends 70% of ESPN's 2026–27 projected FP/G with 30% of actual 2025–26 FP/G when both are available.
- If last season's private ESPN league cannot be opened, the site clearly labels the projection as ESPN-only.
- Once games are played, recent 7-, 14-, and 30-day results use completed box scores and the scoring function in `scoring.py`.
- Weekly matchup totals count only player-games that fit into legal daily lineup slots.
- The weekly lineup is a plan, not an automatic ESPN lineup. Reload it on game day because injuries, news, and new results can change the recommendation.
- Each daily lineup tab shows only recommended starters. Players without a game and players assigned to the bench are intentionally hidden.
- Waivers and News flag possible opportunity when a same-team player at an overlapping position has an ESPN injury designation.
- Players listed OUT, on IR, or suspended are never shown as recommended adds. Day-to-day or uncertain statuses remain visible with a warning to verify availability.
- Waiver targets are also checked against recent matched NBA news. A player with recent injury-related news is excluded from add/drop recommendations until you verify that report.
- Flagrant fouls, ejections, and disqualifications count only when supplied by the data source.
- Missing, stale, or uncertain data is labeled instead of guessed.
- The core scoring, legal-lineup, waiver, and projection engines are deterministic. The AI Analyst is temporarily disabled.
- Private snapshots and decisions are stored under the signed-in account and selected league in `DATABASE_URL`.
- A hosted deployment needs a shared persistent SQL database and pre-provisioned account schema. Do not use the local SQLite example for multiple users.
- If ESPN fails, choose **Manual fallback** and upload or paste the CSV template.

## Replace code from an updated ZIP

1. Stop the site.
2. Keep your existing `.env`, `.venv`, and `fantasy_advisor_accounts.db` files. The older `fantasy_advisor.db` file is not used by this version.
3. Extract the replacement ZIP.
4. Copy its files into `Desktop\fantasy-basketball-advisor`.
5. Choose **Replace files in the destination** when asked.
6. Run the package repair command above, then restart the site.
