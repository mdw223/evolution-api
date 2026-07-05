"""WhatsApp event detection pipeline — Tier 1 keyword filter + Vercel ingest."""

from .pipeline import EventPipeline

__all__ = ["EventPipeline"]
