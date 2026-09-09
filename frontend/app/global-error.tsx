"use client";

/**
 * The last resort: the root layout itself threw.
 *
 * It replaces the whole document, so it carries its own html and body and
 * cannot use anything from the app — the providers, the theme bootstrap and
 * the stylesheet are all part of what failed. Plain inline styles, therefore,
 * and no imports.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: "100dvh",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: "12px",
          padding: "24px",
          textAlign: "center",
          background: "#f1f3ef",
          color: "#14181a",
          fontFamily:
            "ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
        }}
      >
        <h1 style={{ fontSize: "20px", fontWeight: 600, margin: 0 }}>Forecast Hub could not start</h1>
        <p style={{ margin: 0, maxWidth: "46ch", lineHeight: 1.6, color: "#4a5350" }}>
          Something failed before the app had loaded. Reloading is usually enough; if it is not,
          the reference below identifies this in the logs.
        </p>
        {error.digest ? (
          <p style={{ margin: 0, fontSize: "13px", color: "#6b7472" }}>Reference {error.digest}</p>
        ) : null}
        <button
          type="button"
          onClick={reset}
          style={{
            marginTop: "8px",
            border: "1px solid #14181a",
            borderRadius: "8px",
            background: "#14181a",
            color: "#f1f3ef",
            padding: "8px 16px",
            fontSize: "14px",
            cursor: "pointer",
          }}
        >
          Try again
        </button>
      </body>
    </html>
  );
}
