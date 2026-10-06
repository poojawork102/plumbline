const SOURCE_LABEL = { gemini: "AI proposed", deterministic: "Solver", cache: "Cached" };

/** Side-by-side cards for each verified layout option. */
export default function OptionPicker({ options, selected, edited = {}, onSelect }) {
  if (!options?.length) return null;
  return (
    <div className="options" role="radiogroup" aria-label="Layout options" data-testid="options">
      {options.map((o, i) => (
        <button
          key={o.id}
          type="button"
          role="radio"
          aria-checked={selected === i}
          className={`option-card ${selected === i ? "active" : ""}`}
          onClick={() => onSelect(i)}
        >
          <div className="option-top">
            <span className="option-id">{o.id}</span>
            <span className="option-source">{SOURCE_LABEL[o.source] || o.source}</span>
          </div>
          <strong className="option-name">{o.name}</strong>
          <ul className="option-tags">
            <li>{o.features.open_floor_pct}% open floor</li>
            <li>{o.features.wet_zone_grouped ? "Shared plumbing wall" : "Split wet/dry"}</li>
            <li className={o.features.toilet_screened ? "" : "warn"}>
              {o.features.toilet_screened ? "WC screened from door" : "WC faces door"}
            </li>
          </ul>
          {o.reasoning && <p className="option-why">{o.reasoning}</p>}
          {edited[o.id] && <span className="option-edited">Edited</span>}
        </button>
      ))}
    </div>
  );
}
