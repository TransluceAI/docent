from inspect_ai.dataset import MemoryDataset, Sample

from inspect_evals.vas.src.api.cp import ChallengeProjectReadOnly

import json

solution_data = json.load(
    open("/home/ubuntu/clarity/external/inspect_evals/src/inspect_evals/vas/src/dataset/solutions.json")
)


def cp_to_dataset(project: ChallengeProjectReadOnly):
    cpvs = project.get_cpv_info()

    # TODO(vincent): add solution hints

    return MemoryDataset([
        Sample(
            input=cpv,
            target=project.sanitizer_str[sanitizer_id],
            id=int(cpv.replace("cpv", "")),
            metadata={
                "cpv": cpv,
                "cp_source": cp_source,
                "harness_id": harness_id,
                "sanitizer_id": sanitizer_id,
                "sanitizer": project.sanitizer_str[sanitizer_id],
                "files": files,
                "other_patches": other_patches,
                "language": project.language,
                "hint1": solution_data[cpv][0],
                "hint2": solution_data[cpv][1],
            },
        )
        for cpv, cp_source, harness_id, sanitizer_id, files, other_patches in cpvs
    ])
