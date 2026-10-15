import type { ReactNode } from "react";
import { GLOSSARY } from "../utils/glossary";
import type { GlossaryKey } from "../utils/glossary";

/** A technical term with a keyboard- and hover-accessible plain-language explanation. */
export default function Term({ k, children }: { k: GlossaryKey; children: ReactNode }) {
  const id = `tip-${k}`;
  return (
    <span className="group relative inline-block">
      <span
        tabIndex={0}
        aria-describedby={id}
        className="cursor-help border-b border-dotted border-slate-500 outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
      >
        {children}
      </span>
      <span
        role="tooltip"
        id={id}
        className="pointer-events-none absolute left-0 top-full z-[1000] mt-1 hidden w-64 rounded-md bg-slate-900 px-3 py-2 text-xs font-normal normal-case leading-snug tracking-normal text-white shadow-lg group-hover:block group-focus-within:block"
      >
        {GLOSSARY[k]}
      </span>
    </span>
  );
}
