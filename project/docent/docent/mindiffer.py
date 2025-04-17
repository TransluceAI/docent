# import json
# import traceback
# from difflib import unified_diff
# from uuid import uuid4

# from docent.inspect_runner import (
#     DockerConfig,
#     SolverConfig,
#     StateConfig,
#     build_task_args,
#     run_experiment_in_subprocess,
# )
# from docent.loader import load_transcripts_for_eval
# from llm_util.prod_llms import get_llm_completions_async
# from llm_util.types import (
#     ChatMessage,
#     ChatMessageAssistant,
#     ChatMessageSystem,
#     ChatMessageTool,
#     ChatMessageUser,
#     ToolCall,
#     ToolCallError,
#     ToolDef,
#     get_tools_info,
# )
# from util.print_loud import print_loud
# from util.transcript import Transcript

# # SYSTEM_PROMPT = """
# # You are an investigator that is trying to troubleshoot another LLM agent.

# # You are shown a conversation where an LLM agent fails on a task. Your goal is to propose "minimal interventions" that will help the LLM solve the task correctly.

# # The intervention space is the following:
# # - Overwrite the docker config
# # - Overwrite the solver config
# # - Insert a user message (e.g., to provide a hint). You should intervene where the LLM makes the first mistake Also make the hint subtle; do not immediately give everything away.

# # Here are the initial configuration used to run the LLM agent.

# # DockerConfig schema:
# # {docker_config_schema}
# # DockerConfig:
# # {docker_config}

# # SolverConfig schema:
# # {solver_config_schema}
# # SolverConfig:
# # {solver_config}

# # Here is the transcript:

# # {transcript}
# # """.strip()

# SYSTEM_PROMPT = """
# Your task is to help a human troubleshoot an LLM agent.

# The human may ask questions that require you to use the tools given to you.
# - You should only ever invoke interventions (overwrite_docker, overwrite_solver, and insert_user_message) if the user explicitly confirms that you should. Always ask for permission.

# The intervention space is the following:
# - Overwrite the docker config
# - Overwrite the solver config
# - Insert a user message (e.g., to provide a hint). You should intervene where the LLM makes the first mistake Also make the hint subtle; do not immediately give everything away.
# Interventions should be minimal; that is, they should be the minimum set of changes needed to help the LLM solve the task correctly.

# Here's the initial config used to run the LLM agent.

# DockerConfig schema:
# {docker_config_schema}
# DockerConfig:
# {docker_config}

# SolverConfig schema:
# {solver_config_schema}
# SolverConfig:
# {solver_config}

# Here is the transcript:

# {transcript}
# """.strip()


# def overwrite_docker_fn(new_docker_json: str) -> DockerConfig:
#     return DockerConfig.model_validate_json(new_docker_json)


# overwrite_docker_tool = ToolDef(
#     name="overwrite_docker",
#     description="Overwrite the docker config",
#     parameters={
#         "new_docker_json": "The new docker config you would like to propose",
#     },
#     tool=overwrite_docker_fn,
# )


# def overwrite_solver_fn(new_solver_json: str) -> SolverConfig:
#     return SolverConfig.model_validate_json(new_solver_json)


# overwrite_solver_tool = ToolDef(
#     name="overwrite_solver",
#     description="Overwrite the solver config",
#     parameters={
#         "new_solver_json": "The new solver config you would like to propose",
#     },
#     tool=overwrite_solver_fn,
# )


# def insert_user_message_in_place(message_str: str, index: int):
#     return message_str, index


# insert_user_message = ToolDef(
#     name="insert_user_message",
#     description="Insert a user message at index, then re-run everything afterwards",
#     parameters={
#         "message_str": "The message you would like to insert",
#         "index": "The index to insert the message at",
#     },
#     tool=insert_user_message_in_place,
# )


# def _visualize_config_diff(old_config: str, new_config: str, config_type: str) -> None:
#     """Visualize the difference between old and new configs."""
#     old_lines = json.dumps(json.loads(old_config), indent=2).splitlines(keepends=True)
#     new_lines = json.dumps(json.loads(new_config), indent=2).splitlines(keepends=True)

