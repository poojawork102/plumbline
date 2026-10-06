/** Labelled range slider with the current value shown, instead of a number box. */
export default function Slider({ label, value, min, max, step = 1, format = (v) => v, onChange, name }) {
  const pct = ((Number(value) - min) / (max - min)) * 100;
  return (
    <div className="slider">
      <span className="slider-head">
        <label htmlFor={name}>{label}</label>
        <output htmlFor={name} aria-live="polite">{format(Number(value))}</output>
      </span>
      <input
        id={name}
        name={name}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        aria-valuetext={String(format(Number(value)))}
        style={{ "--fill": `${Math.max(0, Math.min(100, pct))}%` }}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </div>
  );
}
