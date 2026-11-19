# SPDX-License-Identifier: AGPL-3.0-or-later
"""Catalogue and price ingestion with Open Food Facts nutrition and rule-based classification."""

from .service import IngestReport, ingest

__all__ = ["IngestReport", "ingest"]
