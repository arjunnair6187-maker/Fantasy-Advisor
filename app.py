"""Fantasy Basketball Advisor — local, read-only Streamlit application."""

from datetime import date, datetime
import html
import os
import uuid

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from streamlit_autorefresh import st_autorefresh

import account_store
from account_auth import require_user_id
from advice_engine import (add_drop_suggestions, build_player_rows,
    injury_pool_from_league, is_unavailable_status, player_positions, rank_waivers,
    recommend_lineup, team_strengths, weekly_lineup_plan)
from database import (forecast_history, initialize_database, move_decision_history,
    power_snapshot_history, save_daily_snapshot, save_matchup_forecasts,
    save_move_decision, save_power_snapshot, save_weekly_result,
    set_tenant_required, set_tenant_scope, snapshot_history, update_move_decision,
    weekly_result_history)
from espn_data import (ESPN_NFL_SEASON_YEAR, ESPN_SEASON_YEAR,
    connect_to_league, connect_to_nfl_league)
from manual_fallback import blank_template, read_pasted_csv, read_uploaded_csv
from intelligence_worker import stop_user_workers
from move_simulator import horizon_totals, rank_streaming_moves, simulate_add_drop
from nba_schedule import (get_matchup_week_schedule, get_team_defense_context,
    get_completed_week_schedules, get_upcoming_week_schedules, teams_playing_on)
from news_data import fetch_nba_news, filter_relevant_news
from projections import project_team_for_week
from scoring import RARE_STATS_WARNING, calculate_fantasy_points
from strategy_engine import (boom_bust_board, draft_recap, league_power_rankings,
    injury_contingency_plans, live_matchup_outlook, matchup_counterstrategy,
    matchup_forecasts, projection_accuracy, projection_accuracy_lab,
    playoff_player_values, playoff_schedule_grades, quantified_strategy_moves,
    remaining_plan_projection, roster_value_board, strategy_plan,
    transaction_portfolio, weekly_player_recap, weekly_team_recap)
from waiver_activity import active_waiver_claims, waiver_activity
from week_state import effective_matchup_period

load_dotenv()

st.set_page_config(
    page_title="Fantasy Advisor · Staging", page_icon="🏀", layout="wide",
    initial_sidebar_state="collapsed",
)

set_tenant_required(True)
USER_ID = require_user_id()
stop_user_workers(USER_ID)
APP_ENV = os.getenv("APP_ENV", "production").strip().lower()
try:
    if APP_ENV == "development":
        account_store.create_development_schema()
    else:
        account_store.verify_schema()
except Exception as error:
    st.error("Account storage is not ready. Configure the database before using this app.")
    st.caption(f"Setup issue: {type(error).__name__}")
    st.stop()

# Rerun the app every 150 seconds. The component delays a refresh while the
# user is actively interacting so it does not interrupt a click or selection.
st_autorefresh(interval=150_000, limit=None, key="automatic_data_refresh")

