import random
from pathlib import Path

marked_neg = """
2025-05-05T23-45-20+00-00_vulnerability-detection-0.1.7_gYf6Xu25QYicsp9BugQkeF.eval
2025-04-17T15-36-56+00-00_automatic-jailbreak_KePp2Uy7YvUPRQvWtk6TTj.eval
2025-04-17T15-29-34+00-00_web-hacking_nKt8Y7zXqMJn58idbxaBYX.eval
2025-05-06T16-38-10+00-00_sadservers-0.1.8_Ag8YTgWDABP8jFS7wN2SHd.eval
[ext] 2025-05-05T15-44-23+00-00_palisade-crackme-0.3.0_anthropic-claude-3-7-sonnet-20250219_JbmRvwsL7KJuuH7YDcncWe.eval
[ext] 2025-05-05T15-52-11+00-00_automatic-jailbreak-1.0.5_SgbaWXvpoVSRWo6TKAWECy.eval
2025-05-13T19-47-48+00-00_pico-ctf_VJMFAPT43m56emdLkAV98V.eval
[ext] 2025-05-02T18-49-46+00-00_adversarially-robust-models-0.2.5_anthropic-claude-3-7-sonnet-20250219_b5UxPnskJEALVjFQT2ycQs.eval
[ext] 2025-05-05T15-41-22+00-00_inference-optimization-1.0.3_anthropic-claude-3-7-sonnet-20250219_NArqapcwgXE3VR8ikt6gJZ.eval
2025-05-07T05-22-07+00-00_inference-optimization-1.0.3_gpt-4.1-mini_JbpXaYG2UqbSuArFUKKDFA.eval
2025-04-17T15-37-23+00-00_local-research-tex-2_gWNFCTEeMXyboSuEBn5uA4.eval
[ext] 2025-04-30T22-48-09+00-00_acronym-chatbot-0.1.4_anthropic-claude-3-7-sonnet-20250219_WeuvjFPYB5MQecro8USevH.eval
2025-05-15T09-41-38+00-00_inference-optimization-1.0.3_kEV722khMLqh8Asmv4Ytuz.eval
2025-05-05T17-40-55+00-00_continue-pattern-1.2.2_n8rx5hDgur2QgQNtCYz6yj.eval
2025-04-17T15-42-50+00-00_backdoor-image-classifier_iJY2Fa8ny8tPnYoWFBn29s.eval
2025-04-17T15-34-25+00-00_make-web-server_ZPPwGjgFrTCtgBwqzTExuT.eval
apps-dataset-debug.eval
2025-05-05T19-07-38+00-00_eliciting-secret-1.1.1_8VUFX5HwXEWTYg6e3BuN8o.eval
2025-05-10T00-12-43+00-00_eliciting-secret-1.1.1_4oUrRkfSjewnfwTAmh6Eof.eval
2025-04-17T15-30-24+00-00_sentiment-probe_bTqMdqrE8THHZp5n57zAL5.eval
[ext] 2025-05-01T14-55-03+00-00_iclr-authors-2.0.0_9VwjB7sepfgtoDG4CQECkc.eval
[ext] 2025-04-30T22-37-18+00-00_pytorch-gc-bug-1.0.4_openai-gpt-4.1-mini-2025-04-14_noxLSWycKY9bnGxQodLMts.eval
2025-05-07T02-59-00+00-00_few-shot-prompting-0.2.0_mvSiyJyrhdYwLms9hgT6K6.eval
[ext] 2025-05-01T14-58-13+00-00_oxdna-simple-0.1.7_Q5u5iJoSYBUJD9hF7Rqgqd.eval
2025-04-17T15-31-01+00-00_data-deduplication_4VR2u95Ca2jRphgsA38KBC.eval
2025-05-07T02-59-00+00-00_few-shot-prompting-0.2.0_claude-3-7-sonnet_mvSiyJyrhdYwLms9hgT6K6.eval
[ext] 2025-05-01T14-46-02+00-00_file-recovery-1.0.8_Cw9E4Uchz8wfagDJGufStg.eval
2025-05-06T16-38-10+00-00_sadservers-0.1.8_RZTEPrsK4DMNJKkLuusApS.eval
2025-04-17T15-42-44+00-00_data-cleaning-arjun_gxGRZuhffWLLfDYi42NCb5.eval
[ext] 2025-05-04T16-26-31+00-00_hash-collision-1.0.4_anthropic-claude-3-7-sonnet-20250219_LjYTPeJtWoQ3ZQWxwNyBiu.eval
2025-05-14T14-04-10+00-00_icpc_F5duxNX62TGLYmX4wvD6un.eval
2025-05-05T19-16-58+00-00_esolang-0.1.6_mjKPm3ymTGiFRXsVnTk6Q8.eval
[ext] 2025-05-05T15-47-00+00-00_anti-bot-site-1.0.3_a7b5WJrL8a6R2PKJJ74gbp.eval
[ext] 2025-05-05T17-40-55+00-00_continue-pattern-1.2.2_n8rx5hDgur2QgQNtCYz6yj.eval
2025-04-17T15-29-44+00-00_sparse-adversarial-perturbations_K7MXBzrWcj5uJ4yViDHwUP.eval
2025-04-17T15-31-06+00-00_tensor-parallelisms_MbhSpAQG7QbQvdJVJcfJup.eval
2025-04-17T15-27-26+00-00_file-recovery_9ZeH4HodpBekiCiBUovrxn.eval
2025-05-05T19-16-58+00-00_esolang-0.1.6_k7y9KXMbkV7QkiBSzBsopC.eval
[ext] 2025-05-01T14-59-52+00-00_pytorch-gc-bug-1.0.4_mSEFk2ePQhHJtQhamtJFUi.eval
[ext] 2025-05-05T17-38-44+00-00_collect-personal-info-0.2.2_jUbt72GJgfx23LEkMJd4V4.eval
2025-05-07T02-34-34+00-00_eliciting-secret-1.1.1_5REerktVh4Javaoynqswth.eval
2025-05-14T13-55-29+00-00_icpc_bRRUtWM3YvULvYZi9gnGwC.eval
2025-05-07T02-59-17+00-00_inference-optimization-1.0.3_claude-3-7-sonnet_NnxEzriParDitRjyVKMzmf.eval
2025-05-14T12-49-00+00-00_icpc_PcqibnxTe3rSuQSEZiBxit.eval
2025-04-17T15-42-23+00-00_molecule-structure_4APwpBkuXcFWXpLwovhGMJ.eval
2025-04-17T15-42-35+00-00_machine-learning-local_hJADLJdfPPhVLZCiPfWohh.eval
2025-05-14T12-51-44+00-00_icpc_dFbEbLmYrxt7U3F8w4dUXF.eval
[ext] 2025-05-01T17-20-47+00-00_search-server-0.2.7_KeAsqGs3yhtkcxoaYaRW7j.eval
2025-05-05T19-07-38+00-00_eliciting-secret-1.1.1_Vnr4y7BBDBoqotPfisRdbX.eval
2025-05-11T03-33-08+00-00_mlab-2.1.3_aUBVfFmauzQTFFtsbeTXSh.eval
[ext] 2025-05-04T16-51-42+00-00_tree-traversal-kernel-0.1.4_anthropic-claude-3-7-sonnet-20250219_KYXaksMFoQ3uJhtybEenxQ.eval
2025-05-07T05-22-07+00-00_inference-optimization-1.0.3_JbpXaYG2UqbSuArFUKKDFA.eval
[ext] 2025-05-01T14-59-52+00-00_pytorch-gc-bug-1.0.4_eEDty9wnjSybgQpqrNxBFJ.eval
[ext] 2025-05-05T15-41-21+00-00_implement-ace-oauth-1.1.3_anthropic-claude-3-7-sonnet-20250219_5ufZQAPvbCyFKapiNKe7VR.eval
2025-05-06T00-10-02+00-00_uav-search-1.0.5_2xPfSm5JvToyN5rftLBG3v.eval
2025-05-14T12-49-00+00-00_icpc_ctbigVvh5Gr2qNufuxryUU.eval
[ext] 2025-05-05T15-46-59+00-00_adversarially-robust-models-0.2.5_ANnNV6zYXQsAdykmYnZXcZ.eval
[ext] 2025-05-01T14-46-02+00-00_file-recovery-1.0.8_ek2EoLvTrFvGBRKjMmpbWM.eval
[ext] 2025-05-01T14-45-09+00-00_few-shot-prompting-0.2.0_Qh3azJGVmoEx4bmadUPcPG.eval
[ext] 2025-05-01T14-58-13+00-00_oxdna-simple-0.1.7_c9jQ2zLXodWC5HWMHaVAYz.eval
[ext] 2025-05-05T17-38-44+00-00_collect-personal-info-0.2.2_B7YPvNXWdHonmTvj9sE9Np.eval
[ext] 2025-05-05T15-45-57+00-00_uav-search-1.0.5_anthropic-claude-3-7-sonnet-20250219_2nJc7FCzgzh4fYm69WftBs.eval
[ext] 2025-05-01T17-05-06+00-00_adversarially-robust-models-0.2.5_2kKAb7gEVRUYfwWunAYiJH.eval
2025-05-07T10-14-21+00-00_implement-ace-oauth-1.1.3_Jyh3rHMpcxyQg5pmmiH4hq.eval
2025-05-07T02-59-17+00-00_inference-optimization-1.0.3_NnxEzriParDitRjyVKMzmf.eval
[ext] 2025-05-05T15-52-11+00-00_automatic-jailbreak-1.0.5_RCZopQfbg7BJXereY9EzXv.eval
""".strip().split(
    "\n"
)


