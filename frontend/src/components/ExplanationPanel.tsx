import type { Explanation } from "../api/intelligence";
import SourceTag from "./SourceTag";

/** Plain-language explanation. The sentences come from the backend, which builds them only from the structured values returned with them. */
export default function ExplanationPanel({ explanation, title = "Explanation", defaultOpenAll = true }: { explanation: { headline: string; sections: Explanation["sections"] }; title?: string; defaultOpenAll?: boolean }) {
  return (
    <section aria-label={title} className="rounded-lg border border-teal-200 bg-teal-50/60 p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <h4 className="font-semibold text-slate-900">{title}</h4>
        <SourceTag kind="interpretation" />
      </div>
      <p className="mt-1 font-medium text-slate-900">{explanation.headline}</p>
      <ol className="mt-2 space-y-2">
        {explanation.sections.map((s) => (
          <li key={s.id}>
            <details open={defaultOpenAll}>
              <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wide text-tide">{s.title}</summary>
              <p className="mt-0.5 text-slate-800">{s.text}</p>
              {s.bullets.length > 0 && (
                <ul className="mt-1 list-disc space-y-0.5 pl-5 text-slate-700">
                  {s.bullets.map((b) => (
                    <li key={b}>{b}</li>
                  ))}
                </ul>
              )}
            </details>
          </li>
        ))}
      </ol>
      <p className="mt-2 text-xs text-slate-500">Written from the values shown on this page; nothing is added from outside the evidence. Scientific values are listed above.</p>
    </section>
  );
}
