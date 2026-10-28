"""Public, sample-only UI demo for the fantasy advisor project."""

import pandas as pd
import streamlit as st


st.set_page_config(
    page_title="Fantasy Advisor Demo",
    page_icon="🏈",
    layout="wide",
)

SAMPLES = {
    "NBA": {
        "team": "Northstar Hoops",
        "period": "Sample matchup week",
        "players": [
            {"Player": "Avery Stone", "Position": "PG", "Opponent": "Lake City", "Projection": 34.2, "Note": "Strong sample play"},
            {"Player": "Riley North", "Position": "SG", "Opponent": "Lake City", "Projection": 28.1, "Note": "Steady sample role"},
            {"Player": "Morgan Vale", "Position": "SF", "Opponent": "Redwood", "Projection": 26.5, "Note": "Good sample schedule"},
            {"Player": "Jordan Wells", "Position": "PF", "Opponent": "Redwood", "Projection": 23.8, "Note": "Monitor sample status"},
            {"Player": "Casey Frost", "Position": "C", "Opponent": "Lake City", "Projection": 22.4, "Note": "Sample rebound edge"},
            {"Player": "Devin Lake", "Position": "G", "Opponent": "Redwood", "Projection": 19.7, "Note": "Lower sample ceiling"},
            {"Player": "Taylor Reed", "Position": "F", "Opponent": "Lake City", "Projection": 17.9, "Note": "Bench comparison"},
        ],
        "waivers": [
            {"Player": "Quinn Harbor", "Position": "G", "Projection": 18.8, "Reason": "More sample games this week"},
            {"Player": "Skyler Pine", "Position": "F", "Projection": 16.3, "Reason": "Useful sample depth"},
        ],
    },
    "NFL": {
        "team": "Weekend Gridiron",
        "period": "Sample matchup week",
        "players": [
            {"Player": "Drew Harbor", "Position": "QB", "Opponent": "Metro Foxes", "Projection": 22.6, "Note": "Strong sample play"},
            {"Player": "Cameron Ridge", "Position": "RB", "Opponent": "Pine Valley", "Projection": 18.9, "Note": "Steady sample role"},
            {"Player": "Emery Brook", "Position": "RB", "Opponent": "Metro Foxes", "Projection": 15.4, "Note": "Good sample matchup"},
            {"Player": "Finley Shore", "Position": "WR", "Opponent": "Pine Valley", "Projection": 17.8, "Note": "Strong sample target share"},
            {"Player": "Harper West", "Position": "WR", "Opponent": "Metro Foxes", "Projection": 14.7, "Note": "Monitor sample status"},
            {"Player": "Rowan Field", "Position": "TE", "Opponent": "Pine Valley", "Projection": 10.8, "Note": "Bench comparison"},
            {"Player": "Parker Glen", "Position": "FLEX", "Opponent": "Metro Foxes", "Projection": 12.1, "Note": "Lower sample ceiling"},
        ],
        "waivers": [
            {"Player": "Sage Miller", "Position": "WR", "Projection": 12.9, "Reason": "More sample opportunities"},
            {"Player": "Reese Summit", "Position": "RB", "Projection": 11.6, "Reason": "Useful sample depth"},
        ],
    },
}


st.title("Fantasy Advisor")
st.caption("A small public preview of the planned read-only fantasy advisor.")
st.warning(
    "Sample data only. Names, projections, matchups, and recommendations are fictional. "
    "This demo does not ask for cookies, connect to ESPN, or store user information."
)

sport = st.radio("Choose a sample sport", ["NBA", "NFL"], horizontal=True)
sample = SAMPLES[sport]
players = pd.DataFrame(sample["players"])
waivers = pd.DataFrame(sample["waivers"])

st.subheader(sample["team"])
st.caption(f"{sport} · {sample['period']} · Fictional example")

top_players = players.nlargest(5, "Projection")
first, second, third = st.columns(3)
first.metric("Sample roster", f"{len(players)} players")
second.metric("Top five projection", f"{top_players['Projection'].sum():.1f} pts")
third.metric("Sample waiver options", f"{len(waivers)}")

view = st.segmented_control(
    "Demo view", ["Roster outlook", "Waiver comparison"], default="Roster outlook"
)
if view == "Roster outlook":
    st.markdown("#### Projected contributors")
    st.bar_chart(top_players.set_index("Player")["Projection"], y_label="Fictional points")
    st.dataframe(players, hide_index=True, use_container_width=True)
    st.info(
        "Demo takeaway: compare projected contributions and the notes beside each player. "
        "Real lineups depend on league scoring, roster slots, injuries, and current data."
    )
else:
    st.markdown("#### Sample add/drop comparison")
    st.dataframe(waivers, hide_index=True, use_container_width=True)
    selected = st.selectbox("Compare a fictional player", players["Player"].tolist())
    roster_row = players.loc[players["Player"] == selected].iloc[0]
    waiver_row = waivers.nlargest(1, "Projection").iloc[0]
    difference = float(waiver_row["Projection"] - roster_row["Projection"])
    st.write(
        f"Sample comparison: {waiver_row['Player']} projects {abs(difference):.1f} points "
        f"{'higher' if difference >= 0 else 'lower'} than {selected}."
    )
    st.caption("This fictional comparison is not a real transaction recommendation.")

with st.expander("What this preview does and does not do"):
    st.markdown(
        "- Shows a sample interface for NBA and NFL fantasy advice.\n"
        "- Uses only fictional names, matchups, projections, and notes bundled with the app.\n"
        "- Makes no network calls and saves no user data.\n"
        "- Does not connect to ESPN, Sleeper, Yahoo, or any fantasy account.\n"
        "- Is not evidence that the full multi-user app or its advice has passed QA."
    )
