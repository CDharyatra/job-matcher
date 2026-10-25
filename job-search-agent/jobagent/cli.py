"""Command-line interface. All local. No paid calls."""

from __future__ import annotations

import argparse
import sys

from . import paths
from .config import load_config
from .database import Store
from .facts import load_facts, write_template
from .intent import build_queries
from .logging_setup import get_logger, setup_logging
from .resume import build_profile, load_or_build

log = get_logger("jobagent.cli")


def cmd_init(_args) -> int:
    paths.ensure_dirs()
    write_template()
    print("Initialized. Next:")
    print("  1. Fill candidate_facts.yaml (CTC, notice period, cities, resume paths).")
    print("  2. Copy .env.example -> .env and add your NVIDIA_API_KEY and Gmail app password.")
    print("  3. python -m jobagent.cli models     # confirm free model ids")
    print("  4. python -m jobagent.cli collect    # read-only collection")
    return 0


def cmd_doctor(_args) -> int:
    from .llm.paid_blocklist import PAID_PROVIDERS, PAID_MODELS, PAID_SERVICE_NAMES
    cfg = load_config()
    facts = load_facts()
    problems: list[str] = []
    print("== JobAgent doctor ==")
    print(f"home: {paths.HOME}")
    print(f"config: {'ok' if paths.CONFIG_PATH.exists() else 'MISSING'}")
    print(f"facts: {'ok' if paths.FACTS_PATH.exists() else 'MISSING (run init)'}")

    from .llm.adapter import _KEY_ENV
    from .llm.rerank import _KEY_ENV as _RERANK_KEYS
    from .config import get_secret
    for prov, envv in _KEY_ENV.items():
        present = bool(get_secret(envv))
        print(f"key {prov}: {'present' if present else 'absent'}")
    for prov, envv in _RERANK_KEYS.items():
        if not envv:
            continue
        present = bool(get_secret(envv))
        print(f"key rerank:{prov}: {'present' if present else 'absent'}")

    missing = facts.critical_missing()
    if missing:
        print(f"critical facts missing: {', '.join(missing)}")

    # paid scan of config + env
    raw = (paths.CONFIG_PATH.read_text(encoding="utf-8") if paths.CONFIG_PATH.exists() else "").lower()
    hits = [m for m in PAID_MODELS if f'"{m}"' in raw or f"'{m}'" in raw or f": {m}" in raw]
    if hits:
        problems.append(f"paid model ids present in config: {hits}")
    for svc in PAID_SERVICE_NAMES:
        if svc in raw:
            problems.append(f"paid service referenced: {svc}")

    # validate every configured model against the free allowlist
    from .llm import policy
    for group in (cfg.llm.judge_chain, cfg.llm.classify_chain, cfg.llm.long_context_chain):
        for m in group:
            try:
                policy.assert_free(m.provider, m.model)
            except policy.PaidModelError as e:
                problems.append(f"chain error: {e}")

    print(f"live_submit_enabled: {cfg.apply.live_submit_enabled}")
    if problems:
        print("\nPROBLEMS:")
        for p in problems:
            print(f"  - {p}")
        return 2
    print("\nCOST AUDIT: $0.00/month  --  paid providers configured: 0")
    return 0


def cmd_models(args) -> int:
    from .llm.adapter import LLMClient
    cfg = load_config()
    client = LLMClient(cfg)
    for provider in ("nvidia", "opencode_zen"):
        ids = client.list_models(provider)
        print(f"{provider}: {len(ids)} models")
        for i in ids[:40]:
            print(f"  {i}")
    return 0


def cmd_resume(_args) -> int:
    facts = load_facts()
    files = [f.get("path", "") for f in (facts.application.get("resume_files") or []) if isinstance(f, dict)]
    profile = load_or_build(files)
    print(f"files: {profile.files}")
    print(f"headline: {profile.headline}")
    print(f"total_years: {profile.total_years}")
    print(f"skills: {', '.join(profile.skills)}")
    print(f"titles: {', '.join(profile.titles)}")
    return 0


def cmd_intent(_args) -> int:
    cfg = load_config()
    facts = load_facts()
    files = [f.get("path", "") for f in (facts.application.get("resume_files") or []) if isinstance(f, dict)]
    profile = load_or_build(files)
    for q in build_queries(cfg, profile)[:20]:
        print(f"- {q.keywords!r} @ {q.location!r} remote={q.remote}")
    return 0