st.markdown("""
<style>
:root { --accent:#18efd1; --accent2:#55c6ff; --panel:#111830; --panel2:#171f3b; --line:#34476f; --muted:#91a6c9; --pink:#ff3f7f; --orange:#ffad45; }
.stApp { background:radial-gradient(circle at 70% -20%,#172448 0%,#070c22 36%,#030718 78%); color:#f8fbff; }
.block-container { max-width:1280px; padding-top:1.4rem; padding-bottom:5rem; }
[data-testid="stSidebar"] { background:linear-gradient(180deg,#090e25,#050919); border-right:1px solid #202e52; }
[data-testid="stSidebar"] * { color:#dce8ff; }
[data-testid="stSidebar"] [role="radiogroup"] label { border-radius:11px; padding:7px 9px; margin:2px 0; }
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) { background:#182442; box-shadow:inset 3px 0 0 var(--accent); }
.app-brand { display:flex; align-items:center; justify-content:space-between; padding:4px 2px 10px; }
.app-brand-name { color:#fff; font-size:1.35rem; font-weight:850; letter-spacing:-.03em; }
.app-brand-status { color:var(--accent); font-size:.78rem; font-weight:800; border:1px solid #285e65; background:#0c2b31; border-radius:999px; padding:5px 10px; }
.command-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:13px; margin:14px 0 24px; }
.command-card { min-height:122px; padding:18px; border:1px solid #2e426d; border-radius:18px; background:linear-gradient(145deg,#141e3b,#0a1128); box-shadow:0 12px 30px rgba(0,0,0,.20); }
.command-label { color:#8298bd; font-size:.7rem; font-weight:850; letter-spacing:.09em; text-transform:uppercase; }
.command-value { color:#fff; font-size:1.65rem; line-height:1.15; font-weight:900; margin:8px 0 5px; }
.command-detail { color:#99acd0; font-size:.78rem; line-height:1.35; }
.command-card.accent { border-color:#238f8b; background:linear-gradient(145deg,#12343c,#0b182d); }
.briefing-grid { display:grid; grid-template-columns:1.25fr .75fr; gap:16px; margin:10px 0 24px; }
.briefing-panel { padding:20px; border:1px solid #2d416b; border-radius:19px; background:#0d152d; }
.briefing-title { color:#fff; font-weight:850; font-size:1rem; margin-bottom:13px; }
.briefing-item { display:grid; grid-template-columns:30px 1fr; gap:9px; align-items:start; padding:10px 0; border-top:1px solid #202f52; color:#a9bad7; }
.briefing-item:first-of-type { border-top:0; }
.briefing-number { display:grid; place-items:center; width:24px; height:24px; border-radius:8px; background:#163a43; color:var(--accent); font-size:.72rem; font-weight:900; }
.action-box { padding:18px; border-radius:15px; background:linear-gradient(140deg,rgba(24,239,209,.14),rgba(85,198,255,.06)); border:1px solid #286b75; }
.action-kicker { color:var(--accent); text-transform:uppercase; letter-spacing:.09em; font-size:.68rem; font-weight:900; }
.action-title { color:#fff; font-size:1.12rem; font-weight:850; margin:7px 0; }
.action-copy { color:#a8bad8; font-size:.83rem; line-height:1.4; }
.win-card { padding:22px; border:1px solid #326071; border-radius:20px; background:radial-gradient(circle at 90% 0,rgba(24,239,209,.16),transparent 35%),linear-gradient(145deg,#111d39,#0b132a); margin:13px 0 22px; }
.win-head { display:flex; justify-content:space-between; align-items:end; gap:16px; }
.win-eyebrow { color:var(--accent); font-size:.7rem; font-weight:900; letter-spacing:.1em; text-transform:uppercase; }
.win-number { color:#fff; font-size:3rem; font-weight:950; line-height:1; margin-top:5px; }
.win-confidence { color:#a9bad8; border:1px solid #334c72; border-radius:999px; padding:6px 10px; font-size:.72rem; font-weight:800; }
.win-track { height:12px; background:#263453; border-radius:999px; overflow:hidden; margin:18px 0 8px; }
.win-fill { height:100%; background:linear-gradient(90deg,#24dcae,#18efd1,#55c6ff); border-radius:999px; }
.win-scale { display:flex; justify-content:space-between; color:#758aaf; font-size:.67rem; font-weight:750; }
.win-projections { display:grid; grid-template-columns:repeat(3,1fr); gap:10px; margin-top:17px; }
.win-stat { padding:12px; border-radius:13px; background:rgba(3,8,24,.42); border:1px solid #263958; }
.win-stat-label { color:#7f94b8; font-size:.65rem; font-weight:800; text-transform:uppercase; letter-spacing:.06em; }
.win-stat-value { color:#fff; font-size:1.08rem; font-weight:850; margin-top:4px; }
.win-summary { color:#b1c1dc; margin-top:14px; font-size:.86rem; }
.value-strip { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin:12px 0 22px; }
.value-tile { padding:16px; border:1px solid #2e426b; border-radius:17px; background:#0d162e; }
.value-tile.good { border-color:#25796f; background:linear-gradient(145deg,#12332f,#0c192b); }
.value-tile.warn { border-color:#735b2d; background:linear-gradient(145deg,#332817,#15172a); }
.value-tile-number { color:#fff; font-size:1.8rem; font-weight:950; }
.value-tile-label { color:#8499bc; font-size:.68rem; font-weight:850; letter-spacing:.07em; text-transform:uppercase; margin-top:4px; }
.playoff-window { display:grid; grid-template-columns:1fr 1fr; gap:14px; margin:12px 0 22px; }
.round-card { padding:19px; border:1px solid #334a75; border-radius:18px; background:linear-gradient(145deg,#131e3b,#0b132a); }
.round-card.final { border-color:#8c7134; background:linear-gradient(145deg,#302817,#11162a); }
.round-label { color:#8ca2c7; font-size:.69rem; text-transform:uppercase; letter-spacing:.09em; font-weight:900; }
.round-dates { color:#fff; font-size:1.2rem; font-weight:900; margin:7px 0; }
.round-note { color:#9cafcf; font-size:.78rem; }
.portfolio-flow { display:grid; grid-template-columns:repeat(3,1fr); gap:13px; margin:12px 0 22px; }
.portfolio-card { position:relative; padding:18px; border:1px solid #334970; border-radius:18px; background:linear-gradient(145deg,#131d39,#0b132a); }
.portfolio-card.primary { border-color:#208f83; background:linear-gradient(145deg,#123b3a,#0b192c); }
.portfolio-card.fallback { border-color:#706036; }
.portfolio-role { color:#8fa4c8; font-size:.68rem; font-weight:900; letter-spacing:.09em; text-transform:uppercase; }
.portfolio-move { color:#fff; font-size:1.05rem; font-weight:900; margin:8px 0; line-height:1.35; }
.portfolio-gain { color:var(--accent); font-size:1.25rem; font-weight:900; }
.portfolio-trigger { color:#98accd; font-size:.77rem; line-height:1.4; margin-top:8px; }
.contingency-card { padding:20px; border:1px solid #62445b; border-left:5px solid #ff6d87; border-radius:18px; background:linear-gradient(145deg,#29182a,#0e1429 60%); margin:12px 0; }
.contingency-head { display:flex; justify-content:space-between; gap:14px; align-items:center; }
.contingency-player { color:#fff; font-size:1.15rem; font-weight:900; }
.contingency-status { color:#ff91a4; background:#351928; border:1px solid #754052; border-radius:999px; padding:5px 9px; font-size:.7rem; font-weight:900; }
.contingency-trigger { color:#aebed9; font-size:.82rem; line-height:1.45; margin:11px 0; }
.contingency-options { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
.contingency-option { padding:12px; border:1px solid #2e4065; border-radius:13px; background:rgba(6,11,28,.5); }
.contingency-option-label { color:#7f95ba; font-size:.64rem; font-weight:850; letter-spacing:.07em; text-transform:uppercase; }
.contingency-option-name { color:#fff; font-weight:800; margin-top:4px; }
.gameplan-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:13px; margin:12px 0 22px; }
.gameplan-card { padding:18px; border:1px solid #31466f; border-radius:18px; background:linear-gradient(145deg,#121c38,#0b1329); }
.gameplan-card.danger { border-color:#6e4052; background:linear-gradient(145deg,#2d1827,#101329); }
.gameplan-card.opportunity { border-color:#26766e; background:linear-gradient(145deg,#123530,#0b1729); }
.gameplan-label { color:#8499bd; font-size:.67rem; font-weight:900; letter-spacing:.08em; text-transform:uppercase; }
.gameplan-value { color:#fff; font-size:1.15rem; font-weight:900; margin:7px 0; }
.gameplan-copy { color:#9eafd0; font-size:.77rem; line-height:1.4; }
.week-rollover { display:flex; justify-content:space-between; align-items:center; gap:16px; padding:14px 17px; margin:0 0 16px; border:1px solid #28756f; border-radius:15px; background:linear-gradient(90deg,#10332f,#0c1830); }
.week-rollover-title { color:#fff; font-weight:900; }
.week-rollover-copy { color:#9eb4d3; font-size:.78rem; margin-top:3px; }
.week-result { color:var(--accent); font-size:1.15rem; font-weight:950; white-space:nowrap; }
.accuracy-grid { display:grid; grid-template-columns:repeat(5,1fr); gap:11px; margin:12px 0 20px; }
.accuracy-card { padding:15px; border:1px solid #30456d; border-radius:16px; background:#0e172e; }
.accuracy-number { color:#fff; font-size:1.45rem; font-weight:950; }
.accuracy-label { color:#8398ba; font-size:.65rem; text-transform:uppercase; letter-spacing:.07em; font-weight:850; margin-top:5px; }
.accuracy-diagnosis { padding:16px 18px; border:1px solid #286f69; border-radius:15px; background:linear-gradient(90deg,#10302e,#0c1830); color:#b5c7df; margin:8px 0 22px; }
.recap-hero-grid { display:grid; grid-template-columns:1.2fr .8fr .8fr; gap:12px; margin:12px 0 22px; }
.recap-card { padding:18px; border:1px solid #31466f; border-radius:18px; background:linear-gradient(145deg,#131d39,#0b132a); }
.recap-card.winner { border-color:#8a7138; background:linear-gradient(145deg,#302716,#11162a); }
.recap-label { color:#879bbd; font-size:.67rem; text-transform:uppercase; letter-spacing:.08em; font-weight:900; }
.recap-value { color:#fff; font-size:1.25rem; font-weight:950; margin:7px 0 3px; }
.recap-detail { color:#9eb0cf; font-size:.77rem; }
.ai-status-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:11px; margin:12px 0 20px; }
.ai-status-card { padding:15px; border:1px solid #303235; border-radius:15px; background:#1b1d1f; }
.ai-status-value { color:#fff; font-size:1rem; font-weight:900; margin-top:6px; overflow:hidden; text-overflow:ellipsis; }
.ai-status-label { color:#85888e; font-size:.64rem; letter-spacing:.08em; text-transform:uppercase; font-weight:850; }
.ai-briefing { padding:20px; border:1px solid #315b35; border-top:4px solid var(--accent); border-radius:16px; background:#1b1d1f; margin:10px 0 20px; }
.ai-headline { color:#fff; font-size:1.25rem; font-weight:950; }
.ai-summary { color:#b1b3b7; font-size:.88rem; line-height:1.5; margin-top:8px; }
.st-key-main_navigation div[data-testid="stRadio"] > label,
[class*="st-key-subnav_"] div[data-testid="stRadio"] > label { display:none; }
.st-key-main_navigation [role="radiogroup"] { display:flex; flex-wrap:nowrap; gap:0; border-bottom:1px solid #28395e; margin-bottom:8px; overflow-x:auto; scrollbar-width:none; }
.st-key-main_navigation [role="radiogroup"]::-webkit-scrollbar { display:none; }
.st-key-main_navigation [role="radiogroup"] label { flex:1 0 auto; justify-content:center; min-width:110px; padding:12px 16px 11px; margin:0; border-radius:0; border-bottom:4px solid transparent; color:#8499be; font-weight:800; letter-spacing:.045em; text-transform:uppercase; background:transparent; }
.st-key-main_navigation [role="radiogroup"] label:has(input:checked) { color:#fff; border-bottom-color:var(--accent); text-shadow:0 0 14px rgba(24,239,209,.45); }
.st-key-main_navigation [role="radiogroup"] label div:first-child,
[class*="st-key-subnav_"] [role="radiogroup"] label div:first-child { display:none; }
[class*="st-key-subnav_"] [role="radiogroup"] { display:flex; flex-wrap:nowrap; gap:4px; border:1px solid #293c66; border-radius:14px; background:#0c142c; padding:4px; margin-bottom:18px; overflow-x:auto; scrollbar-width:thin; }
[class*="st-key-subnav_"] [role="radiogroup"] label { flex:1 0 auto; min-width:118px; justify-content:center; border:0; border-radius:10px; padding:8px 13px; color:#8fa4c9; font-size:.82rem; font-weight:750; }
[class*="st-key-subnav_"] [role="radiogroup"] label:has(input:checked) { color:#061918; background:var(--accent); }
h1,h2,h3 { letter-spacing:-0.03em; color:#fff !important; }
h1 { font-weight:850 !important; }
h2 { color:#a9bee1 !important; margin-top:1.7rem !important; }
p,li,[data-testid="stCaptionContainer"] { color:#9eb1d2; }
[data-testid="stMetric"] { background:linear-gradient(145deg,#16213f,#0d142b); border:1px solid #344a78; border-radius:20px; padding:17px; box-shadow:0 14px 34px rgba(0,0,0,.24); }
[data-testid="stMetricLabel"] { color:#92a8ce; text-transform:uppercase; letter-spacing:.06em; }
[data-testid="stMetricValue"] { color:#fff; }
[data-testid="stMetricDelta"] svg { fill:var(--accent); }
[data-testid="stDataFrame"] { border:1px solid #2a3b63; border-radius:18px; overflow:hidden; background:#0e152c; }
.stAlert { border-radius:16px; border:1px solid #33496f; background:#101a36; }
.stTabs [data-baseweb="tab-list"] { gap:8px; }
.stTabs [data-baseweb="tab"] { background:#121a35; border:1px solid #293a62; border-radius:14px; padding:10px 16px; color:#9eb1d2; }
.stTabs [aria-selected="true"] { color:#041414 !important; background:var(--accent) !important; border-color:var(--accent) !important; }
.hero { padding:27px 30px; border:1px solid #405887; border-radius:24px; background:radial-gradient(circle at 90% 10%,rgba(24,239,209,.20),transparent 35%),linear-gradient(130deg,#172344,#0c132c 62%); margin-bottom:20px; box-shadow:0 18px 48px rgba(0,0,0,.25); }
.hero-kicker { color:var(--accent); font-weight:850; text-transform:uppercase; letter-spacing:.13em; font-size:.76rem; }
.hero-title { color:#fff; font-size:2.2rem; font-weight:850; margin:.3rem 0; }
.hero-copy { color:#a8b9d7; max-width:780px; }
div[data-testid="stExpander"] { border:1px solid #2d416d; border-radius:16px; background:#0d152e; }
.stButton button,.stDownloadButton button { background:#16213f; color:var(--accent); border:1px solid var(--accent); border-radius:999px; font-weight:750; }
.stButton button:hover,.stDownloadButton button:hover { background:var(--accent); color:#041414; }
.match-card { border:1px solid #405784; border-radius:21px; background:linear-gradient(145deg,#141d3a,#0c132a); padding:18px 20px; margin:10px 0; }
.match-top { display:flex; justify-content:space-between; color:#92a8ce; font-size:.83rem; text-transform:uppercase; letter-spacing:.06em; }
.match-teams { display:grid; grid-template-columns:1fr auto 1fr; gap:16px; align-items:center; margin-top:13px; }
.match-team { font-size:1.03rem; font-weight:750; color:#fff; }
.match-team.right { text-align:right; }
.match-score { font-size:1.75rem; font-weight:850; color:#fff; }
.match-vs { color:#7186ae; border:1px solid #31466f; border-radius:11px; padding:7px; font-weight:800; }
.match-bar { height:7px; border-radius:8px; background:#2d3f6b; margin-top:13px; overflow:hidden; }
.match-fill { height:100%; background:linear-gradient(90deg,#18efd1,#4fc3ff); border-radius:8px; }
.match-meta { color:#18efd1; font-weight:750; margin-top:8px; font-size:.9rem; }
.section-chip { display:inline-block; background:#16223f; border:1px solid #334b79; color:#a9bce0; border-radius:999px; padding:6px 11px; font-size:.78rem; font-weight:750; }
.espn-rankings { border:1px solid #30394d; border-top:4px solid #d71920; border-radius:4px; background:#11151d; overflow:hidden; box-shadow:0 16px 40px rgba(0,0,0,.28); margin:8px 0 20px; }
.espn-rankings-title { display:flex; align-items:center; justify-content:space-between; padding:14px 18px; background:#1b2029; border-bottom:1px solid #333b4a; }
.espn-rankings-title strong { color:#fff; font-size:1.02rem; letter-spacing:.02em; text-transform:uppercase; }
.espn-rankings-title span { color:#9ca7b8; font-size:.76rem; font-weight:700; text-transform:uppercase; }
.espn-rank-header,.espn-rank-row { display:grid; grid-template-columns:70px minmax(260px,1.8fr) 100px 105px 105px minmax(170px,1fr); align-items:center; column-gap:12px; }
.espn-rank-header { padding:9px 18px; background:#0b0e14; color:#8e98a8; font-size:.68rem; font-weight:800; letter-spacing:.07em; text-transform:uppercase; }
.espn-rank-row { min-height:86px; padding:10px 18px; border-top:1px solid #2a303d; background:#151a23; }
.espn-rank-row:nth-child(even) { background:#121720; }
.espn-rank-row:hover { background:#202734; }
.espn-rank-row.my-team { background:linear-gradient(90deg,rgba(215,25,32,.18),#171d27 36%); box-shadow:inset 4px 0 0 #d71920; }
.espn-rank-number { color:#fff; font-size:2rem; font-style:italic; font-weight:900; line-height:1; }
.espn-team-cell { display:flex; align-items:center; min-width:0; gap:13px; }
.espn-team-logo,.espn-team-fallback { width:48px; height:48px; flex:0 0 48px; object-fit:contain; }
.espn-team-fallback { display:grid; place-items:center; border-radius:50%; background:#2a3140; border:1px solid #465064; color:#fff; font-size:.8rem; font-weight:900; }
.espn-team-name { color:#fff; font-size:1rem; font-weight:850; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.espn-team-tier { color:#99a4b4; font-size:.77rem; margin-top:3px; }
.espn-rank-stat { color:#f3f5f8; font-size:.9rem; font-weight:800; }
.espn-rank-label { color:#8f9aaa; font-size:.68rem; margin-top:2px; text-transform:uppercase; }
.espn-move-up { color:#48c78e; font-weight:850; }
.espn-move-down { color:#ff6268; font-weight:850; }
.espn-move-flat { color:#a3adbb; font-weight:800; }
.espn-strength { color:#dce3ec; font-size:.82rem; line-height:1.3; }
.espn-strength b { color:#fff; }
.pr-summary-grid { display:grid; grid-template-columns:1fr 1fr; gap:16px; margin:8px 0 18px; }
.pr-trend-card { background:#242526; border-radius:7px; padding:18px 20px; border-top:5px solid #47c653; min-height:150px; }
.pr-trend-card.down { border-top-color:#ff7b81; }
.pr-trend-title { color:#f5f5f5; font-size:.92rem; font-weight:900; letter-spacing:.025em; margin-bottom:14px; }
.pr-trend-line { display:grid; grid-template-columns:1fr auto auto; gap:10px; color:#f2f2f2; font-size:.94rem; line-height:1.65; }
.pr-trend-line .up { color:#47c653; font-weight:900; }
.pr-trend-line .down { color:#ff7b81; font-weight:900; }
.pr-my-team { display:grid; grid-template-columns:2fr 1fr 1fr; gap:12px; background:#242526; border-radius:7px; padding:17px 20px; margin-bottom:22px; }
.pr-my-label { color:#fff; font-size:.78rem; font-weight:900; letter-spacing:.04em; text-transform:uppercase; }
.pr-my-value { color:#f3f3f3; font-size:1rem; margin-top:12px; }
.pr-my-value.good { color:#47c653; font-weight:900; }
.pr-my-value.bad { color:#ff7b81; font-weight:900; }
.pr-movement-panel { background:#1b1c1e; border-radius:7px; padding:22px 20px 16px; margin:8px 0 22px; overflow-x:auto; }
.pr-movement-heading { color:#fff; font-size:1.2rem; font-weight:900; letter-spacing:.08em; text-transform:uppercase; }
.pr-movement-subtitle { color:#d4d4d4; font-size:.9rem; margin:3px 0 18px; }
.pr-chart-key { display:flex; flex-wrap:wrap; gap:22px; border-top:1px dotted #484848; margin-top:10px; padding-top:14px; color:#e6e6e6; font-size:.82rem; }
.pr-key-circle { display:inline-grid; place-items:center; width:23px; height:23px; border-radius:50%; border:2px solid #eee; margin-right:7px; font-size:.65rem; font-weight:900; }
.pr-key-circle.filled { background:#eee; color:#191919; }
@media (max-width:700px) {
  .pr-summary-grid { grid-template-columns:1fr; }
  .pr-my-team { grid-template-columns:1.5fr 1fr 1fr; }
  .command-grid { grid-template-columns:1fr 1fr; }
  .briefing-grid { grid-template-columns:1fr; }
  .value-strip { grid-template-columns:1fr 1fr; }
  .playoff-window { grid-template-columns:1fr; }
  .portfolio-flow { grid-template-columns:1fr; }
  .contingency-options { grid-template-columns:1fr; }
  .gameplan-grid { grid-template-columns:1fr; }
  .accuracy-grid { grid-template-columns:1fr 1fr; }
  .recap-hero-grid { grid-template-columns:1fr; }
  .ai-status-grid { grid-template-columns:1fr 1fr; }
}
@media (max-width:900px) {
  .espn-rank-header { display:none; }
  .espn-rank-row { grid-template-columns:45px minmax(190px,1fr) 72px; column-gap:8px; padding:11px 12px; }
  .espn-rank-row > :nth-child(4),.espn-rank-row > :nth-child(6) { display:none; }
  .espn-team-logo,.espn-team-fallback { width:40px; height:40px; flex-basis:40px; }
}
/* Sleeper-inspired product shell: original branding and analysis, familiar UX. */
:root {
  --accent:#55f05a; --accent2:#31d9a0; --panel:#1b1d1f; --panel2:#232527;
  --line:#303235; --muted:#96989d; --pink:#ff6678; --orange:#f6b94f;
  --app-black:#090a0b; --app-surface:#111315; --link:#669cff;
}
.stApp { background:var(--app-black) !important; color:#f5f5f6; }
.block-container { max-width:1180px; padding-top:.45rem; padding-bottom:5rem; }
[data-testid="stMainBlockContainer"] { color:#f5f5f6; }
[data-testid="stHeader"] { background:rgba(9,10,11,.94); }
[data-testid="stToolbar"] { right:12px; }
[data-testid="stSidebar"] { background:#111214 !important; border-right:1px solid #292b2e; }
[data-testid="stSidebar"] * { color:#dedfe1; }
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) { background:#242628; box-shadow:inset 3px 0 0 var(--accent); }
.app-brand { min-height:58px; display:flex; align-items:center; justify-content:space-between; padding:7px 8px 8px; border-bottom:1px solid #282a2d; }
.app-brand-left { display:flex; align-items:center; gap:11px; }
.app-brand-ball { display:grid; place-items:center; width:38px; height:38px; border-radius:12px; background:#242628; font-size:1.25rem; }
.app-brand-name { color:#fff; font-size:1.08rem; font-weight:900; letter-spacing:-.02em; line-height:1.05; }
.app-brand-subtitle { color:#73767c; font-size:.65rem; font-weight:800; letter-spacing:.08em; text-transform:uppercase; margin-top:4px; }
.app-brand-status { display:flex; align-items:center; gap:6px; color:#d7d9dc; font-size:.68rem; font-weight:850; border:0; background:#222426; border-radius:999px; padding:7px 11px; }
.live-dot { width:7px; height:7px; border-radius:50%; background:var(--accent); box-shadow:0 0 10px rgba(85,240,90,.75); }
.st-key-main_navigation [role="radiogroup"] { background:#090a0b; border-bottom:1px solid #2a2c2f; margin-bottom:12px; }
.st-key-main_navigation [role="radiogroup"] label { min-width:112px; color:#777a80; padding:14px 18px 12px; border-bottom:4px solid transparent; font-size:.79rem; font-weight:900; letter-spacing:.035em; }
.st-key-main_navigation [role="radiogroup"] label:has(input:checked) { color:#fff; border-bottom-color:var(--accent); text-shadow:none; }
[class*="st-key-subnav_"] [role="radiogroup"] { background:#1a1c1e; border:0; border-radius:14px; padding:5px; margin:0 0 20px; box-shadow:0 8px 24px rgba(0,0,0,.18); }
[class*="st-key-subnav_"] [role="radiogroup"] label { min-width:128px; color:#999ba0; border-radius:10px; font-size:.78rem; font-weight:850; padding:9px 14px; }
[class*="st-key-subnav_"] [role="radiogroup"] label:has(input:checked) { color:#090b09; background:var(--accent); }
.league-context { display:flex; align-items:center; justify-content:space-between; gap:16px; padding:14px 16px; background:#17191b; border:1px solid #282a2d; border-radius:15px; margin:2px 0 18px; }
.league-context-left { display:flex; align-items:center; gap:12px; min-width:0; }
.league-avatar { width:44px; height:44px; border-radius:50%; object-fit:cover; background:#282a2d; border:2px solid #3a3c40; }
.league-avatar-fallback { display:grid; place-items:center; color:#fff; font-weight:950; }
.league-team-name { color:#fff; font-size:1rem; font-weight:900; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.league-meta { color:#81848a; font-size:.72rem; margin-top:3px; }
.league-week { color:var(--accent); font-size:.72rem; font-weight:900; text-align:right; white-space:nowrap; }
h1,h2,h3 { color:#f5f5f6 !important; letter-spacing:-.025em; }
h1 { font-size:1.65rem !important; font-weight:900 !important; }
h2 { color:#f5f5f6 !important; font-size:1.05rem !important; font-weight:900 !important; text-transform:uppercase; letter-spacing:.025em; margin-top:1.6rem !important; }
h3 { font-size:1rem !important; }
p,li,[data-testid="stCaptionContainer"] { color:#999ca2; }
.stMarkdown p { line-height:1.52; }
label,[data-testid="stWidgetLabel"] { color:#d7d9dc !important; }
[data-testid="stTextInput"] input,
[data-testid="stTextArea"] textarea,
[data-testid="stNumberInput"] input,
[data-testid="stDateInput"] input,
[data-baseweb="select"] > div {
  color:#f5f5f6 !important; background:#111315 !important;
  border-color:#36393d !important; border-radius:9px !important;
}
[data-testid="stTextInput"] input:focus,
[data-testid="stTextArea"] textarea:focus,
[data-testid="stNumberInput"] input:focus,
[data-baseweb="select"] > div:focus-within {
  border-color:var(--accent) !important;
  box-shadow:0 0 0 1px rgba(85,240,90,.35) !important;
}
[data-testid="stCheckbox"] label,[data-testid="stRadio"] label { color:#d7d9dc !important; }
[data-testid="stForm"] { background:#17191b; border:1px solid #303235; border-radius:14px; padding:16px; }
.hero { padding:22px 23px; border:1px solid #2d2f32; border-radius:18px; background:linear-gradient(145deg,#202224,#17191b); margin-bottom:16px; box-shadow:0 14px 34px rgba(0,0,0,.24); }
.hero-kicker { color:var(--accent); font-size:.68rem; letter-spacing:.11em; }
.hero-title { font-size:1.75rem; margin:.35rem 0; }
.hero-copy { color:#a1a3a8; font-size:.88rem; max-width:760px; }
.hero { border-top:3px solid var(--accent); background:#1b1d1f; box-shadow:none; }
[data-testid="stMetric"] { background:#1c1e20; border:1px solid #2f3134; border-radius:15px; padding:15px; box-shadow:none; }
[data-testid="stMetricLabel"] { color:#8e9197; font-size:.68rem; font-weight:850; }
[data-testid="stMetricValue"] { color:#fff; font-weight:900; }
[data-testid="stDataFrame"] { border:1px solid #2f3134; border-radius:13px; background:#17191b; }
.stAlert,[data-testid="stAlert"] { border-radius:13px; border:1px solid #34363a; background:#1b1d1f; color:#e1e3e6; }
div[data-testid="stExpander"] { border:1px solid #303236; border-radius:13px; background:#191b1d; }
.streamlit-expanderHeader { color:#e1e3e6 !important; font-weight:800; }
.stTabs [data-baseweb="tab"] { background:#1d1f21; border:0; border-radius:10px; color:#a1a3a8; }
.stTabs [aria-selected="true"] { color:#090b09 !important; background:var(--accent) !important; }
.stButton button,.stDownloadButton button { background:#222426; color:#f4f5f5; border:1px solid #37393c; border-radius:10px; font-weight:850; }
.stButton button:hover,.stDownloadButton button:hover { background:var(--accent); border-color:var(--accent); color:#0a0b0a; }
.stButton button:focus-visible,.stDownloadButton button:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
.stButton button[kind="primary"] { background:var(--accent); color:#081008; border-color:var(--accent); }
.stButton button[kind="primary"]:hover { background:#74f477; border-color:#74f477; }
.command-card,.briefing-panel,.win-card,.value-tile,.round-card,.portfolio-card,.gameplan-card,.accuracy-card,.recap-card { background:#1b1d1f !important; border-color:#303235 !important; box-shadow:none; }
.command-card.accent,.value-tile.good,.gameplan-card.opportunity { border-top:3px solid var(--accent) !important; }
.command-card.warn,.value-tile.warn,.gameplan-card.danger { border-top:3px solid #ff6878 !important; }
.command-value,.value-tile-number,.win-number { color:#fff; }
.win-fill,.match-fill { background:var(--accent); }
.win-card { border-top:3px solid var(--accent) !important; }
.match-card { border:1px solid #303235; background:#1b1d1f; border-radius:15px; box-shadow:none; }
.match-vs { background:#111315; border-color:#34363a; color:#8e9197; }
.match-meta,.section-chip { color:var(--accent); }
.section-chip { background:#1d2a1e; border-color:#315735; }
.week-rollover,.accuracy-diagnosis,.action-box { background:#172319; border-color:#315b35; }
.espn-rankings { border-color:#303235; border-top-color:var(--accent); background:#151719; }
.espn-rankings-title,.espn-rank-row { background:#1b1d1f; }
.espn-rank-row:nth-child(even) { background:#181a1c; }
.espn-rank-row.my-team { background:linear-gradient(90deg,rgba(85,240,90,.12),#1b1d1f 36%); box-shadow:inset 4px 0 0 var(--accent); }
.pr-trend-card,.pr-my-team { background:#222426; }
.pr-movement-panel { background:#1b1d1f; }
hr { border-color:#303235 !important; }
@media (max-width:700px) {
  .block-container { padding-left:.65rem; padding-right:.65rem; }
  .app-brand { padding-left:2px; padding-right:2px; }
  .app-brand-subtitle { display:none; }
  .st-key-main_navigation [role="radiogroup"] label { min-width:86px; padding-left:11px; padding-right:11px; font-size:.7rem; }
  .league-context { padding:11px 12px; }
  .league-avatar { width:38px; height:38px; }
  .hero { padding:19px 17px; }
  .hero-title { font-size:1.5rem; }
}
</style>
""", unsafe_allow_html=True)


def hero(kicker, title, copy):
    safe_kicker = html.escape(str(kicker))
    safe_title = html.escape(str(title))
    safe_copy = html.escape(str(copy))
    st.markdown(
        f'<div class="hero"><div class="hero-kicker">{safe_kicker}</div>'
        f'<div class="hero-title">{safe_title}</div>'
        f'<div class="hero-copy">{safe_copy}</div></div>',
        unsafe_allow_html=True,
    )


def updated_caption():
    st.caption(f"Last updated: {datetime.now():%b %d, %Y at %I:%M %p}")


@st.cache_resource(ttl=150)
def load_league(user_id, league_id, connection_id, connection_version,
                provider_league_id, session_key, season=ESPN_SEASON_YEAR,
                sport="nba"):
    credentials = account_store.get_provider_credentials(user_id, connection_id)
    connector = connect_to_nfl_league if str(sport).lower() == "nfl" else connect_to_league
    return connector(year=season, credentials=credentials, league_id=provider_league_id)


@st.cache_resource(ttl=1800)
def load_previous_league(user_id, league_id, connection_id, connection_version,
                         provider_league_id, session_key, season=ESPN_SEASON_YEAR):
    """Last season is helpful but optional; failure never blocks the site."""
    try:
        credentials = account_store.get_provider_credentials(user_id, connection_id)
        return connect_to_league(
            year=season - 1, credentials=credentials,
            league_id=provider_league_id,
        )
    except Exception:
        return None


@st.cache_data(ttl=3600)
def load_schedule():
    return get_matchup_week_schedule()


@st.cache_data(ttl=3600)
def load_upcoming_schedules():
    return get_upcoming_week_schedules(count=4)


@st.cache_data(ttl=3600)
def load_season_schedules():
    return get_upcoming_week_schedules(count=30)


@st.cache_data(ttl=3600)
def load_completed_schedules():
    return get_completed_week_schedules(count=30)


@st.cache_data(ttl=3600)
def load_defense_context():
    return get_team_defense_context()


@st.cache_data(ttl=150)
def load_news():
    return fetch_nba_news()


@st.cache_data(ttl=150, show_spinner=False)
def calculate_league_intelligence(cache_scope, active_period, _league, _previous_league):
    """One shared league model for rankings, strategy, scouting, and draft value."""
    power, history, team_rows = league_power_rankings(_league, _previous_league)
    stored = pd.DataFrame(power_snapshot_history())
    prior = stored[stored["snapshot_week"] < int(active_period)] if not stored.empty else pd.DataFrame()
    if not prior.empty:
        prior_week = int(prior["snapshot_week"].max())
        ranks = prior[prior["snapshot_week"] == prior_week].set_index("team_name")["rank"].to_dict()
        power["Previous week rank"] = power["Team"].map(ranks)
        power["Week movement"] = (
            power["Previous week rank"] - power["Rank"]
        ).fillna(0).astype(int)
        power["Movement"] = power["Week movement"].map(
            lambda change: "—" if change == 0 else f"▲ {change}" if change > 0 else f"▼ {abs(change)}"
        )
    else:
        power["Previous week rank"] = power["Draft rank"]
        power["Week movement"] = power["Draft rank"] - power["Rank"]
    return power, history, team_rows


