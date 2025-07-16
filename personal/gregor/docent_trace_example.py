"""
Multi-Turn Customer Service Chat Evaluation using Inspect AI
"""

# Initialize OpenTelemetry
from docent_trace import agent_run_score, initialize_tracing, transcript_context
from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.model import ChatMessageAssistant, ChatMessageSystem, ChatMessageUser, get_model
from inspect_ai.scorer import Score, Target, accuracy, mean, scorer
from inspect_ai.solver import Generate, solver
from inspect_ai.tool import tool

# Initialize OpenTelemetry for this service
initialize_tracing(collection_name="multi-turn-chat-eval")


# Sample tools for customer service agent
@tool
def lookup_customer():
    async def execute(email: str):
        """Look up customer information by email address.

        Args:
            email: The email address of the customer to look up
        """
        # Simulate customer lookup
        if email == "john@email.com":
            return f"Customer: John Smith, Account: ACT-12345, Status: Active"
        else:
            return f"Customer not found for email: {email}"

    return execute


@tool
def check_order_status():
    async def execute(order_number: str):
        """Check the status of an order by order number.

        Args:
            order_number: The order number to check
        """
        # Simulate order lookup
        if order_number == "12345":
            return f"Order #{order_number}: Blue Sweater, Size M, Status: Delivered on 2024-01-15"
        else:
            return f"Order not found for order number: {order_number}"

    return execute


@tool
def initiate_password_reset():
    async def execute(email: str):
        """Initiate a password reset for the given email address.

        Args:
            email: The email address to send the password reset to
        """
        return f"Password reset email sent to {email}. Please check your inbox."

    return execute


@tool
def create_return_request():
    async def execute(order_number: str, reason: str):
        """Create a return request for an order.

        Args:
            order_number: The order number to create a return for
            reason: The reason for the return request
        """
        return f"Return request created for order #{order_number}. Reason: {reason}. Return label sent to customer email."

    return execute


# Sample conversation scenarios
SCENARIOS = [
    {
        "scenario": "Password Reset",
        "turns": [
            "Hi, I can't log into my account",
            "I think I forgot my password. My email is john@email.com",
            "I don't see the reset email anywhere",
        ],
    },
    {
        "scenario": "Product Return",
        "turns": [
            "I want to return something I bought",
            "It's order #12345, a sweater that doesn't fit",
            "Do I need to pay for return shipping?",
        ],
    },
    # {
    #     "scenario": "Billing Question",
    #     "turns": [
    #         "I have a question about my bill",
    #         "There's a $29.99 charge I don't recognize",
    #         "Can you remove this charge?"
    #     ]
    # }
]


@solver
def multi_turn_solver():
    """Solver that conducts multi-turn conversations with tools"""

    async def solve(state, generate: Generate):

        # Create solver transcript context with agent_run_id and transcript_id (auto-detects async context)
        async with transcript_context() as (context, agent_run_id, transcript_id):
            # Add system message
            system_prompt = """You are a helpful customer service representative.
            Be polite, professional, and work to resolve customer issues.
            You have access to tools to help customers with their requests.
            Use tools when appropriate to provide accurate information and assistance."""

            state.messages = [ChatMessageSystem(content=system_prompt)]

            # Add tools to the state
            state.tools = [
                lookup_customer(),
                check_order_status(),
                initiate_password_reset(),
                create_return_request(),
            ]

            # Get conversation turns
            turns = state.metadata.get("turns", [])
            responses = []
            tool_usage = []

            # Conduct conversation
            for i, user_message in enumerate(turns):
                # Add user message
                state.messages.append(ChatMessageUser(content=user_message))

                # Generate response (may include tool calls)
                state = await generate(state)

                # Track tool usage if any
                if hasattr(state.output, "tool_calls") and state.output.tool_calls:
                    for tool_call in state.output.tool_calls:
                        tool_usage.append(
                            {
                                "turn": i + 1,
                                "tool_name": tool_call.function.name,
                                "arguments": tool_call.function.arguments,
                                "result": getattr(tool_call, "result", "N/A"),
                            }
                        )

                # Store response
                if state.output and state.output.completion:
                    response = state.output.completion
                    responses.append(response)
                    # Add assistant message to conversation history
                    state.messages.append(ChatMessageAssistant(content=response))

            # Store conversation data for scoring
            state.metadata["responses"] = responses
            state.metadata["user_turns"] = turns
            state.metadata["tool_usage"] = tool_usage
            state.metadata["agent_run_id"] = agent_run_id  # Store agent_run_id for scorer to use
            state.metadata["solver_transcript_id"] = transcript_id  # Store solver transcript_id

            return state

    return solve