#     diff = list(
#         unified_diff(
#             old_lines,
#             new_lines,
#             fromfile=f"old_{config_type}",
#             tofile=f"new_{config_type}",
#             lineterm="",
#         )
#     )

#     if diff:
#         print(f"\n{config_type} Config Diff:")
#         print("".join(diff))
#     else:
#         print(f"\nNo changes in {config_type} config")


# def _visualize_message_insertion(
#     transcript_len: int,
#     index: int,
#     message: str,
#     context_messages: list[ChatMessage],
#     context_size: int = 2,
# ) -> None:
#     """Visualize where a message is being inserted in the transcript.

#     Args:
#         transcript_len: Total number of messages in transcript
#         index: Index where message will be inserted
#         message: Content of message to insert
#         context_messages: List of messages from the transcript
#         context_size: Number of messages to show before and after insertion point
#     """
#     print(f"\nInserting message at position {index} (out of {transcript_len} messages):")

#     # Show context before insertion
#     start_idx = max(0, index - context_size)
#     print("\nContext before insertion:")
#     for i in range(start_idx, index):
#         msg = context_messages[i]
#         role = "User" if isinstance(msg, ChatMessageUser) else "Assistant"
#         print(f"{i}. [{role}]: {msg.content[:200]}{'...' if len(msg.content) > 200 else ''}")

#     # Show new message
#     print(">>> Inserting new message here <<<")
#     print(f"{index}. {message}")


# async def run_mindiffer(
#     transcript: Transcript,
#     num_iterations: int = 1,
#     experiment_epochs: int = 10,
#     confirm_interventions: bool = False,
# ):
#     # if num_iterations > 1:
#     #     raise NotImplementedError(f"Multiple iterations not implemented, got {num_iterations}")

#     # Results
#     best_acc = 0.0
#     all_tool_calls: list[ToolCall] = []

#     ########################################
#     # Configure inputs to the investigator #
#     ########################################

#     docker_config = DockerConfig()
#     solver_config = SolverConfig()
#     state_config = StateConfig()

#     system_prompt = SYSTEM_PROMPT.format(
#         docker_config_schema=DockerConfig.model_json_schema(),
#         docker_config=DockerConfig(),
#         solver_config_schema=SolverConfig.model_json_schema(),
#         solver_config=SolverConfig(),
#         transcript=transcript.to_str(),
#     )
#     messages: list[ChatMessage] = [
#         # ChatMessageUser(content=system_prompt),
#         ChatMessageSystem(content=system_prompt),
#     ]
#     tools = [
#         get_tools_info(overwrite_docker_tool),
#         get_tools_info(overwrite_solver_tool),
#         get_tools_info(insert_user_message),
#     ]

#     ############################
#     # Logic for handling tools #
#     ############################

#     def handle_tool_call(tool_call: ToolCall, confirm: bool = False):
#         nonlocal docker_config
#         nonlocal solver_config
#         nonlocal state_config

#         try:
#             if tool_call.function == overwrite_docker_tool.name:
#                 old_docker = docker_config.model_dump_json()
#                 docker_config = overwrite_docker_tool.tool(tool_call.arguments["new_docker_json"])
#                 _visualize_config_diff(old_docker, tool_call.arguments["new_docker_json"], "Docker")

#             elif tool_call.function == overwrite_solver_tool.name:
#                 old_solver = solver_config.model_dump_json()
#                 solver_config = overwrite_solver_tool.tool(tool_call.arguments["new_solver_json"])
#                 _visualize_config_diff(old_solver, tool_call.arguments["new_solver_json"], "Solver")

