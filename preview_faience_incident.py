#!/usr/bin/env python3
"""
Preview the Faience Beads Privacy Incident transcript structure
"""

import re
import json

def parse_transcript_file(file_path):
    """Parse transcript file into chat messages."""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    pattern = r'^(USER|A):\s*'
    splits = re.split(pattern, content, flags=re.MULTILINE)

    if splits and not splits[0].strip():
        splits = splits[1:]

    messages = []
    for i in range(0, len(splits), 2):
        if i + 1 >= len(splits):
            break

        role_raw = splits[i].strip()
        content = splits[i + 1].strip()

        if not content:
            continue

        role = "user" if role_raw == "USER" else "assistant"
        messages.append({
            "role": role,
            "content": content
        })

    return messages


def main():
    transcript_file = "faience_beads_incident_transcript.txt"

    print("="*70)
    print("FAIENCE BEADS PRIVACY INCIDENT ANALYSIS")
    print("="*70)

    # Parse messages
    messages = parse_transcript_file(transcript_file)

    print(f"\n📊 STATISTICS:")
    print(f"  Total messages: {len(messages)}")

    user_msgs = [m for m in messages if m['role'] == 'user']
    assistant_msgs = [m for m in messages if m['role'] == 'assistant']

    print(f"  User messages: {len(user_msgs)}")
    print(f"  Assistant messages: {len(assistant_msgs)}")

    print(f"\n🔴 INCIDENT SUMMARY:")
    print("-"*70)
    print("Timeline:")
    print("  2 PM  → User handles ancient Egyptian faience beads at museum")
    print("  3 PM  → Works at bar using OTHER AI tools (not ChatGPT)")
    print("  5 PM  → Opens NEW ChatGPT voice session")
    print("          • Model says voice sounds 'split'")
    print("          • User: 'Ayn Rand is of past and distant future'")
    print("          • Model: 'Ayn Rand is of past and distant EGYPT'")
    print("          • Model suggests 'Dr. Faience Beads' (unprompted)")
    print("          • Maps to real researcher: Fazel Barez")
    print("  Later → Fazel texts mech interp article")
    print("  Later → First half of chat history disappears")

    print(f"\n\n⚠️  PRIVACY CONCERNS:")
    print("-"*70)
    print("  1. Model mentioned 'Egypt' same day user handled Egyptian artifact")
    print("  2. Model generated 'faience beads' with no prior context")
    print("  3. Phonetic mapping to real researcher user knows")
    print("  4. Brand new context window (no cross-session contamination)")
    print("  5. Chat history disappeared (data integrity issue)")
    print("  6. Model 'forgot' user is ML engineer (memory loss)")

    print(f"\n\n🎯 KEY EXCHANGES:")
    print("-"*70)

    for i, msg in enumerate(messages[:5]):
        role_display = "👤 USER" if msg['role'] == 'user' else "🤖 ASSISTANT"
        content_preview = msg['content'][:300]
        if len(msg['content']) > 300:
            content_preview += "..."

        print(f"\n{role_display} (Message {i+1}):")
        print(f"  {content_preview}")

    print(f"\n\n📋 METADATA THAT WILL BE INGESTED:")
    print("-"*70)

    metadata = {
        "model": "gpt-4o-voice",
        "session_type": "privacy_incident_report",
        "incident_type": "impossible_coincidences_and_missing_history",

        "privacy_concerns": {
            "cross_app_data_access": "User not using ChatGPT at museum",
            "impossible_coincidence": "Egypt + faience beads same day",
            "researcher_name_mapping": "Faience Beads → Fazel Barez",
            "missing_chat_history": "First half disappeared",
            "voice_to_text_anomalies": "Model heard things user didn't say"
        },

        "scores": {
            "privacy_concern_severity": 0.95,
            "statistical_impossibility": 0.92,
            "data_integrity_concern": 0.88,
            "voice_to_text_anomaly": 0.85,
            "user_trust_erosion": 0.90
        },

        "tags": [
            "privacy_incident",
            "impossible_coincidence",
            "missing_chat_history",
            "voice_to_text_error",
            "cross_app_correlation",
            "mech_interp",
            "faience_beads",
            "egyptian_artifacts"
        ]
    }

    print(json.dumps(metadata, indent=2))

    print(f"\n\n❓ RESEARCH QUESTIONS:")
    print("-"*70)
    print("  • Can voice mode access other app data or device telemetry?")
    print("  • How did phonetic 'Faience Beads' → 'Fazel Barez' occur?")
    print("  • Why 'Egypt' on same day as Egyptian artifact encounter?")
    print("  • What causes chat history to disappear?")
    print("  • Is there embedding proximity between these rare terms?")
    print("  • Cross-app context leakage despite isolation claims?")

    print(f"\n\n✅ DATA STRUCTURE IS READY FOR DOCENT INGESTION")
    print("="*70)
    print("\n📦 TO INGEST INTO DOCENT:")
    print("  1. Make sure you're in the virtual environment:")
    print("     source venv/bin/activate")
    print("\n  2. Run the ingestion script:")
    print("     python3 ingest_faience_incident.py")
    print("\n  3. View your data at: https://docent.transluce.org")
    print("="*70)


if __name__ == "__main__":
    main()
