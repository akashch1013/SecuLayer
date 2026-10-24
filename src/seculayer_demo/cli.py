"""The `seculayer` command-line tool."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Annotated, cast

import typer
from pydantic import ValidationError

from seculayer.types import LayerSwitches
from seculayer_demo.config import Mode, Settings, get_settings, is_loopback

app = typer.Typer(
    help="SecuLayer: a prompt-injection demo and a layered defense.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_show_locals=False,
)


@app.command("mcp")
def mcp_command(
    policy: Annotated[
        Path | None,
        typer.Option(
            help="Trusted local TOML policy; see docs/MCP.md.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
        ),
    ] = None,
) -> None:
    """Start local MCP tools over stdio (no API key or web server required)."""
    from seculayer.policy import PolicyError
    from seculayer_demo.mcp_server import run_server

    try:
        run_server(policy)
    except (OSError, ValueError, PolicyError):
        typer.echo("MCP could not start. Check the policy file and local configuration.", err=True)
        raise typer.Exit(2) from None


@app.command("mcp-config")
def mcp_config(
    policy: Annotated[
        Path | None, typer.Option(help="Local policy to use.", exists=True, dir_okay=False)
    ] = None,
) -> None:
    """Print ready-to-paste desktop MCP JSON for this installation."""
    args = ["-m", "seculayer_demo.cli", "mcp"]
    if policy is not None:
        args.extend(["--policy", str(policy.resolve())])
    typer.echo(
        json.dumps(
            {
                "mcpServers": {
                    "seculayer": {
                        "command": sys.executable,
                        "args": args,
                    }
                }
            },
            indent=2,
        )
    )


def _load_settings() -> Settings:
    try:
        return get_settings()
    except ValidationError as error:
        for problem in error.errors():
            typer.echo(f"Configuration problem: {problem['msg']}", err=True)
        raise typer.Exit(2) from None


@app.command()
def serve(
    host: Annotated[str | None, typer.Option(help="Loopback address to bind.")] = None,
    port: Annotated[int | None, typer.Option(help="Port to listen on.")] = None,
    mode: Annotated[str | None, typer.Option(help="replay (default) or live.")] = None,
    reload: Annotated[bool, typer.Option(help="Restart on code changes (make dev).")] = False,
) -> None:
    """Start the demo server (API and built frontend)."""
    import uvicorn

    settings = _load_settings()
    host = host or settings.host
    port = port or settings.port
    chosen = mode or settings.mode
    if chosen not in ("replay", "live"):
        typer.echo(f"Unknown mode {chosen!r}; use replay or live.", err=True)
        raise typer.Exit(2)
    if not is_loopback(host):
        typer.echo(f"Refusing to bind {host}: the demo only listens on loopback.", err=True)
        raise typer.Exit(2)
    if chosen == "live" and not settings.has_api_key:
        typer.echo("Live mode needs an OpenAI key in .env (OPENAI_API_KEY).", err=True)
        raise typer.Exit(2)

    # The factory reads settings from the environment, which also survives --reload restarts.
    os.environ["SECULAYER_MODE"] = chosen
    get_settings.cache_clear()
    mode_label: Mode = "live" if chosen == "live" else "replay"
    typer.echo(f"SecuLayer ({mode_label} mode) at http://{host}:{port}")
    uvicorn.run(
        "seculayer_demo.server.app:create_app",
        factory=True,
        host=host,
        port=port,
        reload=reload,
        reload_dirs=["src"] if reload else None,
        log_level=settings.log_level,
        server_header=False,
    )


@app.command()
def doctor(
    online: Annotated[bool, typer.Option(help="Also make one tiny live call per model.")] = False,
) -> None:
    """Check the environment: tools, disk space, caches, port, key, classifier, recordings."""
    from seculayer_demo.doctor import format_report, run_checks

    settings = _load_settings()
    checks = list(run_checks(settings))
    if online:
        if not settings.has_api_key:
            typer.echo("doctor --online needs OPENAI_API_KEY in .env.", err=True)
            raise typer.Exit(2)
        from seculayer_demo.doctor import online_checks
        from seculayer_demo.gateway.openai_client import OpenAITransport

        transport = OpenAITransport(settings.openai_api_key.get_secret_value())
        checks += list(online_checks(settings, transport))
    typer.echo(format_report(checks))
    if any(check.status == "fail" for check in checks):
        raise typer.Exit(1)


@app.command("fetch-model")
def fetch_model(
    verify_only: Annotated[
        bool, typer.Option("--verify-only", help="Only check the files already present.")
    ] = False,
) -> None:
    """Download the pinned classifier files from Hugging Face and check their SHA-256."""
    from seculayer_demo.fetch_model import FetchError, fetch, load_manifest, verify

    settings = _load_settings()
    manifest = load_manifest()
    directory = settings.classifier_path
    if verify_only:
        result = verify(directory, manifest)
        for name, state in result.states.items():
            typer.echo(f"  {state:<9} {name}")
        raise typer.Exit(0 if result.ok else 1)

    typer.echo(f"Classifier {manifest.name} at revision {manifest.revision[:12]} into {directory}")
    try:
        result = fetch(directory, manifest, log=typer.echo)
    except FetchError as error:
        typer.echo(f"Download failed: {error}", err=True)
        raise typer.Exit(1) from None
    if not result.ok:
        typer.echo(f"Some files don't match the manifest: {result.states}", err=True)
        raise typer.Exit(1)
    typer.echo("All classifier files present and hash-checked.")


def _layers(spec: str) -> LayerSwitches:
    from seculayer_demo.console import parse_layers

    try:
        return parse_layers(spec)
    except ValueError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(2) from None


@app.command()
def screen(
    case: Annotated[str, typer.Option("--case", help="Case ID, e.g. inbox.hidden_forward.")],
    layers: Annotated[str, typer.Option(help="all, none, a list to keep on, or -layer,…")] = "all",
) -> None:
    """Print the hidden-text cleaner's and screening's verdicts for a case's inputs.

    Runs locally with no model call, so the LLM judge is always off here.
    """
    from seculayer_demo.console import screen_case
    from seculayer_demo.server.runs import make_classifier

    settings = _load_settings()
    try:
        inspections = screen_case(case, _layers(layers), make_classifier(settings))
    except KeyError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(2) from None
    steps = ["The user's message", "Tool result: the inbox"]
    for title, inspection in zip(steps, inspections, strict=False):
        typer.echo(title + (":" if len(inspections) > 1 else " and outside content:"))
        for verdict in inspection.verdicts:
            typer.echo(f"  [{verdict.layer.value:<11}] {verdict.action.value:<9} {verdict.reason}")
            for line in verdict.detail:
                typer.echo(f"      · {line[:150]}")
        if inspection.withheld_ids:
            typer.echo(f"  withheld: {', '.join(inspection.withheld_ids)}")
        if inspection.blocked:
            typer.echo(f"  blocked: {inspection.block_reason}")
    typer.echo("(The LLM judge is off here: it needs a model call. Use `seculayer run`.)")


@app.command()
def run(
    case: Annotated[str, typer.Option("--case", help="Case ID, e.g. inbox.hidden_forward.")],
    protected: Annotated[bool, typer.Option("--protected", help="Run with SecuLayer.")] = False,
    layers: Annotated[str, typer.Option(help="all, none, a list to keep on, or -layer,…")] = "all",
    mode: Annotated[str, typer.Option(help="replay (default), live or record.")] = "replay",
    trial: Annotated[int, typer.Option(min=1, help="Which recorded trial to replay.")] = 1,
    model: Annotated[str | None, typer.Option(help="Model snapshot (default: target).")] = None,
    decision: Annotated[
        str, typer.Option(help="If SecuLayer asks before sending: stop, approve or decline.")
    ] = "stop",
) -> None:
    """Run one case and print its events compactly."""
    from seculayer_demo.console import print_events
    from seculayer_demo.gateway import ModelGateway, RecordingStore, TokenBudget
    from seculayer_demo.gateway.openai_client import OpenAITransport
    from seculayer_demo.runner import AgentRunner, ConfirmPolicy, RunRequest
    from seculayer_demo.server.runs import make_classifier

    settings = _load_settings()
    if mode not in ("replay", "live", "record"):
        typer.echo(f"Unknown mode {mode!r}; use replay, live or record.", err=True)
        raise typer.Exit(2)
    if decision not in ("stop", "approve", "decline"):
        typer.echo("--decision must be stop, approve or decline.", err=True)
        raise typer.Exit(2)
    transport = None
    if mode != "replay":
        if not settings.has_api_key:
            typer.echo(f"{mode} mode needs OPENAI_API_KEY in .env.", err=True)
            raise typer.Exit(2)
        transport = OpenAITransport(settings.openai_api_key.get_secret_value())
    budget = TokenBudget(settings.token_budget, settings.spend_log)
    gateway = ModelGateway(
        mode,  # type: ignore[arg-type]
        RecordingStore(settings.recordings_dir),
        transport=transport,
        budget=budget,
    )
    switches = _layers(layers) if protected else LayerSwitches.all_off()
    try:
        runner = AgentRunner(
            RunRequest(
                case,
                protected,
                model or settings.model,
                switches,
                trial,
                on_confirm=cast(ConfirmPolicy, decision),
            ),
            gateway=gateway,
            judge_model=settings.judge_model,
            classifier=make_classifier(settings),
            run_id="cli",
        )
    except KeyError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(2) from None
    try:
        print_events(runner.events(), typer.echo)
    finally:
        budget.flush(label=f"seculayer run {case}")
    if runner.finished is None or runner.finished.outcome == "error":
        raise typer.Exit(1)


@app.command()
def record(
    cases: Annotated[str, typer.Option(help="Case IDs or patterns, comma-separated.")],
    configs: Annotated[str, typer.Option(help="A, B, C, D, C+ and/or combos.")] = "A,B",
    trials: Annotated[int, typer.Option(min=1, max=5, help="Trials per case.")] = 3,
    yes: Annotated[bool, typer.Option("--yes", help="Don't ask before starting.")] = False,
    replacement: Annotated[
        str | None,
        typer.Option("--replace-recording", help="Approved repair of one exact SHA256:TRIAL."),
    ] = None,
) -> None:
    """Record missing model calls (live, within SECULAYER_TOKEN_BUDGET)."""
    from seculayer_demo.gateway import ModelGateway, RecordingStore, TokenBudget
    from seculayer_demo.gateway.openai_client import OpenAITransport
    from seculayer_demo.recording_batch import (
        configs as make_configs,
    )
    from seculayer_demo.recording_batch import (
        estimate_by_model,
        plan_jobs,
        run_jobs,
        select_cases,
    )
    from seculayer_demo.server.runs import make_classifier

    settings = _load_settings()
    if replacement is not None:
        from seculayer_demo.recording_repair import replace_recording

        try:
            replace_recording(
                settings,
                cases,
                replacement,
                confirm=lambda message: yes or typer.confirm(message),
                log=typer.echo,
            )
        except (ValueError, RuntimeError) as error:
            typer.echo(str(error), err=True)
            raise typer.Exit(1) from None
        return
    names = [n.strip() for n in configs.split(",") if n.strip()]
    try:
        chosen = make_configs(names, settings.model, settings.compare_model)
        selected = select_cases(cases)
    except ValueError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(2) from None
    jobs = plan_jobs(selected, chosen, trials, combos="combos" in names, target=settings.model)
    budget = TokenBudget(settings.token_budget, settings.spend_log)
    typer.echo(f"{len(selected)} cases, {len(jobs)} runs; estimates before recording reuse:")
    from seculayer_demo.gateway import BudgetExceeded

    try:
        estimates = estimate_by_model(jobs, settings.judge_model)
        estimates.setdefault(settings.compare_model, (0, 0))
        estimates.setdefault(settings.model, (0, 0))
        budget.preflight(estimates, typer.echo)
    except BudgetExceeded as error:
        typer.echo(f"Batch exceeds the remaining budget: {error}. Not starting.", err=True)
        raise typer.Exit(1) from None
    if not settings.has_api_key:
        typer.echo("record needs OPENAI_API_KEY in .env.", err=True)
        raise typer.Exit(2)
    if not yes and not typer.confirm("Start recording?"):
        raise typer.Exit(1)
    transport = OpenAITransport(settings.openai_api_key.get_secret_value())
    gateway = ModelGateway(
        "record", RecordingStore(settings.recordings_dir), transport=transport, budget=budget
    )
    try:
        counts = run_jobs(
            jobs,
            gateway,
            judge_model=settings.judge_model,
            classifier=make_classifier(settings),
            log=typer.echo,
        )
    except RuntimeError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from None
    finally:
        written = budget.flush(label=f"record {cases} {configs} x{trials}")
    typer.echo(f"Done: {counts}. {written:,} tokens logged to data/spend.jsonl.")


@app.command("eval")
def evaluate_command(
    mode: Annotated[str, typer.Option(help="replay (default, offline) or live.")] = "replay",
    record_missing: Annotated[
        bool, typer.Option("--record", help="Live mode: record missing calls first.")
    ] = False,
    configs: Annotated[str, typer.Option(help="Configurations: A,B,C,D,C+.")] = "A,B,C,D,C+",
    cases: Annotated[str | None, typer.Option(help="Case IDs or patterns (default all).")] = None,
    out_dir: Annotated[str, typer.Option(help="Where latest.json and runs/ go.")] = "data/eval",
    results_md: Annotated[
        str | None, typer.Option(help="docs/RESULTS.md path (default for full runs).")
    ] = None,
    yes: Annotated[bool, typer.Option("--yes", help="Don't ask before live calls.")] = False,
) -> None:
    """Recompute every metric from the recordings and write latest.json and RESULTS.md."""
    from pathlib import Path

    from seculayer_demo.config import REPO_ROOT
    from seculayer_demo.evaluation import report
    from seculayer_demo.evaluation.runner import EVAL_CONFIGS, OBSERVE, TRIALS, evaluate, plan
    from seculayer_demo.gateway import RecordingStore
    from seculayer_demo.server.runs import make_classifier

    settings = _load_settings()
    names = [n.strip() for n in configs.split(",") if n.strip()]
    unknown = [n for n in names if n not in EVAL_CONFIGS]
    if unknown or mode not in ("replay", "live"):
        typer.echo("Use --mode replay|live and --configs from A,B,C,D,C+.", err=True)
        raise typer.Exit(2)
    if mode == "live":
        if not record_missing:
            typer.echo("Live evaluation records what it calls: pass --record.", err=True)
            raise typer.Exit(2)
        # Fill in missing recordings with the same budgeted batch as `seculayer record`; only
        # keys that aren't recorded yet call the API.
        for name in names:
            ids = sorted({job.case.id for job in plan(settings, [name], cases)})
            if ids:
                record(
                    cases=",".join(ids),
                    configs=name,
                    trials=TRIALS[name],
                    yes=yes,
                    replacement=None,
                )
    if "A" in names:
        names.append(OBSERVE)
    classifier = make_classifier(settings)
    records = evaluate(settings, classifier, names=names, patterns=cases, log=typer.echo)
    errors = [r for r in records if r["outcome"] == "error"]
    if errors:
        for r in errors[:10]:
            typer.echo(f"  {r['config']} {r['case_id']} trial {r['trial']}: {r['error']}")
        typer.echo(f"{len(errors)} runs failed to replay; no results written.", err=True)
        raise typer.Exit(1)
    store = RecordingStore(settings.recordings_dir)
    summary = report.build_summary(
        records,
        models={
            "target": settings.model,
            "compare": settings.compare_model,
            "judge": settings.judge_model,
        },
        recordings=report.recordings_info(store, [settings.model, settings.compare_model]),
        live=report.live_measurements(records, classifier),
    )
    out = Path(out_dir)
    out = out if out.is_absolute() else REPO_ROOT / out
    runs = report.write_runs(records, out / "runs", report.run_stamp())
    report.write_summary(summary, out / "latest.json")
    full_run = cases is None and set(names) >= {"A", "B", "C", "D"}
    target_md = results_md or ("docs/RESULTS.md" if full_run else None)
    if target_md:
        md = Path(target_md)
        md = md if md.is_absolute() else REPO_ROOT / md
        md.parent.mkdir(parents=True, exist_ok=True)
        md.write_text(report.results_markdown(summary), encoding="utf-8")
        typer.echo(f"Wrote {md.relative_to(REPO_ROOT) if md.is_relative_to(REPO_ROOT) else md}")
    for config in summary["configs"]:
        attacks = config["attacks"]
        if attacks:
            typer.echo(
                f"  {config['id']:<3} {config['label']}: attacks worked "
                f"{attacks['count']} of {attacks['total']} runs"
            )
    typer.echo(f"Wrote {out / 'latest.json'} and {runs.name}")


@app.command("replay-check")
def replay_check_command(
    cases: Annotated[str, typer.Option(help="Case IDs or patterns.")] = "*",
    model: Annotated[str | None, typer.Option(help="Default: gpt-5.4-mini target.")] = None,
    trials: Annotated[int, typer.Option(min=1, max=3)] = 3,
) -> None:
    """Audit offline coverage and report unreferenced recordings; never deletes files."""
    from seculayer_demo.replay_check import replay_check

    missing = replay_check(_load_settings(), cases, model, trials, typer.echo)
    raise typer.Exit(1 if missing else 0)


@app.command()
def qualify(
    cases: Annotated[str, typer.Option(help="Attack case IDs or patterns.")],
    round_name: Annotated[
        str, typer.Option("--round", help="Audit label, e.g. original or round-1.")
    ],
) -> None:
    """Three LIVE configuration-A trials; append an audit, never API recordings."""
    from seculayer_demo.qualification import qualify_cases

    try:
        qualify_cases(_load_settings(), cases, round_name, typer.echo)
    except (ValueError, RuntimeError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from None


@app.command("warm-classifier")
def warm_classifier_command() -> None:
    """Score every curated input with the classifier and save the scores to
    data/cache/classifier_scores.jsonl (committed, so machines without the model can use them)."""
    from seculayer_demo.server.runs import classifier_cache_path, make_classifier, warm_classifier

    settings = _load_settings()
    classifier = make_classifier(settings)
    if not classifier.model_available:
        typer.echo("The classifier isn't downloaded. Run: uv run seculayer fetch-model", err=True)
        raise typer.Exit(1)
    scored = warm_classifier(classifier)
    typer.echo(
        f"Scored {scored} new texts; {len(classifier.cache)} in {classifier_cache_path(settings)}."
    )


@app.command("recording-report")
def recording_report_command(
    output: Annotated[
        str, typer.Option(help="Offline M6 outcome inventory.")
    ] = "data/m6-recordings.json",
) -> None:
    """Replay the measured matrix into an outcome inventory (no API calls)."""
    import json
    from pathlib import Path

    from seculayer_demo.recording_report import recording_report

    report = recording_report(_load_settings())
    errors = [
        (case_id, config, row["trial"])
        for case_id, configurations in report["cases"].items()
        for config, rows in configurations.items()
        for row in rows
        if row["outcome"] == "error" or row.get("if_approved") == "error"
    ]
    if errors:
        typer.echo(f"Incomplete matrix: {len(errors)} runs failed to replay. No report written.")
        raise typer.Exit(1)
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    typer.echo(f"Offline outcome inventory: {path}")


@app.command("export-openapi")
def export_openapi(
    path: Annotated[str, typer.Argument(help="Where to write the OpenAPI JSON.")] = (
        "web/src/api/openapi.json"
    ),
) -> None:
    """Write the API's OpenAPI document (make types turns it into TypeScript)."""
    import json
    from pathlib import Path

    from seculayer_demo.server.app import create_app

    document = create_app(_load_settings(), warm=False).openapi()
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    typer.echo(f"Wrote {target}")


if __name__ == "__main__":
    app()
