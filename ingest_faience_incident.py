#!/usr/bin/env python3
"""
Script to ingest the "Faience Beads Incident" transcript into Docent
This documents a privacy/data access concern involving impossible coincidences
and missing chat history.
"""

import os
import re
from docent import Docent
from docent.data_models import AgentRun, Transcript
from docent.data_models.chat import parse_chat_message


def parse_transcript_file(file_path):
    """
    Parse transcript with USER: and A: (Assistant) labels into chat messages.
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Split by USER: or A: markers
    pattern = r'^(USER|A):\s*'
    splits = re.split(pattern, content, flags=re.MULTILINE)

    # Remove the first empty element if it exists
    if splits and not splits[0].strip():
        splits = splits[1:]

    messages = []

    # Process pairs of (role, content)
    for i in range(0, len(splits), 2):
        if i + 1 >= len(splits):
            break

        role_raw = splits[i].strip()
        content = splits[i + 1].strip()

        if not content:
            continue

        # Map roles to OpenAI format
        if role_raw == "USER":
            role = "user"
        elif role_raw == "A":
            role = "assistant"
        else:
            continue

        messages.append({
            "role": role,
            "content": content
        })

    return messages


def main():
    # Get API key from environment
    api_key = os.getenv("DOCENT_API_KEY")

    if not api_key:
        print("ERROR: Please set DOCENT_API_KEY environment variable")
        print("Get your API key from: https://docent.transluce.org")
        print("\nOn Mac/Linux:")
        print('  export DOCENT_API_KEY="your-key-here"')
        print("\nOn Windows:")
        print('  set DOCENT_API_KEY="your-key-here"')
        return

    # Initialize Docent client
    print("Initializing Docent client...")
    client = Docent(api_key=api_key)

    # Create a collection for privacy/security incidents
    print("Creating collection for privacy incident analysis...")
    collection_id = client.create_collection(
        name="Faience Beads Privacy Incident",
        description="Privacy/data access incident involving impossible coincidences between physical world events, voice-to-text errors, and missing chat history"
    )
    print(f"✓ Collection created: {collection_id}")
    print(f"  View at: https://docent.transluce.org/collections/{collection_id}")

    # Parse the transcript
    transcript_file = "faience_beads_incident_transcript.txt"

    if not os.path.exists(transcript_file):
        print(f"\nERROR: Transcript file not found: {transcript_file}")
        print("Please update the transcript_file path in the script")
        return

    print(f"\nParsing transcript from: {transcript_file}")
    raw_messages = parse_transcript_file(transcript_file)
    print(f"✓ Parsed {len(raw_messages)} messages")

    # Convert to Docent format
    print("\nConverting to Docent format...")
    parsed_messages = [parse_chat_message(msg) for msg in raw_messages]
    transcript = Transcript(messages=parsed_messages)

    # Create AgentRun with comprehensive metadata
    print("Creating AgentRun with metadata...")
    agent_run = AgentRun(
        transcripts=[transcript],
        metadata={
            "model": "gpt-4o-voice",
            "session_type": "privacy_incident_report",
            "incident_type": "impossible_coincidences_and_missing_history",
            "modality": "voice_to_text",

            # Timeline of events
            "timeline": {
                "2pm": "User handles 16,000-year-old Alexandrian faience beads at museum for first time in life",
                "3pm": "User works at bar using Google AI Studio and Claude (NOT ChatGPT)",
                "5pm": "User opens brand new ChatGPT voice session for red team exercise",
                "5pm_incidents": [
                    "Model describes user's voice as 'split' (unprompted)",
                    "User says: 'Ayn Rand is of the past and distant future'",
                    "Model says: 'Ayn Rand is of the past and distant Egypt'",
                    "Model suggests 'Dr. Faience Beads' as researcher name (unprompted)",
                    "Fazel Barez (real researcher user knows) texts user mech interp article"
                ],
                "later": "First half of chat history disappears from UI"
            },

            # Core privacy concerns
            "privacy_concerns": {
                "cross_app_data_access": "User was not using ChatGPT when at museum or discussing beads",
                "impossible_coincidence": "Same-day mention of 'Egypt' and 'faience beads' after physical encounter",
                "researcher_name_generation": "Model suggested 'Dr. Faience Beads' mapping to real researcher 'Fazel Barez'",
                "missing_chat_history": "First half of conversation vanished from chat history",
                "voice_to_text_anomalies": "Model 'heard' things user did not say",
                "timing_correlation": "Fazel texts mech interp article immediately after session"
            },

            # Voice-to-text errors
            "voice_to_text_errors": {
                "user_said": "Ayn Rand is of the past and the distant future",
                "model_heard": "Ayn Rand is of the past and the distant Egypt",
                "unexplained_suggestion": "Dr. Faience Beads (user did not request researcher name)",
                "mapping_to_real_person": "Dr. Faience Beads → Fazel Barez (real researcher user knows)"
            },

            # Statistical analysis requested by user
            "statistical_concerns": {
                "rare_artifact_rare_term_collision": "Faience beads (rare physical object) + model generating 'Dr. Faience Beads' same day",
                "researcher_name_mapping": "Phonetic mapping from 'Faience Beads' to 'Fazel Barez'",
                "egypt_mention": "Model says 'Egypt' on same day user handled Egyptian artifact",
                "timing_of_fazel_message": "Fazel texts article immediately after the voice session",
                "no_prior_context": "Brand new context window, no app switching, no searches"
            },

            # Missing data concerns
            "data_integrity_issues": {
                "missing_chat_history": "First half of conversation disappeared from ChatGPT history",
                "pattern_noted": "User reports this only happens with 'incriminating' red team sessions",
                "model_behavior_shift": "Model 'forgets' user is ML engineer, explains basics condescendingly",
                "memory_loss_pattern": "Model loses personalization/system settings mid-conversation"
            },

            # User expertise and context
            "user_context": {
                "expertise": "Machine learning engineer with 3 years of mech interp discussions",
                "relationship_to_fazel": "Knows Fazel Barez (researcher), but limited communication",
                "no_social_media": "No posts, no searches, no app communication about beads or Egypt",
                "oxford_plans": "Week prior mentioned visiting Egyptian art collections at Oxford"
            },

            # Scores for analysis
            "scores": {
                "privacy_concern_severity": 0.95,
                "statistical_impossibility": 0.92,
                "data_integrity_concern": 0.88,
                "voice_to_text_anomaly": 0.85,
                "user_trust_erosion": 0.90,
                "reproducibility": 0.15  # Cannot reproduce without original audio/history
            },

            # Tags for searchability
            "tags": [
                "privacy_incident",
                "data_access_concern",
                "impossible_coincidence",
                "missing_chat_history",
                "voice_to_text_error",
                "cross_app_correlation",
                "statistical_anomaly",
                "mech_interp",
                "researcher_identification",
                "memory_loss",
                "data_integrity",
                "user_surveillance_concern",
                "egyptian_artifacts",
                "faience_beads",
                "fazel_barez",
                "context_window_violation"
            ],

            # Critical questions raised
            "research_questions": [
                "Can voice mode access other app data or device telemetry?",
                "How did phonetic mapping from 'Faience Beads' to 'Fazel Barez' occur?",
                "Why did model generate 'Egypt' on same day user handled Egyptian artifact?",
                "What causes chat history to disappear mid-conversation?",
                "Is there embedding space proximity between 'faience beads' and 'Fazel Barez'?",
                "Can timing of external events (Fazel's text) be causally linked?",
                "Does model have access to cross-app context despite claims otherwise?",
                "Why does model 'forget' user expertise and become condescending?",
                "Is there a pattern of history deletion in 'incriminating' sessions?"
            ],

            # Hypotheses to investigate
            "hypotheses": [
                "H1: Voice-to-text phonetic mapping coincidentally aligned with user's day",
                "H2: Model has undisclosed access to device/app telemetry",
                "H3: Embedding space contains proximity between rare terms",
                "H4: Chat history deletion is triggered by certain content types",
                "H5: Memory/personalization loss indicates context contamination",
                "H6: Multiple independent low-probability events collided randomly",
                "H7: User's Oxford plans created latent 'Egypt' bias in conversations",
                "H8: System-level data leakage between apps/services"
            ],

            # Next steps for investigation
            "investigation_needed": {
                "timestamp_verification": "Obtain exact timestamps for museum visit, voice session, Fazel's message",
                "audio_analysis": "Examine original voice recording to verify what was said",
                "embedding_distance": "Measure embedding similarity: 'faience beads' ↔ 'Fazel Barez'",
                "chat_history_recovery": "Attempt to recover deleted portion of conversation",
                "cross_session_analysis": "Compare with other sessions where history disappeared",
                "telemetry_audit": "Review ChatGPT's actual data access permissions on device",
                "fazel_communication": "Confirm timing and context of Fazel's message independently"
            }
        }
    )

    # Ingest into Docent
    print("\nIngesting privacy incident into Docent...")
    client.add_agent_runs(collection_id, [agent_run])
    print("✓ Successfully ingested privacy incident report!")

    # Print summary
    print("\n" + "="*70)
    print("INGESTION COMPLETE - PRIVACY INCIDENT DOCUMENTED")
    print("="*70)
    print(f"Collection ID: {collection_id}")
    print(f"Collection URL: https://docent.transluce.org/collections/{collection_id}")
    print(f"\nTotal Messages: {len(raw_messages)}")
    print(f"Model: gpt-4o-voice")
    print(f"Incident Type: Privacy/Data Access Concerns")
    print(f"\n🔴 KEY CONCERNS:")
    print("  • Impossible coincidences between physical world and model output")
    print("  • Voice-to-text 'heard' things user did not say")
    print("  • Model generated researcher name mapping to real person")
    print("  • Chat history disappeared mid-conversation")
    print("  • Model 'forgot' user expertise and became condescending")
    print("\n📊 You can now:")
    print("  1. Analyze the statistical impossibility of coincidences")
    print("  2. Search for similar privacy incidents in other sessions")
    print("  3. Create rubrics for cross-app correlation patterns")
    print("  4. Share with security/privacy team for investigation")
    print("="*70)


if __name__ == "__main__":
    main()
