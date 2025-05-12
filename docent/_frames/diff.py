from docent._frames.transcript import MULTI_BLOCK_CITE_INSTRUCTION, Transcript
from docent._llm_util.prod_llms import get_llm_completions_async
from docent._llm_util.provider_preferences import PROVIDER_PREFERENCES


async def compare_transcripts(
    transcript_1: Transcript,
    transcript_2: Transcript,
) -> str:
    prompt = f"""
Here are two different sequences of actions an agent took to solve a task.
First transcript:
{transcript_1.to_str(transcript_idx_label=0)}
Second transcript:
{transcript_2.to_str(transcript_idx_label=1)}
Provide a CONCISE summary of key differences between the two transcripts. Do not re-explain individual transcripts.
We are interested in all kinds of key differences. Some examples (but you should not feel limited by these):
- Instances where one agent took actions that resulted in success while the other had critical mistakes or misconceptions
- Instances where one agent used tools in a very different way than the other
- Instances where one agent had very different higher-level strategies or approaches than the other
- Instances where one agent hallucinates a lot more than the other
- Significant differences in vibes or personality
Avoid repeating yourself in the output and avoid mentioning topics extremely similar to previously mentioned topics.
Always refer to the first transcript as "Agent 1" and the second as "Agent 2".
You are encouraged to cite evidence from the transcripts: {MULTI_BLOCK_CITE_INSTRUCTION}.
Avoid mentioning actions that both agents took, since that can never count as evidence for the two agents being different.
Format your output as follows:
Claim 1: agent 1 exhibits more of feature X than agent 2
Evidence 1: ways in which agent 1 is more of X than agent 2, with citations
Claim 2: agent 1 exhibits more of feature Y than agent 2
Evidence 2: ways in which agent 1 is more of Y than agent 2, with citations
...
    """.strip()

    outputs = await get_llm_completions_async(
        [
            [
                {
                    "role": "user",
                    "content": prompt,
                },
            ]
        ],
        PROVIDER_PREFERENCES.compare_transcripts,
        max_new_tokens=8192 * 2,
        timeout=180.0,
        use_cache=True,
    )

    text = outputs[0].first_text
    if text is None:
        return ""
    return text


NO_EVIDENCE_STR = "There is no evidence for this claim."


async def get_evidence_for_claims(
    transcript_1: Transcript,
    transcript_2: Transcript,
    claims: list[str],
) -> str:
    if claims == []:
        return ""
    prompt = f"""
Here are two different sequences of actions an agent took to solve a task.
First transcript:
{transcript_1.to_str(transcript_idx_label=0)}
Second transcript:
{transcript_2.to_str(transcript_idx_label=1)}
Someone has proposed a list of differences between the two agents / transcripts. Many of these are unsubstantiated claims.
For each difference, your job is to either provide evidence supporting the claim, or to say that the claim has no evidence.
Always refer to the first transcript as "Agent 1" and the second as "Agent 2". Do not re-explain individual transcripts.
You are encouraged to cite evidence from the transcripts: {MULTI_BLOCK_CITE_INSTRUCTION}.
Avoid mentioning actions that both agents took, since that can never count as evidence for the two agents being different.
You will be given claims in the following format:
Claim 1: agent 1 exhibits more of feature X than agent 2
Claim 2: agent 1 exhibits more of feature Y than agent 2
...
Format your output as follows:
Evidence 1: <if the claim does not ever seem to be true, write "{NO_EVIDENCE_STR}" and nothing else. Otherwise, explain ways in which agent 1 is more of X than agent 2, with citations; jump directly to the evidence with no additional commentary>
Evidence 2: <if the claim does not ever seem to be true, write "{NO_EVIDENCE_STR}" and nothing else. Otherwise, explain ways in which agent 1 is more of Y than agent 2, with citations; jump directly to the evidence with no additional commentary>
Here are the claims:
{"\n".join(claims)}
    """.strip()

    outputs = await get_llm_completions_async(
        [
            [
                {
                    "role": "user",
                    "content": prompt,
                },
            ]
        ],
        PROVIDER_PREFERENCES.compare_transcripts,
        max_new_tokens=8192 * 2,
        timeout=180.0,
        use_cache=True,
    )

    text = outputs[0].first_text
    if text is None:
        return ""
    return text


