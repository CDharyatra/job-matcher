"""Golden-set evaluation. Live submit stays frozen until auto-apply precision >= 0.80.

The golden set is a YAML file (labels/golden_set.yaml) of jobs with a human label:
  label: apply | inbox | discard
and the pipeline's score/route for each. Precision for the 70-90 auto-apply band is
the fraction of jobs the system would auto-apply whose human label is 'apply'.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .clean import BUCKET_APPLY, BUCKET_DISCARD, BUCKET_INBOX
from .config import load_config
from .facts import load_facts
from .llm.adapter import LLMClient
from .logging_setup import get_logger
from .matcher import match_job
from .models import Job
from .paths import HOME

log = get_logger("jobagent.evaluate")
GOLDEN_PATH = HOME / "labels" / "golden_set.yaml"


@dataclass
class EvalReport:
    total: int
    apply_predicted: int
    apply_correct: int
    precision: float
    passed: bool
    detail: list[dict]
    apply_labeled: int = 0
    recall: float = 0.0
    f1: float = 0.0
    confusion: dict = None

    def __str__(self) -> str:
        lines = [
            f"Golden set: {self.total} jobs",
            f"Would auto-apply: {self.apply_predicted}",
            f"Correct among those: {self.apply_correct}",
            f"Auto-apply precision: {self.precision:.2f}",
            f"Auto-apply recall: {self.recall:.2f} "
            f"({self.apply_correct}/{self.apply_labeled} labeled-apply caught)",
            f"Auto-apply F1: {self.f1:.2f}",
            f"Gate (precision >= 0.80): {'PASS' if self.passed else 'FAIL -- keep dry-run'}",
        ]
        if self.confusion:
            lines.append("Confusion (label -> prediction):")
            for (label, bucket), n in sorted(self.confusion.items()):
                lines.append(f"  {label:8} -> {bucket:12} : {n}")
        for d in self.detail:
            lines.append(f"  {d['title'][:40]:40} pred={d['bucket']:12} label={d['label']:8} score={d['score']}")
        return "\n".join(lines)


def run_evaluation(path: Path | None = None, use_llm: bool = True) -> EvalReport:
    path = path or GOLDEN_PATH
    cfg = load_config()
    facts = load_facts()
    from .resume import load_or_build
    files = [f.get("path", "") for f in (facts.application.get("resume_files") or []) if isinstance(f, dict)]
    profile = load_or_build(files)
    llm = LLMClient(cfg) if use_llm else None
    from .llm.rerank import RerankClient
    rerank = RerankClient(cfg) if use_llm else None

    if not path.exists():
        log.warning("no golden set at %s", path)
        return EvalReport(0, 0, 0, 0.0, False, [])

    rows = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    apply_pred = apply_correct = apply_labeled = 0
    confusion = {}
    detail = []
    for i, row in enumerate(rows):
        job = Job(
            source=row.get("source", "linkedin"), canonical_url=row.get("url", f"golden://{i}"),
            title=row.get("title", ""), company=row.get("company", ""),
            location=row.get("location", ""), description_text=row.get("description", ""),
            apply_type=row.get("apply_type", "easy_apply"),
            experience_min=row.get("experience_min"), experience_max=row.get("experience_max"),
            salary_raw=row.get("salary_raw", ""), posted_at=row.get("posted_at"),
        )
        res = match_job(job, i, facts, cfg, profile, llm=llm, use_llm=use_llm,
                        rerank=rerank)
        bucket = res.decision.bucket
        label = row.get("label", "")
        confusion[(label, bucket)] = confusion.get((label, bucket), 0) + 1
        if label == "apply":
            apply_labeled += 1
        if bucket == BUCKET_APPLY:
            apply_pred += 1
            if label == "apply":
                apply_correct += 1
        detail.append({"title": job.title, "bucket": bucket, "label": label, "score": res.overall_match})
    precision = (apply_correct / apply_pred) if apply_pred else 0.0
    recall = (apply_correct / apply_labeled) if apply_labeled else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return EvalReport(len(rows), apply_pred, apply_correct, precision, precision >= 0.80, detail,
                      apply_labeled=apply_labeled, recall=recall, f1=f1, confusion=confusion)