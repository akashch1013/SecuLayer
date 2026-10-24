import { clsx } from "clsx";
import { Check, Copy } from "lucide-react";
import { Tabs } from "radix-ui";
import { useId, useState, type ReactNode } from "react";

import type { AnatomyMessage, AnatomyPart, Finding, ModelRequest } from "../../../api/types";
import { Button } from "../../../components/Button";
import { Switch } from "../../../components/Switch";
import { Term } from "../../../components/Term";
import type { RunState } from "../useRun";
import type { Side } from "./RunColumn";

type Source = AnatomyPart["source"];

const BLOCK_STYLE: Record<AnatomyMessage["role"], string> = {
  developer: "border-l-dev-ink bg-dev-bg",
  user: "border-l-user-ink bg-user-bg",
  assistant: "border-l-border-strong bg-page",
  tool_call: "border-l-border-strong bg-page",
  tool_result: "border-l-outside-border bg-outside-bg",
};

const BLOCK_LABEL_STYLE: Record<AnatomyMessage["role"], string> = {
  developer: "text-dev-ink",
  user: "text-user-ink",
  assistant: "text-ink-2",
  tool_call: "text-ink-2",
  tool_result: "text-outside-ink",
};

const PART_STYLE: Record<Source, string> = {
  developer: "text-ink",
  user: "text-ink",
  external: "text-ink",
  model: "text-ink-2",
  injected: "rounded-chip border border-danger-border bg-danger-bg text-danger-ink",
  seculayer: "rounded-chip border border-dashed border-safe-border bg-safe-bg text-safe-ink",
};

/** Share-bar order and labels; "model" is the assistant's own earlier text. */
const SHARE: { source: string; label: string; bar: string }[] = [
  { source: "developer", label: "developer", bar: "bg-dev-ink" },
  { source: "seculayer", label: "SecuLayer", bar: "bg-safe-solid" },
  { source: "user", label: "user", bar: "bg-user-ink" },
  { source: "model", label: "assistant", bar: "bg-border-strong" },
  { source: "external", label: "outside content", bar: "bg-outside-solid" },
  { source: "injected", label: "attacker", bar: "bg-danger-solid" },
];

const LEGEND: { label: ReactNode; key: string; swatch: string }[] = [
  { key: "developer", label: "Developer instructions", swatch: "border-dev-ink bg-dev-bg" },
  { key: "user", label: "User", swatch: "border-user-ink bg-user-bg" },
  {
    key: "outside",
    label: <Term id="outsideContent">Outside content</Term>,
    swatch: "border-outside-border bg-outside-bg",
  },
  {
    key: "injected",
    label: "Injected by the attacker",
    swatch: "border-danger-border bg-danger-bg",
  },
  {
    key: "seculayer",
    label: "Added by SecuLayer",
    swatch: "border-dashed border-safe-border bg-safe-bg",
  },
];

const ZERO_WIDTH: Record<number, string> = {
  0x200b: "ZWSP",
  0x200c: "ZWNJ",
  0x200d: "ZWJ",
  0x2060: "WJ",
  0xfeff: "BOM",
};

/** Percentages that sum to exactly 100 (largest remainder), in SHARE order, zeros dropped. */
export function shares(tokens: Record<string, number>): { source: string; percent: number }[] {
  const entries = SHARE.map(({ source }) => ({ source, value: tokens[source] ?? 0 })).filter(
    (e) => e.value > 0,
  );
  const total = entries.reduce((sum, e) => sum + e.value, 0);
  if (total === 0) return [];
  const raw = entries.map((e) => ({ ...e, exact: (e.value / total) * 100 }));
  const floored = raw.map((e) => ({ ...e, percent: Math.floor(e.exact) }));
  let left = 100 - floored.reduce((sum, e) => sum + e.percent, 0);
  [...floored]
    .sort((a, b) => b.exact - Math.floor(b.exact) - (a.exact - Math.floor(a.exact)))
    .forEach((e) => {
      if (left > 0) {
        e.percent += 1;
        left -= 1;
      }
    });
  return floored.map(({ source, percent }) => ({ source, percent }));
}

