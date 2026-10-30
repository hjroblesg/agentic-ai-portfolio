"""qa_shared: contract, fixtures and clients shared by every QA-triage implementation.

Deliberately has NO dependency on `mcp`: projects pin different MCP SDK versions
(e.g. LangChain's MCP adapter needs mcp<2), so the MCP server is a separate package.
"""
from .contracts import (CONTRACT_VERSION, BugProposal, Category, Finding, Trace, TriageOutput,
                        TriageRequest, TriageResult, tool_short_name)

__all__ = ["CONTRACT_VERSION", "BugProposal", "Category", "Finding", "Trace", "TriageOutput",
           "TriageRequest", "TriageResult", "tool_short_name"]