def sample_eval_files(max_files=100):
    current_dir = Path.cwd()

    # First, find all marked negative files that exist
    marked_neg_found = []
    missing = 0
    for fname in marked_neg:
        fname = fname.strip()
        if fname:  # Skip empty lines
            pattern = fname.replace("[ext]", "[[]ext[]]")
            matches = list(current_dir.rglob(f"*{pattern}*"))
            if matches:
                marked_neg_found.extend(matches)
            else:
                print(f"warn: could not find {fname}")
                missing += 1
    print(f"missing: {missing} / {len(marked_neg)} negative files")

    # Remove duplicates
    marked_neg_found = list(set(marked_neg_found))

    # Get all eval files
    all_eval_files = list(current_dir.rglob("*.eval"))

    # Remove marked negative files from the pool to avoid duplicates
    remaining_files = [f for f in all_eval_files if f not in marked_neg_found]

    # Calculate how many more files we need
    remaining_slots = max_files - len(marked_neg_found)

    # Sample from remaining files if we need more
    if remaining_slots > 0 and remaining_files:
        if len(remaining_files) <= remaining_slots:
            additional_files = remaining_files
        else:
            additional_files = random.sample(remaining_files, remaining_slots)
    else:
        additional_files = []

    # Combine marked negative files with additional sampled files
    sampled_files = marked_neg_found + additional_files
    print(
        f"sampled: {len(marked_neg_found)} negative + {len(additional_files)} other = {len(sampled_files)} total"
    )

    return sampled_files


def copy_sampled_files(sampled_files, output_dir="sampled_evals"):
    import shutil

    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)

    for file_path in sampled_files:
        dest_path = output_path / file_path.name
        shutil.copy2(file_path, dest_path)
        print(f"Copied: {file_path.name}")

    print(f"All files copied to {output_path}")


if __name__ == "__main__":
    ans = sample_eval_files()
    copy_sampled_files(ans)
