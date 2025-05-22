# Chat messages

We support 4 types of message objects:

- [`SystemMessage`][docent.data_models.chat.message.SystemMessage]: Instructions and context for the conversation
- [`UserMessage`][docent.data_models.chat.message.UserMessage]: Messages from end users to the assistant
- [`AssistantMessage`][docent.data_models.chat.message.AssistantMessage]: Responses from the AI assistant, potentially including tool calls
- [`ToolMessage`][docent.data_models.chat.message.ToolMessage]: Results from tools invoked during the conversation

Notes on the construction of messages:

- Each message has a `content` field, which can either be a `str` or a list of [`Content`][docent.data_models.chat.content] objects with [text][docent.data_models.chat.content.ContentText] and/or [reasoning][docent.data_models.chat.content.ContentReasoning]. We don't support audio/image/video content yet.
- [`AssistantMessage`][docent.data_models.chat.message.AssistantMessage] objects also have a `tool_calls` field, which supports a list of [`ToolCall`][docent.data_models.chat.tool.ToolCall] objects.

### Usage

The easiest way to convert a `dict` into a `ChatMessage` is to use [`parse_chat_message`][docent.data_models.chat.message.parse_chat_message]:

```python
from docent.data_models.chat import parse_chat_message

message_data = [
    {
        "role": "user",
        "content": "What is the capital of France?",
    },
    {
        "role": "assistant",
        "content": "Paris",
    },
]

messages = [parse_chat_message(msg) for msg in message_data]
```

The function will automatically raise validation errors if the input message does not conform to the schema.

You may also want to create messages manually:

```python
from docent.data_models.chat import (
    SystemMessage,
    UserMessage,
    AssistantMessage,
    ContentText,
    ContentReasoning,
    ToolCall,
    ToolCallContent,
)

messages = [
    SystemMessage(content="You are a helpful assistant."),
    UserMessage(content=[ContentText(text="Help me with this problem.")]),
    AssistantMessage(content="I'll help you solve that.", tool_calls=[ToolCall(id="call_123", function="calculator", arguments={"operation": "add", "a": 5, "b": 3}, view=ToolCallContent(format="markdown", content="Calculating: 5 + 3"))]),
    ToolMessage(content="8", tool_call_id="call_123", function="calculator"),
]
```

::: docent.data_models.chat.message
::: docent.data_models.chat.content
::: docent.data_models.chat.tool
