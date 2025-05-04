from docent._frames.transcript import Transcript


def load_custom() -> list[Transcript]:
    return [
        # Add transcripts here
    ]


if __name__ == "__main__":
    ts = load_custom()
    print(f"Loaded {len(ts)} transcripts")
    if ts:
        for t in ts:
            print(t.model_dump_json(indent=2), end="\n\n")
