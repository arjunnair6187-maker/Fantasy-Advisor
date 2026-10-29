"""Grounded OpenAI interpretation for locally collected fantasy evidence."""

from __future__ import annotations

import hashlib
import json
import os

from dotenv import load_dotenv
from pydantic import BaseModel


load_dotenv()

AI_DATA_SHARING_SETTING = "ai_data_sharing_consent"


class ProjectionAdjustment(BaseModel):
    player: str
    percent_change: float
    reason: str
    evidence: list[str]
    confidence: str


class IntelligenceBriefing(BaseModel):
    headline: str
    summary: str
    reasons: list[str]
    action_items: list[str]
    risks: list[str]
    data_gaps: list[str]
    projection_adjustments: list[ProjectionAdjustment]


def configured_model():
    return os.getenv("OPENAI_MODEL", "gpt-6-luna").strip() or "gpt-6-luna"


def ai_is_configured():
    return bool(os.getenv("OPENAI_API_KEY", "").strip())


def ai_data_sharing_enabled():
    """Read the current league's saved opt-in, failing closed on missing consent."""
    from database import get_app_setting

    return get_app_setting(AI_DATA_SHARING_SETTING, "false") == "true"


def evidence_hash(payload):
    """Stable fingerprint that ignores collection time and never includes secrets."""
    comparable = dict(payload)
    comparable.pop("collected_at", None)
    encoded = json.dumps(comparable, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def deterministic_briefing(payload, summary=None):
    """Useful local fallback when the cloud model is not configured or unavailable."""
    roster = payload.get("my_roster", [])
    injuries = [row for row in roster if str(row.get("injury_status", "")).upper() not in {"ACTIVE", "NORMAL", "HEALTHY", ""}]
    opponent = payload.get("matchup", {}).get("opponent", "the current opponent")
    reasons = [
        f"The evidence packet contains {len(roster)} roster players and current schedule context.",
        f"The active matchup is against {opponent}.",
    ]
    if injuries:
        reasons.append(
            "Current injury flags: " + ", ".join(
                f"{row.get('player')} ({row.get('injury_status')})" for row in injuries[:4]
            ) + "."
        )
    return {
        "headline": "Grounded intelligence snapshot",
        "summary": summary or "Structured data has been collected. AI interpretation is unavailable; deterministic analysis remains available.",
        "reasons": reasons,
        "action_items": ["Verify injury designations near tipoff.", "Review the legal lineup plan before games lock."],
        "risks": ["AI interpretation is not active; deterministic analysis remains available."],
        "data_gaps": payload.get("data_gaps", []),
        "projection_adjustments": [],
    }


def generate_briefing(payload):
    """Generate a schema-validated briefing using only supplied evidence."""
    if not ai_data_sharing_enabled():
        return deterministic_briefing(
            payload,
            "Structured data has been collected. AI data sharing is off for this league; deterministic analysis is shown.",
        ), "deterministic", None
    if not ai_is_configured():
        return deterministic_briefing(
            payload,
            "Structured data has been collected. Add OPENAI_API_KEY in Streamlit Community Cloud Secrets (or a private .env file locally) to enable AI interpretation.",
        ), "deterministic", None
    try:
        from openai import OpenAI

        client = OpenAI()
        model = configured_model()
        response = client.responses.parse(
            model=model,
            store=False,
            instructions=(
                "You are the evidence analyst for a read-only fantasy basketball app. "
                "Use only the supplied JSON evidence. Never claim knowledge not present in it. "
                "Separate facts from inference, name stale or conflicting evidence, and state data gaps. "
                "Projection adjustments are shadow-mode research suggestions, not final projections. "
                "Only propose a percentage adjustment when dated performance, injury, role, schedule, or news evidence supports it. "
                "Keep percent_change between -15 and 15. Be concise and conversational."
            ),
            input=[{
                "role": "user",
                "content": "Analyze this JSON evidence packet:\n" + json.dumps(payload, default=str),
            }],
            text_format=IntelligenceBriefing,
        )
        parsed = response.output_parsed
        return parsed.model_dump(), model, None
    except Exception as error:
        fallback = deterministic_briefing(
            payload,
            "Structured data has been collected, but the AI request did not complete. Deterministic analysis is shown.",
        )
        fallback["risks"].append(
            f"OpenAI interpretation was unavailable ({type(error).__name__}); local fallback shown."
        )
        return fallback, "deterministic", type(error).__name__


def answer_grounded_question(question, payload):
    """Answer one user question without allowing unsupplied live knowledge."""
    if not ai_data_sharing_enabled():
        return (
            "OpenAI sharing is off for this league. Enable it in AI Analyst preferences to send a question and league evidence.",
            "disabled",
        )
    if not ai_is_configured():
        return "OpenAI is not configured yet. Add OPENAI_API_KEY in Streamlit Community Cloud app Settings → Secrets (or to a private .env file for local development), then restart and ask again.", "deterministic"
    try:
        from openai import OpenAI

        client = OpenAI()
        model = configured_model()
        response = client.responses.create(
            model=model,
            store=False,
            instructions=(
                "Answer as a concise fantasy basketball analyst. Use only the supplied evidence packet. "
                "Cite evidence using its source label and timestamp in plain language. "
                "If the evidence cannot answer the question, say exactly what is missing. "
                "Never invent news, injuries, stats, transactions, or return dates. "
                "This is read-only advice; never imply that a move was submitted."
            ),
            input=[{
                "role": "user",
                "content": (
                    "EVIDENCE:\n" + json.dumps(payload, default=str)
                    + "\n\nQUESTION:\n" + str(question)
                ),
            }],
        )
        return response.output_text.strip(), model
    except Exception as error:
        return f"The AI response could not be generated ({type(error).__name__}). The saved evidence remains available below.", "unavailable"
