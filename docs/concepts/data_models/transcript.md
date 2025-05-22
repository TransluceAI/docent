# Transcript

A [`Transcript`][docent.data_models.transcript.Transcript] object represents a sequence of chat messages (user, assistant, system, tool) from the perspective of *a single* agent. See [here for more details on the chat message schemas](./chat_messages.md).


## Action units

Action units are logical groupings of related messages in a conversation. They represent complete interaction cycles between users, AI assistants, and tools.

Action units are determined by the following rules:

1. **System Messages**: Each system message forms its own standalone action unit
2. **User-Assistant Exchanges**:
    - A new user message starts a new action unit (unless following another user message)
    - Assistant messages following a user or another assistant stay in the same unit
    - Tool messages are always part of the current unit

For precise details on how action units are determined, refer to the `_compute_units_of_action` method implementation.

### Conceptual Examples

Example 1: basic action units

```
Action Unit 0:
  [System] "You are a helpful AI assistant..."

Action Unit 1:
  [User] "What's the weather today?"
  [Assistant] "The weather in your area is sunny with a high of 72°F"

Action Unit 2:
  [User] "What should I wear?"
  [Assistant] "Given the sunny weather, light clothing would be appropriate"
```

Example 2: action units with tools

```
Action Unit 0:
  [System] "You are a coding assistant..."

Action Unit 1:
  [User] "Create a Python function to calculate Fibonacci numbers"
  [Assistant] "I'll create that function for you"
  [Tool] Code generation tool output

Action Unit 2:
  [Assistant] "Here's the function I created: ..."
```

### Edge cases

Multiple consecutive user messages stay in same unit

```
Action Unit 0:
  [User] "Hello"
  [User] "Can you help me with something?"
  [Assistant] "Yes, I'd be happy to help."
```

::: docent.data_models.transcript
