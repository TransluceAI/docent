# autoflake: skip_file
# pyright: ignore

# %%

import IPython

IPython.get_ipython().run_line_magic("load_ext", "autoreload")  # type: ignore
IPython.get_ipython().run_line_magic("autoreload", "2")  # type: ignore

# %%

from docent import Docent
from docent_core._env_util import ENV

# DOCENT_API_KEY = ENV.get("DOCENT_API_KEY")
# DOCENT_SERVER_URL = ENV.get("NEXT_PUBLIC_API_HOST")
# if not DOCENT_SERVER_URL or not DOCENT_API_KEY:
#     raise ValueError("DOCENT_API_KEY and DOCENT_SERVER_URL must be set")

DOCENT_API_KEY = ENV.get("DOCENT_API_KEY")
DOCENT_DOMAIN = ENV.get("DOCENT_DOMAIN")
if not DOCENT_DOMAIN or not DOCENT_API_KEY:
    raise ValueError("DOCENT_API_KEY and DOCENT_DOMAIN must be set")
dc = Docent(api_key=DOCENT_API_KEY, domain=DOCENT_DOMAIN, server_url="http://localhost:8890")

# %%

import random
import string

from docent.data_models.agent_run import AgentRun, AgentRunView
from docent.data_models.chat import AssistantMessage, ChatMessage, UserMessage
from docent.data_models.transcript import Transcript


def create_dummy_agent_run(
    num_messages: int = 10,
    chars_per_message: int = 100,
) -> AgentRun:
    """Create a dummy AgentRun with one transcript containing random character messages.

    Args:
        num_messages: Number of messages to include in the transcript.
        chars_per_message: Number of random characters per message.

    Returns:
        AgentRun with a single transcript containing the specified messages.
    """
    messages: list[ChatMessage] = []
    for i in range(num_messages):
        # Generate random content
        content = "".join(
            random.choices(string.ascii_letters + string.digits + " ", k=chars_per_message)
        )
        # Alternate between user and assistant messages
        if i % 2 == 0:
            messages.append(UserMessage(content=content))
        else:
            messages.append(AssistantMessage(content=content))

    # Create metadata with super long key names (~300 chars each) and long values
    long_key_metadata = {
        "this_is_an_extremely_long_metadata_key_name_that_spans_approximately_three_hundred_characters_to_test_how_the_system_handles_very_long_key_names_in_the_metadata_dictionary_structure_for_transcripts_and_agent_runs_testing_edge_cases_number_one": "This is a very long metadata value that contains a lot of text to test how the system handles large amounts of data in metadata values. It includes multiple sentences and paragraphs worth of content to ensure we're testing edge cases properly. The quick brown fox jumps over the lazy dog multiple times in this extended test string.",
        "another_incredibly_lengthy_metadata_key_designed_to_push_the_boundaries_of_what_is_typically_expected_for_key_lengths_in_metadata_dictionaries_this_key_should_be_around_three_hundred_characters_long_to_test_system_limits_and_edge_cases_two": "Another extremely long value that spans many characters and includes various types of content such as numbers 12345, special characters !@#$%, and unicode symbols like émojis and àccénts. This helps test the robustness of the metadata handling system across different character types and encodings in the database and UI.",
        "yet_one_more_absurdly_long_key_name_for_testing_purposes_that_contains_many_words_and_underscores_to_reach_the_target_length_of_approximately_three_hundred_characters_testing_metadata_key_length_limits_in_the_transcript_system_edge_case_three": "A third lengthy value containing repetitive content: Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit.",
    }
    transcript = Transcript(messages=messages, metadata=long_key_metadata)
    return AgentRun(transcripts=[transcript])


# %%

from tqdm.auto import tqdm

from docent.data_models._tiktoken_util import get_token_count

ars = [create_dummy_agent_run(num_messages=250, chars_per_message=2000) for _ in tqdm(range(100))]

# %%

cid = "3b10f51d-ddbc-4c07-b125-ba0f5bf0151c"
dc.add_agent_runs(cid, ars)

# %%
