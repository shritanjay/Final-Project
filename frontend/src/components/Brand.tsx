export default function Brand({ small = false }: { small?: boolean }) {
  return (
    <div className={`brand ${small ? "brand-small" : ""}`}>
      <span className="brand-mark">CS</span>
      <span className="brand-name">
        Career <em>Scout</em>
      </span>
    </div>
  );
}