@scorer(metrics=[accuracy(), mean()])
def conversation_scorer():
    """Score the multi-turn conversation quality"""

    async def score(state, target: Target):

        responses = state.metadata.get("responses", [])
        user_turns = state.metadata.get("user_turns", [])
        tool_usage = state.metadata.get("tool_usage", [])
        scenario = state.input
        agent_run_id = state.metadata.get("agent_run_id", "unknown")

        if not responses:
            return Score(value=0.0, explanation="No responses generated")

        # Create scoring transcript context with same agent_run_id but different transcript_id (auto-detects async context)
        async with transcript_context(agent_run_id=agent_run_id) as (context, _, transcript_id):
            # Create evaluation prompt
            conversation = []
            for i, (user_msg, response) in enumerate(zip(user_turns, responses)):
                conversation.append(f"Turn {i+1}:")
                conversation.append(f"User: {user_msg}")
                conversation.append(f"Agent: {response}")
                conversation.append("")

            # Add tool usage information to the conversation
            tool_info = ""
            if tool_usage:
                tool_info = "\n\nTools Used:\n"
                for tool in tool_usage:
                    tool_info += f"- Turn {tool['turn']}: {tool['tool_name']}({tool['arguments']}) → {tool['result']}\n"

            eval_prompt = f"""
Rate this customer service conversation from 0.0 to 1.0 based on:
- Helpfulness and professionalism
- Context awareness across turns
- Problem-solving approach
- Appropriate use of tools when needed

Scenario: {scenario}

Conversation:
{chr(10).join(conversation)}{tool_info}

Provide only a decimal number between 0.0 and 1.0:"""

            try:
                # Use model to evaluate
                evaluator = get_model()
                eval_result = await evaluator.generate(eval_prompt)

                # Parse score
                score_text = eval_result.completion.strip()
                try:
                    score_value = float(score_text)
                    score_value = max(0.0, min(1.0, score_value))
                except ValueError:
                    score_value = 0.5

                # Record the conversation quality score
                agent_run_score(
                    name="conversation_quality",
                    score=score_value,
                )

                # Record tool usage metrics
                if tool_usage:
                    agent_run_score(
                        name="tool_usage_effectiveness",
                        score=min(1.0, len(tool_usage) / len(user_turns)),  # Tool usage ratio
                    )

                return Score(
                    value=score_value, explanation=f"Conversation quality: {score_value:.2f}"
                )

            except Exception as e:
                return Score(value=0.0, explanation=f"Evaluation error: {str(e)}")

    return score


@task
def multi_turn_chat():
    """Multi-turn customer service chat evaluation"""

    # Create samples from scenarios
    samples = []
    for i, scenario_data in enumerate(SCENARIOS):
        sample = Sample(
            id=f"scenario_{i}",
            input=scenario_data["scenario"],
            target="Provide helpful customer service",
            metadata={"turns": scenario_data["turns"], "scenario_name": scenario_data["scenario"]},
        )
        samples.append(sample)

    return Task(
        dataset=MemoryDataset(samples), solver=multi_turn_solver(), scorer=conversation_scorer()
    )
