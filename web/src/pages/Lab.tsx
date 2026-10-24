import { ChevronLeft, RotateCw, SearchX, TriangleAlert } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, type ReactNode } from "react";
import { Link, useParams, useSearchParams } from "react-router";

import { ApiError, useApi } from "../api/client";
import type { CaseDetail, ScenarioDetail } from "../api/types";
import { Button, ButtonLink } from "../components/Button";
import { Code } from "../components/Code";
import { EmptyState, ErrorState } from "../components/EmptyState";
import { Container, Page } from "../components/Page";
import { Term } from "../components/Term";
import { ScenarioCards } from "../features/home/ScenarioCards";
import { ShortcutHelp, usePresenterShortcuts } from "../features/lab/PresenterShortcuts";
import { RunArea } from "../features/lab/run/RunArea";
import type { Side } from "../features/lab/run/RunColumn";
import { AboutCase } from "../features/lab/setup/AboutCase";
import { CaseList, listedCases } from "../features/lab/setup/CaseList";
import { ScenarioHeader } from "../features/lab/setup/ScenarioHeader";
import { SetupPanel } from "../features/lab/setup/SetupPanel";

function isScenarioDetail(data: unknown): data is ScenarioDetail {
  return typeof data === "object" && data !== null && Array.isArray((data as ScenarioDetail).cases);
}

function Breadcrumb() {
  return (
    <nav aria-label="Breadcrumb" className="mb-3">
      <Link
        to="/lab"
        className="inline-flex items-center gap-1 text-small font-semibold text-accent underline-offset-4 hover:text-accent-hover hover:underline"
      >
        <ChevronLeft size={16} strokeWidth={1.75} aria-hidden="true" />
        All scenarios
      </Link>
    </nav>
  );
}

/** Loading and error states share one frame, so the heading stays the same element. */
function LabFrame({ children }: { children: ReactNode }) {
  return (
    <Container className="py-12">
      <Breadcrumb />
      <h1 className="text-h1 text-ink">Attack Lab</h1>
      <div className="mt-6">{children}</div>
    </Container>
  );
}

/** /lab: pick a scenario. */
function LabIndex() {
  return (
    <Page
      title="Attack Lab"
      lead={
        <>
          Pick a toy app. You'll run an attack on it without SecuLayer, then with it, and see
          exactly what the model read and what changed. Every app has some or all of the{" "}
          <Term id="lethalTrifecta">lethal trifecta</Term>.
        </>
      }
    >
      <ScenarioCards />
    </Page>
  );
}

function defaultCaseId(detail: ScenarioDetail): string {
  const { attacks, normal } = listedCases(detail.cases);
  return attacks[0]?.id ?? normal[0]?.id ?? "";
}

/** /lab/:scenarioId?case=…: the core demo. */
function ScenarioLab({ scenarioId }: { scenarioId: string }) {
  const scenario = useApi<ScenarioDetail>(`/api/scenarios/${encodeURIComponent(scenarioId)}`);
  const [params, setParams] = useSearchParams();
  const detail = scenario.status === "ok" && isScenarioDetail(scenario.data) ? scenario.data : null;

  const requested = params.get("case");
  const selected: CaseDetail | undefined = detail
    ? (detail.cases.find((c) => c.id === requested) ??
      detail.cases.find((c) => c.id === defaultCaseId(detail)))
    : undefined;

  const select = useCallback(
    (id: string) =>
      setParams(
        (previous) => {
          const next = new URLSearchParams(previous);
          next.set("case", id);
          return next;
        },
        { replace: true },
      ),
    [setParams],
  );

  useEffect(() => {
    document.title = `${detail?.title ?? "Attack Lab"} · SecuLayer`;
  }, [detail?.title]);

  const runRef = useRef<((side: Side) => void) | null>(null);
  const selectedId = selected?.id;
  const shortcuts = useMemo(() => {
    const listed = detail ? listedCases(detail.cases) : { attacks: [], normal: [] };
    const order = [...listed.attacks, ...listed.normal].map((c) => c.id);
    const step = (by: number) => {
      const at = order.indexOf(selectedId ?? "");
      const next = order[Math.min(Math.max(at + by, 0), order.length - 1)];
      if (next && next !== selectedId) select(next);
    };
    return {
      previous: () => step(-1),
      next: () => step(1),
      run: (side: Side) => runRef.current?.(side),
      prompt: () => {
        const target = document.getElementById("prompt-anatomy");
        target?.scrollIntoView({ block: "start" });
        target?.focus({ preventScroll: true });
      },
    };
  }, [detail, selectedId, select]);
  const { helpOpen, closeHelp } = usePresenterShortcuts(shortcuts);

  if (scenario.status === "loading") {
    return (
      <LabFrame>
        <p className="text-body text-ink-3" aria-live="polite">
          Loading the scenario…
        </p>
      </LabFrame>
    );
  }

  if (scenario.status === "error" || !detail) {
    const missing =
      scenario.status === "error" &&
      scenario.error instanceof ApiError &&
      scenario.error.status === 404;
    return (
      <LabFrame>
        {missing ? (
          <EmptyState
            icon={SearchX}
            title="There's no scenario with that name."
            help={
              <>
                <Code>{scenarioId}</Code> isn't one of the four toy apps.
              </>
            }
            action={
              <ButtonLink to="/lab" variant="secondary">
                See all scenarios
              </ButtonLink>
            }
          />
        ) : (
          <ErrorState
            icon={TriangleAlert}
            title="Couldn't load this scenario."
            help="The server answered, but not with the scenario's data."
            action={
              <Button
                variant="secondary"
                icon={RotateCw}
                onClick={scenario.status === "error" ? scenario.retry : undefined}
              >
                Try again
              </Button>
            }
          />
        )}
      </LabFrame>
    );
  }

  return (
    <Container className="py-10">
      <ScenarioHeader scenario={detail} />
      <div className="mt-10 grid items-start gap-8 border-t border-border pt-8 lg:grid-cols-[15rem_minmax(0,1fr)] xl:grid-cols-[17rem_minmax(0,1fr)]">
        <aside className="lg:sticky lg:top-4" aria-label="Attacks and normal use">
          {selected && <CaseList cases={detail.cases} selectedId={selected.id} onSelect={select} />}
          <p className="mt-6 text-caption text-ink-3">
            Presenting? Press <kbd className="font-mono">?</kbd> for shortcuts.
          </p>
        </aside>
        {selected ? (
          <div className="min-w-0 space-y-10">
            <SetupPanel key={`setup:${selected.id}`} scenario={detail} caseDetail={selected} />
            <RunArea
              key={`run:${selected.id}`}
              scenario={detail}
              caseDetail={selected}
              runRef={runRef}
            />
            <AboutCase caseDetail={selected} />
          </div>
        ) : (
          <EmptyState icon={SearchX} title="This scenario has no cases yet." />
        )}
      </div>
      <ShortcutHelp open={helpOpen} onClose={closeHelp} />
    </Container>
  );
}

export function LabPage() {
  const { scenarioId } = useParams();
  return scenarioId ? <ScenarioLab key={scenarioId} scenarioId={scenarioId} /> : <LabIndex />;
}