def _platforms_arg(args) -> list[str] | None:
    choice = (getattr(args, "platform", None) or "both").lower()
    if choice == "both":
        return None
    return [choice]


def cmd_collect(args) -> int:
    from .pipeline import Pipeline
    setup_logging()
    p = Pipeline()
    result = p.run(phase="collect", dry_run=True, platforms=_platforms_arg(args),
                   force=bool(getattr(args, "force", False)))
    print(result)
    return 0


def cmd_run(args) -> int:
    from .pipeline import Pipeline
    setup_logging()
    p = Pipeline()
    dry = not args.live
    result = p.run(phase="full", dry_run=dry, platforms=_platforms_arg(args),
                   force=bool(getattr(args, "force", False)))
    print(result)
    return 0


def cmd_eval(args) -> int:
    from .evaluate import run_evaluation
    setup_logging()
    report = run_evaluation()
    print(report)
    return 0


def cmd_resend(args) -> int:
    from .pipeline import Pipeline
    setup_logging()
    p = Pipeline()
    result = p.resend_run(args.run)
    print(result)
    return 0 if result.get("sent") else 2


def cmd_apply(args) -> int:
    """Single-job supervised apply. Re-enriches fresh, re-scores with current
    code, and submits only for Bucket A with all gates passing. An explicit
    user invocation is attended by definition, so quiet hours do not apply."""
    import uuid
    from datetime import datetime, timezone

    from .browser.session import CheckpointError, attach_session
    from .clean import BUCKET_APPLY
    from .matcher import match_job
    from .models import job_from_row
    from .pipeline import Pipeline
    setup_logging()
    p = Pipeline()
    row = p.store.get_job(args.job)
    if row is None:
        print(f"unknown job id: {args.job}")
        return 2
    if p.store.has_event(row["id"], "applied"):
        print(f"job {args.job} already has a recorded application; refusing.")
        return 2
    if args.live:
        if not p.cfg.apply.live_submit_enabled:
            print("refused: apply.live_submit_enabled is false in config.yaml")
            return 2
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if p.store.applied_today(row["source"] or "", today) >= \
                p.cfg.apply.daily_auto_apply_cap_per_platform:
            print("refused: daily auto-apply cap already reached")
            return 2
    run_id = (f"single-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-"
              f"{uuid.uuid4().hex[:6]}")
    p.store.start_run(run_id, "single")
    # NOTE: only one Playwright sync session may live in a process at a time,
    # so the enrich session is fully stopped before _apply attaches its own.
    try:
        session = attach_session(p.cfg.browser)
    except Exception as e:  # noqa: BLE001
        print(f"browser unavailable: {e}")
        return 2
    try:
        from .browser import linkedin as li
        from .browser import naukri as nk
        obj = job_from_row(row)
        try:
            if obj.source == "linkedin":
                li.enrich_from_detail(session, obj, p.cfg)
            elif obj.source == "naukri":
                nk.enrich_from_detail(session, obj, p.cfg)
            else:
                print(f"unsupported source: {obj.source}")
                p.store.finish_run(run_id, {"single": args.job})
                return 2
        except CheckpointError:
            print("checkpoint hit during enrich; not attempting. Try again later.")
            p.store.finish_run(run_id, {"single": args.job})
            return 2
        res = match_job(obj, row["id"], p.facts, p.cfg, p.resume, llm=p.llm,
                        use_llm=p.cfg.llm.enabled, rerank=p.rerank)
        p.store.upsert_score(row["id"], run_id, {
            "overall_match": res.overall_match,
            "deterministic_score": res.deterministic_score,
            "llm_score": res.llm_score, "bucket": res.decision.bucket,
            "reasons": res.reasons, "evidence": res.evidence,
            "missing_facts": res.decision.missing_facts,
            "resume_used": res.resume_used})
        print(f"score={res.overall_match} bucket={res.decision.bucket} "
              f"apply_type={obj.apply_type}")
        for reason in res.reasons[:8]:
            print(f"  - {reason[:130]}")
        if res.decision.bucket != BUCKET_APPLY:
            print(f"verdict: would NOT apply (bucket {res.decision.bucket}). "
                  f"Open manually: {obj.canonical_url}")
            p.store.finish_run(run_id, {"single": args.job})
            return 0
        if not args.live:
            print(f"verdict: WOULD apply. Re-run with --live to submit. "
                  f"Missing facts: {res.decision.missing_facts or 'none'}")
            p.store.finish_run(run_id, {"single": args.job})
            return 0
    finally:
        try:
            session.stop()
        except Exception:  # noqa: BLE001
            pass
    ok, detail = p._apply(obj, res, run_id)
    p.store.finish_run(run_id, {"single": args.job})
    print(f"SUBMITTED: {detail}" if ok else f"FAILED: {detail}. "
          f"Apply manually: {obj.canonical_url}")
    return 0 if ok else 3


