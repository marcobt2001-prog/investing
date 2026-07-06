"""LLM qualitative evaluation layer.

Pluggable backend (Claude API or local Ollama) that produces a structured
risk/quality assessment for a company from its financial statements. Always
on-demand — never invoked during ingestion or scoring.
"""
