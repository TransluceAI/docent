import re

from pydantic import BaseModel

from docent._log_util import get_logger

logger = get_logger(__name__)


class RegexSnippet(BaseModel):
    snippet: str
    match_start: int
    match_end: int


def get_regex_snippets(text: str, pattern: str, window_size: int = 50) -> list[RegexSnippet]:
    """Extracts snippets from text that match a regex pattern, with surrounding context.

    Args:
        text: The text to search in.
        pattern: The regex pattern to match.
        window_size: The number of characters to include before and after the match.

    Returns:
        A list of RegexSnippet objects containing the snippets and match positions.
    """
    # Find all matches
    try:
        matches = list(re.compile(pattern, re.IGNORECASE | re.DOTALL).finditer(text))
        if not matches:
            logger.warning(f"No regex matches found for {pattern}: this shouldn't happen!")

        if not matches:
            return []

        snippets: list[RegexSnippet] = []
        for match in matches:
            start, end = match.span()

            # Calculate window around the match
            snippet_start = max(0, start - window_size)
            snippet_end = min(len(text), end + window_size)

            # Create the snippet with the match indices adjusted for the window
            snippets.append(
                RegexSnippet(
                    snippet=text[snippet_start:snippet_end],
                    match_start=start - snippet_start,
                    match_end=end - snippet_start,
                )
            )

        return snippets
    except re.error as e:
        logger.error(f"Got regex error: {e}")
        return []
