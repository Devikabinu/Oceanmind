import SourceTag from "./SourceTag";

/** "Why am I seeing this?": numbered evidence, plus the labelled data sources and classification. */
export default function WhyPanel({
  title = "Why this?",
  reasons,
  sources,
  classification,
  recommendation,
}: {
  title?: string;
  reasons: string[];
  sources?: string[];
  classification?: string;
  recommendation?: string;
}) {
  return (
    <div className="rounded-md border border-slate-200 bg-slate-50 p-3 text-sm">
      <div className="flex items-center gap-2 font-semibold text-slate-900">
        {title} <SourceTag kind="interpretation" />
      </div>
      <ol className="mt-2 list-decimal space-y-1 pl-5 text-slate-800">
        {reasons.map((r, i) => (
          <li key={i}>{r}</li>
        ))}
      </ol>
      {classification && <p className="mt-2 text-xs text-slate-600">Basis: {classification}</p>}
      {sources && sources.length > 0 && <p className="mt-1 text-xs text-slate-600">Sources: {sources.join(" · ")}</p>}
      {recommendation && <p className="mt-1 text-xs text-slate-600">Suggested action: {recommendation}</p>}
    </div>
  );
}