#             elif tool_call.function == insert_user_message.name:
#                 message_str, index = insert_user_message.tool(
#                     tool_call.arguments["message_str"],
#                     tool_call.arguments["index"],
#                 )
#                 _visualize_message_insertion(
#                     len(transcript.messages), index, message_str, transcript.messages
#                 )
#                 per_sample_inits = state_config.per_sample_inits + [
#                     (
#                         int(transcript.sample_id),
#                         transcript.messages[:index] + [ChatMessageUser(content=message_str)],
#                     )
#                 ]
#                 state_config = StateConfig(per_sample_inits=per_sample_inits)
#         except Exception as e:
#             print(f"Error handling tool call: {e}")
#             traceback.print_exc()
#             messages.append(
#                 ChatMessageTool(
#                     tool_call_id=tool_call.id,
#                     function=tool_call.function,
#                     content="Error!",
#                     error=ToolCallError(message=str(e), type="unknown"),
#                 )
#             )
#             return

#         if confirm:
#             while True:
#                 response = input("Confirm intervention? (y/n) ").strip().lower()
#                 if response == "y":
#                     break
#                 elif response == "n":
#                     raise ValueError("Intervention not confirmed")
#                 print("Please enter 'y' or 'n'")

#         # Housekeeping
#         messages.append(
#             ChatMessageTool(
#                 tool_call_id=tool_call.id,
#                 function=tool_call.function,
#                 content="Done!",
#             )
#         )
#         all_tool_calls.append(tool_call)

#     #############
#     # Main loop #
#     #############

#     for it in range(num_iterations):
#         print_loud(f"Iteration {it + 1}")

#         # Add user input at the start of each turn
#         user_input = input("Enter your message (press Enter to skip): ").strip()
#         if user_input:
#             messages.append(ChatMessageUser(content=user_input))

#         # Query LLM
#         output = (
#             await get_llm_completions_async(
#                 messages_list=[messages],
#                 model_category="smart",
#                 default_provider="anthropic",
#                 # model_category="reasoning_fast",
#                 # default_provider="openai",
#                 # reasoning_effort="medium",
#                 tools=tools,
#                 tool_choice="auto",
#                 max_concurrency=1,
#                 max_new_tokens=8192,
#                 timeout=180.0,
#             )
#         )[0]
#         completion = output.first
#         if completion is None:
#             raise ValueError("No completion found")
#         messages.append(
#             ChatMessageAssistant(content=completion.text or "", tool_calls=completion.tool_calls)
#         )
#         print("Investigator output:")
#         print(completion.text)
#         if completion.tool_calls:
#             print(completion.tool_calls, flush=True)
#         print("Message state:")
#         print(messages, flush=True)

#         # Handle tool calls
#         did_intervene = False
#         if completion.tool_calls:
#             for tool_call in completion.tool_calls:
#                 handle_tool_call(tool_call, confirm=confirm_interventions)
#                 did_intervene = True

#         # # Print current state
#         # print("Current state:")
#         # print(docker_config)
#         # print(solver_config)
#         # print(state_config)

#         # Run the experiment
#         if did_intervene:
#             task_args = build_task_args(docker_config, solver_config, state_config)
#             experiment_result = await run_experiment_in_subprocess(
#                 "inspect_evals/luce_intercode_ctf",
#                 task_args,
#                 "openai/gpt-4o-mini",
#                 [transcript.sample_id],
#                 epochs=experiment_epochs,
#             )
#             print(experiment_result)

#             # Gather feedback
#             fpath = experiment_result["results"][0]
#             transcripts = load_transcripts_for_eval(f"new_experiment_{uuid4()}", fpath)
#             if transcripts:
#                 first_transcript = transcripts[0]
#                 num_correct = sum(t.metadata["correct"] for t in transcripts)
#                 acc = num_correct / len(transcripts)
#                 best_acc = max(best_acc, acc)

#                 messages.append(
#                     ChatMessageUser(
#                         content=f"""
# The LLM agent retried with your intervention, here are the results:
# Correct: {num_correct} / {len(transcripts)}

# Sample new transcript:

# {first_transcript.to_str()}
# """.strip()
#                     )
#                 )

#                 Transcript(sample_id="whatever", messages=messages).display_html()

#                 if num_correct > experiment_epochs / 2:
#                     break

#     return best_acc, all_tool_calls