def cmd_golden(args) -> int:
    from .config import load_config
    from .database import Store
    from .golden import append_golden_set, build_golden_entries, write_golden_set
    cfg = load_config()
    store = Store(cfg.storage.sqlite_path)
    entries = build_golden_entries(store, n=args.n if not args.append else args.n * 2)
    if not entries:
        print("No scored jobs yet — run `collect` first.")
        return 2
    if args.append:
        path, added = append_golden_set(None, entries, args.append)
        print(f"Kept existing entries, added {added} fresh jobs to {path}.")
        print("Fill the blank labels, then run `eval`.")
        return 0
    try:
        path = write_golden_set(None, entries, overwrite=args.overwrite)
    except FileExistsError as e:
        print(e)
        return 2
    blank = sum(1 for e in entries if not e["label"])
    print(f"Wrote {len(entries)} jobs to {path} ({blank} labels to fill).")
    print("Fill label: apply | inbox | discard on each, then run `eval`.")
    return 0


def cmd_browser(args) -> int:
    """Attach to the dedicated Chrome and report session health. No scraping.

    With --dump, also saves each homepage's HTML to data/debug/ and prints the
    page's button labels, so a human can share ground-truth DOM for selector
    repair. Nothing leaves the machine.
    """
    from .browser import selectors as S
    from .browser.session import (BrowserSession, CheckpointError, SessionDeadError,
                                  detect_checkpoint)
    cfg = load_config()
    dump = bool(getattr(args, "dump", False))
    print("attaching to dedicated chrome...")
    try:
        session = BrowserSession(cfg.browser).start()
    except SessionDeadError as e:
        print(f"ATTACH FAILED: {e}")
        print("Is the dedicated Chrome window (remote-debugging-port) running?")
        return 2
    try:
        print(f"attached: contexts={len(session._browser.contexts)}")
        from .browser import linkedin as _li
        from .browser import naukri as _nk
        from .facts import load_facts as _load_facts
        from .intent import build_queries as _build_queries
        from .resume import load_or_build as _load_or_build
        _facts = _load_facts()
        _files = [f.get("path", "") for f in (_facts.application.get("resume_files") or [])
                  if isinstance(f, dict)]
        _queries = _build_queries(cfg, _load_or_build(_files))
        _q0 = _queries[0] if _queries else None
        _pages = [
            ("linkedin", "https://www.linkedin.com/feed/", S.LINKEDIN["logged_in"],
             S.LINKEDIN.get("logged_in_fallbacks"),
             _li.build_url(_q0.keywords, _q0.location, 24,
                           easy_apply=True, remote=_q0.remote) if _q0 else None,
             S.LINKEDIN["job_card"]),
            ("naukri", None, S.NAUKRI["job_card"], None,
             _nk.build_urls(_q0.keywords, _q0.location, 1)[0] if _q0 else None,
             S.NAUKRI["job_card"]),
        ]
        from . import paths as _paths
        from .browser.session import (looks_logged_out as _looks_logged_out,
                                      require_logged_in as _require_logged_in,
                                      wait_for_any_selector as _wait_any)
        dbg = _paths.DATA_DIR / "debug"
        if dump:
            dbg.mkdir(parents=True, exist_ok=True)
        for name, url, selector, fallbacks, search_url, card_selector in _pages:
            for label, target in (("home", url), ("search", search_url)):
                if not target:
                    continue
                page = session.new_page()
                try:
                    page.goto(target, wait_until="domcontentloaded")
                    print(f"[{name}/{label}] url={page.url}")
                    print(f"[{name}/{label}] title={page.title()[:100]!r}")
                    if not dump and label == "home":
                        # LinkedIn verdict (Naukri verifies on its search page:
                        # mnjuser/homepage renders a Next.js error shell).
                        try:
                            _require_logged_in(page, selector, name, fallbacks=fallbacks)
                            print(f"{name}: LOGGED IN (url={page.url})")
                        except CheckpointError as e:
                            print(f"{name}: CHECKPOINT ({e})")
                        except SessionDeadError as e:
                            print(f"{name}: NOT LOGGED IN ({e})")
                        continue
                    if not dump and label == "search" and name == "naukri":
                        # Naukri verdict on the search page itself.
                        if detect_checkpoint(page):
                            print(f"{name}: CHECKPOINT (url={page.url})")
                        elif _wait_any(page, [card_selector], timeout_ms=20000) is not None:
                            print(f"{name}: SESSION OK, cards loading (url={page.url})")
                        elif _looks_logged_out(page):
                            print(f"{name}: NOT LOGGED IN (url={page.url})")
                        else:
                            print(f"{name}: UNCLEAR - no cards, no login form "
                                  f"(url={page.url})")
                        continue
                    # Dump mode: save HTML + card count (ground truth for repair).
                    # Search pages hydrate client-side; wait for content first.
                    if label == "search":
                        markers = (S.LINKEDIN["hydration_markers"] if name == "linkedin"
                                   else [S.NAUKRI["job_card"]])
                        _wait_any(page, markers, timeout_ms=25000)
                    out = dbg / f"{name}-{label}.html"
                    out.write_text(page.content(), encoding="utf-8")
                    print(f"[{name}/{label}] html saved to {out} ({out.stat().st_size} bytes)")
                    if label == "search":
                        _dump_detail(session, dbg, name, page)
                    if label == "home":
                        try:
                            labels = page.eval_on_selector_all(
                                "button, nav a, header a",
                                "els => els.slice(0, 60).map(e => (e.getAttribute('aria-label') || e.innerText || e.getAttribute('href') || '').trim().slice(0, 80))",
                            )
                            print(f"[{name}] nav labels:")
                            for lab in dict.fromkeys(l for l in labels if l):
                                print(f"    - {lab}")
                        except Exception as e:  # noqa: BLE001
                            print(f"[{name}] label dump failed: {e}")
                    else:
                        try:
                            from .browser.pacing import human_scroll as _scroll
                            _scroll(page, steps=2)
                            cards = page.query_selector_all(card_selector)
                            print(f"[{name}/{label}] cards with current selectors: {len(cards)}")
                        except Exception as e:  # noqa: BLE001
                            print(f"[{name}/{label}] card count failed: {e}")
                finally:
                    page.close()
    finally:
        session.stop()
    return 0