def matchup_for_team(league, team, matchup_period=None):
    matchup_period = int(
        matchup_period
        or getattr(league, "currentMatchupPeriod", 1)
        or 1
    )
    try:
        matchups = league.box_scores(
            matchup_period=matchup_period
        )
    except Exception:
        try:
            matchups = league.scoreboard(matchupPeriod=matchup_period)
        except TypeError:
            matchups = league.scoreboard()
    for matchup in matchups:
        ids = {getattr(matchup.home_team, "team_id", None), getattr(matchup.away_team, "team_id", None)}
        if team.team_id in ids:
            return matchup
    return None


def archive_previous_matchup(league, team, active_period):
    """Save the last completed matchup once after the site advances weeks."""
    previous_period = int(active_period) - 1
    if previous_period < 1:
        return None
    previous = matchup_for_team(league, team, previous_period)
    if previous is None:
        return None
    is_home = previous.home_team.team_id == team.team_id
    my_score = _matchup_score(previous, "home" if is_home else "away")
    opponent_score = _matchup_score(previous, "away" if is_home else "home")
    if my_score == 0 and opponent_score == 0:
        return None
    opponent = previous.away_team if is_home else previous.home_team
    save_weekly_result(
        ESPN_SEASON_YEAR, previous_period, team.team_name,
        opponent.team_name, my_score, opponent_score,
    )
    return {
        "matchup_period": previous_period,
        "opponent": opponent.team_name,
        "team_score": my_score,
        "opponent_score": opponent_score,
        "result": "W" if my_score > opponent_score else "L" if my_score < opponent_score else "T",
    }


def opponent_for(matchup, team):
    if matchup is None:
        return None
    return matchup.away_team if matchup.home_team.team_id == team.team_id else matchup.home_team


def _matchup_score(matchup, side):
    for name in [f"{side}_score", f"{side}_team_live_score", f"{side}_final_score"]:
        value = getattr(matchup, name, None)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                pass
    return 0.0


@st.cache_data(ttl=150, show_spinner=False)
def calculate_live_outlook(cache_scope, team_name, _league, _previous_league, _matchup,
                           _schedule):
    if _matchup is None or not _schedule:
        return None
    selected = next(t for t in _league.teams if t.team_name == team_name)
    opponent = opponent_for(_matchup, selected)
    if opponent is None:
        return None
    my_plan = weekly_lineup_plan(
        _league, selected, _schedule, _previous_league
    )
    opponent_plan = weekly_lineup_plan(
        _league, opponent, _schedule, _previous_league
    )
    my_remaining, my_games = remaining_plan_projection(my_plan, _schedule)
    opponent_remaining, opponent_games = remaining_plan_projection(
        opponent_plan, _schedule
    )
    is_home = _matchup.home_team.team_id == selected.team_id
    my_live = _matchup_score(_matchup, "home" if is_home else "away")
    opponent_live = _matchup_score(_matchup, "away" if is_home else "home")
    outlook = live_matchup_outlook(
        my_live, opponent_live, my_remaining, opponent_remaining,
        my_games, opponent_games,
    )
    outlook.update({
        "my_live": my_live,
        "opponent_live": opponent_live,
        "opponent_name": opponent.team_name,
    })
    return outlook


def render_win_probability(outlook):
    if not outlook:
        st.info("Live win probability will appear when ESPN supplies a matchup and the NBA schedule is available.")
        return
    probability = int(outlook["win_probability"])
    margin = float(outlook["projected_margin"])
    margin_text = f"{margin:+.1f} pts"
    st.markdown(
        '<div class="win-card">'
        '<div class="win-head"><div><div class="win-eyebrow">Live win probability</div>'
        f'<div class="win-number">{probability}%</div></div>'
        f'<div class="win-confidence">{html.escape(outlook["confidence"])} confidence</div></div>'
        f'<div class="win-track"><div class="win-fill" style="width:{probability}%"></div></div>'
        '<div class="win-scale"><span>0%</span><span>Toss-up</span><span>100%</span></div>'
        '<div class="win-projections">'
        f'<div class="win-stat"><div class="win-stat-label">Projected final</div><div class="win-stat-value">{outlook["my_projected_final"]:.1f}–{outlook["opponent_projected_final"]:.1f}</div></div>'
        f'<div class="win-stat"><div class="win-stat-label">Projected margin</div><div class="win-stat-value">{margin_text}</div></div>'
        f'<div class="win-stat"><div class="win-stat-label">Usable games left</div><div class="win-stat-value">{outlook["my_remaining_games"]:g}–{outlook["opponent_remaining_games"]:g}</div></div>'
        '</div>'
        f'<div class="win-summary">{html.escape(outlook["summary"])}</div></div>',
        unsafe_allow_html=True,
    )


def load_manual_data():
    st.subheader("Manual fallback")
    st.write("Use this if ESPN cannot connect. Values remain in this browser session only.")
    st.download_button("Download blank CSV template", blank_template().to_csv(index=False), "fantasy_roster_template.csv", "text/csv")
    upload = st.file_uploader("Upload completed CSV", type=["csv"])
    pasted = st.text_area("Or paste CSV data", placeholder="Side,Player,NBA team,Position,Fantasy slot,FP/G\nMe,Example Player,BOS,PG,PG,42.5\nOpponent,Another Player,LAL,C,C,38.0")
    try:
        if upload is not None:
            return read_uploaded_csv(upload)
        if pasted.strip():
            return read_pasted_csv(pasted)
    except Exception as error:
        st.error(f"Manual data could not be read: {error}")
    return None


def render_matchup(matchup):
    st.subheader("This week's matchup")
    if matchup is None:
        st.info("ESPN has not provided a current matchup yet.")
        return
    home = getattr(matchup, "home_score", None)
    away = getattr(matchup, "away_score", None)
    if home is None:
        home = getattr(matchup, "home_team_live_score", None)
    if away is None:
        away = getattr(matchup, "away_team_live_score", None)
    if home is None:
        home = getattr(matchup, "home_final_score", None)
    if away is None:
        away = getattr(matchup, "away_final_score", None)
    home_text = "—" if home is None else f"{home:.1f}"
    away_text = "—" if away is None else f"{away:.1f}"
    st.markdown(
        f'<div class="match-card"><div class="match-top"><span>Live ESPN matchup</span><span>Read only</span></div>'
        f'<div class="match-teams"><div><div class="match-team">{html.escape(str(matchup.home_team.team_name))}</div><div class="match-score">{home_text}</div></div>'
        f'<div class="match-vs">VS</div><div class="match-team right">{html.escape(str(matchup.away_team.team_name))}<div class="match-score">{away_text}</div></div></div></div>',
        unsafe_allow_html=True,
    )


def render_home(league, previous_league, team, matchup, schedule):
    hero("Front office overview", team.team_name, "One place to understand your matchup, roster health, schedule leverage, and most important next decision.")
    updated_caption()
    active_period = int(getattr(league, "currentMatchupPeriod", 1) or 1)
    completed = weekly_result_history(ESPN_SEASON_YEAR, team.team_name)
    if completed and int(completed[0]["matchup_period"]) == active_period - 1:
        latest = completed[0]
        prior_forecasts = forecast_history(ESPN_SEASON_YEAR, team.team_name)
        prior = next(
            (row for row in prior_forecasts
             if int(row["matchup_period"]) == int(latest["matchup_period"])),
            None,
        )
        forecast_note = ""
        if prior:
            error = float(latest["team_score"]) - float(prior["team_projection"])
            forecast_note = (
                f" Forecast {float(prior['team_projection']):.1f}–"
                f"{float(prior['opponent_projection']):.1f}; your score error {error:+.1f}."
            )
        st.markdown(
            '<div class="week-rollover"><div>'
            f'<div class="week-rollover-title">Week {active_period} is now active</div>'
            f'<div class="week-rollover-copy">Week {int(latest["matchup_period"])} finalized vs {html.escape(str(latest["opponent"]))}.{html.escape(forecast_note)} Predictions now use the new matchup, current roster, and new NBA schedule.</div>'
            f'</div><div class="week-result">{html.escape(str(latest["result"]))} · {float(latest["team_score"]):.1f}–{float(latest["opponent_score"]):.1f}</div></div>',
            unsafe_allow_html=True,
        )
    opponent = opponent_for(matchup, team)
    wins = int(getattr(team, "wins", 0) or 0)
    losses = int(getattr(team, "losses", 0) or 0)
    local_wins = sum(row["result"] == "W" for row in completed)
    local_losses = sum(row["result"] == "L" for row in completed)
    if local_wins + local_losses > wins + losses:
        wins, losses = local_wins, local_losses
    standing = getattr(team, "standing", None)
    injured = [
        p.name for p in team.roster
        if str(getattr(p, "injuryStatus", "")).upper()
        not in {"ACTIVE", "NORMAL", "HEALTHY", ""}
    ]
    my_score = opponent_score = None
    if matchup is not None:
        is_home = matchup.home_team.team_id == team.team_id
        my_score = getattr(matchup, "home_score" if is_home else "away_score", None)
        opponent_score = getattr(matchup, "away_score" if is_home else "home_score", None)
    matchup_value = "Not started"
    if my_score is not None and opponent_score is not None:
        matchup_value = f"{float(my_score):.1f}–{float(opponent_score):.1f}"
    standing_text = f"#{int(standing)}" if standing else "—"
    opponent_text = html.escape(opponent.team_name) if opponent else "Not available"
    st.markdown(
        '<div class="command-grid">'
        f'<div class="command-card accent"><div class="command-label">Season record</div><div class="command-value">{wins}–{losses}</div><div class="command-detail">Current ESPN record</div></div>'
        f'<div class="command-card"><div class="command-label">League position</div><div class="command-value">{standing_text}</div><div class="command-detail">Power ranking analysis lives in League</div></div>'
        f'<div class="command-card"><div class="command-label">Live matchup</div><div class="command-value">{matchup_value}</div><div class="command-detail">vs {opponent_text}</div></div>'
        f'<div class="command-card"><div class="command-label">Roster alerts</div><div class="command-value">{len(injured)}</div><div class="command-detail">Players needing an injury check</div></div>'
        '</div>',
        unsafe_allow_html=True,
    )
    with st.spinner("Updating live matchup outlook..."):
        outlook = calculate_live_outlook(
            CACHE_SCOPE, team.team_name, league, previous_league, matchup, schedule
        )
        render_win_probability(outlook)
    if outlook and opponent and schedule:
        save_matchup_forecasts(
            ESPN_SEASON_YEAR, team.team_name,
            pd.DataFrame([{
                "Fantasy week": active_period,
                "Dates": f"{schedule['start_date']:%b %d}–{schedule['end_date']:%b %d}",
                "Opponent": opponent.team_name,
                "Your projection": outlook["my_projected_final"],
                "Opponent projection": outlook["opponent_projected_final"],
            }]),
        )
    alerts = []
    if not team.roster:
        alerts.append("Your ESPN roster is empty; this is expected before the draft completes.")
    else:
        alerts.append(f"Recheck injury news for {', '.join(injured[:3])}." if injured else "No roster injury flags were returned by ESPN.")
    alerts.append(f"Your current opponent is {opponent.team_name}." if opponent else "ESPN has not supplied a current opponent yet.")
    if schedule and not schedule["game_counts"].empty:
        maximum = schedule["game_counts"]["Games"].max()
        leaders = schedule["game_counts"].query("Games == @maximum")["NBA team"].tolist()
        alerts.append(f"Schedule edge: {', '.join(leaders)} lead the week with {maximum} games.")
    else:
        alerts.append("The NBA schedule is unavailable; projections are incomplete.")
    next_action = (
        f"Check {injured[0]}'s status" if injured
        else "Review this week's lineup"
    )
    action_copy = (
        "An injury designation can change both your starters and waiver priorities."
        if injured else
        "Confirm every active player fits a legal daily slot before the first game locks."
    )
    alert_markup = "".join(
        f'<div class="briefing-item"><div class="briefing-number">{index}</div><div>{html.escape(alert)}</div></div>'
        for index, alert in enumerate(alerts[:3], 1)
    )
    st.markdown(
        '<div class="briefing-grid">'
        f'<div class="briefing-panel"><div class="briefing-title">Morning briefing</div>{alert_markup}</div>'
        '<div class="briefing-panel"><div class="briefing-title">Recommended next action</div>'
        f'<div class="action-box"><div class="action-kicker">Priority</div><div class="action-title">{html.escape(next_action)}</div><div class="action-copy">{html.escape(action_copy)}</div></div></div>'
        '</div>',
        unsafe_allow_html=True,
    )
    render_matchup(matchup)


def _lineup_total(plans):
    total = 0.0
    starters = 0
    for rows in plans.values():
        for row in rows:
            if str(row["Recommendation"]).startswith("Start") and row["Advice score"] is not None:
                total += float(row["Advice score"])
                starters += 1
    return (round(total, 2) if starters else None), starters


def render_schedule(league, previous_league, team, matchup, schedule):
    st.title("Schedule & matchup projection")
    updated_caption()
    if not schedule:
        st.error("NBA schedule data is unavailable, so this page cannot calculate projections.")
        return
    st.caption(f"{schedule['week_name']}: {schedule['start_date']:%b %d}–{schedule['end_date']:%b %d, %Y}")
    if schedule.get("source") == "cached":
        st.warning("NBA.com timed out, so this page is using the last successfully saved schedule.")
    render_win_probability(calculate_live_outlook(
        CACHE_SCOPE, team.team_name, league, previous_league, matchup, schedule
    ))
    st.dataframe(schedule["game_counts"], hide_index=True, use_container_width=True)
    opponent = opponent_for(matchup, team)
    if opponent is None:
        st.info("ESPN has not provided an opponent yet.")
        return
    with st.spinner("Calculating custom projections..."):
        mine, _, my_missing = project_team_for_week(league, team, schedule["game_counts"], previous_league)
        theirs, _, opp_missing = project_team_for_week(league, opponent, schedule["game_counts"], previous_league)
        my_total, my_starts = _lineup_total(weekly_lineup_plan(league, team, schedule, previous_league))
        opp_total, opp_starts = _lineup_total(weekly_lineup_plan(league, opponent, schedule, previous_league))
    left, right = st.columns(2)
    with left:
        st.subheader(team.team_name)
        st.dataframe(mine, hide_index=True, use_container_width=True)
        st.metric("Projected legal-lineup total", "N/A" if my_total is None else f"{my_total:.1f}", help=f"{my_starts} projected player-games fit into legal daily slots.")
    with right:
        st.subheader(opponent.team_name)
        st.dataframe(theirs, hide_index=True, use_container_width=True)
        st.metric("Projected legal-lineup total", "N/A" if opp_total is None else f"{opp_total:.1f}", help=f"{opp_starts} projected player-games fit into legal daily slots.")
    if my_total is not None and opp_total is not None:
        difference = my_total - opp_total
        favored = team.team_name if difference >= 0 else opponent.team_name
        st.success(f"{favored} is favored by about {abs(difference):.1f} points based on projected FP/G, the NBA schedule, and legal daily lineup slots.")
    if my_missing or opp_missing:
        st.warning("Projection is incomplete for one or more players because ESPN did not return a current projection or last-season result.")
    if previous_league is None:
        st.info("Last season's ESPN league data was unavailable, so available 2026–27 ESPN projections are used by themselves.")
    st.caption("Blended FP/G = 70% ESPN 2026–27 projection + 30% actual 2025–26 FP/G when both are available. Totals count only legal daily starters.")


def render_today(league, previous_league, team, schedule):
    st.title("Weekly lineup plan")
    updated_caption()
    if not schedule:
        st.error("NBA schedule data is unavailable. No start/sit advice was generated.")
        return
    with st.spinner("Building a legal lineup for every day this week..."):
        plans = weekly_lineup_plan(league, team, schedule, previous_league)
    if not plans or not any(plans.values()):
        st.info("No drafted players are available yet.")
        return
    st.info("This is a planning view. It refreshes when you reload the page and may change after injuries, news, or completed games.")
    dates = list(plans)
    tabs = st.tabs([f"{day:%a %b %d}" + (" · TODAY" if day == date.today() else "") for day in dates])
    initialize_database()
    for tab, day in zip(tabs, dates):
        with tab:
            rows = plans[day]
            starter_rows = [
                {
                    "Slot": row["Recommendation"].replace("Start — ", ""),
                    "Player": row["Player"],
                    "NBA team": row["NBA team"],
                    "Positions": row["Positions"],
                    "Injury status": row["Injury status"],
                    "Reason": row["Reason"],
                    "May update if": row["May update if"],
                }
                for row in rows
                if str(row["Recommendation"]).startswith("Start")
            ]
            starters = len(starter_rows)
            if starter_rows:
                st.dataframe(pd.DataFrame(starter_rows), hide_index=True, use_container_width=True)
            else:
                st.info("No players on your roster have an NBA game this day.")
            st.caption(f"{starters} projected starters. Recheck this tab on game day before the first tipoff.")
            save_daily_snapshot(day, team.team_name, rows)
    st.success("The week's planning snapshots were saved locally for trend tracking.")
    with st.expander("Recent saved snapshots"):
        st.dataframe(pd.DataFrame(snapshot_history(team.team_name, 50)), hide_index=True, use_container_width=True)


@st.cache_data(ttl=150, show_spinner=False)
def calculate_contingencies(cache_scope, team_name, _league, _previous_league, _schedule):
    selected = next(t for t in _league.teams if t.team_name == team_name)
    playing = teams_playing_on(_schedule, date.today())
    roster_rows = build_player_rows(
        _league, selected, playing, previous_league=_previous_league
    )
    roster_rows = recommend_lineup(roster_rows)
    waivers = rank_waivers(
        _league, _schedule["game_counts"], size=50,
        previous_league=_previous_league,
        injury_pool=injury_pool_from_league(_league),
    )
    try:
        pending = active_waiver_claims(_league, selected.team_id)
    except Exception:
        pending = []
    pending_adds = {
        str(claim.get("Add")).casefold()
        for claim in pending if claim.get("Add")
    }
    if not waivers.empty and pending_adds:
        waivers = waivers[
            ~waivers["Player"].astype(str).str.casefold().isin(pending_adds)
        ]
    return injury_contingency_plans(roster_rows, waivers, playing), pending


