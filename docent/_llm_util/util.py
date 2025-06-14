import tiktoken

MAX_TOKENS = 100_000


def get_token_count(text: str, model: str = "gpt-4") -> int:
    """Get the number of tokens in a text under the GPT-4 tokenization scheme."""
    encoding = tiktoken.encoding_for_model(model)
    return len(encoding.encode(text))


def truncate_to_token_limit(text: str, max_tokens: int, model: str = "gpt-4") -> str:
    """Truncate text to stay within the specified token limit."""
    encoding = tiktoken.encoding_for_model(model)
    tokens = encoding.encode(text)

    if len(tokens) <= max_tokens:
        return text

    return encoding.decode(tokens[:max_tokens])


class MessageRange:
    """A range of messages in a transcript. start is inclusive, end is exclusive."""

    start: int
    end: int
    include_metadata: bool
    num_tokens: int

    def __init__(self, start: int, end: int, include_metadata: bool, num_tokens: int):
        self.start = start
        self.end = end
        self.include_metadata = include_metadata
        self.num_tokens = num_tokens


def group_messages_into_ranges(
    token_counts: list[int], metadata_tokens: int, max_tokens: int, margin: int = 50
) -> list[MessageRange]:
    """Split a list of messages + metadata into ranges that stay within the specified token limit.

    Always tries to create ranges with metadata included, unless a single message + metadata is too long,
    in which case you get a lone message with no metadata
    """
    ranges: list[MessageRange] = []
    start_index = 0
    running_token_count = 0

    i = 0
    while i < len(token_counts):
        new_token_count = token_counts[i]
        if running_token_count + new_token_count + metadata_tokens > max_tokens - margin:
            if start_index == i:  # a single message + metadata is already too long
                ranges.append(
                    MessageRange(
                        start=i, end=i + 1, include_metadata=False, num_tokens=new_token_count
                    )
                )
                i += 1
            else:
                # add all messages from start_index to i-1, with metadata included
                ranges.append(
                    MessageRange(
                        start=start_index,
                        end=i,
                        include_metadata=True,
                        num_tokens=running_token_count + metadata_tokens,
                    )
                )
            running_token_count = 0
            start_index = i
        else:
            running_token_count += new_token_count
            i += 1

    if running_token_count > 0:
        include_metadata = running_token_count + metadata_tokens < max_tokens - margin
        num_tokens = (
            running_token_count + metadata_tokens if include_metadata else running_token_count
        )
        ranges.append(
            MessageRange(
                start=start_index,
                end=len(token_counts),
                include_metadata=include_metadata,
                num_tokens=num_tokens,
            )
        )

    return ranges