/** How a run of invisible characters is shown: code points, and what tag characters spell. */
export function hiddenChip(part: AnatomyPart): { codes: string; reads: string; count: number } {
  const points = [...part.text].map((ch) => ch.codePointAt(0) ?? 0);
  const names = points.map(
    (p) => ZERO_WIDTH[p] ?? `U+${p.toString(16).toUpperCase().padStart(4, "0")}`,
  );
  const codes = names.length > 3 ? `${names.slice(0, 3).join(" ")} …` : names.join(" ");
  const reads =
    part.hidden_kind === "tag_chars"
      ? points
          .filter((p) => p >= 0xe0020 && p <= 0xe007e)
          .map((p) => String.fromCharCode(p - 0xe0000))
          .join("")
      : "";
  return { codes, reads, count: points.length };
}

/** The default call to show: the one where the model asked to act, else the last one.
 * (`call_index` counts from 0; the UI counts from 1.) */
export function defaultCall(state: RunState): number {
  const acting = state.responses.find((r) => r.tool_calls.some((c) => c.name === "send_email"));
  if (acting) return acting.call_index;
  return state.requests.at(-1)?.call_index ?? 0;
}

function callDescription(state: RunState, callIndex: number): string {
  const response = state.responses.find((r) => r.call_index === callIndex);
  if (!response) return "";
  const names = response.tool_calls.map((c) => c.name);
  if (names.includes("send_email")) return "the call where the assistant decided to send email";
  if (names.length > 0) return `the call where the assistant asked to run ${names.join(", ")}`;
  return "the call that wrote the reply";
}

export function rawText(messages: AnatomyMessage[]): string {
  return messages
    .map((m) => `[${m.label}]\n${m.parts.map((p) => (p.removed ? "" : p.text)).join("")}`)
    .join("\n\n");
}

/** Splits text so every occurrence of a flagged excerpt can be underlined. */
function underline(text: string, excerpts: string[]): ReactNode {
  const hits = excerpts.filter((e) => e.length >= 4 && text.includes(e));
  if (hits.length === 0) return text;
  const pieces: ReactNode[] = [];
  let rest = text;
  let key = 0;
  while (rest.length > 0) {
    let best: { at: number; excerpt: string } | null = null;
    for (const excerpt of hits) {
      const at = rest.indexOf(excerpt);
      if (at >= 0 && (best === null || at < best.at)) best = { at, excerpt };
    }
    if (!best) {
      pieces.push(rest);
      break;
    }
    if (best.at > 0) pieces.push(rest.slice(0, best.at));
    pieces.push(
      <span
        key={key++}
        data-flagged="true"
        className="underline decoration-ink decoration-wavy decoration-1 underline-offset-4"
      >
        {best.excerpt}
      </span>,
    );
    rest = rest.slice(best.at + best.excerpt.length);
  }
  return pieces;
}

function Part({ part, excerpts }: { part: AnatomyPart; excerpts: string[] }) {
  if (part.removed) {
    const size = part.text.length;
    return (
      <details className="mx-0.5 inline-block align-baseline font-ui text-caption">
        <summary className="cursor-pointer rounded-chip border border-dashed border-safe-border bg-safe-bg px-1 text-safe-ink line-through">
          hidden text removed by SecuLayer ({size} characters)
        </summary>
        <span className="mt-1 block font-mono text-mono text-danger-ink whitespace-pre-wrap">
          {part.text}
        </span>
      </details>
    );
  }
  if (part.hidden_kind === "tag_chars" || part.hidden_kind === "zero_width") {
    const chip = hiddenChip(part);
    return (
      <span
        data-testid="hidden-chip"
        className="mx-0.5 inline-block rounded-chip border border-danger-border bg-danger-bg px-1 font-ui text-caption text-danger-ink"
      >
        {chip.codes} · {chip.count} invisible {chip.count === 1 ? "character" : "characters"}
        {chip.reads && <> · reads “{chip.reads}”</>}
      </span>
    );
  }
  return (
    <span
      data-source={part.source}
      className={clsx(
        PART_STYLE[part.source],
        part.hidden && "underline decoration-danger-solid decoration-dotted underline-offset-4",
      )}
    >
      {underline(part.text, part.segment_id ? excerpts : [])}
    </span>
  );
}