def render_contingencies(league, previous_league, team, schedule):
    hero(
        "Know the next move before news breaks", "Injury Contingencies",
        "Pre-build an if/then response for every current roster injury flag using legal positions, today's games, and healthy waiver availability.",
    )
    updated_caption()
    if not schedule:
        st.error("NBA schedule data is unavailable, so today's replacement options cannot be verified.")
        return
    with st.spinner("Building injury scenarios..."):
        plans, pending = calculate_contingencies(
            CACHE_SCOPE, team.team_name, league, previous_league, schedule
        )
    if plans.empty:
        st.success("ESPN currently reports no roster injury designations requiring a contingency plan.")
        return
    if pending:
        st.info("Players in active waiver claims are not offered again as contingency targets.")
    st.caption("Roster replacements are limited to healthy bench players who have a game today and share an eligible position. Waiver fallbacks follow the same checks.")
    for _, plan in plans.iterrows():
        roster_fp = plan["Roster replacement FP/G"]
        waiver_fp = plan["Waiver fallback FP/G"]
        roster_text = html.escape(str(plan["Roster replacement"]))
        waiver_text = html.escape(str(plan["Waiver fallback"]))
        if pd.notna(roster_fp):
            roster_text += f" · {float(roster_fp):.1f} FP/G"
        if pd.notna(waiver_fp):
            waiver_text += f" · {float(waiver_fp):.1f} FP/G"
        st.markdown(
            '<div class="contingency-card">'
            f'<div class="contingency-head"><div class="contingency-player">If {html.escape(str(plan["Player"]))} cannot play</div><div class="contingency-status">{html.escape(str(plan["Status"]))}</div></div>'
            f'<div class="contingency-trigger"><b>Trigger:</b> {html.escape(str(plan["Trigger"]))}<br><b>Action:</b> {html.escape(str(plan["Immediate action"]))}</div>'
            '<div class="contingency-options">'
            f'<div class="contingency-option"><div class="contingency-option-label">Roster replacement</div><div class="contingency-option-name">{roster_text}</div></div>'
            f'<div class="contingency-option"><div class="contingency-option-label">Waiver fallback</div><div class="contingency-option-name">{waiver_text}</div></div>'
            '</div></div>',
            unsafe_allow_html=True,
        )
    st.warning("Always verify official status near tipoff. The app cannot move a player, activate IR, or submit a waiver claim.")


@st.cache_data(ttl=150, show_spinner=False)
def calculate_opponent_gameplan(cache_scope, team_name, _league, _previous_league,
                                _matchup, _schedule):
    selected = next(t for t in _league.teams if t.team_name == team_name)
    opponent = opponent_for(_matchup, selected)
    if opponent is None:
        return pd.DataFrame(), pd.DataFrame(), [], pd.DataFrame(), None
    my_plan = weekly_lineup_plan(
        _league, selected, _schedule, _previous_league
    )
    opponent_plan = weekly_lineup_plan(
        _league, opponent, _schedule, _previous_league
    )
    daily, threats = matchup_counterstrategy(my_plan, opponent_plan)
    opponent_rows = build_player_rows(
        _league, opponent, set(), previous_league=_previous_league
    )
    injuries = [
        row for row in opponent_rows
        if str(row.get("Injury status", "")).upper()
        not in {"ACTIVE", "NORMAL", "HEALTHY", ""}
    ]
    outlook = calculate_live_outlook(
        cache_scope, team_name, _league, _previous_league, _matchup, _schedule
    )
    _, _, moves, _ = calculate_streaming_plan(
        cache_scope, team_name, _league, _previous_league
    )
    impacts = []
    if outlook and not moves.empty:
        positive = moves[moves["Week 1 gain"] > 0].sort_values(
            "Week 1 gain", ascending=False
        ).drop_duplicates("Add").head(5)
        for _, move in positive.iterrows():
            revised = live_matchup_outlook(
                outlook["my_live"], outlook["opponent_live"],
                outlook["my_remaining"] + float(move["Week 1 gain"]),
                outlook["opponent_remaining"],
                outlook["my_remaining_games"],
                outlook["opponent_remaining_games"],
            )
            impacts.append({
                "Add": move["Add"], "Drop": move["Drop"],
                "Projected week gain": move["Week 1 gain"],
                "Current win probability": f"{outlook['win_probability']}%",
                "Estimated after move": f"{revised['win_probability']}%",
                "Probability lift": f"+{max(0, revised['win_probability'] - outlook['win_probability'])} pts",
            })
    return daily, threats, injuries, pd.DataFrame(impacts), outlook


def render_opponent_gameplan(league, previous_league, team, matchup, schedule):
    hero(
        "Win this matchup, not an average matchup", "Opponent Gameplan",
        "Find the opponent's biggest threats, the most important day, and the available move that creates the most matchup-specific leverage.",
    )
    updated_caption()
    if matchup is None or not schedule:
        st.error("A current ESPN matchup and NBA schedule are required.")
        return
    with st.spinner("Building the opponent-specific gameplan..."):
        daily, threats, injuries, impacts, outlook = calculate_opponent_gameplan(
            CACHE_SCOPE, team.team_name, league, previous_league, matchup, schedule
        )
    opponent = opponent_for(matchup, team)
    if daily.empty or opponent is None:
        st.info("ESPN did not return enough lineup data for an opponent gameplan.")
        return
    dangerous = daily.sort_values("Daily edge").iloc[0]
    best_day = daily.sort_values("Daily edge", ascending=False).iloc[0]
    top_threat = threats.iloc[0] if not threats.empty else None
    threat_name = top_threat["Player"] if top_threat is not None else "Not available"
    threat_points = (
        f"{float(top_threat['Projected matchup points']):.1f} projected points"
        if top_threat is not None else "Projection unavailable"
    )
    st.markdown(
        '<div class="gameplan-grid">'
        f'<div class="gameplan-card danger"><div class="gameplan-label">Biggest opponent threat</div><div class="gameplan-value">{html.escape(str(threat_name))}</div><div class="gameplan-copy">{threat_points}</div></div>'
        f'<div class="gameplan-card danger"><div class="gameplan-label">Day to protect</div><div class="gameplan-value">{dangerous["Date"]:%A, %b %d}</div><div class="gameplan-copy">Projected daily edge {float(dangerous["Daily edge"]):+.1f} points</div></div>'
        f'<div class="gameplan-card opportunity"><div class="gameplan-label">Best attack day</div><div class="gameplan-value">{best_day["Date"]:%A, %b %d}</div><div class="gameplan-copy">Projected daily edge {float(best_day["Daily edge"]):+.1f} points</div></div>'
        '</div>',
        unsafe_allow_html=True,
    )
    if outlook:
        render_win_probability(outlook)
    if injuries:
        injury_text = ", ".join(
            f"{row['Player']} ({row['Injury status']})" for row in injuries[:5]
        )
        st.info(
            f"Opponent injury watch: {injury_text}. Recalculate if any status changes."
        )
    st.subheader("Daily leverage map")
    st.dataframe(daily, hide_index=True, use_container_width=True)
    st.subheader(f"{opponent.team_name}'s projected point leaders")
    st.dataframe(threats.head(8), hide_index=True, use_container_width=True)
    st.subheader("Moves that improve this matchup")
    if impacts.empty:
        st.info("No available tested waiver move currently creates a positive week-one gain after active claims.")
    else:
        st.dataframe(impacts.head(3), hide_index=True, use_container_width=True)
    st.caption("Probability lift is an estimate based on the move's legal-lineup week-one gain. It does not assume the claim succeeds or predict opponent transactions.")


def render_waivers(league, previous_league, team, schedule):
    st.title("Waiver wire")
    updated_caption()
    if st.button("↻ Refresh waiver wire now", key="refresh_waiver_wire"):
        st.cache_resource.clear()
        st.cache_data.clear()
        st.rerun()
    st.caption("Waiver availability and active claims are read directly from ESPN on every page refresh.")
    if not schedule:
        st.error("Schedule data is unavailable; waiver rankings would be incomplete.")
        return
    roster_rows = build_player_rows(league, team, teams_playing_on(schedule, date.today()), previous_league=previous_league)
    injury_pool = injury_pool_from_league(league)
    with st.spinner("Calculating custom waiver ratings..."):
        waivers = rank_waivers(league, schedule["game_counts"], size=50, previous_league=previous_league, injury_pool=injury_pool)
    if waivers.empty:
        st.info("ESPN returned no free agents.")
        return
    try:
        pending_claims = active_waiver_claims(league, team.team_id)
    except Exception:
        pending_claims = []
    pending_names = {
        str(claim["Add"]).casefold() for claim in pending_claims if claim.get("Add")
    }
    pending_drops = {
        str(claim["Drop"]) for claim in pending_claims if claim.get("Drop")
    }
    waivers["Claim status"] = waivers["Player"].map(
        lambda name: "Pending claim" if str(name).casefold() in pending_names else "Available"
    )
    if pending_claims:
        st.info(
            "Pending targets are shown for context but excluded from the next-move recommendations. "
            "Players already scheduled to be dropped are also protected from duplicate drop recommendations. "
            "The Strategy Board evaluates the roster as if the highest-priority non-conflicting claims succeed."
        )
        st.markdown("**Active claims already counted**")
        st.dataframe(
            pd.DataFrame(pending_claims).rename(columns={
                "Add": "Pending add", "Drop": "Pending drop",
            }),
            hide_index=True, use_container_width=True,
        )
    try:
        news_items, _ = load_news()
        waiver_news = filter_relevant_news(news_items, waivers["Player"].tolist())
        news_by_player = {}
        for item in waiver_news:
            for player_name in item["players"]:
                existing = news_by_player.get(player_name)
                if existing is None or item["injury_related"]:
                    news_by_player[player_name] = item
        waivers["Recent news"] = waivers["Player"].map(
            lambda name: news_by_player.get(name, {}).get("title", "")
        )
        waivers["News injury flag"] = waivers["Player"].map(
            lambda name: bool(news_by_player.get(name, {}).get("injury_related", False))
        )
        waivers["Availability check"] = waivers.apply(
            lambda row: (
                "Do not recommend — ESPN lists unavailable"
                if is_unavailable_status(row["Injury status"])
                else "Verify injury news before claiming"
                if row["News injury flag"]
                else "Available based on current data"
            ),
            axis=1,
        )
    except Exception:
        waivers["Recent news"] = "News feed unavailable"
        waivers["News injury flag"] = False
        waivers["Availability check"] = waivers["Injury status"].map(
            lambda status: "Do not recommend — ESPN lists unavailable" if is_unavailable_status(status) else "ESPN status checked; news unavailable"
        )
    st.subheader("Top available players")
    featured = waivers[
        (~waivers["Injury status"].apply(is_unavailable_status))
        & (~waivers["Player"].astype(str).str.casefold().isin(pending_names))
    ].head(3)
    cards = st.columns(3)
    for card, (_, player) in zip(cards, featured.iterrows()):
        with card:
            st.metric(player["Player"], f"{player['Weighted rating']:.1f} FP/G", f"{int(player['Games this week'])} games")
            st.caption(f"{player['Positions']} · {player['NBA team']} · {player['Injury status']}")
    available_waivers = waivers[
        ~waivers["Player"].astype(str).str.casefold().isin(pending_names)
    ].copy()
    waiver_columns = [
        "Player", "NBA team", "Positions", "Injury status", "Availability check",
        "Weighted rating", "Projected FP/G", "FP/G last 14", "Games this week",
        "Minutes trend", "Opportunity flag", "Recent news",
    ]
    waiver_columns = [column for column in waiver_columns if column in available_waivers.columns]
    st.dataframe(
        available_waivers[waiver_columns], hide_index=True, use_container_width=True
    )
    st.caption("Weighted rating favors the last 14 days once games exist; before then it uses the blended ESPN/last-season projection. Availability checks use ESPN's current free-agent/waiver pool, reconciled active claims, injury status, and matched recent news.")
    st.subheader("Top add/drop ideas")
    next_move_pool = waivers[
        ~waivers["Player"].astype(str).str.casefold().isin(pending_names)
    ]
    ideas = add_drop_suggestions(
        next_move_pool, roster_rows, excluded_drop_players=pending_drops
    )
    if ideas:
        st.dataframe(pd.DataFrame(ideas), hide_index=True, use_container_width=True)
    else:
        if pending_claims:
            st.info(
                "Your active claim already uses the best projected drop option. No additional "
                "non-conflicting waiver move currently improves the remaining roster. This is a "
                "hold recommendation—not a missing-data error."
            )
        else:
            st.info(
                "No available waiver player currently projects as an upgrade over an eligible "
                "player on your roster. Hold for now and recheck after new games or injury news."
            )
    st.warning("Waiver claims process on ESPN's schedule. Place a desired claim a day ahead when possible.")
    st.caption("Minutes trend is shown as unavailable until game-level MIN data exists; the app does not guess it.")


@st.cache_data(ttl=150, show_spinner=False)
def calculate_roster_value(cache_scope, team_name, _league, _previous_league, _schedule):
    selected = next(t for t in _league.teams if t.team_name == team_name)
    roster_rows = build_player_rows(
        _league, selected, set(), previous_league=_previous_league
    )
    waivers = rank_waivers(
        _league, _schedule["game_counts"], size=50,
        previous_league=_previous_league,
        injury_pool=injury_pool_from_league(_league),
    )
    try:
        pending = active_waiver_claims(_league, selected.team_id)
    except Exception:
        pending = []
    pending_adds = {
        str(claim.get("Add")).casefold()
        for claim in pending if claim.get("Add")
    }
    if not waivers.empty and pending_adds:
        waivers = waivers[
            ~waivers["Player"].astype(str).str.casefold().isin(pending_adds)
        ]
    board, replacement = roster_value_board(roster_rows, waivers)
    return board, replacement, pending


def render_roster_value(league, previous_league, team, schedule):
    hero(
        "Value beyond the name", "Roster Value",
        "Measure what each player contributes above the strongest healthy waiver replacement at the same position.",
    )
    updated_caption()
    if not schedule:
        st.error("NBA schedule data is unavailable, so waiver replacement levels cannot be calculated.")
        return
    with st.spinner("Comparing every roster spot with the waiver market..."):
        board, replacement, pending = calculate_roster_value(
            CACHE_SCOPE, team.team_name, league, previous_league, schedule
        )
    if board.empty:
        st.info("ESPN did not return enough roster data for a value audit.")
        return
    foundations = int((board["Value tier"] == "Foundation").sum())
    starters = int((board["Value tier"] == "Strong starter").sum())
    replaceable = int((board["Value tier"] == "Below replacement").sum())
    known = board["VORP"].dropna()
    average = float(known.mean()) if not known.empty else 0.0
    st.markdown(
        '<div class="value-strip">'
        f'<div class="value-tile good"><div class="value-tile-number">{foundations}</div><div class="value-tile-label">Foundation players</div></div>'
        f'<div class="value-tile"><div class="value-tile-number">{starters}</div><div class="value-tile-label">Strong starters</div></div>'
        f'<div class="value-tile warn"><div class="value-tile-number">{replaceable}</div><div class="value-tile-label">Below replacement</div></div>'
        f'<div class="value-tile"><div class="value-tile-number">{average:+.1f}</div><div class="value-tile-label">Average roster VORP</div></div>'
        '</div>',
        unsafe_allow_html=True,
    )
    if pending:
        st.info("Players in active waiver claims are excluded from the replacement baseline so the comparison reflects your next available option.")
    st.subheader("Roster value ladder")
    st.dataframe(board, hide_index=True, use_container_width=True)
    st.caption("VORP = the player's custom projected/recent FP/G minus the strongest healthy available alternative at an eligible position. Positive is better.")
    with st.expander("See replacement level by position"):
        st.dataframe(replacement, hide_index=True, use_container_width=True)
        st.caption("Replacement level changes whenever waivers, injuries, roles, or active claims change.")


@st.cache_data(ttl=3600, show_spinner=False)
def calculate_playoff_plan(cache_scope, team_name, _league, _previous_league):
    schedules = load_season_schedules()
    current_period = int(getattr(_league, "currentMatchupPeriod", 1) or 1)
    regular_periods = getattr(getattr(_league, "settings", None), "reg_season_count", None)
    assumption = False
    if regular_periods is None:
        # Only used when the unofficial ESPN library omits the setting.
        offset = max(0, len(schedules) - 4)
        assumption = True
    else:
        offset = max(0, int(regular_periods) + 1 - current_period)
    playoff_weeks = schedules[offset:offset + 4]
    if len(playoff_weeks) < 4 and len(schedules) >= 4:
        playoff_weeks = schedules[-4:]
        assumption = True
    grades = playoff_schedule_grades(playoff_weeks)
    selected = next(t for t in _league.teams if t.team_name == team_name)
    roster_rows = build_player_rows(
        _league, selected, set(), previous_league=_previous_league
    )
    if not playoff_weeks:
        return playoff_weeks, grades, pd.DataFrame(), pd.DataFrame(), assumption
    waivers = rank_waivers(
        _league, playoff_weeks[0]["game_counts"], size=50,
        previous_league=_previous_league,
        injury_pool=injury_pool_from_league(_league),
    )
    try:
        pending = active_waiver_claims(_league, selected.team_id)
    except Exception:
        pending = []
    pending_adds = {
        str(claim.get("Add")).casefold()
        for claim in pending if claim.get("Add")
    }
    if not waivers.empty and pending_adds:
        waivers = waivers[
            ~waivers["Player"].astype(str).str.casefold().isin(pending_adds)
        ]
    roster_board, waiver_board = playoff_player_values(
        roster_rows, waivers, grades
    )
    return playoff_weeks, grades, roster_board, waiver_board, assumption


def render_playoff_planner(league, previous_league, team):
    hero(
        "Build for the games that decide the season", "Playoff Planner",
        "Grade schedules for both two-week playoff rounds and identify players whose championship value differs from their regular-season value.",
    )
    updated_caption()
    with st.spinner("Mapping the NBA schedule onto your fantasy playoffs..."):
        weeks, grades, roster_board, waiver_board, assumption = calculate_playoff_plan(
            CACHE_SCOPE, team.team_name, league, previous_league
        )
    if len(weeks) < 4 or grades.empty:
        st.warning("Four complete NBA schedule weeks were not available for the projected playoff window.")
        return
    round_one_dates = f"{weeks[0]['start_date']:%b %d}–{weeks[1]['end_date']:%b %d, %Y}"
    final_dates = f"{weeks[2]['start_date']:%b %d}–{weeks[3]['end_date']:%b %d, %Y}"
    st.markdown(
        '<div class="playoff-window">'
        f'<div class="round-card"><div class="round-label">Semifinal · two weeks</div><div class="round-dates">{round_one_dates}</div><div class="round-note">First four-team playoff matchup</div></div>'
        f'<div class="round-card final"><div class="round-label">Championship · two weeks</div><div class="round-dates">{final_dates}</div><div class="round-note">Weighted slightly more heavily in schedule grades</div></div>'
        '</div>',
        unsafe_allow_html=True,
    )
    if assumption:
        st.warning("ESPN did not expose a complete playoff-period mapping, so the final four available NBA schedule weeks are shown as an explicit fallback assumption.")
    leaders = grades.head(5)
    st.subheader("Best NBA playoff schedules")
    st.dataframe(leaders, hide_index=True, use_container_width=True)
    if not roster_board.empty:
        st.subheader("Your roster's playoff value")
        st.dataframe(roster_board, hide_index=True, use_container_width=True)
        difficult = roster_board[roster_board["Schedule tier"] == "Difficult"]
        if not difficult.empty:
            st.warning(
                f"Schedule risk: {', '.join(difficult['Player'].head(4))} project into difficult playoff volume. Do not drop them automatically; use this as a trade and depth-planning signal."
            )
    if not waiver_board.empty:
        st.subheader("Early playoff waiver targets")
        st.dataframe(waiver_board.head(12), hide_index=True, use_container_width=True)
    st.caption("Projected playoff points = current custom FP/G rating × scheduled games. It does not assume health, unchanged roles, or that every game will fit a legal lineup slot months in advance.")


