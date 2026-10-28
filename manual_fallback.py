"""Helpers for read-only manual roster and matchup data."""

import io

import pandas as pd


REQUIRED_COLUMNS = [
    "Side",
    "Player",
    "NBA team",
    "Position",
    "Fantasy slot",
    "FP/G",
]


def blank_template() -> pd.DataFrame:
    """Return an empty template with the expected columns."""
    return pd.DataFrame(columns=REQUIRED_COLUMNS)


def read_uploaded_csv(uploaded_file) -> pd.DataFrame:
    """Read an uploaded CSV without changing any external data."""
    data = pd.read_csv(uploaded_file)
    return validate_manual_data(data)


def read_pasted_csv(pasted_text: str) -> pd.DataFrame:
    """Read CSV text pasted into the website."""
    data = pd.read_csv(io.StringIO(pasted_text.strip()))
    return validate_manual_data(data)


def validate_manual_data(data: pd.DataFrame) -> pd.DataFrame:
    """Check and clean manually supplied roster data."""
    missing = [
        column for column in REQUIRED_COLUMNS if column not in data.columns
    ]

    if missing:
        raise ValueError(
            "Missing column(s): " + ", ".join(missing)
        )

    cleaned = data[REQUIRED_COLUMNS].copy()
    cleaned["FP/G"] = pd.to_numeric(cleaned["FP/G"], errors="coerce")

    return cleaned