function blockLabel(message: AnatomyMessage): string {
  if (message.role === "developer") return "Developer instructions";
  if (message.role === "user") return "User";
  return message.label;
}

export function SourceBlocks({
  messages,
  findings,
}: {
  messages: AnatomyMessage[];
  findings: Finding[];
}) {
  const excerpts = findings.map((f) => f.excerpt).filter(Boolean);
  return (
    <ol className="space-y-2">
      {messages.map((message, index) => (
        <li
          key={index}
          className={clsx("rounded-chip border-l-3 px-4 py-3", BLOCK_STYLE[message.role])}
        >
          <p className={clsx("text-caption font-semibold", BLOCK_LABEL_STYLE[message.role])}>
            {blockLabel(message)}
          </p>
          {message.parts.length > 0 && (
            <p className="mt-1 font-mono text-mono break-words whitespace-pre-wrap text-ink">
              {message.parts.map((part, i) => (
                <Part key={i} part={part} excerpts={excerpts} />
              ))}
            </p>
          )}
        </li>
      ))}
    </ol>
  );
}

export function ShareBar({ tokens }: { tokens: Record<string, number> }) {
  const parts = shares(tokens);
  if (parts.length === 0) return null;
  const label = (source: string) => SHARE.find((s) => s.source === source)?.label ?? source;
  return (
    <figure className="space-y-1.5">
      <figcaption className="text-caption text-ink-2">Share of this prompt</figcaption>
      <div className="flex h-3 w-full overflow-hidden rounded-chip" aria-hidden="true">
        {parts.map((p) => (
          <div
            key={p.source}
            className={SHARE.find((s) => s.source === p.source)?.bar}
            style={{ width: `${p.percent}%` }}
          />
        ))}
      </div>
      <ul className="flex flex-wrap gap-x-4 gap-y-1 text-caption text-ink-2" data-testid="share">
        {parts.map((p) => (
          <li key={p.source}>
            {label(p.source)} <span className="tabular-nums">{p.percent}%</span>
          </li>
        ))}
      </ul>
    </figure>
  );
}

function Legend() {
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-2 text-caption text-ink-2">
      {LEGEND.map((item) => (
        <li key={item.key} className="inline-flex items-center gap-1.5">
          <span aria-hidden="true" className={clsx("size-3 rounded-chip border", item.swatch)} />
          {item.label}
        </li>
      ))}
      <li className="inline-flex items-center gap-1.5">
        <span className="underline decoration-ink decoration-wavy decoration-1 underline-offset-4">
          Flagged
        </span>{" "}
        by SecuLayer
      </li>
    </ul>
  );
}

