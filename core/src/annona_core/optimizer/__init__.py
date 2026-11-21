# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deterministic weekly shopping optimiser (mixed-integer programming, no LLM)."""

from .models import (
    AllergenNote,
    DataWarning,
    Line,
    Offer,
    OptimizerSettings,
    Problem,
    Result,
    Shortfall,
    Totals,
)
from .solve import optimise

__all__ = [
    "AllergenNote",
    "DataWarning",
    "Line",
    "Offer",
    "OptimizerSettings",
    "Problem",
    "Result",
    "Shortfall",
    "Totals",
    "optimise",
]