def _dump_detail(session, dbg, name: str, search_page) -> None:
    """Open the first result's detail page and dump it (read-only navigation)."""
    from .browser import selectors as S
    detail_url = ""
    try:
        if name == "linkedin":
            from .browser.linkedin import _harvest_ids
            ids = _harvest_ids(search_page)
            print(f"[linkedin/search] harvested ids: {len(ids)}")
            if ids:
                detail_url = f"https://www.linkedin.com/jobs/view/{ids[0][0]}/"
        else:
            hrefs = search_page.eval_on_selector_all(
                S.NAUKRI["job_card"],
                "els => els.map(e => { const a = e.querySelector('a[href*=\\'job-listings\\']'); "
                "return a ? a.getAttribute('href') : ''; })",
            )
            hrefs = [h for h in (hrefs or []) if h]
            print(f"[naukri/search] card hrefs: {len(hrefs)}")
            if hrefs:
                detail_url = hrefs[0]
                if detail_url.startswith("/"):
                    detail_url = "https://www.naukri.com" + detail_url
    except Exception as e:  # noqa: BLE001
        print(f"[{name}] detail harvest failed: {e}")
        return
    if not detail_url:
        print(f"[{name}] no detail url to dump")
        return
    page = session.new_page()
    try:
        page.goto(detail_url, wait_until="domcontentloaded")
        # Detail pages hydrate client-side; wait before snapshotting.
        try:
            from .browser.session import wait_for_any_selector as _wait_any2
            markers = ([S.LINKEDIN["detail_description"], S.LINKEDIN["easy_apply_button"]]
                       if name == "linkedin" else
                       [S.NAUKRI["detail_description"], S.NAUKRI["in_platform_apply"],
                        S.NAUKRI["company_site_apply"]])
            _wait_any2(page, markers, timeout_ms=20000)
        except Exception:  # noqa: BLE001
            pass
        print(f"[{name}/detail] url={page.url}")
        print(f"[{name}/detail] title={page.title()[:100]!r}")
        out = dbg / f"{name}-detail.html"
        out.write_text(page.content(), encoding="utf-8")
        print(f"[{name}/detail] html saved to {out} ({out.stat().st_size} bytes)")
        if name == "linkedin":
            print(f"[{name}/detail] easy-apply btn: "
                  f"{page.query_selector(S.LINKEDIN['easy_apply_button']) is not None}, "
                  f"external btn: "
                  f"{page.query_selector(S.LINKEDIN['external_apply_link']) is not None}, "
                  f"desc: {page.query_selector(S.LINKEDIN['detail_description']) is not None}")
        else:
            print(f"[{name}/detail] in-platform btn: "
                  f"{page.query_selector(S.NAUKRI['in_platform_apply']) is not None}, "
                  f"company-site btn: "
                  f"{page.query_selector(S.NAUKRI['company_site_apply']) is not None}, "
                  f"desc: {page.query_selector(S.NAUKRI['detail_description']) is not None}")
    except Exception as e:  # noqa: BLE001
        print(f"[{name}/detail] failed: {e}")
    finally:
        page.close()