def render_my_moves(league, team):
    hero("Your ESPN transaction center", "My Moves", "See pending waiver claims and recent results directly from ESPN. This page is read-only and cannot submit, reorder, or cancel a claim.")
    updated_caption()
    waiver_rank = getattr(team, "waiver_rank", None)
    acquisitions = getattr(team, "acquisitions", None)
    first, second, third = st.columns(3)
    first.metric("Active team", team.team_name)
    second.metric("Waiver priority", "Not supplied" if waiver_rank is None else f"#{waiver_rank}")
    third.metric("Season acquisitions", "Not supplied" if acquisitions is None else acquisitions)
    try:
        active, recent = waiver_activity(league, team.team_id)
    except Exception as error:
        st.warning("ESPN did not return waiver activity. Your claims are unchanged; check the ESPN app for confirmation.")
        st.caption(f"Technical error type: {type(error).__name__}")
        return
    active_tab, recent_tab = st.tabs([f"Active claims ({len(active)})", "Recent results"])
    with active_tab:
        if active:
            st.dataframe(pd.DataFrame(active), hide_index=True, use_container_width=True)
            st.info("Claims are listed as ESPN returned them. Use the ESPN app to change their order or cancel one.")
        else:
            st.success("ESPN reports no active waiver claims for this team.")
    with recent_tab:
        if recent:
            st.dataframe(pd.DataFrame(recent), hide_index=True, use_container_width=True)
        else:
            st.info("ESPN returned no recent waiver results for this scoring period.")
    st.caption("This page refreshes with the site every 2.5 minutes. ESPN remains the final authority if a claim is close to processing time.")


def render_move_simulator(league, previous_league, team):
    hero("Decision laboratory", "Move Simulator", "Test an add/drop before placing it. Results use your custom scoring, legal daily lineup slots, schedule congestion, and rest-of-season projections.")
    updated_caption()
    schedules = load_upcoming_schedules()
    if not schedules:
        st.error("NBA schedule data is unavailable, so a responsible simulation cannot be run.")
        return
    base_rows = build_player_rows(
        league, team, set(), previous_league=previous_league
    )
    with st.spinner("Loading current waiver options..."):
        waivers = rank_waivers(
            league, schedules[0]["game_counts"], size=75,
            previous_league=previous_league,
            injury_pool=injury_pool_from_league(league),
        )
    healthy = waivers[
        (~waivers["Injury status"].apply(is_unavailable_status))
        & (waivers["Weighted rating"].notna())
    ]
    if not base_rows or healthy.empty:
        st.info("A roster and at least one rated healthy waiver player are required.")
        return
    left, right = st.columns(2)
    with left:
        add_name = st.selectbox("Player to add", healthy["Player"].tolist())
    with right:
        drop_name = st.selectbox(
            "Player to drop",
            [row["Player"] for row in sorted(
                base_rows,
                key=lambda row: row["Advice score"] if row["Advice score"] is not None else -1,
            )],
        )
    selected = healthy[healthy["Player"] == add_name].iloc[0]
    add_row = {
        "Player": selected["Player"],
        "NBA team": selected["NBA team"],
        "Positions": selected["Positions"],
        "Eligible": str(selected["Positions"]).split("/"),
        "Injury status": selected["Injury status"],
        "Advice score": selected["Weighted rating"],
        "Projected FP/G": selected["Projected FP/G"],
        "FP last 7": None,
        "FP last 14": selected["FP/G last 14"],
        "FP last 30": None,
    }
    weekly, season_delta, position_counts, warnings = simulate_add_drop(
        base_rows, add_row, drop_name, schedules
    )
    horizons = horizon_totals(weekly)
    st.subheader("Decision summary")
    cards = st.columns(4)
    for card, (_, result) in zip(cards[:3], horizons.iterrows()):
        card.metric(
            result["Horizon"], f"{result['After move']:.1f}",
            f"{result['Projected change']:+.1f} points",
        )
    cards[3].metric(
        "Season FP/G change",
        "Unknown" if season_delta is None else f"{season_delta:+.1f}",
    )
    if warnings:
        for warning in warnings:
            st.error(warning)
    elif float(horizons.iloc[0]["Projected change"]) > 0 and (season_delta is None or season_delta >= 0):
        st.success("This move improves the immediate projection without an obvious rest-of-season sacrifice.")
    elif float(horizons.iloc[0]["Projected change"]) > 0:
        st.warning("This is a short-term streaming gain but may reduce rest-of-season value.")
    else:
        st.info("This move does not improve the current one-week legal-lineup projection.")
    st.dataframe(horizons, hide_index=True, use_container_width=True)
    st.subheader("Week-by-week effect")
    st.dataframe(weekly, hide_index=True, use_container_width=True)
    st.subheader("Roster coverage after move")
    st.dataframe(
        pd.DataFrame([position_counts]), hide_index=True, use_container_width=True
    )
    if st.button("Save this scenario", key="save_move_scenario"):
        decision_id = save_move_decision(
            team.team_name, add_name, drop_name, horizons, season_delta
        )
        st.success(f"Scenario #{decision_id} was saved to the Decision Tracker.")
    st.caption("This is a counterfactual planning tool. It never submits a transaction to ESPN.")


def render_decision_tracker(team):
    hero("Accountable advice", "Decision Tracker", "Remember every saved move, record whether you followed it, and build the evidence needed for accuracy and regret analysis.")
    updated_caption()
    decisions = move_decision_history(team.team_name)
    if not decisions:
        st.info("No decisions have been saved yet. Open Move Simulator and save a scenario first.")
        return
    frame = pd.DataFrame(decisions)
    first, second, third = st.columns(3)
    first.metric("Saved scenarios", len(frame))
    second.metric("Followed", int((frame["status"] == "Followed").sum()))
    third.metric("Pending review", int((frame["status"] == "Pending").sum()))
    labels = {
        str(row["id"]): f"{str(row['id'])[:8]} · Add {row['add_player']} / Drop {row['drop_player']}"
        for _, row in frame.iterrows()
    }
    selected_id = st.selectbox(
        "Review a saved decision", list(labels), format_func=labels.get
    )
    selected = frame[frame["id"].astype(str) == selected_id].iloc[0]
    status_options = ["Pending", "Followed", "Skipped"]
    current_index = status_options.index(selected["status"]) if selected["status"] in status_options else 0
    status = st.radio("What did you do?", status_options, index=current_index, horizontal=True)
    notes = st.text_area(
        "Notes", value=str(selected.get("notes") or ""),
        placeholder="Why did you follow or skip this move?",
    )
    if st.button("Update decision", key="update_move_decision"):
        update_move_decision(selected_id, team.team_name, status, notes)
        st.success("Decision updated locally.")
        st.rerun()
    shown_columns = [
        "id", "saved_at", "add_player", "drop_player", "one_week_change",
        "two_week_change", "four_week_change", "season_fppg_change", "status", "notes",
    ]
    st.subheader("Decision history")
    st.dataframe(frame[shown_columns], hide_index=True, use_container_width=True)
    st.caption("Later phases will compare followed decisions with actual results and calculate projection error and regret.")


def render_accuracy_lab(team):
    hero(
        "Measure the model, not just the matchup", "Projection Accuracy Lab",
        "Compare predictions saved before each matchup with archived final results, reveal systematic bias, and let confidence grow only when evidence grows.",
    )
    updated_caption()
    forecasts = forecast_history(ESPN_SEASON_YEAR, team.team_name)
    results = weekly_result_history(ESPN_SEASON_YEAR, team.team_name)
    frame, summary = projection_accuracy_lab(forecasts, results)
    if frame.empty:
        st.info("No completed matchup has both a saved pre-matchup forecast and an archived final result yet. The site is now recording both automatically.")
        return
    st.markdown(
        '<div class="accuracy-grid">'
        f'<div class="accuracy-card"><div class="accuracy-number">{summary["weeks"]}</div><div class="accuracy-label">Completed samples</div></div>'
        f'<div class="accuracy-card"><div class="accuracy-number">±{summary["score_mae"]:.1f}</div><div class="accuracy-label">Score MAE</div></div>'
        f'<div class="accuracy-card"><div class="accuracy-number">±{summary["margin_mae"]:.1f}</div><div class="accuracy-label">Margin MAE</div></div>'
        f'<div class="accuracy-card"><div class="accuracy-number">{summary["winner_accuracy"]}%</div><div class="accuracy-label">Winner accuracy</div></div>'
        f'<div class="accuracy-card"><div class="accuracy-number">{summary["confidence"]}</div><div class="accuracy-label">Evidence level</div></div>'
        '</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="accuracy-diagnosis"><b>Current diagnosis:</b> {html.escape(summary["diagnosis"])} '
        f'Average probability error (Brier score): {summary["brier"]:.3f}. Lower is better.</div>',
        unsafe_allow_html=True,
    )
    st.subheader("Week-by-week audit")
    st.dataframe(frame, hide_index=True, use_container_width=True)
    chart = frame.set_index("Week")[["Score error", "Margin error"]]
    st.subheader("Error trend")
    st.line_chart(chart)
    st.caption("Score error = actual minus projected. Positive means the model projected too low. The evidence label remains cautious until several completed matchups exist.")


@st.cache_data(ttl=150, show_spinner=False)
def calculate_streaming_plan(cache_scope, team_name, _league, _previous_league):
    """Build the expensive planner once per team during each refresh window."""
    schedules = load_upcoming_schedules()
    if len(schedules) < 2:
        return schedules, [], pd.DataFrame(), {"waivers": 0, "rated": 0, "eligible": 0, "drops": 0}
    team = next(team for team in _league.teams if team.team_name == team_name)
    base_rows = build_player_rows(
        _league, team, set(), previous_league=_previous_league
    )
    try:
        pending_claims = active_waiver_claims(_league, team.team_id)
    except Exception:
        pending_claims = []
    pending_adds = {
        str(claim["Add"]).casefold() for claim in pending_claims if claim.get("Add")
    }
    protected_drops = {
        str(claim["Drop"]) for claim in pending_claims if claim.get("Drop")
    }
    waivers = rank_waivers(
        _league, schedules[0]["game_counts"], size=40,
        previous_league=_previous_league,
        injury_pool=injury_pool_from_league(_league),
    )
    if waivers.empty:
        return schedules, pending_claims, pd.DataFrame(), {
            "waivers": 0, "rated": 0, "eligible": 0,
            "drops": max(0, len(base_rows) - len(protected_drops)),
        }
    # At the beginning of a season, ESPN sometimes omits the recent-form
    # field even though a season projection is available. Never discard that
    # player merely because the preferred rating column is temporarily blank.
    waivers = waivers.copy()
    waivers["Planner rating"] = waivers["Weighted rating"]
    for fallback_column in ["Projected FP/G", "Season FP/G", "FP/G last 14"]:
        waivers["Planner rating"] = waivers["Planner rating"].fillna(
            waivers[fallback_column]
        )
    healthy_mask = ~waivers["Injury status"].apply(is_unavailable_status)
    rated_mask = waivers["Planner rating"].notna()
    available_mask = ~waivers["Player"].astype(str).str.casefold().isin(pending_adds)
    candidates = waivers[
        healthy_mask & rated_mask & available_mask
    ].head(20)
    waiver_rows = [{
        "Player": row["Player"], "NBA team": row["NBA team"],
        "Eligible": str(row["Positions"]).split("/"),
        "Injury status": row["Injury status"],
        "Advice score": row["Planner rating"],
        "Projected FP/G": row["Projected FP/G"],
        "FP last 7": None, "FP last 14": row["FP/G last 14"],
        "FP last 30": None,
    } for _, row in candidates.iterrows()]
    moves = rank_streaming_moves(
        base_rows, waiver_rows, schedules,
        protected_drops=protected_drops,
    )
    diagnostics = {
        "waivers": len(waivers),
        "rated": int((healthy_mask & rated_mask).sum()),
        "eligible": len(candidates),
        "drops": len([
            row for row in base_rows
            if str(row["Player"]).casefold()
            not in {name.casefold() for name in protected_drops}
        ]),
    }
    return schedules, pending_claims, moves, diagnostics


def render_streaming_planner(league, previous_league, team):
    hero("Plan multiple moves ahead", "Streaming Planner", "Find waiver sequences that create usable lineup games—not merely players with the largest raw schedule.")
    updated_caption()
    with st.spinner("Testing legal-lineup combinations..."):
        schedules, pending_claims, moves, diagnostics = calculate_streaming_plan(
            CACHE_SCOPE, team.team_name, league, previous_league
        )
    if len(schedules) < 2:
        st.error("At least two NBA schedule weeks are required for sequence planning.")
        return
    if pending_claims:
        st.info("Players already being added are excluded, and players already scheduled to be dropped are protected.")
    if moves.empty:
        st.warning(
            "The planner could not build a comparison from the current ESPN data. "
            f"It found {diagnostics['waivers']} free agents, "
            f"{diagnostics['rated']} healthy players with projections, "
            f"{diagnostics['eligible']} available candidates, and "
            f"{diagnostics['drops']} possible roster drops."
        )
        return
    positive = moves[moves["2-week gain"] > 0].copy()
    if positive.empty:
        st.info("No tested move improves the next two weeks. Holding the roster is the preferred sequence.")
        st.dataframe(moves.head(10), hide_index=True, use_container_width=True)
        return
    best_first = positive.sort_values("Week 1 gain", ascending=False).iloc[0]
    second_options = positive[
        (positive["Add"] != best_first["Add"])
        & (positive["Drop"] == best_first["Drop"])
    ].sort_values("Week 2 gain", ascending=False)
    first, second = st.columns(2)
    with first:
        st.markdown("### Move 1 · This week")
        st.success(
            f"Add {best_first['Add']} and drop {best_first['Drop']}. "
            f"Projected week-one gain: {best_first['Week 1 gain']:+.1f} points."
        )
    with second:
        st.markdown("### Move 2 · Reassess next week")
        if second_options.empty or float(second_options.iloc[0]["Week 2 gain"]) <= 0:
            st.info("No planned second move currently beats holding Move 1. Recalculate after this week's games.")
        else:
            pivot = second_options.iloc[0]
            st.success(
                f"If still available, replace {best_first['Add']} with {pivot['Add']}. "
                f"Projected week-two gain versus the original roster: {pivot['Week 2 gain']:+.1f} points."
            )
    st.subheader("Best tested combinations")
    st.dataframe(positive.head(15), hide_index=True, use_container_width=True)
    st.warning("This is a planning sequence, not an instruction to churn automatically. Recheck injuries, claim processing, and availability before each move.")


def render_transaction_portfolio(league, previous_league, team):
    hero(
        "Plan for claims that fail", "Transaction Portfolio",
        "Organize active claims, the best next move, a direct fallback, and an independent roster pivot without recommending the same solution twice.",
    )
    updated_caption()
    with st.spinner("Building a non-conflicting waiver plan..."):
        schedules, pending_claims, moves, diagnostics = calculate_streaming_plan(
            CACHE_SCOPE, team.team_name, league, previous_league
        )
        portfolio = transaction_portfolio(moves, pending_claims)
    if pending_claims:
        st.subheader("Already in progress")
        st.dataframe(
            pd.DataFrame(pending_claims).rename(columns={
                "Add": "Pending add", "Drop": "Pending drop",
            }),
            hide_index=True, use_container_width=True,
        )
        st.caption("These claims are treated as work already underway. Their adds are excluded and their drops are protected from the next recommendations.")
    if portfolio.empty:
        st.info(
            "No additional positive two-week transaction is available after accounting for active claims. Holding is the current portfolio decision."
        )
        return
    cards = []
    classes = {"Primary": "primary", "Fallback": "fallback", "Independent pivot": "pivot"}
    for _, move in portfolio.iterrows():
        cards.append(
            f'<div class="portfolio-card {classes.get(move["Role"], "")}">'
            f'<div class="portfolio-role">#{int(move["Priority"])} · {html.escape(str(move["Role"]))}</div>'
            f'<div class="portfolio-move">Add {html.escape(str(move["Add"]))}<br>Drop {html.escape(str(move["Drop"]))}</div>'
            f'<div class="portfolio-gain">{float(move["2-week gain"]):+.1f} pts</div>'
            f'<div class="portfolio-trigger">{html.escape(str(move["Trigger"]))}</div></div>'
        )
    st.markdown(
        f'<div class="portfolio-flow">{"".join(cards)}</div>',
        unsafe_allow_html=True,
    )
    st.subheader("Priority and contingency table")
    st.dataframe(portfolio, hide_index=True, use_container_width=True)
    st.warning("Enter and prioritize claims yourself on ESPN. The app reads transactions but cannot submit, cancel, or reorder them.")


def trade_ideas(summaries, my_name, my_strength, my_weakness):
    if "Unknown" in {my_strength, my_weakness}:
        return []
    ideas = []
    for summary in summaries:
        if "Unknown" not in {summary["Weakest"], summary["Strongest"]} and summary["Team"] != my_name and summary["Weakest"] == my_strength and summary["Strongest"] == my_weakness:
            ideas.append(f"Talk with {summary['Team']}: offer depth at {my_strength} for help at {my_weakness}.")
        if len(ideas) == 3:
            break
    return ideas