function CallView({ state, side }: { state: RunState; side: Side }) {
  const [chosen, setChosen] = useState<number | null>(null);
  const [raw, setRaw] = useState(false);
  const [copied, setCopied] = useState(false);
  const selectId = useId();
  const requests = state.requests;
  const callIndex = chosen ?? defaultCall(state);
  const request: ModelRequest | undefined =
    requests.find((r) => r.call_index === callIndex) ?? requests.at(-1);

  if (!request) {
    const ran = state.status !== "idle" || state.finished;
    return (
      <p className="text-body text-ink-3">
        {ran
          ? "The model wasn't called in this run: SecuLayer stopped it first."
          : `Run ${side === "with" ? "with" : "without"} SecuLayer to see what the model received.`}
      </p>
    );
  }

  const findings = side === "with" ? state.verdicts.flatMap((v) => v.findings) : [];
  const text = rawText(request.anatomy);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <label htmlFor={selectId} className="sr-only">
          Model call
        </label>
        <select
          id={selectId}
          value={request.call_index}
          onChange={(e) => setChosen(Number(e.target.value))}
          className="h-8 rounded-control border border-border-control bg-page px-2 text-small text-ink"
        >
          {requests.map((r) => (
            <option key={r.call_index} value={r.call_index}>
              Model call {r.call_index + 1} of {requests.length}
            </option>
          ))}
        </select>
        <span className="text-small text-ink-2">{callDescription(state, request.call_index)}</span>
        <div className="ml-auto flex items-center gap-4">
          <Switch label="Raw text" checked={raw} onCheckedChange={setRaw} />
          <Button
            variant="secondary"
            size="small"
            icon={copied ? Check : Copy}
            onClick={() => void copy()}
          >
            {copied ? "Copied" : "Copy"}
          </Button>
        </div>
      </div>
      <Legend />
      {side === "with" && (
        <p className="text-small text-ink-2">
          SecuLayer adds a security policy to the developer instructions and wraps each piece of
          outside content in markers (<Term id="spotlighting">spotlighting</Term>), so the model can
          tell it apart.
        </p>
      )}
      <ShareBar tokens={request.tokens_by_source} />
      {raw ? (
        <pre className="max-h-[40rem] overflow-auto rounded-chip border border-border p-4 font-mono text-mono whitespace-pre-wrap text-ink">
          {text}
        </pre>
      ) : (
        <div className="max-h-[40rem] overflow-y-auto">
          <SourceBlocks messages={request.anatomy} findings={findings} />
        </div>
      )}
    </div>
  );
}

/**
 * What the model received (§3.3): the prompt of one model call, coloured by where each piece
 * came from, for the run without SecuLayer and the run with it.
 */
export function PromptAnatomy({
  without,
  withSecuLayer,
  last,
}: {
  without: RunState;
  withSecuLayer: RunState;
  last: Side | null;
}) {
  const [tab, setTab] = useState<Side | null>(null);
  const active = tab ?? last ?? "without";
  const headingId = useId();
  const anyRun = without.requests.length > 0 || withSecuLayer.requests.length > 0 || last;
  return (
    <section
      id="prompt-anatomy"
      tabIndex={-1}
      aria-labelledby={headingId}
      className="space-y-4 border-t border-border pt-6"
    >
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h2 id={headingId} className="text-h3 text-ink">
          What the model received
        </h2>
      </div>
      {!anyRun ? (
        <p className="text-body text-ink-3">Run the attack first, then look here.</p>
      ) : (
        <Tabs.Root value={active} onValueChange={(v) => setTab(v as Side)}>
          <Tabs.List aria-label="Which run" className="flex gap-6 border-b border-border">
            {(["without", "with"] as const).map((side) => (
              <Tabs.Trigger
                key={side}
                value={side}
                className="-mb-px border-b-2 border-transparent pb-2 text-small font-semibold text-ink-2 hover:text-ink data-[state=active]:border-accent data-[state=active]:text-ink"
              >
                {side === "with" ? "With SecuLayer" : "Without SecuLayer"}
              </Tabs.Trigger>
            ))}
          </Tabs.List>
          <Tabs.Content value="without" className="pt-4">
            <CallView key={`without-${without.started?.run_id}`} state={without} side="without" />
          </Tabs.Content>
          <Tabs.Content value="with" className="pt-4">
            <CallView
              key={`with-${withSecuLayer.started?.run_id}`}
              state={withSecuLayer}
              side="with"
            />
          </Tabs.Content>
        </Tabs.Root>
      )}
      <p className="text-small text-ink-3">
        Why the model gets confused: these blocks reach the model as one sequence of text. Only the
        wording tells it which part came from a stranger. That's{" "}
        <Term id="promptInjection">prompt injection</Term>.
      </p>
    </section>
  );
}