def cmd_schedule(args) -> int:
    from .scheduler import install_tasks, print_plan
    if args.install:
        return install_tasks()
    print_plan()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jobagent", description="Local $0 job-search agent")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="create dirs + facts template").set_defaults(func=cmd_init)
    sub.add_parser("doctor", help="cost + secret + config audit").set_defaults(func=cmd_doctor)
    sub.add_parser("models", help="list free model ids").set_defaults(func=cmd_models)
    sub.add_parser("resume", help="parse resume + build profile").set_defaults(func=cmd_resume)
    sub.add_parser("intent", help="show search queries").set_defaults(func=cmd_intent)
    collect_p = sub.add_parser("collect", help="read-only collection")
    collect_p.add_argument("--platform", choices=["both", "linkedin", "naukri", "ats"],
                           default="both", help="run one platform only")
    collect_p.add_argument("--force", action="store_true",
                           help="override the single-run lock")
    collect_p.set_defaults(func=cmd_collect)
    br = sub.add_parser("browser", help="check dedicated-chrome session health")
    br.add_argument("--dump", action="store_true",
                    help="save homepage HTML to data/debug + print nav labels (for selector repair)")
    br.set_defaults(func=cmd_browser)

    run_p = sub.add_parser("run", help="full pipeline (dry-run unless --live)")
    run_p.add_argument("--live", action="store_true", help="enable submit (requires config gate)")
    run_p.add_argument("--platform", choices=["both", "linkedin", "naukri", "ats"],
                       default="both", help="run one platform only")
    run_p.add_argument("--force", action="store_true",
                       help="override the single-run lock")
    run_p.set_defaults(func=cmd_run)

    sub.add_parser("eval", help="golden-set precision report").set_defaults(func=cmd_eval)

    resend_p = sub.add_parser("resend", help="re-send a past run's digest (no browser, no models)")
    resend_p.add_argument("--run", default=None, help="run id (default: latest run)")
    resend_p.set_defaults(func=cmd_resend)

    apply_p = sub.add_parser("apply", help="score and optionally submit ONE job by id (supervised)")
    apply_p.add_argument("--job", type=int, required=True, help="job id from the database")
    apply_p.add_argument("--live", action="store_true",
                         help="actually submit (requires live_submit_enabled + cap room)")
    apply_p.set_defaults(func=cmd_apply)

    gold = sub.add_parser("golden", help="build labeling file from collected jobs")
    gold.add_argument("--n", type=int, default=50, help="jobs to include")
    gold.add_argument("--overwrite", action="store_true",
                      help="replace existing labels/golden_set.yaml")
    gold.add_argument("--append", type=int, default=0, metavar="N",
                      help="keep existing entries (labels intact), add N fresh ones")
    gold.set_defaults(func=cmd_golden)

    sch = sub.add_parser("schedule", help="show/install Task Scheduler plan")
    sch.add_argument("--install", action="store_true")
    sch.set_defaults(func=cmd_schedule)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())