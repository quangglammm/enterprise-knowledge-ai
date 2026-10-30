// The stops an answer took, drawn as a route: the one bold element of the page.
// Each stop appears in turn when the answer arrives (skipped under reduced motion).

export function RouteLine({ stops, tone }: { stops: string[]; tone: "teal" | "bamboo" }) {
  const dot = tone === "teal" ? "bg-teal" : "bg-bamboo";
  const line = tone === "teal" ? "bg-teal/40" : "bg-bamboo/40";
  return (
    <ol className="flex items-center" aria-label="Route this answer took">
      {stops.map((stop, i) => (
        <li
          key={`${stop}-${i}`}
          className="flex items-center motion-safe:animate-[stop-in_300ms_ease-out_both]"
          style={{ animationDelay: `${i * 120}ms` }}
        >
          {i > 0 && <span className={`h-0.5 w-6 sm:w-10 ${line}`} aria-hidden />}
          <span className="flex flex-col items-center gap-1">
            <span className={`size-3 rounded-full ${dot}`} aria-hidden />
            <span className="text-xs font-medium whitespace-nowrap text-ink-soft">{stop}</span>
          </span>
        </li>
      ))}
    </ol>
  );
}