def extract_claims_and_evidence(llm_output: str) -> tuple[list[str], list[str]]:
    if llm_output == "":
        return [], []
    lines = llm_output.split("\n")
    claims: list[str] = []
    evidences: list[str] = []
    for line in lines:
        if line.startswith("Claim"):
            claims.append(line.split(":")[1].strip())
        elif line.startswith("Evidence"):
            evidences.append(line.split(":")[1].strip())
    return claims, evidences


def swap_agent_indices_and_citaitons(evidence: str) -> str:
    evidence = (
        evidence.replace("Agent 1", "Agent 3")
        .replace("Agent 2", "Agent 1")
        .replace("Agent 3", "Agent 2")
    )
    # get [T0Bx], [T0Bx-T0By] and replace with [T1Bx], [T1Bx-T1By], vice versa
    evidence = evidence.replace("T0B", "T2B").replace("T1B", "T0B").replace("T2B", "T1B")
    return evidence


def extract_reverse_evidence(llm_output: str) -> list[str]:
    if llm_output == "":
        return []
    lines = llm_output.split("\n")
    evidence_number = 1
    evidences: list[str] = []
    current_evidence = ""
    for line in lines:
        new_evidence_prefix = f"Evidence {evidence_number}: "
        if line.startswith(new_evidence_prefix):
            if evidence_number > 1:
                evidences.append(current_evidence)
            current_evidence = line.removeprefix(new_evidence_prefix)
            evidence_number += 1
        else:
            current_evidence += "\n" + line
    evidences.append(current_evidence)
    for i, evidence in enumerate(evidences):
        if evidence.find(NO_EVIDENCE_STR) != -1:
            evidences[i] = "There is no evidence for the reverse claim."
        else:
            current_evidence = evidence
            # TODO(vincent): figure out how to prompt so this doesn't get said
            if current_evidence.startswith("There is evidence for this claim. "):
                current_evidence = current_evidence.removeprefix(
                    "There is evidence for this claim. "
                )
            current_evidence = swap_agent_indices_and_citaitons(current_evidence)
            evidences[i] = current_evidence
    return evidences


from pydantic import BaseModel


class TranscriptPairDiff(BaseModel):
    claims: list[str]
    evidences: list[str]
    reverse_evidences: list[str]

    # trim to shortest length
    def __post_init__(self):
        min_length = min(len(self.claims), len(self.evidences), len(self.reverse_evidences))
        self.claims = self.claims[:min_length]
        self.evidences = self.evidences[:min_length]
        self.reverse_evidences = self.reverse_evidences[:min_length]

    def __str__(self) -> str:
        num_claims = len(self.claims)
        result = ""
        for i in range(num_claims):
            result += f"Claim: {self.claims[i]}\n"
            result += f"Evidence: {self.evidences[i]}\n"
            result += f"Reverse Evidence: {self.reverse_evidences[i]}\n"
            if i < num_claims - 1:
                result += "-" * 16 + "\n"
        return result


full_results: dict[str, TranscriptPairDiff] = {}


async def compute_diff_and_evidence(
    t1: Transcript, t2: Transcript
) -> tuple[tuple[str, str, str], ...]:
    initial_diff = await compare_transcripts(t1, t2)
    claims, evidences = extract_claims_and_evidence(initial_diff)
    reverse_evidence = await get_evidence_for_claims(t2, t1, claims)
    reverse_evidences = extract_reverse_evidence(reverse_evidence)
    min_length = min(len(claims), len(evidences), len(reverse_evidences))
    return tuple((claims[i], evidences[i], reverse_evidences[i]) for i in range(min_length))