def render_league(league, previous_league, team, matchup, schedule):
    st.title("League scouting & trades")
    updated_caption()
    if not schedule:
        st.error("Schedule data is unavailable; scouting totals may be incomplete.")
        return
    summaries, rows_by_team = [], {}
    with st.spinner("Scouting all ten teams with custom scoring..."):
        active_period = int(getattr(league, "currentMatchupPeriod", 1) or 1)
        power, _, shared_rows = calculate_league_intelligence(
            CACHE_SCOPE, active_period, league, previous_league
        )
        save_power_snapshot(active_period, power)
        power_by_team = power.set_index("Team").to_dict("index")
        for fantasy_team in league.teams:
            rows = shared_rows.get(fantasy_team.team_id, [])
            rows_by_team[fantasy_team.team_name] = rows
            scores = [row["Advice score"] for row in rows if row["Advice score"] is not None]
            strongest, weakest = team_strengths(rows)
            intelligence = power_by_team.get(fantasy_team.team_name, {})
            summaries.append({"Team": fantasy_team.team_name, "Record": intelligence.get("Record", "0-0-0"), "Points/week": intelligence.get("Points/week"), "Power rank": intelligence.get("Rank"), "Power movement": intelligence.get("Movement", "—"), "Roster custom FP/G": None if not scores else round(sum(scores), 1), "Strongest": strongest, "Weakest": weakest})
    st.dataframe(pd.DataFrame(summaries), hide_index=True, use_container_width=True)
    opponent = opponent_for(matchup, team)
    if opponent:
        st.subheader(f"Next opponent: {opponent.team_name}")
        opponent_rows = rows_by_team.get(opponent.team_name, [])
        injuries = [r["Player"] for r in opponent_rows if r["Injury status"].upper() not in {"ACTIVE", "NORMAL", ""}]
        st.write("Injury flags: " + (", ".join(injuries) if injuries else "None returned by ESPN."))
        projection, _, missing = project_team_for_week(league, opponent, schedule["game_counts"], previous_league)
        total, _ = _lineup_total(weekly_lineup_plan(league, opponent, schedule, previous_league))
        st.dataframe(projection, hide_index=True, use_container_width=True)
        st.metric("Opponent projected total", "N/A" if total is None else f"{total:.1f}")
        if missing:
            st.warning("Opponent projection is incomplete.")
    my_strength, my_weakness = team_strengths(rows_by_team.get(team.team_name, []))
    st.subheader("Trade ideas")
    ideas = trade_ideas(summaries, team.team_name, my_strength, my_weakness)
    if ideas:
        for idea in ideas:
            st.write(f"- {idea}")
    else:
        st.info("Not enough positional data exists for responsible trade ideas yet.")
    st.caption("Trade ideas identify complementary team needs; you make every offer manually on ESPN.")


def render_news(league, previous_league, team, matchup, schedule):
    st.title("News & injuries")
    updated_caption()
    names = [p.name for p in team.roster]
    opponent = opponent_for(matchup, team)
    if opponent:
        names.extend(p.name for p in opponent.roster)
    try:
        if schedule:
            injury_pool = injury_pool_from_league(league)
            waivers = rank_waivers(league, schedule["game_counts"], size=20, previous_league=previous_league, injury_pool=injury_pool)
            names.extend(waivers["Player"].tolist())
        items, fetched_at = load_news()
        relevant = filter_relevant_news(items, names)
    except Exception as error:
        st.error(f"News could not be loaded. Error type: {type(error).__name__}")
        return
    st.caption(f"Feed fetched: {fetched_at:%b %d, %Y at %H:%M UTC}")
    if schedule and 'waivers' in locals():
        opportunities = waivers[
            (waivers["Opportunity flag"].astype(str).str.len() > 0)
            & (~waivers["Injury status"].apply(is_unavailable_status))
        ][["Player", "NBA team", "Positions", "Injury status", "Opportunity flag"]]
        st.subheader("Injury opportunity watch")
        if opportunities.empty:
            st.info("No healthy top waiver target currently has a known injured, position-competing teammate in ESPN's league data.")
        else:
            st.dataframe(opportunities, hide_index=True, use_container_width=True)
    if not relevant:
        st.info("No recent feed items matched your roster, opponent, or top waiver targets.")
    else:
        for item in relevant:
            st.markdown(f"### [{item['title']}]({item['link']})")
            st.write(f"Players matched: {', '.join(item['players'])}")
            st.write(item["impact"])
            st.caption(item["published"])
    st.warning("RSS headlines can be incomplete. Confirm unclear injury status before changing a lineup.")


def render_strategy(league, previous_league, team):
    hero("Championship planning", "Strategy Board", "A living plan for today, the next four weeks, and the full season. Projections never replace a final injury check.")
    updated_caption()
    with st.spinner("Building league strategy and four-week forecasts..."):
        active_period = int(getattr(league, "currentMatchupPeriod", 1) or 1)
        power, history, team_rows = calculate_league_intelligence(
            CACHE_SCOPE, active_period, league, previous_league
        )
        save_power_snapshot(active_period, power)
        schedules = load_upcoming_schedules()
        forecasts, details = matchup_forecasts(league, team, schedules, previous_league, team_rows)
        saved_before = forecast_history(ESPN_SEASON_YEAR, team.team_name)
        _, prior_accuracy = projection_accuracy(league, team, saved_before)
        current_schedule = schedules[0] if schedules else load_schedule()
        try:
            pending_claims = active_waiver_claims(league, team.team_id)
        except Exception:
            pending_claims = []
        weaknesses, waiver_fixes, trade_fixes, applied_claims, long_term_fixes = quantified_strategy_moves(
            league, team, power, team_rows, current_schedule["game_counts"],
            previous_league, pending_claims=pending_claims,
        )
    mine = power[power["Team"] == team.team_name]
    if not mine.empty:
        row = mine.iloc[0]
        a, b, c, d = st.columns(4)
        a.metric("League power rank", f"#{int(row['Rank'])}", row["Movement"])
        b.metric("Power score", f"{row['Power score']:.1f}")
        c.metric("Strongest position", row["Strongest"])
        d.metric("Biggest need", row["Weakest"])
        st.subheader("Your team assessment")
        st.success(row["Plain-English assessment"])
        with st.expander("Technical explanation"):
            st.write(row["Technical analysis"])
    st.subheader("Weak-spot repair plan")
    if not applied_claims.empty:
        st.info("Strategy has been recalculated as if the highest-priority non-conflicting active claims below succeed. Recommendations now address the next remaining weakness.")
        st.dataframe(applied_claims, hide_index=True, use_container_width=True)
    elif pending_claims:
        st.warning("ESPN showed active claims, but their players could not be matched to the current waiver pool. Strategy remains based on your current roster.")
    st.markdown('<span class="section-chip">MEASURED AGAINST ALL 10 TEAMS</span>', unsafe_allow_html=True)
    st.dataframe(weaknesses, hide_index=True, use_container_width=True)
    focus = weaknesses.iloc[0]
    st.info(
        f"Short-term priority: raise {focus['Position']} from {focus['Short-term FP/G']:.1f} to at least "
        f"the {focus['League average']:.1f} league average—a {abs(min(0, focus['Short-term gap'])):.1f} FP/G gap."
    )
    left, right = st.columns(2)
    with left:
        st.subheader("Best waiver fixes")
        if waiver_fixes.empty:
            st.info("No available player currently produces a measurable upgrade. Hold your roster and keep monitoring.")
        else:
            st.dataframe(waiver_fixes, hide_index=True, use_container_width=True)
            best = waiver_fixes.iloc[0]
            st.success(
                f"Best immediate move: add {best['Add']} for {best['Drop']}. Estimated change: "
                f"{best['FP/G gain']:+.1f} FP/G and {best['This-week gain']:+.1f} points this week."
            )
    with right:
        st.subheader("Trade targets")
        if trade_fixes.empty:
            st.info("No fair one-for-one trade creates a positive measurable gain right now. Avoid forcing a trade.")
        else:
            st.dataframe(trade_fixes, hide_index=True, use_container_width=True)
            best_trade = trade_fixes.iloc[0]
            st.success(
                f"Best trade fit: offer {best_trade['Offer']} for {best_trade['Target']}. "
                f"Estimated net starter improvement: {best_trade['Estimated net starter gain']:+.1f} FP/G."
            )
    st.subheader("Strategy by horizon")
    one_week_tab, two_week_tab, four_week_tab, season_tab = st.tabs(
        ["1 week", "2 weeks", "4 weeks", "Season"]
    )

    def forecast_window(count):
        window = forecasts.head(count).copy() if not forecasts.empty else pd.DataFrame()
        if window.empty:
            return None
        probabilities = window["Win probability"].astype(str).str.rstrip("%").astype(float)
        hardest_index = probabilities.idxmin()
        return {
            "weeks": len(window),
            "average_chance": probabilities.mean(),
            "favored": int((probabilities >= 50).sum()),
            "hardest_opponent": window.loc[hardest_index, "Opponent"],
            "hardest_chance": probabilities.loc[hardest_index],
            "average_margin": window["Projected margin"].astype(float).mean(),
        }

    with one_week_tab:
        one_week = forecast_window(1)
        if one_week:
            a, b, c = st.columns(3)
            a.metric("Current win chance", f"{one_week['average_chance']:.0f}%")
            b.metric("Projected margin", f"{one_week['average_margin']:+.1f}")
            c.metric("Opponent", one_week["hardest_opponent"])
        if not waiver_fixes.empty:
            immediate = waiver_fixes.iloc[0]
            st.success(
                f"Best 1-week action: claim {immediate['Add']} for {immediate['Drop']}. "
                f"Estimated current-week change: {immediate['This-week gain']:+.1f} points."
            )
        else:
            st.info("No measurable one-week waiver upgrade is available. Protect active games and avoid a low-value churn move.")
        short_view = weaknesses[["Position", "Short-term FP/G", "League average", "Short-term gap", "Short-term status", "League rank"]]
        st.dataframe(short_view, hide_index=True, use_container_width=True)
        st.caption("This view reacts to the current opponent, games this week, recent player form, injuries, and pending claims.")

    with two_week_tab:
        two_week = forecast_window(2)
        if two_week:
            a, b, c = st.columns(3)
            a.metric("Average win chance", f"{two_week['average_chance']:.0f}%")
            b.metric("Favored matchups", f"{two_week['favored']}/{two_week['weeks']}")
            c.metric("Hardest opponent", two_week["hardest_opponent"], f"{two_week['hardest_chance']:.0f}% win chance")
        remaining = weaknesses[weaknesses["Short-term status"] == "Still weak"].head(2)
        if remaining.empty:
            st.success("Pending moves project to cover every major short-term positional gap. Preserve flexibility for injury or schedule changes.")
        else:
            priorities = ", ".join(remaining["Position"].tolist())
            st.info(f"Two-week priority: improve {priorities}. Prefer multi-position players who help across both matchup weeks.")
        if not waiver_fixes.empty:
            st.dataframe(waiver_fixes.head(3), hide_index=True, use_container_width=True)
        st.caption("This view recalculates as the next two opponents, player form, and claim results change.")

    with four_week_tab:
        four_week = forecast_window(4)
        if four_week:
            a, b, c = st.columns(3)
            a.metric("Average win chance", f"{four_week['average_chance']:.0f}%")
            b.metric("Favored matchups", f"{four_week['favored']}/{four_week['weeks']}")
            c.metric("Hardest opponent", four_week["hardest_opponent"], f"{four_week['hardest_chance']:.0f}% win chance")
            if four_week["favored"] < max(2, four_week["weeks"] / 2):
                st.warning("The four-week outlook is below break-even. Prioritize a meaningful starter upgrade instead of a small bench improvement.")
            else:
                st.success("The four-week outlook is at or above break-even. Keep depth and avoid overpaying for a marginal upgrade.")
        if not trade_fixes.empty:
            st.markdown("**Best multi-week trade options**")
            st.dataframe(trade_fixes.head(3), hide_index=True, use_container_width=True)
        st.caption("This view responds to all four scheduled opponents, projected margins, power-rank movement, and completed results.")

    with season_tab:
        long_view = weaknesses[["Position", "Long-term FP/G", "Long-term gap", "Long-term status", "Weakest current option"]].sort_values("Long-term gap")
        st.dataframe(long_view, hide_index=True, use_container_width=True)
        if long_term_fixes.empty:
            st.info("No waiver player currently projects as a measurable rest-of-season upgrade.")
        else:
            try:
                news_items, _ = load_news()
                target_news = filter_relevant_news(news_items, long_term_fixes["Target"].tolist())
                headlines = {}
                for item in target_news:
                    for player_name in item["players"]:
                        headlines.setdefault(player_name, item["title"])
                long_term_fixes["Return/news evidence"] = long_term_fixes["Target"].map(
                    lambda name: headlines.get(name, "No dated return report found in fetched news")
                )
            except Exception:
                long_term_fixes["Return/news evidence"] = "News unavailable—return date unknown"
            st.dataframe(long_term_fixes, hide_index=True, use_container_width=True)
            st.caption("An injured player is a watch/stash candidate, not an immediate add. Never assume a return month unless the fetched news states it.")
        if not mine.empty:
            season_row = mine.iloc[0]
            st.info(
                f"Season position: #{int(season_row['Rank'])} in power rating ({season_row['Tier']}). "
                f"Long-term priority remains the position with the largest negative rest-of-season gap."
            )
        st.caption("As the season develops, completed wins, losses, scoring margins, opponent quality, injuries, and projection accuracy receive updated weight.")
    st.subheader("Championship action plan")
    st.dataframe(pd.DataFrame(strategy_plan(power, team.team_name)), hide_index=True, use_container_width=True)
    st.subheader("Next four matchups")
    if forecasts.empty:
        st.info("ESPN has not supplied future fantasy matchups yet.")
    else:
        if prior_accuracy["mae"] is not None:
            error = prior_accuracy["mae"]
            forecasts["Expected range"] = forecasts["Your projection"].map(
                lambda value: f"{max(0, value-error):.0f}–{value+error:.0f}"
            )
            forecasts["Accuracy basis"] = f"±{error:.1f} points from {prior_accuracy['weeks']} completed forecast(s)"
        else:
            forecasts["Expected range"] = "Provisional"
            forecasts["Accuracy basis"] = "No completed forecast history yet"
        for _, forecast in forecasts.iterrows():
            probability = float(str(forecast["Win probability"]).strip("%"))
            probability = max(0.0, min(100.0, probability))
            dates_label = html.escape(str(forecast["Dates"]))
            confidence_label = html.escape(str(forecast["Confidence"]))
            probability_label = html.escape(str(forecast["Win probability"]))
            range_label = html.escape(str(forecast["Expected range"]))
            st.markdown(
                f'<div class="match-card">'
                f'<div class="match-top"><span>Fantasy week {int(forecast["Fantasy week"])}</span><span>{dates_label} · {confidence_label} confidence</span></div>'
                f'<div class="match-teams">'
                f'<div><div class="match-team">{html.escape(str(team.team_name))}</div><div class="match-score">{forecast["Your projection"]:.1f}</div></div>'
                f'<div class="match-vs">VS</div>'
                f'<div class="match-team right">{html.escape(str(forecast["Opponent"]))}<div class="match-score">{forecast["Opponent projection"]:.1f}</div></div>'
                f'</div><div class="match-bar"><div class="match-fill" style="width:{probability}%"></div></div>'
                f'<div class="match-meta">{probability_label} win chance · {forecast["Projected margin"]:+.1f} projected margin · Range {range_label}</div>'
                f'</div>', unsafe_allow_html=True,
            )
        save_matchup_forecasts(ESPN_SEASON_YEAR, team.team_name, forecasts)
        projected_wins = sum(float(value.strip("%")) >= 50 for value in forecasts["Win probability"])
        st.caption(f"Current forecast: approximately {projected_wins} favored matchup(s) out of {len(forecasts)}. Later weeks have lower confidence.")
    st.subheader("Projection accuracy")
    accuracy_table, accuracy = projection_accuracy(
        league, team, forecast_history(ESPN_SEASON_YEAR, team.team_name)
    )
    if accuracy["weeks"] == 0:
        st.info("Accuracy is provisional. The first comparison appears after a forecasted matchup is completed.")
    else:
        x, y, z = st.columns(3)
        x.metric("Completed forecasts", accuracy["weeks"])
        y.metric("Average score error", f"±{accuracy['mae']:.1f}")
        z.metric("Winner accuracy", f"{accuracy['winner_accuracy']}%")
        st.dataframe(accuracy_table, hide_index=True, use_container_width=True)
        st.caption(f"Average bias: {accuracy['bias']:+.1f} points. Positive means the model has projected too low.")


