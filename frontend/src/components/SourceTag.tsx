import Badge from "./Badge";
import type { BadgeTone } from "./Badge";

export type DataKind = "observed" | "forecast" | "derived" | "evaluation" | "interpretation" | "demo" | "generated";

const KIND: Record<DataKind, { label: string; tone: BadgeTone; hint: string }> = {
  observed: { label: "Observation", tone: "green", hint: "Measured / recorded data from an external source" },
  forecast: { label: "Model output", tone: "blue", hint: "Prediction from the project ConvLSTM model, not an observation" },
  derived: { label: "Derived metric", tone: "slate", hint: "Calculated from observations and/or model output" },
  evaluation: { label: "Test evaluation", tone: "slate", hint: "Measured on a held-out test period" },
  interpretation: { label: "Interpretation", tone: "yellow", hint: "Plain-language reading of the numbers; not a scientific conclusion" },
  generated: { label: "Modelled data", tone: "slate", hint: "Values come from a modelled dataset rather than direct measurements; see Ocean Data for the source" },
  demo: { label: "Reference rows", tone: "yellow", hint: "Reference rows stored with the application, not model output" },
};

/** Small badge that says what kind of information a card, chart or table is showing. */
export default function SourceTag({ kind }: { kind: DataKind }) {
  return (
    <span title={KIND[kind].hint}>
      <Badge tone={KIND[kind].tone}>{KIND[kind].label}</Badge>
    </span>
  );
}
