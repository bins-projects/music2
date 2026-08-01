import re
from dataclasses import dataclass

from compiler.repair import (
    DuplicateChoiceBlockRecord,
    RepairEntry,
    apply_repairs,
    create_duplicate_choice_block_record,
    exact_duplicate_choice_block,
)


@dataclass(frozen=True)
class DuplicateChoiceBatchPlan:
    proposals: tuple[DuplicateChoiceBlockRecord, ...]


def finding_id_for_duplicate_choice_block(question_id: str) -> str:
    safe_question = re.sub(r"[^A-Za-z0-9]+", "-", question_id)
    return f"PFQA-DUPLICATE-CHOICES-{safe_question}".upper()


def plan_exact_duplicate_choice_blocks(
    pack: dict,
    records: list[RepairEntry],
) -> DuplicateChoiceBatchPlan:
    candidate = apply_repairs(pack, records)
    proposals = []
    for question in candidate["questions"]:
        if exact_duplicate_choice_block(question) is None:
            continue
        proposals.append(
            create_duplicate_choice_block_record(
                candidate,
                question_id=question["id"],
                repair_id=finding_id_for_duplicate_choice_block(
                    question["id"]
                ),
            )
        )
    return DuplicateChoiceBatchPlan(proposals=tuple(proposals))
