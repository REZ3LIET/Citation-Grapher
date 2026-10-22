from __future__ import annotations

import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from .config import Settings, get_settings
from .database import SessionLocal
from ..discovery.scheduler import Candidate, schedule_balanced
from ..exports import export_run
from ..models import CitationRecord, PaperRecord, RunRecord
from ..providers import OpenAlexClient, ProviderBudgetExceeded, ProviderRateLimited, Work
from ..providers.arxiv import resolve_arxiv
from ..topics import TopicAnnotator


ACTIVE_PHASES = {
    "created", "resolving", "collecting_frontier", "scheduling_frontier",
    "completing_edges", "annotating", "exporting",
}


class RunFailure(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def loads(value: str, default):
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def work_from_paper(paper: PaperRecord) -> Work:
    raw = loads(paper.raw_json, {})
    return Work(
        canonical_id=paper.canonical_id,
        openalex_id=paper.openalex_id,
        doi=paper.doi,
        arxiv_id=paper.arxiv_id,
        title=paper.title,
        authors=loads(paper.authors_json, []),
        year=paper.year,
        venue=paper.venue,
        abstract=paper.abstract,
        url=paper.url,
        citation_count=paper.provider_citation_count,
        referenced_works=[item.rsplit("/", 1)[-1] for item in raw.get("referenced_works", [])],
        raw=raw,
    )


class DiscoveryRunner:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="citation-discovery")
        self._scheduled: set[str] = set()
        self._lock = threading.Lock()

    def enqueue(self, run_id: str) -> None:
        with self._lock:
            if run_id in self._scheduled:
                return
            self._scheduled.add(run_id)
        self.executor.submit(self._execute_guarded, run_id)

    def resume_interrupted(self) -> None:
        with SessionLocal() as session:
            records = session.scalars(select(RunRecord).where(RunRecord.phase.in_(ACTIVE_PHASES))).all()
            # A local deployment has one worker. Leases loaded at application
            # startup belong to the previous process and are safe to reclaim.
            for run in records:
                run.lease_owner = None
                run.lease_expires_at = None
            session.commit()
            ids = [run.id for run in records]
        for run_id in ids:
            self.enqueue(run_id)

    def _execute_guarded(self, run_id: str) -> None:
        try:
            self._execute(run_id)
        except Exception as exc:  # provider failures should not kill the API process
            with SessionLocal() as session:
                run = session.get(RunRecord, run_id)
                if run:
                    run.error = str(exc) if isinstance(exc, RunFailure) else f"{type(exc).__name__}: {exc}"
                    retained = session.scalar(
                        select(func.count(PaperRecord.id)).where(PaperRecord.run_id == run_id)
                    ) or 0
                    if not isinstance(exc, RunFailure) and retained:
                        coverage = loads(run.coverage_json, {})
                        coverage["retrieval_complete"] = False
                        coverage.setdefault("limitations", []).append({
                            "reason": "level_processing_error",
                            "level": loads(run.checkpoint_json, {}).get("depth", 0) + 1,
                            "error_type": type(exc).__name__,
                        })
                        run.coverage_json = dumps(coverage)
                        counters = loads(run.counters_json, {})
                        counters["papers"] = retained
                        counters["citations"] = session.scalar(
                            select(func.count(CitationRecord.id)).where(CitationRecord.run_id == run_id)
                        ) or 0
                        counters["discovered_papers"] = session.scalar(
                            select(func.count(PaperRecord.id)).where(
                                PaperRecord.run_id == run_id, PaperRecord.is_seed.is_(False)
                            )
                        ) or 0
                        run.counters_json = dumps(counters)
                        run.phase = "completed_partial"
                        run.outcome = "level_processing_error"
                        session.commit()
                        try:
                            export_run(session, run, self.settings.runs_dir)
                        except Exception as export_exc:
                            run.error += f"; partial export failed: {type(export_exc).__name__}: {export_exc}"
                            session.commit()
                    else:
                        run.phase = "failed"
                        run.outcome = exc.code if isinstance(exc, RunFailure) else "failed"
                        session.commit()
        finally:
            with self._lock:
                self._scheduled.discard(run_id)

    def _consume_request(self, session, run: RunRecord) -> None:
        counters = loads(run.counters_json, {})
        used = counters.get("provider_requests", 0)
        if used >= self.settings.max_provider_requests_per_run:
            raise ProviderBudgetExceeded("Run-wide provider request budget reached")
        counters["provider_requests"] = used + 1
        run.counters_json = dumps(counters)
        session.commit()  # request budget is durable before network activity

    @staticmethod
    def _add_warning(run: RunRecord, code: str, message: str, **details) -> None:
        warnings = loads(run.warnings_json, [])
        warnings.append({"code": code, "message": message, **details})
        run.warnings_json = dumps(warnings)

    @staticmethod
    def _add_exclusion(run: RunRecord, reason: str, value: str, **details) -> None:
        exclusions = loads(run.exclusions_json, [])
        exclusions.append({"reason": reason, "value": value, **details})
        run.exclusions_json = dumps(exclusions)

    def _mark_incomplete(self, run: RunRecord, reason: str, **details) -> None:
        coverage = loads(run.coverage_json, {})
        coverage["retrieval_complete"] = False
        coverage.setdefault("limitations", []).append({"reason": reason, **details})
        run.coverage_json = dumps(coverage)

    @staticmethod
    def _record_retrieval(run: RunRecord, report: dict) -> None:
        coverage = loads(run.coverage_json, {})
        coverage.setdefault("retrieval_attempts", []).append(report)
        counts = coverage.setdefault("candidate_counts", {"forward": 0, "backward": 0})
        direction = report.get("direction")
        if direction in counts:
            counts[direction] += int(report.get("retrieved") or 0)
        run.coverage_json = dumps(coverage)

    @staticmethod
    def _publish_seed_diagnostics(run: RunRecord, seed_results: list[dict]) -> None:
        coverage = loads(run.coverage_json, {})
        coverage["seed_diagnostics"] = seed_results
        run.coverage_json = dumps(coverage)

    def _store_paper(
        self,
        session,
        run_id: str,
        work: Work,
        *,
        is_seed: bool,
        depth: int,
        provenance: dict,
    ) -> PaperRecord:
        existing = session.scalar(
            select(PaperRecord).where(
                PaperRecord.run_id == run_id, PaperRecord.canonical_id == work.canonical_id
            )
        )
        if existing:
            current = loads(existing.provenance_json, {})
            current_frontiers = set(current.get("frontiers", []))
            current_frontiers.update(provenance.get("frontiers", []))
            current["frontiers"] = sorted(current_frontiers)
            current.setdefault("directions", [])
            current["directions"] = sorted(
                set(current["directions"]) | set(provenance.get("directions", []))
            )
            existing.provenance_json = dumps(current)
            existing.is_seed = existing.is_seed or is_seed
            existing.depth = min(existing.depth, depth)
            return existing
        compact_raw = {
            "referenced_works": work.referenced_works,
            **{
                key: work.raw[key]
                for key in (
                    "bibliography_evidence", "seed_source", "provider", "anthology_id",
                    "resolution_status",
                )
                if key in work.raw
            },
        }
        paper = PaperRecord(
            run_id=run_id,
            canonical_id=work.canonical_id,
            openalex_id=work.openalex_id,
            doi=work.doi,
            arxiv_id=work.arxiv_id,
            title=work.title,
            authors_json=dumps(work.authors),
            year=work.year,
            venue=work.venue,
            abstract=work.abstract,
            url=work.url,
            is_seed=is_seed,
            depth=depth,
            provider_citation_count=work.citation_count,
            provenance_json=dumps(provenance),
            raw_json=dumps(compact_raw),
        )
        session.add(paper)
        session.flush()
        return paper

    def _resolve_seeds(self, session, run: RunRecord, provider: OpenAlexClient) -> dict:
        config = loads(run.config_json, {})
        checkpoint = loads(run.checkpoint_json, {})
        seed_results = checkpoint.setdefault("seed_results", [])
        start_index = checkpoint.get("seed_index", 0)
        run.phase = "resolving"
        session.commit()
        for index in range(start_index, len(config["seeds"])):
            seed = config["seeds"][index]
            work = None
            error = None
            try:
                work = provider.resolve(seed, lambda: self._consume_request(session, run))
            except ProviderBudgetExceeded:
                raise
            except ProviderRateLimited as exc:
                reason = "provider_daily_budget" if exc.daily_budget_exhausted else "provider_rate_limited"
                error = str(exc)
                self._mark_incomplete(
                    run, reason, seed=seed, retry_after_seconds=exc.retry_after_seconds,
                )
                self._add_warning(
                    run, reason,
                    "The provider's keyless request allowance is temporarily unavailable; retained results remain valid.",
                    seed=seed, retry_after_seconds=exc.retry_after_seconds,
                )
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
            if work is None:
                try:
                    fallback = resolve_arxiv(seed, lambda: self._consume_request(session, run))
                    if fallback:
                        work = Work(
                            canonical_id=f"doi:10.48550/arxiv.{fallback['arxiv_id'].lower()}", openalex_id=None,
                            doi=f"10.48550/arxiv.{fallback['arxiv_id'].lower()}",
                            arxiv_id=fallback["arxiv_id"], title=fallback["title"],
                            authors=fallback["authors"], year=fallback["year"], venue="arXiv",
                            abstract=fallback["abstract"], url=fallback["url"], citation_count=None,
                            resolution_method="provider_identifier:arxiv_api",
                        )
                        error = None
                except ProviderBudgetExceeded:
                    raise
                except Exception as exc:
                    prefix = f"{error}; " if error else ""
                    error = f"{prefix}arXiv fallback: {type(exc).__name__}: {exc}"
            result = {
                "input": seed, "resolved": False, "status": "seed_resolution_failure",
                "canonical_id": None, "resolution_method": None, "publication_year": None,
                "reference_count": None, "citing_paper_count": None,
                "candidates_retrieved": 0, "excluded_by_year": 0, "error": error,
            }
            if work is None:
                self._add_exclusion(run, "seed_resolution_failure", seed, error=error)
            elif work.year is None:
                self._add_exclusion(run, "missing_year", seed, title=work.title)
                result.update({
                    "status": "missing_publication_year", "canonical_id": work.canonical_id,
                    "resolution_method": work.resolution_method,
                    "reference_count": len(work.referenced_works),
                    "citing_paper_count": work.citation_count,
                })
            elif not config["min_year"] <= work.year <= config["max_year"]:
                self._add_exclusion(run, "outside_year_range", seed, year=work.year)
                result.update({
                    "status": "excluded_by_year", "canonical_id": work.canonical_id,
                    "resolution_method": work.resolution_method, "publication_year": work.year,
                    "reference_count": len(work.referenced_works),
                    "citing_paper_count": work.citation_count,
                })
            else:
                provider_name = (
                    "openalex" if work.openalex_id else
                    "acl_anthology" if work.canonical_id.startswith("acl:") else
                    "arxiv"
                )
                self._store_paper(
                    session, run.id, work, is_seed=True, depth=0,
                    provenance={"providers": [provider_name],
                                "frontiers": [work.canonical_id], "directions": ["seed"],
                                "seed_input": seed},
                )
                result.update({
                    "resolved": True, "status": "resolved", "canonical_id": work.canonical_id,
                    "resolution_method": work.resolution_method or (
                        "provider_identifier:openalex" if work.openalex_id else "provider_identifier"
                    ),
                    "publication_year": work.year,
                    "reference_count": len(work.referenced_works),
                    "citing_paper_count": work.citation_count, "error": None,
                })
            seed_results.append(result)
            checkpoint["seed_index"] = index + 1
            checkpoint["seed_results"] = seed_results
            run.checkpoint_json = dumps(checkpoint)
            self._publish_seed_diagnostics(run, seed_results)
            session.commit()
        resolved = [item["canonical_id"] for item in seed_results if item.get("resolved")]
        if len(set(resolved)) < 1:
            raise RunFailure(
                "insufficient_resolved_seeds",
                "At least one year-eligible seed paper must resolve.",
            )
        checkpoint.update({
            "seed_order": list(dict.fromkeys(resolved)),
            "depth": 0,
            "frontier": list(dict.fromkeys(resolved)),
            "parent_index": 0,
            "direction_index": 0,
            "operation_index": 0,
            "retrieval_order": "direction_first",
            "candidates": {},
            "retrievals": [],
            "stage": "collecting",
        })
        run.checkpoint_json = dumps(checkpoint)
        counters = loads(run.counters_json, {})
        counters.update({"input_seeds": len(config["seeds"]), "resolved_seeds": len(set(resolved)),
                         "papers_by_depth": {"0": len(set(resolved))}})
        run.counters_json = dumps(counters)
        session.commit()
        return checkpoint

    def _candidate_from_work(self, work: Work, parent: PaperRecord, direction: str) -> Candidate:
        provenance = loads(parent.provenance_json, {})
        provider = work.raw.get("provider") or ("openalex" if work.openalex_id else "unknown")
        return Candidate(
            work=work,
            parents={parent.canonical_id},
            directions={direction},
            frontiers=set(provenance.get("frontiers", [])),
            providers={provider},
        )

    def _collect_frontier(self, session, run: RunRecord, provider: OpenAlexClient, checkpoint: dict) -> dict:
        config = loads(run.config_json, {})
        depth = checkpoint["depth"]
        frontier = checkpoint["frontier"]
        # Run cheap forward lookups across the whole frontier before expensive
        # bibliography resolution so backward work cannot starve every forward query.
        directions = ["forward", "backward"] if config["direction"] == "both" else [config["direction"]]
        candidates = {
            key: Candidate.from_checkpoint(value)
            for key, value in checkpoint.get("candidates", {}).items()
        }
        retained_count = session.scalar(
            select(func.count(PaperRecord.id)).where(PaperRecord.run_id == run.id)
        ) or 0
        level_candidate_limit = min(
            self.settings.max_pending_candidates_per_depth,
            max(0, self.settings.paper_hard_limit - retained_count),
        )

        def seal_candidates(finalize_after: str | None = None) -> dict:
            ordered = schedule_balanced(list(candidates.values()), checkpoint["seed_order"])
            checkpoint.update({
                "stage": "scheduling",
                "ordered_candidates": [item.to_checkpoint() for item in ordered],
                "schedule_index": checkpoint.get("schedule_index", 0),
                "next_frontier": checkpoint.get("next_frontier", []),
            })
            # Once collection is sealed, ordered_candidates is the durable
            # queue. Keeping candidates too would duplicate the whole level.
            checkpoint.pop("candidates", None)
            if finalize_after:
                checkpoint["finalize_after_schedule"] = finalize_after
                checkpoint.pop("force_finalize", None)
            run.phase = "scheduling_frontier"
            run.checkpoint_json = dumps(checkpoint)
            session.commit()
            return checkpoint

        run.phase = "collecting_frontier"
        session.commit()
        if "retrieval_order" not in checkpoint:
            has_legacy_progress = bool(
                checkpoint.get("parent_index", 0) or checkpoint.get("direction_index", 0)
            )
            checkpoint["retrieval_order"] = "parent_first_legacy" if has_legacy_progress else "direction_first"
        if checkpoint["retrieval_order"] == "direction_first":
            operations = [(pi, direction) for direction in directions for pi in range(len(frontier))]
            start_operation = checkpoint.get("operation_index", 0)
        else:
            legacy_directions = ["backward", "forward"] if config["direction"] == "both" else directions
            operations = [(pi, direction) for pi in range(len(frontier)) for direction in legacy_directions]
            start_operation = (
                checkpoint.get("parent_index", 0) * len(legacy_directions)
                + checkpoint.get("direction_index", 0)
            )
        for operation_index in range(start_operation, len(operations)):
            pi, direction = operations[operation_index]
            if run.stop_requested:
                checkpoint["force_finalize"] = "user_stopped"
                break
            parent = session.scalar(select(PaperRecord).where(
                PaperRecord.run_id == run.id, PaperRecord.canonical_id == frontier[pi]
            ))
            if parent is None:
                continue
            work = work_from_paper(parent)
            try:
                if direction == "backward":
                    found, report = provider.backward(
                        work, self.settings.max_candidates_per_parent_direction,
                        lambda: self._consume_request(session, run),
                    )
                else:
                    found, report = provider.forward(
                        work, config["min_year"], config["max_year"],
                        self.settings.max_pages_per_query,
                        self.settings.max_candidates_per_parent_direction,
                        lambda: self._consume_request(session, run),
                    )
            except ProviderBudgetExceeded:
                self._mark_incomplete(run, "run_request_budget", parent=parent.canonical_id,
                                      direction=direction)
                self._add_warning(run, "collection_budget", "Provider request budget reached; finalizing retrieved candidates.")
                checkpoint["force_finalize"] = "collection_budget_reached"
                checkpoint["operation_index"] = operation_index
                return seal_candidates("collection_budget_reached")
            except ProviderRateLimited as exc:
                report = {
                    "retrieved": 0, "failed": True,
                    "reason": "provider_daily_budget" if exc.daily_budget_exhausted else "provider_rate_limited",
                    "message": str(exc), "retry_after_seconds": exc.retry_after_seconds,
                }
                found = []
                self._mark_incomplete(run, report["reason"], parent=parent.canonical_id,
                                      direction=direction, retry_after_seconds=exc.retry_after_seconds)
                self._add_warning(
                    run, report["reason"],
                    "The provider's keyless request allowance is temporarily unavailable; retained results remain valid.",
                    parent=parent.canonical_id, direction=direction,
                    retry_after_seconds=exc.retry_after_seconds,
                )
            except Exception as exc:
                report = {"retrieved": 0, "failed": True, "reason": type(exc).__name__, "message": str(exc)}
                found = []
                self._mark_incomplete(run, "provider_failure", parent=parent.canonical_id,
                                      direction=direction, error=str(exc))
            report.update({"parent": parent.canonical_id, "direction": direction, "depth": depth})
            checkpoint.setdefault("retrievals", []).append(report)
            self._record_retrieval(run, report)
            limitation_details = {key: value for key, value in report.items() if key != "reason"}
            limitation_details["provider_reason"] = report.get("reason")
            if report.get("capped"):
                self._mark_incomplete(run, "application_collection_budget", **limitation_details)
            if report.get("failed"):
                self._mark_incomplete(run, "provider_retrieval_failure", **limitation_details)
            if report.get("unresolved"):
                self._mark_incomplete(run, "bibliography_resolution_incomplete", **limitation_details)
                self._add_warning(
                    run, "unresolved_bibliography_entries",
                    "Some bibliography entries could not be resolved conservatively and were not added.",
                    parent=parent.canonical_id, count=report["unresolved"],
                )
            if report.get("unsupported"):
                self._mark_incomplete(run, "provider_retrieval_unsupported", **limitation_details)
                self._add_warning(
                    run, "provider_retrieval_incomplete",
                    "A resolved seed has no provider citation identifier; its available metadata was preserved.",
                    parent=parent.canonical_id, direction=direction,
                )
            excluded_by_year = 0
            for found_work in found:
                if found_work.year is None:
                    self._add_exclusion(run, "missing_year", found_work.canonical_id)
                    continue
                if not config["min_year"] <= found_work.year <= config["max_year"]:
                    self._add_exclusion(run, "outside_year_range", found_work.canonical_id,
                                        year=found_work.year)
                    excluded_by_year += 1
                    continue
                candidate = self._candidate_from_work(found_work, parent, direction)
                existing = candidates.get(found_work.canonical_id)
                if existing:
                    existing.merge(candidate)
                elif len(candidates) < level_candidate_limit:
                    candidates[found_work.canonical_id] = candidate
                else:
                    self._mark_incomplete(
                        run, "level_paper_capacity", level=depth + 1,
                        limit=level_candidate_limit,
                    )
                    checkpoint["force_finalize"] = "collection_budget_reached"
                    break
            if parent.is_seed:
                for seed_result in checkpoint.get("seed_results", []):
                    if seed_result.get("canonical_id") == parent.canonical_id:
                        if report.get("bibliography_total") is not None:
                            seed_result["reference_count"] = report["bibliography_total"]
                        seed_result["candidates_retrieved"] = int(
                            seed_result.get("candidates_retrieved") or 0
                        ) + len(found)
                        seed_result["excluded_by_year"] = int(
                            seed_result.get("excluded_by_year") or 0
                        ) + excluded_by_year
                        by_direction = seed_result.setdefault("candidates_by_direction", {})
                        by_direction[direction] = int(by_direction.get(direction) or 0) + len(found)
                        excluded_by_direction = seed_result.setdefault("excluded_by_year_by_direction", {})
                        excluded_by_direction[direction] = int(excluded_by_direction.get(direction) or 0) + excluded_by_year
                self._publish_seed_diagnostics(run, checkpoint.get("seed_results", []))
            checkpoint["candidates"] = {key: value.to_checkpoint() for key, value in candidates.items()}
            checkpoint["operation_index"] = operation_index + 1
            run.checkpoint_json = dumps(checkpoint)
            session.commit()
            if checkpoint.get("force_finalize"):
                return seal_candidates(checkpoint["force_finalize"])
        return seal_candidates()

    def _add_edge(self, session, run_id: str, citing: str, cited: str, provenance: dict) -> None:
        if citing == cited:
            return
        exists = session.scalar(select(CitationRecord.id).where(
            CitationRecord.run_id == run_id,
            CitationRecord.citing_paper_id == citing,
            CitationRecord.cited_paper_id == cited,
        ))
        if not exists:
            session.add(CitationRecord(
                run_id=run_id, citing_paper_id=citing, cited_paper_id=cited,
                provenance_json=dumps(provenance), retrieval_date=date.today().isoformat(),
            ))

    def _schedule_frontier(self, session, run: RunRecord, checkpoint: dict) -> dict:
        ordered = [Candidate.from_checkpoint(item) for item in checkpoint.get("ordered_candidates", [])]
        next_frontier = checkpoint.get("next_frontier", [])
        start = checkpoint.get("schedule_index", 0)
        depth = checkpoint["depth"] + 1
        run.phase = "scheduling_frontier"
        session.commit()
        for index in range(start, len(ordered)):
            session.refresh(run)
            if run.stop_requested:
                checkpoint["force_finalize"] = "user_stopped"
                break
            candidate = ordered[index]
            paper_count = session.scalar(select(func.count(PaperRecord.id)).where(PaperRecord.run_id == run.id)) or 0
            existing = session.scalar(select(PaperRecord).where(
                PaperRecord.run_id == run.id,
                PaperRecord.canonical_id == candidate.work.canonical_id,
            ))
            if not existing and paper_count >= self.settings.paper_hard_limit:
                checkpoint["force_finalize"] = "partial_limit_reached"
                break
            paper_provenance = {
                "providers": sorted(candidate.providers),
                "frontiers": sorted(candidate.frontiers),
                "directions": sorted(candidate.directions),
                "parents": sorted(candidate.parents),
            }
            if candidate.work.raw.get("resolution_status"):
                paper_provenance["resolution_status"] = candidate.work.raw["resolution_status"]
            if candidate.work.raw.get("bibliography_evidence"):
                paper_provenance["bibliography_evidence"] = candidate.work.raw["bibliography_evidence"]
            paper = self._store_paper(
                session, run.id, candidate.work, is_seed=False, depth=depth,
                provenance=paper_provenance,
            )
            if not existing:
                next_frontier.append(paper.canonical_id)
                counters = loads(run.counters_json, {})
                contributions = counters.setdefault("seed_frontier_contributions", {})
                for frontier in candidate.frontiers:
                    contributions[frontier] = contributions.get(frontier, 0) + 1
                run.counters_json = dumps(counters)
            for parent_id in candidate.parents:
                if "backward" in candidate.directions:
                    self._add_edge(session, run.id, parent_id, paper.canonical_id,
                                   {"providers": sorted(candidate.providers), "stage": "discovery",
                                    "evidence": "source_bibliography"})
                if "forward" in candidate.directions:
                    self._add_edge(session, run.id, paper.canonical_id, parent_id,
                                   {"providers": sorted(candidate.providers), "stage": "discovery"})
            checkpoint["schedule_index"] = index + 1
            checkpoint["next_frontier"] = next_frontier
            run.checkpoint_json = dumps(checkpoint)
            session.commit()
            paper_count = session.scalar(select(func.count(PaperRecord.id)).where(PaperRecord.run_id == run.id)) or 0
            if paper_count == self.settings.paper_warning_threshold and not checkpoint.get("warning_acknowledged"):
                run.phase = "awaiting_continue"
                self._add_warning(run, "paper_warning_threshold",
                                  "Discovery paused at 500 papers. Continuing may reach the final 1,000-paper limit.")
                run.checkpoint_json = dumps(checkpoint)
                session.commit()
                return checkpoint
            if paper_count >= self.settings.paper_hard_limit:
                checkpoint["force_finalize"] = "partial_limit_reached"
                break
        counters = loads(run.counters_json, {})
        counters.setdefault("papers_by_depth", {})[str(depth)] = len(next_frontier)
        run.counters_json = dumps(counters)
        if checkpoint.get("finalize_after_schedule"):
            checkpoint["force_finalize"] = checkpoint.pop("finalize_after_schedule")
        if checkpoint.get("force_finalize"):
            coverage = loads(run.coverage_json, {})
            coverage["unprocessed_candidates"] = max(
                0, len(ordered) - checkpoint.get("schedule_index", 0)
            )
            run.coverage_json = dumps(coverage)
            run.checkpoint_json = dumps(checkpoint)
            session.commit()
            return checkpoint
        coverage = loads(run.coverage_json, {})
        completed_levels = coverage.setdefault("completed_levels", [])
        if not any(item.get("level") == depth for item in completed_levels):
            completed_levels.append({
                "level": depth,
                "retained_papers": len(next_frontier),
                "status": "checkpointed",
            })
        coverage["highest_completed_level"] = depth
        run.coverage_json = dumps(coverage)
        checkpoint.update({
            "depth": depth, "frontier": next_frontier, "parent_index": 0,
            "direction_index": 0, "operation_index": 0,
            "retrieval_order": "direction_first", "candidates": {}, "retrievals": [],
            "stage": "collecting", "ordered_candidates": [], "schedule_index": 0,
            "next_frontier": [],
            "highest_completed_level": depth,
        })
        run.checkpoint_json = dumps(checkpoint)
        run.phase = "collecting_frontier"
        session.commit()
        return checkpoint

    def _complete_edges(self, session, run: RunRecord) -> None:
        run.phase = "completing_edges"
        session.commit()
        papers = session.scalars(select(PaperRecord).where(PaperRecord.run_id == run.id)).all()
        by_openalex = {paper.openalex_id: paper.canonical_id for paper in papers if paper.openalex_id}
        paper_ids = {paper.canonical_id for paper in papers}
        for paper in papers:
            raw = loads(paper.raw_json, {})
            for ref in raw.get("referenced_works", []) or []:
                target = by_openalex.get(ref.rsplit("/", 1)[-1])
                if target in paper_ids:
                    self._add_edge(session, run.id, paper.canonical_id, target,
                                   {"provider": "openalex", "stage": "edge_completion"})
        session.commit()
        edges = session.scalars(select(CitationRecord).where(CitationRecord.run_id == run.id)).all()
        incoming: dict[str, int] = {}
        outgoing: dict[str, int] = {}
        for edge in edges:
            outgoing[edge.citing_paper_id] = outgoing.get(edge.citing_paper_id, 0) + 1
            incoming[edge.cited_paper_id] = incoming.get(edge.cited_paper_id, 0) + 1
        for paper in papers:
            paper.internal_in_count = incoming.get(paper.canonical_id, 0)
            paper.internal_out_count = outgoing.get(paper.canonical_id, 0)
        coverage = loads(run.coverage_json, {})
        coverage["edge_completion"] = {
            "status": "complete_for_retained_reference_lists",
            "papers_checked": len(papers),
            "does_not_guarantee_real_world_completeness": True,
        }
        run.coverage_json = dumps(coverage)
        session.commit()

    def _annotate(self, session, run: RunRecord) -> None:
        run.phase = "annotating"
        session.commit()
        config = loads(run.config_json, {})
        papers = session.scalars(select(PaperRecord).where(PaperRecord.run_id == run.id)).all()
        annotator = TopicAnnotator(self.settings.embedding_model, self.settings.topic_threshold)
        results, metadata = annotator.annotate(
            [{"title": paper.title, "abstract": paper.abstract} for paper in papers], config["topics"]
        )
        for paper, result in zip(papers, results):
            paper.topics_json = dumps(result["topics"])
            paper.relevance_scores_json = dumps(result["scores"])
            paper.classification_status = result["status"]
        coverage = loads(run.coverage_json, {})
        coverage["topic_annotation"] = metadata
        if metadata["backend"].startswith("local-hash"):
            self._add_warning(run, "embedding_fallback",
                              "Sentence-transformer model unavailable; deterministic local fallback used.")
        run.coverage_json = dumps(coverage)
        session.commit()

    def _finalize(self, session, run: RunRecord, reason: str | None) -> None:
        self._complete_edges(session, run)
        self._annotate(session, run)
        run.phase = "exporting"
        session.commit()
        counts = loads(run.counters_json, {})
        counts["papers"] = session.scalar(select(func.count(PaperRecord.id)).where(PaperRecord.run_id == run.id)) or 0
        counts["discovered_papers"] = session.scalar(select(func.count(PaperRecord.id)).where(
            PaperRecord.run_id == run.id, PaperRecord.is_seed.is_(False))) or 0
        counts["citations"] = session.scalar(select(func.count(CitationRecord.id)).where(CitationRecord.run_id == run.id)) or 0
        run.counters_json = dumps(counts)
        coverage = loads(run.coverage_json, {})
        retrieval_incomplete = not coverage.get("retrieval_complete", True)
        partial = reason is not None or retrieval_incomplete
        candidate_counts = coverage.get("candidate_counts", {})
        candidate_total = sum(int(value or 0) for value in candidate_counts.values())
        if reason is not None:
            run.outcome = reason
        elif retrieval_incomplete:
            run.outcome = "provider_retrieval_incomplete"
        elif counts["discovered_papers"] == 0 and candidate_total == 0:
            run.outcome = "no_citation_candidates"
        else:
            run.outcome = "fully_processed_attempted_traversal"
        run.phase = "completed_partial" if partial else "completed"
        session.commit()
        export_run(session, run, self.settings.runs_dir)

    def _execute(self, run_id: str) -> None:
        with SessionLocal() as session:
            run = session.get(RunRecord, run_id)
            if not run or run.phase in {"awaiting_continue", "completed", "completed_partial", "failed"}:
                return
            lease_owner = str(uuid.uuid4())
            now = datetime.now(timezone.utc)
            if run.lease_expires_at and run.lease_expires_at.replace(tzinfo=timezone.utc) > now and run.lease_owner:
                return
            run.lease_owner = lease_owner
            run.lease_expires_at = now + timedelta(minutes=5)
            session.commit()
            provider = OpenAlexClient(
                self.settings.openalex_base_url,
                self.settings.request_timeout_seconds,
                max_retries=self.settings.provider_max_retries,
                retry_base_seconds=self.settings.provider_retry_base_seconds,
                retry_max_seconds=self.settings.provider_retry_max_seconds,
            )
            try:
                checkpoint = loads(run.checkpoint_json, {})
                if not checkpoint.get("seed_results") or len(checkpoint.get("seed_results", [])) < len(loads(run.config_json, {})["seeds"]):
                    checkpoint = self._resolve_seeds(session, run, provider)
                while True:
                    session.refresh(run)
                    if run.phase == "awaiting_continue":
                        return
                    if run.stop_requested:
                        checkpoint["force_finalize"] = "user_stopped"
                    config = loads(run.config_json, {})
                    if checkpoint.get("force_finalize"):
                        self._finalize(session, run, checkpoint["force_finalize"])
                        return
                    if checkpoint["depth"] >= config["depth"] or not checkpoint["frontier"]:
                        self._finalize(session, run, None)
                        return
                    if checkpoint.get("stage") == "collecting":
                        checkpoint = self._collect_frontier(session, run, provider, checkpoint)
                    if checkpoint.get("stage") == "scheduling":
                        checkpoint = self._schedule_frontier(session, run, checkpoint)
            finally:
                provider.close()
                run.lease_owner = None
                run.lease_expires_at = None
                session.commit()


runner = DiscoveryRunner()