def render_power_rankings(league, previous_league, team):
    hero("League intelligence", "Power Rankings", "Roster strength meets opponent-adjusted results. Rankings gain more weight from real wins, losses, margins, and opponent quality each week.")
    updated_caption()
    active_period = int(getattr(league, "currentMatchupPeriod", 1) or 1)
    with st.spinner("Ranking every team..."):
        power, calculated_history, team_rows = calculate_league_intelligence(
            CACHE_SCOPE, active_period, league, previous_league
        )
    stored_before = pd.DataFrame(power_snapshot_history())
    save_power_snapshot(active_period, power)
    movement_power = power.copy()
    movement_power["Draft change"] = movement_power["Draft rank"] - movement_power["Rank"]
    prior = stored_before[stored_before["snapshot_week"] < active_period] if not stored_before.empty else pd.DataFrame()
    if not prior.empty:
        prior_week = int(prior["snapshot_week"].max())
        prior_ranks = prior[prior["snapshot_week"] == prior_week].set_index("team_name")["rank"].to_dict()
        movement_power["Previous rank"] = movement_power["Team"].map(prior_ranks)
        movement_power["Weekly change"] = (
            movement_power["Previous rank"] - movement_power["Rank"]
        ).fillna(0).astype(int)
        movement_label = f"Week {prior_week} to Week {active_period}"
    else:
        movement_power["Previous rank"] = movement_power["Draft rank"]
        movement_power["Weekly change"] = movement_power["Draft change"].astype(int)
        movement_label = "Draft baseline to current"
    movement_power["Movement"] = movement_power["Weekly change"].map(
        lambda change: "—" if change == 0 else f"▲ {change}" if change > 0 else f"▼ {abs(change)}"
    )
    power = movement_power.copy()
    risers = movement_power[movement_power["Weekly change"] > 0].nlargest(3, "Weekly change")
    fallers = movement_power[movement_power["Weekly change"] < 0].nsmallest(3, "Weekly change")

    def trend_lines(rows, direction):
        if rows.empty:
            return '<div class="pr-trend-line"><span>No movement yet</span><span>—</span><span>0</span></div>'
        lines = []
        for _, trend in rows.iterrows():
            change = abs(int(trend["Weekly change"]))
            arrow = "▲" if direction == "up" else "▼"
            lines.append(
                f'<div class="pr-trend-line"><span>{html.escape(str(trend["Team"]))}</span>'
                f'<span class="{direction}">{arrow}</span><span>{change}</span></div>'
            )
        return "".join(lines)

    st.markdown(
        f'<div class="section-chip">MOVEMENT BASIS · {html.escape(movement_label.upper())}</div>'
        '<div class="pr-summary-grid">'
        '<div class="pr-trend-card"><div class="pr-trend-title">TRENDING UP</div>'
        + trend_lines(risers, "up") + '</div>'
        '<div class="pr-trend-card down"><div class="pr-trend-title">TRENDING DOWN</div>'
        + trend_lines(fallers, "down") + '</div></div>',
        unsafe_allow_html=True,
    )
    mine = movement_power[movement_power["Team"] == team.team_name].iloc[0]
    mine_direction = "good" if mine["Weekly change"] > 0 else "bad" if mine["Weekly change"] < 0 else ""
    ordinal = lambda value: f"{int(value)}" + ("th" if 10 <= int(value) % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(int(value) % 10, "th"))
    st.markdown(
        '<div class="pr-my-team">'
        f'<div><div class="pr-my-label">My team</div><div class="pr-my-value">{html.escape(team.team_name)}</div></div>'
        f'<div><div class="pr-my-label">Previous</div><div class="pr-my-value">{ordinal(mine["Previous rank"])}</div></div>'
        f'<div><div class="pr-my-label">Current</div><div class="pr-my-value {mine_direction}">{ordinal(mine["Rank"])}</div></div>'
        '</div>', unsafe_allow_html=True,
    )

    # ESPN-style draft-to-current arrow chart. SVG keeps it crisp and makes
    # all ten teams readable without adding another charting dependency.
    chart_width, chart_height = 980, 70 + 48 * len(movement_power)
    left, right = 250, 930
    def rank_x(rank):
        return left + (10 - int(rank)) * (right - left) / 9
    svg = [f'<svg viewBox="0 0 {chart_width} {chart_height}" role="img" aria-label="Draft day versus current power rankings" style="min-width:760px;width:100%;height:auto;font-family:Arial,sans-serif">']
    svg.append('<defs><marker id="up-arrow" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 Z" fill="#47c653"/></marker><marker id="down-arrow" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 Z" fill="#ff7b81"/></marker></defs>')
    for rank in range(10, 0, -1):
        x = rank_x(rank)
        svg.append(f'<line x1="{x:.1f}" y1="42" x2="{x:.1f}" y2="{chart_height-25}" stroke="#333638" stroke-width="1"/><text x="{x:.1f}" y="{chart_height-5}" fill="#dedede" font-size="17" text-anchor="middle">{rank}</text>')
    for index, (_, chart_row) in enumerate(movement_power.iterrows()):
        y = 55 + index * 48
        start, end = rank_x(chart_row["Draft rank"]), rank_x(chart_row["Rank"])
        change = int(chart_row["Draft change"])
        color = "#47c653" if change > 0 else "#ff7b81" if change < 0 else "#a7aaad"
        marker = ' marker-end="url(#up-arrow)"' if change > 0 else ' marker-end="url(#down-arrow)"' if change < 0 else ""
        display_name = str(chart_row["Team"])
        short_name = display_name if len(display_name) <= 21 else display_name[:19] + "…"
        weight = "700" if display_name == team.team_name else "400"
        svg.append(f'<text x="8" y="{y+6}" fill="#f2f2f2" font-size="17" font-weight="{weight}">{html.escape(short_name)}</text>')
        svg.append(f'<line x1="{start:.1f}" y1="{y}" x2="{end:.1f}" y2="{y}" stroke="{color}" stroke-width="2"{marker}/>')
        svg.append(f'<circle cx="{start:.1f}" cy="{y}" r="14" fill="#1b1c1e" stroke="{color}" stroke-width="2"/><text x="{start:.1f}" y="{y+5}" fill="{color}" font-size="13" font-weight="800" text-anchor="middle">{int(chart_row["Draft rank"])}</text>')
        svg.append(f'<circle cx="{end:.1f}" cy="{y}" r="14" fill="{color}"/><text x="{end:.1f}" y="{y+5}" fill="#111" font-size="13" font-weight="900" text-anchor="middle">{int(chart_row["Rank"])}</text>')
    svg.append('</svg>')
    st.markdown(
        '<div class="pr-movement-panel"><div class="pr-movement-heading">Power Rankings</div>'
        '<div class="pr-movement-subtitle">Draft Day vs. Current Rankings</div>'
        + "".join(svg)
        + '<div class="pr-chart-key"><span><span class="pr-key-circle">#</span>Draft Day - Power Ranking</span>'
        '<span><span class="pr-key-circle filled">#</span>Current - Power Ranking</span></div></div>',
        unsafe_allow_html=True,
    )
    teams_by_name = {league_team.team_name: league_team for league_team in league.teams}
    ranking_rows = []
    for _, row in power.iterrows():
        ranked_team = teams_by_name.get(row["Team"])
        raw_logo = (
            getattr(ranked_team, "logo_url", None)
            or getattr(ranked_team, "logo", None)
            or ""
        )
        logo = str(raw_logo) if str(raw_logo).startswith(("https://", "http://")) else ""
        initials = "".join(word[0] for word in str(row["Team"]).split() if word)[:3].upper()
        logo_html = (
            f'<img class="espn-team-logo" src="{html.escape(logo, quote=True)}" alt="">'
            if logo else f'<div class="espn-team-fallback">{html.escape(initials)}</div>'
        )
        movement = str(row["Movement"])
        movement_class = "espn-move-up" if "▲" in movement else "espn-move-down" if "▼" in movement else "espn-move-flat"
        mine = " my-team" if row["Team"] == team.team_name else ""
        team_note = " · YOUR TEAM" if mine else ""
        ranking_rows.append(
            f'<div class="espn-rank-row{mine}">'
            f'<div class="espn-rank-number">{int(row["Rank"])}</div>'
            f'<div class="espn-team-cell">{logo_html}<div><div class="espn-team-name">{html.escape(str(row["Team"]))}</div>'
            f'<div class="espn-team-tier">{html.escape(str(row["Tier"]))}{team_note}</div></div></div>'
            f'<div><div class="espn-rank-stat">{html.escape(str(row["Record"]))}</div><div class="espn-rank-label">Record</div></div>'
            f'<div><div class="espn-rank-stat">{float(row["Power score"]):.1f}</div><div class="espn-rank-label">Power</div></div>'
            f'<div><div class="{movement_class}">{html.escape(movement)}</div><div class="espn-rank-label">Previous</div></div>'
            f'<div class="espn-strength"><b>{html.escape(str(row["Strongest"]))}</b> strength<br>'
            f'{html.escape(str(row["Weakest"]))} need · {int(row["Injury flags"])} injury flag(s)</div>'
            f'</div>'
        )
    st.markdown(
        '<div class="espn-rankings">'
        '<div class="espn-rankings-title"><strong>League Power Rankings</strong><span>Updated weekly</span></div>'
        '<div class="espn-rank-header"><div>Rank</div><div>Team</div><div>Record</div><div>Rating</div><div>Trend</div><div>Team profile</div></div>'
        + "".join(ranking_rows) + '</div>',
        unsafe_allow_html=True,
    )
    st.caption("Early in the season, roster projections carry most of the weight. Each completed week shifts more weight toward opponent-adjusted results.")
    stored = pd.DataFrame(power_snapshot_history())
    if not stored.empty and stored["snapshot_week"].nunique() > 1:
        chart = stored.pivot(index="snapshot_week", columns="team_name", values="rank")
        st.subheader("Ranking movement by week")
        st.line_chart(chart)
        st.caption("Lower is better: rank 1 is the top line position.")
    st.subheader("Every team explained")
    for _, row in power.iterrows():
        label = f"#{int(row['Rank'])} {row['Team']} · {row['Tier']} · {row['Movement']}"
        with st.expander(label, expanded=row["Team"] == team.team_name):
            st.markdown("**Simple assessment**")
            st.write(row["Plain-English assessment"])
            st.markdown("**Technical assessment**")
            st.write(row["Technical analysis"])


@st.cache_data(ttl=150, show_spinner=False)
def calculate_weekly_recap(cache_scope, period, _league):
    try:
        matchups = _league.box_scores(matchup_period=int(period))
    except Exception:
        matchups = _league.scoreboard(matchupPeriod=int(period))
    prior_scores = {}
    for earlier in range(1, int(period)):
        try:
            earlier_matchups = _league.box_scores(matchup_period=earlier)
        except Exception:
            try:
                earlier_matchups = _league.scoreboard(matchupPeriod=earlier)
            except Exception:
                continue
        earlier_frame = weekly_team_recap(earlier_matchups)
        if earlier_frame.empty:
            continue
        for _, row in earlier_frame.iterrows():
            prior_scores.setdefault(row["Team"], []).append(float(row["Score"]))
    teams = weekly_team_recap(matchups, prior_scores)
    completed_schedules = load_completed_schedules()
    regular_periods = int(
        getattr(getattr(_league, "settings", None), "reg_season_count", 18) or 18
    )
    if int(period) <= regular_periods:
        chosen = [
            schedule for schedule in completed_schedules
            if int(schedule["week_number"]) == int(period)
        ]
    else:
        playoff_offset = (int(period) - regular_periods - 1) * 2
        wanted = {regular_periods + 1 + playoff_offset, regular_periods + 2 + playoff_offset}
        chosen = [
            schedule for schedule in completed_schedules
            if int(schedule["week_number"]) in wanted
        ]
    if not chosen and completed_schedules:
        chosen = [completed_schedules[-1]]
    start_date = min((item["start_date"] for item in chosen), default=None)
    end_date = max((item["end_date"] for item in chosen), default=None)
    lineup_players, owner_by_player = [], {}
    for matchup in matchups:
        for side in ["home", "away"]:
            fantasy_team = getattr(matchup, f"{side}_team", None)
            lineup = getattr(matchup, f"{side}_lineup", None) or []
            for player in lineup:
                lineup_players.append(player)
                owner_by_player[player.name] = fantasy_team.team_name if fantasy_team else "Unknown"
    if not lineup_players:
        for fantasy_team in _league.teams:
            for player in fantasy_team.roster:
                lineup_players.append(player)
                owner_by_player[player.name] = fantasy_team.team_name
    details = lineup_players
    player_ids = [
        player.playerId for player in lineup_players
        if getattr(player, "playerId", None) is not None
    ]
    if player_ids:
        try:
            fetched = _league.player_info(playerId=list(dict.fromkeys(player_ids)))
            details = fetched if isinstance(fetched, list) else [fetched]
        except Exception:
            pass
    players = (
        weekly_player_recap(details, start_date, end_date)
        if start_date is not None and end_date is not None
        else pd.DataFrame()
    )
    if not players.empty:
        players.insert(
            1, "Fantasy team",
            players["Player"].map(owner_by_player).fillna("Current/free agent"),
        )
    return teams, players, start_date, end_date


def render_weekly_recap(league, team):
    hero(
        "Learn from what actually happened", "Weekly Recap",
        "Review every team's result, the week's strongest custom-scoring performances, and interpretations that compare each team with the league and its own developing baseline.",
    )
    updated_caption()
    active_period = int(getattr(league, "currentMatchupPeriod", 1) or 1)
    completed_periods = list(range(1, active_period))
    if not completed_periods:
        st.info("The first recap will appear after the opening matchup is completed.")
        return
    selected_period = st.selectbox(
        "Completed fantasy week", completed_periods[::-1],
        format_func=lambda value: f"Week {value}",
    )
    with st.spinner("Reconstructing the completed week..."):
        teams, players, start_date, end_date = calculate_weekly_recap(
            CACHE_SCOPE, selected_period, league
        )
    if teams.empty:
        st.warning("ESPN did not return completed scores for this fantasy week.")
        return
    winner = teams.iloc[0]
    biggest = teams.iloc[teams["Margin"].abs().argmax()]
    top_player = players.iloc[0] if not players.empty else None
    date_text = (
        f"{start_date:%b %d}–{end_date:%b %d, %Y}"
        if start_date and end_date else "Dates unavailable"
    )
    player_name = top_player["Player"] if top_player is not None else "Player data unavailable"
    player_detail = (
        f"{float(top_player['Total custom FP']):.1f} custom FP"
        if top_player is not None else "ESPN did not return dated player box scores"
    )
    st.markdown(
        '<div class="recap-hero-grid">'
        f'<div class="recap-card winner"><div class="recap-label">Weekly scoring champion</div><div class="recap-value">{html.escape(str(winner["Team"]))}</div><div class="recap-detail">{float(winner["Score"]):.1f} points · {date_text}</div></div>'
        f'<div class="recap-card"><div class="recap-label">Largest margin</div><div class="recap-value">{html.escape(str(biggest["Team"]))}</div><div class="recap-detail">{float(biggest["Margin"]):+.1f} vs {html.escape(str(biggest["Opponent"]))}</div></div>'
        f'<div class="recap-card"><div class="recap-label">Top player production</div><div class="recap-value">{html.escape(str(player_name))}</div><div class="recap-detail">{player_detail}</div></div>'
        '</div>',
        unsafe_allow_html=True,
    )
    my_row = teams[teams["Team"] == team.team_name]
    if not my_row.empty:
        row = my_row.iloc[0]
        message = f"Your Week {selected_period}: {row['Result']} with {float(row['Score']):.1f} points, ranked #{int(row['Weekly scoring rank'])} in league scoring. {row['Interpretation']}"
        (st.success if row["Result"] == "W" else st.warning)(message)
    st.subheader("Every team — result and interpretation")
    st.dataframe(teams, hide_index=True, use_container_width=True)
    st.subheader("Player performance leaders")
    if players.empty:
        st.info("ESPN did not provide enough dated player box-score data to reconstruct individual production.")
    else:
        st.dataframe(players.head(30), hide_index=True, use_container_width=True)
        st.caption("Player production includes custom points from completed NBA games in the period, whether or not that player was placed in an active fantasy slot. Team scores above remain the official ESPN matchup totals.")


def render_draft_recap(league, previous_league):
    hero("Season-long accountability", "Draft Recap", "Every pick is regraded from 1–10 as performance, health, replacement value, and rest-of-season outlook change.")
    updated_caption()
    with st.spinner("Regrading the draft..."):
        active_period = int(getattr(league, "currentMatchupPeriod", 1) or 1)
        power, _, team_rows = calculate_league_intelligence(
            CACHE_SCOPE, active_period, league, previous_league
        )
        save_power_snapshot(active_period, power)
        recap = draft_recap(league, team_rows, previous_league)
    if recap.empty:
        st.info("ESPN did not return draft results for this league.")
        return
    selected = st.selectbox("Show draft for", ["Entire league"] + sorted(recap["Drafted by"].dropna().unique().tolist()))
    shown = recap if selected == "Entire league" else recap[recap["Drafted by"] == selected]
    st.dataframe(shown, hide_index=True, use_container_width=True)
    st.caption("The value score measures value at the draft price—not simply how good the player is. Preseason grades rely heavily on projections and are provisional.")
    team_grades = recap.groupby("Drafted by")["Value score (1–10)"].mean().sort_values(ascending=False).round(1).reset_index(name="Draft grade")
    st.subheader("Team draft grades")
    st.dataframe(team_grades, hide_index=True, use_container_width=True)


def render_boom_bust(league, previous_league, team, schedule, user_id, league_id):
    hero("Range, not false certainty", "Boom or Bust", "See the upside, downside, and uncertainty around each projection. Injury information and role changes are shown beside the numbers.")
    updated_caption()
    if not schedule:
        st.error("NBA schedule data is unavailable.")
        return
    with st.spinner("Measuring player volatility and opportunity..."):
        board = boom_bust_board(
            league, schedule, previous_league,
            defense_context=load_defense_context(),
        )
    if board.empty:
        st.info("There is not enough projection or completed-game data yet.")
        return
    my_names = {player.name for player in team.roster}
    scope = st.radio("Players", ["My roster", "All rostered and top waivers"], horizontal=True)
    shown = board[board["Player"].isin(my_names)] if scope == "My roster" else board
    st.dataframe(shown, hide_index=True, use_container_width=True)
    st.caption("Boom and bust differentials are one estimated standard deviation above or below the adjusted projection. Low-confidence rows rely mainly on ESPN projections because too few 2026–27 games exist.")


def render_scoring_check():
    st.title("Scoring check")
    updated_caption()
    st.write("Enter one real NBA box score. Bonuses are derived automatically.")
    fields = ["PTS", "REB", "AST", "STL", "BLK", "TO", "3PM", "FTM", "FTA"]
    with st.form("score_check"):
        columns = st.columns(3)
        values = {field: columns[index % 3].number_input(field, min_value=0, step=1) for index, field in enumerate(fields)}
        submitted = st.form_submit_button("Calculate")
    if submitted:
        st.success(f"Custom fantasy points: {calculate_fantasy_points(values):.2f}")
    st.caption(RARE_STATS_WARNING)


def _nfl_stat_number(value):
    try:
        number = float(value)
        return round(number, 2) if pd.notna(number) else None
    except (TypeError, ValueError):
        return None


def _nfl_roster_rows(players, week):
    rows = []
    for player in players:
        stats = getattr(player, "stats", None) or {}
        week_stats = stats.get(week, stats.get(str(week), {})) if isinstance(stats, dict) else {}
        week_stats = week_stats if isinstance(week_stats, dict) else {}
        slots = getattr(player, "eligibleSlots", None) or []
        rows.append({
            "Player": getattr(player, "name", "Unknown"),
            "Position": getattr(player, "position", "Unknown"),
            "NFL team": getattr(player, "proTeam", "Unknown"),
            "Lineup slot": getattr(player, "lineupSlot", "Unknown"),
            "Eligible slots": ", ".join(map(str, slots)),
            "Injury status": getattr(player, "injuryStatus", "Unknown") or "Unknown",
            "Week points": _nfl_stat_number(week_stats.get("points")),
            "Week projection": _nfl_stat_number(week_stats.get("projected_points")),
            "Season points": _nfl_stat_number(getattr(player, "total_points", None)),
            "Season avg": _nfl_stat_number(getattr(player, "avg_points", None)),
        })
    return rows


