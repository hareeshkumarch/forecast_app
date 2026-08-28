export function Mark({ size = 31 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 34"
      fill="none"
      aria-hidden
      className="shrink-0"
    >
      <path d="M16 1 30 9 16 17 2 9 16 1Z" fill="var(--land-mark-crown)" />
      <path d="m2 9 14 8v16L2 25V9Z" fill="var(--land-mark-shadow)" />
      <path d="m30 9-14 8v16l14-8V9Z" fill="var(--accent)" />
    </svg>
  );
}
