"""
Generate sample agent runs with message metadata for testing purposes.

This module creates procedurally generated short transcripts with metadata
and multiple transcript groups for testing the Docent application.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
from uuid import uuid4

# Add the docent package to the path
sys.path.insert(0, str(Path(__file__).parent.parent / "docent"))

from docent.data_models.agent_run import AgentRun
from docent.data_models.chat.content import ContentReasoning, ContentText
from docent.data_models.chat.message import (
    AssistantMessage,
    ChatMessage,
    SystemMessage,
    UserMessage,
)
from docent.data_models.chat.tool import ToolCall
from docent.data_models.transcript import Transcript, TranscriptGroup
from docent.sdk.client import Docent

from .utils import get_server_host, log_error, log_info, log_success


def generate_sample_metadata_patterns() -> List[Dict[str, Any]]:
    """Generate various sample metadata patterns for testing."""
    patterns = [
        # API metadata
        {
            "source": "api",
            "endpoint": "/v1/chat/completions",
            "model": "gpt-4",
            "temperature": 0.7,
            "max_tokens": 1000,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        # Performance metadata
        {
            "timing": {
                "start_time": "2024-01-15T10:30:00Z",
                "end_time": "2024-01-15T10:30:05Z",
                "duration_ms": 5234,
            },
            "tokens": {
                "input": 150,
                "output": 200,
                "total": 350,
            },
        },
        # Classification metadata
        {
            "classification": {
                "category": "code_generation",
                "complexity": "medium",
                "confidence": 0.89,
            },
            "tags": ["python", "function", "algorithm"],
        },
        # Error/debugging metadata
        {
            "error_info": {
                "has_error": True,
                "error_type": "syntax_error",
                "error_line": 42,
                "retry_count": 2,
            },
            "debug_flags": {
                "verbose": True,
                "trace_enabled": False,
            },
        },
        # User context metadata
        {
            "user_context": {
                "session_id": str(uuid4()),
                "user_tier": "premium",
                "feature_flags": ["beta_features", "advanced_tools"],
            },
            "preferences": {
                "code_style": "pep8",
                "explanation_level": "detailed",
            },
        },
        # Tool execution metadata
        {
            "tool_execution": {
                "tool_name": "code_interpreter",
                "execution_time_ms": 1234,
                "memory_usage_mb": 45.2,
                "success": True,
            },
            "environment": {
                "python_version": "3.11.5",
                "os": "linux",
                "container_id": "abc123",
            },
        },
        # Quality assessment metadata
        {
            "quality_metrics": {
                "coherence_score": 0.92,
                "relevance_score": 0.88,
                "factual_accuracy": 0.95,
            },
            "review_status": "approved",
            "reviewer_notes": "High quality response with good examples",
        },
        # Experimental metadata
        {
            "experiment": {
                "experiment_id": "exp_001",
                "variant": "control",
                "hypothesis": "Metadata improves debugging",
            },
            "flags": {
                "is_test": True,
                "collect_metrics": True,
            },
        },
    ]
    return patterns


def create_short_conversation_transcript(
    transcript_id: str,
    name: str,
    topic: str,
    metadata_patterns: List[Dict[str, Any]],
    transcript_group_id: str | None = None,
    as_json: bool = False,
) -> Transcript:
    """Create a short conversation transcript with metadata."""

    messages: list[ChatMessage] = []

    # System message
    system_msg = SystemMessage(
        content=f"You are a helpful assistant. Help the user with {topic}.",
        metadata=metadata_patterns[0],  # API metadata
    )
    messages.append(system_msg)

    # User question
    user_msg = UserMessage(
        content=f"Can you help me understand {topic}?",
        metadata=metadata_patterns[4],  # User context metadata
    )
    messages.append(user_msg)

    # Assistant response
    if as_json:
        assistant_msg = AssistantMessage(
            content=json.dumps(
                {
                    "topic": topic,
                    "summary": "brief",
                    "ok": True,
                    "stats": {"examples": 1, "level": "intro"},
                },
                separators=(",", ":"),
            ),
            metadata=metadata_patterns[2],  # Classification metadata
        )
    else:
        assistant_msg = AssistantMessage(
            content=f"I'd be happy to help you understand {topic}. Here's a brief explanation:",
            metadata=metadata_patterns[2],  # Classification metadata
        )
    messages.append(assistant_msg)

    # User follow-up
    user_msg2 = UserMessage(
        content="That's helpful, can you give me a practical example?",
        metadata=metadata_patterns[6],  # Quality assessment metadata
    )
    messages.append(user_msg2)

    # Assistant with example
    if as_json:
        assistant_msg2 = AssistantMessage(
            content=json.dumps(
                [
                    {"step": 1, "action": "define", "topic": topic},
                    {"step": 2, "action": "apply", "result": "ok"},
                ],
                separators=(",", ":"),
            ),
            metadata=metadata_patterns[1],  # Performance metadata
        )
    else:
        assistant_msg2 = AssistantMessage(
            content=f"Here's a practical example of {topic} in action...",
            metadata=metadata_patterns[1],  # Performance metadata
        )
    messages.append(assistant_msg2)

    # Optional: include reasoning and a tool call to exercise viewer features
    if as_json:
        assistant_msg3 = AssistantMessage(
            content=[
                ContentReasoning(reasoning="thinking through a short plan"),
                ContentText(text="Calling a tool with simple args"),
            ],
            metadata=metadata_patterns[5],
            tool_calls=[
                ToolCall(id=str(uuid4()), function="lookup", arguments={"topic": topic, "n": 1})
            ],
        )
        messages.append(assistant_msg3)

    return Transcript(
        id=transcript_id,
        name=name,
        description=f"Short conversation about {topic}",
        messages=messages,
        transcript_group_id=transcript_group_id,
        metadata={
            "conversation_type": "educational",
            "topic": topic,
            "length": "short",
            "has_metadata": True,
        },
    )


def create_agent_run_with_multiple_groups(run_number: int, collection_id: str) -> AgentRun:
    """Create an agent run with multiple transcript groups."""

    agent_run_id = str(uuid4())
    metadata_patterns = generate_sample_metadata_patterns()

    # Create transcript groups
    group1_id = str(uuid4())
    group2_id = str(uuid4())
    group3_id = str(uuid4())

    transcript_groups = [
        TranscriptGroup(
            id=group1_id,
            name="Algorithm Discussions",
            description="Conversations about algorithms and data structures",
            agent_run_id=agent_run_id,
            metadata={"topic_category": "algorithms", "difficulty": "beginner"},
        ),
        TranscriptGroup(
            id=group2_id,
            name="Debugging Sessions",
            description="Code debugging and troubleshooting conversations",
            agent_run_id=agent_run_id,
            metadata={"topic_category": "debugging", "difficulty": "intermediate"},
        ),
        TranscriptGroup(
            id=group3_id,
            name="Best Practices",
            description="Software development best practices and patterns",
            agent_run_id=agent_run_id,
            metadata={"topic_category": "best_practices", "difficulty": "advanced"},
        ),
    ]

    # Create transcripts for each group
    transcripts = [
        # Algorithm group transcripts
        create_short_conversation_transcript(
            str(uuid4()),
            "Sorting Algorithm Basics",
            "sorting algorithms",
            metadata_patterns,
            group1_id,
        ),
        create_short_conversation_transcript(
            str(uuid4()),
            "Binary Search Explained",
            "binary search",
            metadata_patterns,
            group1_id,
            as_json=True,
        ),
        # Debugging group transcripts
        create_short_conversation_transcript(
            str(uuid4()),
            "Null Pointer Debugging",
            "null pointer errors",
            metadata_patterns,
            group2_id,
        ),
        create_short_conversation_transcript(
            str(uuid4()),
            "Memory Leak Investigation",
            "memory leak debugging",
            metadata_patterns,
            group2_id,
            as_json=True,
        ),
        # Best practices group transcripts
        create_short_conversation_transcript(
            str(uuid4()),
            "Code Review Guidelines",
            "code review practices",
            metadata_patterns,
            group3_id,
        ),
        create_short_conversation_transcript(
            str(uuid4()),
            "Testing Strategies",
            "unit testing strategies",
            metadata_patterns,
            group3_id,
            as_json=True,
        ),
    ]

    # Create agent run
    agent_run = AgentRun(
        id=agent_run_id,
        name=f"Multi-Group Learning Session {run_number}",
        description=f"Generated agent run with multiple transcript groups (Run {run_number})",
        transcripts=transcripts,
        transcript_groups=transcript_groups,
        metadata={
            "generated": True,
            "generator": "data.generate",
            "run_number": run_number,
            "creation_timestamp": datetime.now(timezone.utc).isoformat(),
            "features": ["message_metadata", "transcript_groups", "multi_topic"],
            "statistics": {
                "total_transcript_groups": len(transcript_groups),
                "total_transcripts": len(transcripts),
                "total_messages": sum(len(t.messages) for t in transcripts),
                "messages_with_metadata": sum(
                    len([m for m in t.messages if m.metadata]) for t in transcripts
                ),
            },
        },
    )

    return agent_run


async def generate_and_ingest_agent_runs(
    count: int,
    collection_name: str,
    api_key: str | None = None,
    server_url: str | None = None,
) -> None:
    """Generate and ingest agent runs with multiple transcript groups."""

    # Set up server URL
    if not server_url:
        server_url = get_server_host()
    assert server_url is not None

    # Set up API key
    if not api_key:
        api_key = os.getenv("DOCENT_API_KEY")
        if not api_key:
            from .ingest import ensure_api_key

            api_key = await ensure_api_key()
    assert api_key is not None

    log_info(f"Generating {count} agent runs with multiple transcript groups...")

    # Initialize client
    try:
        # Use localhost web URL for local development
        web_url = "http://localhost:3000"
        client = Docent(server_url=server_url, web_url=web_url, api_key=api_key)

        # Create collection
        collection_id = client.create_collection(name=collection_name)
        log_success(f"Created/found collection: '{collection_name}' (ID: {collection_id})")

    except Exception as e:
        log_error(f"Failed to initialize client or create collection: {e}")
        raise

    # Generate agent runs
    agent_runs: list[AgentRun] = []
    for i in range(1, count + 1):
        log_info(f"Generating agent run {i}/{count}...")
        agent_run = create_agent_run_with_multiple_groups(i, collection_id)
        agent_runs.append(agent_run)

    log_success(f"Generated {len(agent_runs)} agent runs")

    # Ingest agent runs
    try:
        result = client.add_agent_runs(collection_id=collection_id, agent_runs=agent_runs)
        log_success(f"Successfully ingested {result['total_runs_added']} agent runs!")
        log_info(f"View them at: {web_url}/dashboard/{collection_id}")

    except Exception as e:
        log_error(f"Error ingesting agent runs: {e}")
        raise


def print_agent_run_summary(agent_runs: List[AgentRun]) -> None:
    """Print a summary of the generated agent runs."""
    print(f"\nGenerated {len(agent_runs)} agent runs:")
    print("-" * 60)

    for i, agent_run in enumerate(agent_runs, 1):
        print(f"Run {i}: {agent_run.name}")
        print(f"  ID: {agent_run.id}")
        print(f"  Transcript Groups: {len(agent_run.transcript_groups)}")
        print(f"  Transcripts: {len(agent_run.transcripts)}")
        print(f"  Total messages: {sum(len(t.messages) for t in agent_run.transcripts)}")

        # Count messages with metadata
        messages_with_metadata = 0
        for transcript in agent_run.transcripts:
            messages_with_metadata += len([m for m in transcript.messages if m.metadata])

        print(f"  Messages with metadata: {messages_with_metadata}")
        print()