def render_nfl_dashboard(league, team, league_record):
    week = int(getattr(league, "current_week", None)
               or getattr(league, "nfl_week", None) or 1)
    hero(
        f"ESPN fantasy football · {league_record['season']} season · Week {week}",
        "Football Center",
        "Read-only roster and matchup context from your ESPN league. Make lineup and transaction changes in ESPN.",
    )
    updated_caption()
    try:
        matchups = league.scoreboard(week=week)
    except Exception:
        matchups = []
    matchup = next((item for item in matchups if team.team_id in {
        getattr(getattr(item, "home_team", None), "team_id", None),
        getattr(getattr(item, "away_team", None), "team_id", None),
    }), None)
    opponent = None
    my_score = opp_score = my_projection = opp_projection = None
    if matchup is not None:
        is_home = matchup.home_team.team_id == team.team_id
        opponent = matchup.away_team if is_home else matchup.home_team
        my_score = getattr(matchup, "home_score" if is_home else "away_score", None)
        opp_score = getattr(matchup, "away_score" if is_home else "home_score", None)
        my_projection = getattr(matchup, "home_projected" if is_home else "away_projected", None)
        opp_projection = getattr(matchup, "away_projected" if is_home else "home_projected", None)

    record = "–".join(str(getattr(team, name, 0) or 0) for name in ("wins", "losses", "ties"))
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Record", record)
    c2.metric("Current week", week)
    c3.metric("Points for", _nfl_stat_number(getattr(team, "points_for", None)) or "—")
    c4.metric("Matchup", opponent.team_name if opponent else "Not available")
    if opponent:
        score_text = "Score not returned yet"
        if my_score is not None and opp_score is not None:
            score_text = f"{float(my_score):.1f} – {float(opp_score):.1f}"
        projection_text = "Projection not returned"
        if my_projection is not None and opp_projection is not None:
            projection_text = f"ESPN projection: {float(my_projection):.1f} – {float(opp_projection):.1f}"
        st.info(f"Week {week} matchup vs {opponent.team_name}: {score_text}. {projection_text}.")
    else:
        st.info("ESPN has not returned a matchup for your team in the current week.")

    roster_rows = _nfl_roster_rows(getattr(team, "roster", []), week)
    st.subheader("Roster and weekly projections")
    if roster_rows:
        roster = pd.DataFrame(roster_rows)
        st.dataframe(roster, hide_index=True, use_container_width=True)
        st.caption("ESPN supplies league-scored points and projections. This view does not change your lineup.")
        bench_slots = {"BE", "BN", "BENCH", "IR", "INJURED RESERVE", "PUP"}
        swaps = []
        starters = [row for row in roster_rows
                    if str(row["Lineup slot"]).strip().upper() not in bench_slots
                    and row["Week projection"] is not None]
        bench = [row for row in roster_rows
                 if str(row["Lineup slot"]).strip().upper() in bench_slots
                 and row["Week projection"] is not None
                 and str(row["Injury status"]).strip().upper() not in {"OUT", "IR", "INJURED RESERVE", "SUSPENDED"}]
        for starter in starters:
            same_position = [candidate for candidate in bench
                             if candidate["Position"] == starter["Position"]
                             and candidate["Player"] != starter["Player"]]
            if not same_position:
                continue
            replacement = max(same_position, key=lambda row: row["Week projection"])
            difference = replacement["Week projection"] - starter["Week projection"]
            if difference >= 2.0:
                swaps.append({
                    "Current starter": starter["Player"],
                    "Position": starter["Position"],
                    "Bench option": replacement["Player"],
                    "Starter projection": starter["Week projection"],
                    "Bench projection": replacement["Week projection"],
                    "Projection difference": round(difference, 2),
                    "Injury status": replacement["Injury status"],
                })
        st.subheader("Same-position projection checks")
        if swaps:
            st.dataframe(pd.DataFrame(swaps), hide_index=True, use_container_width=True)
            st.caption("Flags a same-position bench player only when ESPN projects at least 2 more points this week. Check late injury news and lineup eligibility in ESPN.")
        else:
            st.info("No same-position bench player clears the 2-point projection threshold, or ESPN did not return enough weekly projections.")
    else:
        st.info("ESPN returned an empty roster for this team.")

    st.subheader("Available players")
    try:
        available = league.free_agents(week=week, size=25)
    except Exception as error:
        available = None
        st.caption(f"ESPN free-agent list unavailable ({type(error).__name__}).")
    if available:
        available_rows = []
        for player in available:
            stats = getattr(player, "stats", None) or {}
            week_stats = stats.get(week, stats.get(str(week), {})) if isinstance(stats, dict) else {}
            week_stats = week_stats if isinstance(week_stats, dict) else {}
            available_rows.append({
                "Player": getattr(player, "name", "Unknown"),
                "Position": getattr(player, "position", "Unknown"),
                "NFL team": getattr(player, "proTeam", "Unknown"),
                "Injury status": getattr(player, "injuryStatus", "Unknown") or "Unknown",
                "Week projection": _nfl_stat_number(week_stats.get("projected_points")),
                "Season avg": _nfl_stat_number(getattr(player, "avg_points", None)),
                "Rostered %": _nfl_stat_number(getattr(player, "percent_owned", None)),
            })
        available_rows.sort(
            key=lambda row: (row["Week projection"] is not None,
                             row["Week projection"] if row["Week projection"] is not None else -1),
            reverse=True,
        )
        st.dataframe(pd.DataFrame(available_rows), hide_index=True, use_container_width=True)
    elif available is not None:
        st.info("ESPN returned no available players for this week.")
    st.caption("Available-player projections use your ESPN league's scoring. Review injury news and claim settings in ESPN before acting.")


def render_new_espn_connection(user_id, expanded=True):
    with st.sidebar.expander("Connect an ESPN fantasy league", expanded=expanded):
        st.caption("Cookies are sent only after you submit this form and are encrypted before they are saved.")
        with st.form("new_espn_connection"):
            sport_label = st.selectbox(
                "League sport", ["Basketball", "Football"], key="new_espn_sport"
            )
            league_id = st.text_input("ESPN league ID", key="new_espn_league_id")
            espn_s2 = st.text_input("espn_s2 cookie", type="password", key="new_espn_s2")
            swid = st.text_input("SWID cookie", type="password", key="new_espn_swid")
            label = st.text_input("Connection label", value="My ESPN league", key="new_espn_label")
            submitted = st.form_submit_button("Validate and save connection")
        if not submitted:
            return
        credentials = {"espn_s2": espn_s2.strip(), "swid": swid.strip()}
        if not league_id.strip() or not all(credentials.values()):
            st.session_state.pop("new_espn_s2", None)
            st.session_state.pop("new_espn_swid", None)
            st.error("Enter the league ID and both required cookies.")
            return
        sport = "nfl" if sport_label == "Football" else "nba"
        season = ESPN_NFL_SEASON_YEAR if sport == "nfl" else ESPN_SEASON_YEAR
        connector = connect_to_nfl_league if sport == "nfl" else connect_to_league
        try:
            league = connector(year=season, credentials=credentials,
                               league_id=league_id.strip())
        except Exception as error:
            st.session_state.pop("new_espn_s2", None)
            st.session_state.pop("new_espn_swid", None)
            st.error("The ESPN league check failed. The connection was not saved.")
            st.caption(f"ESPN check issue: {type(error).__name__}")
            return

        connection_id = None
        try:
            connection_id = account_store.create_provider_connection(
                user_id, "espn", credentials, label=label,
            )
            league_name = str(getattr(getattr(league, "settings", None), "name", "") or label)
            league_record_id = account_store.create_league(
                user_id, connection_id, league_id.strip(), sport,
                season, name=league_name,
            )
            st.session_state["active_league_selector"] = league_record_id
            st.session_state.pop("new_espn_s2", None)
            st.session_state.pop("new_espn_swid", None)
            load_league.clear()
            load_previous_league.clear()
        except Exception as error:
            if connection_id:
                try:
                    account_store.disconnect_provider(user_id, connection_id)
                except Exception:
                    pass
            st.session_state.pop("new_espn_s2", None)
            st.session_state.pop("new_espn_swid", None)
            st.error("The ESPN league check succeeded, but the app could not save the connection.")
            st.caption(f"Save issue: {type(error).__name__}")
            return
        st.rerun()


def render_credential_refresh(user_id, league_record, connection_id):
    with st.sidebar.expander("Update ESPN cookies"):
        st.caption("Use this after ESPN expires the saved session cookies.")
        with st.form(f"refresh_espn_{league_record['id']}"):
            espn_s2 = st.text_input("New espn_s2 cookie", type="password", key="refresh_espn_s2")
            swid = st.text_input("New SWID cookie", type="password", key="refresh_espn_swid")
            submitted = st.form_submit_button("Validate and replace cookies")
        if not submitted:
            return
        credentials = {"espn_s2": espn_s2.strip(), "swid": swid.strip()}
        if not all(credentials.values()):
            st.session_state.pop("refresh_espn_s2", None)
            st.session_state.pop("refresh_espn_swid", None)
            st.error("Enter both current ESPN cookies.")
            return
        try:
            connector = (connect_to_nfl_league if league_record["sport"] == "nfl"
                         else connect_to_league)
            connector(
                year=int(league_record["season"]), credentials=credentials,
                league_id=league_record["provider_league_id"],
            )
            if not account_store.update_provider_credentials(
                user_id, connection_id, credentials,
            ):
                raise LookupError("Connection not found for this user.")
            st.session_state.pop("refresh_espn_s2", None)
            st.session_state.pop("refresh_espn_swid", None)
            load_league.clear()
            load_previous_league.clear()
        except Exception as error:
            st.session_state.pop("refresh_espn_s2", None)
            st.session_state.pop("refresh_espn_swid", None)
            st.error("ESPN could not verify the replacement cookies. The saved connection was not changed.")
            st.caption(f"Connection issue: {type(error).__name__}")
            return
        st.rerun()


st.sidebar.title("League Settings")
source = st.sidebar.radio("Data source", ["ESPN connection", "Manual fallback"])
st.sidebar.caption("Data refreshes every 2.5 minutes. This site is read-only.")
if APP_ENV != "development" and st.sidebar.button("Sign out"):
    stop_user_workers(USER_ID)
    st.logout()

st.markdown(
    '<div class="app-brand"><div class="app-brand-left">'
    '<div class="app-brand-ball">🏀🏈</div><div>'
    '<div class="app-brand-name">Fantasy Advisor</div>'
    '<div class="app-brand-subtitle">League intelligence platform</div></div></div>'
    '<div class="app-brand-status"><span class="live-dot"></span>STAGING · READ ONLY</div></div>',
    unsafe_allow_html=True,
)

NAVIGATION = {
    "ROSTER": ["Championship Dashboard"],
    "MATCHUP": ["Matchup Center", "Opponent Gameplan", "Lineup Planner", "Injury Contingencies"],
    "PLAYERS": ["Waiver Market", "Roster Value", "Transactions", "Player Forecasts", "News"],
    "LEAGUE": ["Weekly Recap", "Power Rankings", "League Scout", "Draft Review"],
    "GM HUB": ["Strategy Board", "Playoff Planner", "Move Simulator", "Streaming Planner", "Transaction Portfolio", "Decision Tracker", "Accuracy Lab", "Scoring Check"],
    "NFL": ["Football Center"],
}
primary_page = st.radio(
    "Main section", list(NAVIGATION), horizontal=True,
    label_visibility="collapsed", key="main_navigation",
)
section_pages = NAVIGATION[primary_page]
if len(section_pages) == 1:
    page = section_pages[0]
else:
    page = st.radio(
        "Section page", section_pages, horizontal=True,
        label_visibility="collapsed", key=f"subnav_{primary_page}",
    )
if source == "Manual fallback":
    st.title("🏀 Fantasy Basketball Advisor")
    updated_caption()
    manual = load_manual_data()
    if manual is not None:
        mine = manual[manual["Side"].astype(str).str.casefold() == "me"]
        opponent = manual[manual["Side"].astype(str).str.casefold() == "opponent"]
        st.subheader("My roster")
        st.dataframe(mine.drop(columns=["Side"]), hide_index=True, use_container_width=True)
        st.subheader("Opponent")
        st.dataframe(opponent.drop(columns=["Side"]), hide_index=True, use_container_width=True)
        st.warning("Manual FP/G is accepted as supplied and cannot be verified against raw box scores.")
    st.stop()

try:
    available_leagues = [
        league_record for league_record in account_store.list_leagues(USER_ID)
        if league_record["sport"] in {"nba", "nfl"}
        and account_store.get_provider_connection(
            USER_ID, league_record["provider_connection_id"]
        ) is not None
    ]
except Exception as error:
    st.error("Your account's saved leagues could not be loaded.")
    st.caption(f"Account data issue: {type(error).__name__}")
    st.stop()

if not available_leagues:
    render_new_espn_connection(USER_ID)
    st.info("Connect an ESPN basketball or football league to load your private roster and matchup data.")
    st.stop()

league_by_id = {item["id"]: item for item in available_leagues}
league_labels = {
    item["id"]: f"{item['name'] or 'ESPN league'} · {item['sport'].upper()} · {item['season']}"
    for item in available_leagues
}
active_league_key = "active_league_selector"
if st.session_state.get(active_league_key) not in league_by_id:
    st.session_state[active_league_key] = available_leagues[0]["id"]
ACTIVE_LEAGUE_ID = st.sidebar.selectbox(
    "Connected league",
    list(league_by_id),
    format_func=league_labels.get,
    key=active_league_key,
)
active_league_record = league_by_id[ACTIVE_LEAGUE_ID]
connection_id = active_league_record["provider_connection_id"]
connection = account_store.get_provider_connection(USER_ID, connection_id)
if connection is None or connection["provider"] != "espn":
    st.error("The selected league connection is unavailable for this account.")
    st.stop()
connection_version = (
    connection["updated_at"].isoformat()
    if connection.get("updated_at") else str(connection.get("created_at", ""))
)
render_new_espn_connection(USER_ID, expanded=False)
render_credential_refresh(USER_ID, active_league_record, connection_id)
if st.sidebar.button("Disconnect selected ESPN league", key=f"disconnect_{ACTIVE_LEAGUE_ID}"):
    account_store.disconnect_provider(USER_ID, connection_id)
    st.session_state.pop(active_league_key, None)
    st.session_state.pop(f"selected_team_{ACTIVE_LEAGUE_ID}", None)
    load_league.clear()
    load_previous_league.clear()
    st.rerun()

set_tenant_scope(USER_ID, ACTIVE_LEAGUE_ID)
if "fantasy_cache_session_id" not in st.session_state:
    st.session_state["fantasy_cache_session_id"] = uuid.uuid4().hex
SESSION_CACHE_KEY = st.session_state["fantasy_cache_session_id"]
CACHE_SCOPE = f"{USER_ID}:{ACTIVE_LEAGUE_ID}:{connection_id}:{SESSION_CACHE_KEY}"

try:
    league = load_league(
        USER_ID, ACTIVE_LEAGUE_ID, connection_id, connection_version,
        active_league_record["provider_league_id"], SESSION_CACHE_KEY,
        int(active_league_record["season"]), active_league_record["sport"],
    )
except Exception as error:
    st.error("ESPN could not be reached for this saved league. Update its cookies or use Manual fallback.")
    st.caption(f"Connection issue: {type(error).__name__}")
    st.stop()

team_names = [team.team_name for team in league.teams]
selected_name = st.sidebar.selectbox(
    "My team", team_names, key=f"selected_team_{ACTIVE_LEAGUE_ID}"
)
team = next(team for team in league.teams if team.team_name == selected_name)
if active_league_record["sport"] == "nfl":
    if page == "Football Center":
        render_nfl_dashboard(league, team, active_league_record)
    else:
        st.info("This is an NFL league. Open the NFL tab and choose Football Center; the other sections currently cover basketball.")
    st.stop()

schedule = None
try:
    schedule = load_schedule()
except Exception as error:
    st.sidebar.warning(f"NBA schedule unavailable ({type(error).__name__}).")

reported_period = int(getattr(league, "currentMatchupPeriod", 1) or 1)
active_period = effective_matchup_period(league, schedule)
# This changes only the local read-only object. Every downstream calculation
# now sees the same reconciled week; nothing is written back to ESPN.
league.currentMatchupPeriod = active_period
if active_period > reported_period:
    st.sidebar.info(
        f"Week rollover detected: ESPN reported {reported_period}, dated NBA schedule is Week {active_period}."
    )
archive_previous_matchup(league, team, active_period)
matchup = matchup_for_team(league, team, active_period)
previous_league = load_previous_league(
    USER_ID, ACTIVE_LEAGUE_ID, connection_id, connection_version,
    active_league_record["provider_league_id"], SESSION_CACHE_KEY,
    int(active_league_record["season"]),
)
context_opponent = opponent_for(matchup, team)
raw_team_logo = getattr(team, "logo_url", None) or getattr(team, "logo", None) or ""
team_logo = str(raw_team_logo) if str(raw_team_logo).startswith(("https://", "http://")) else ""
team_initials = "".join(word[0] for word in team.team_name.split() if word)[:3].upper()
avatar_html = (
    f'<img class="league-avatar" src="{html.escape(team_logo)}" alt="">'
    if team_logo else
    f'<div class="league-avatar league-avatar-fallback">{html.escape(team_initials)}</div>'
)
opponent_label = (
    f"vs {html.escape(context_opponent.team_name)}"
    if context_opponent else "Opponent pending"
)
schedule_label = (
    f"{schedule['start_date']:%b %d}–{schedule['end_date']:%b %d}"
    if schedule else "Schedule unavailable"
)
st.markdown(
    '<div class="league-context"><div class="league-context-left">'
    f'{avatar_html}<div><div class="league-team-name">{html.escape(team.team_name)}</div>'
    f'<div class="league-meta">{opponent_label} · ESPN H2H Points</div></div></div>'
    f'<div class="league-week">WEEK {active_period}<br><span style="color:#85888d;font-weight:700">{schedule_label}</span></div></div>',
    unsafe_allow_html=True,
)

if page == "Championship Dashboard":
    render_home(league, previous_league, team, matchup, schedule)
elif page == "Strategy Board":
    render_strategy(league, previous_league, team)
elif page == "Playoff Planner":
    render_playoff_planner(league, previous_league, team)
elif page == "Move Simulator":
    render_move_simulator(league, previous_league, team)
elif page == "Streaming Planner":
    render_streaming_planner(league, previous_league, team)
elif page == "Transaction Portfolio":
    render_transaction_portfolio(league, previous_league, team)
elif page == "Decision Tracker":
    render_decision_tracker(team)
elif page == "Accuracy Lab":
    render_accuracy_lab(team)
elif page == "Power Rankings":
    render_power_rankings(league, previous_league, team)
elif page == "Weekly Recap":
    render_weekly_recap(league, team)
elif page == "Matchup Center":
    render_schedule(league, previous_league, team, matchup, schedule)
elif page == "Opponent Gameplan":
    render_opponent_gameplan(league, previous_league, team, matchup, schedule)
elif page == "Lineup Planner":
    render_today(league, previous_league, team, schedule)
elif page == "Injury Contingencies":
    render_contingencies(league, previous_league, team, schedule)
elif page == "Waiver Market":
    render_waivers(league, previous_league, team, schedule)
elif page == "Roster Value":
    render_roster_value(league, previous_league, team, schedule)
elif page == "Transactions":
    render_my_moves(league, team)
elif page == "Draft Review":
    render_draft_recap(league, previous_league)
elif page == "Player Forecasts":
    render_boom_bust(league, previous_league, team, schedule, USER_ID, ACTIVE_LEAGUE_ID)
elif page == "League Scout":
    render_league(league, previous_league, team, matchup, schedule)
elif page == "News":
    render_news(league, previous_league, team, matchup, schedule)
elif page == "Scoring Check":
    render_scoring_check()
elif page == "Football Center":
    st.info("Select an ESPN football league in the sidebar, or use the connection form to add one.")
