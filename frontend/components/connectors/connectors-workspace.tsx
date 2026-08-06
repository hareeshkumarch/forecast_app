"use client";


import { Download, Pencil, Plug, Plus, Trash2 } from "lucide-react";

import { CONNECTOR_LOGOS, type ConnectorLogoKey } from "@/components/connectors/connector-logos";
import { Badge, Button, Card, ErrorState, InlineError, Skeleton } from "@/components/ui/primitives";
import { useConnectors, useDeleteConnector, useTestConnector } from "@/hooks/use-dashboard";
import { formatRelativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useUiStore } from "@/stores/ui-store";
import type { Connector, ConnectorStatus } from "@/types/api";


const DISPLAY_ORDER: ConnectorLogoKey[] = [
  "bigquery",
  "snowflake",
  "redshift",
  "sqlserver",
  "mysql",
  "postgresql",
  "supabase",
  "google_sheets",
  "excel",
  "rest_api",
  "salesforce",
];

const STATUS_LABEL: Record<ConnectorStatus, string> = {
  connected: "Connected",
  configured: "Configured, not tested",
  error: "Connection error",
  not_configured: "Not configured",
};

function orderConnectors(connectors: Connector[]): Connector[] {
  const rank = new Map(DISPLAY_ORDER.map((type, index) => [type, index] as const));
  return [...connectors].sort(
    (a, b) => (rank.get(a.type as ConnectorLogoKey) ?? 99) - (rank.get(b.type as ConnectorLogoKey) ?? 99),
  );
}

export function ConnectorsWorkspace() {
  const { data, isLoading, isError, error, refetch } = useConnectors();
  const openModal = useUiStore((state) => state.openModal);
  const connectors = data ? orderConnectors(data) : [];
  const connected = connectors.filter((item) => item.status === "connected").length;
  const configured = connectors.filter((item) => item.status === "configured").length;
  const errors = connectors.filter((item) => item.status === "error").length;

  return (
    <main id="main-content" className="scroll-thin min-w-0 flex-1 overflow-y-auto bg-canvas px-4 py-4 sm:px-6 sm:py-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-heading font-semibold tracking-[-0.015em] text-text-primary">Connectors</h1>
          <p className="mt-0.5 text-meta text-text-secondary">
            Configure, test, and import data from every forecasting source.
          </p>
        </div>
        <Button variant="primary" icon={Plus} onClick={() => openModal("add-connector")}>
          Add connector
        </Button>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          ["Available", connectors.length, "neutral"],
          ["Connected", connected, "positive"],
          ["Configured", configured, "warning"],
          ["Needs attention", errors, errors ? "negative" : "neutral"],
        ].map(([label, value, tone]) => (
          <Card key={String(label)} className="p-3.5">
            <p className="text-caption text-text-muted">{label}</p>
            <p className={cn("mt-1 text-kpi font-semibold num", tone === "negative" ? "text-negative" : "text-text-primary")}>
              {value}
            </p>
          </Card>
        ))}
      </div>

      {isLoading ? (
        <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3" aria-hidden>
          {Array.from({ length: 6 }).map((_, index) => <Skeleton key={index} className="h-44 w-full" />)}
        </div>
      ) : isError ? (
        <Card className="mt-4"><ErrorState error={error} onRetry={() => void refetch()} /></Card>
      ) : (
        <section className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3" aria-label="Data connectors">
          {connectors.map((connector) => {
            const Logo = CONNECTOR_LOGOS[connector.type as ConnectorLogoKey] ?? CONNECTOR_LOGOS.csv;
            const tone = connector.status === "connected" ? "positive" : connector.status === "error" ? "negative" : connector.status === "configured" ? "warning" : "neutral";
            return (
              <Card key={connector.id} className="flex min-h-[176px] flex-col p-4">
                <div className="flex items-start gap-3">
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-input border border-border bg-surface-muted">
                    <Logo className="h-5 w-5" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <h2 className="truncate text-subhead font-semibold text-text-primary">{connector.name}</h2>
                    <p className="mt-0.5 truncate text-caption text-text-muted">{connector.type.replaceAll("_", " ")}</p>
                  </div>
                  <Badge tone={tone}>{STATUS_LABEL[connector.status]}</Badge>
                </div>

                <dl className="mt-4 grid grid-cols-2 gap-2 text-caption">
                  <div>
                    <dt className="text-text-muted">Import</dt>
                    <dd className="mt-0.5 font-medium text-text-primary">{connector.supports_import ? "Supported" : "Configuration only"}</dd>
                  </div>
                  <div>
                    <dt className="text-text-muted">Last tested</dt>
                    <dd className="mt-0.5 font-medium text-text-primary">
                      {connector.last_tested_at ? formatRelativeTime(connector.last_tested_at) : "Never"}
                    </dd>
                  </div>
                </dl>

                <div className="mt-auto pt-3">
                  <ConnectorActions connector={connector} onImport={() => openModal("connector-import", connector.id)} />
                </div>
              </Card>
            );
          })}
        </section>
      )}
    </main>
  );
}

/**
 * Revealed under the selected connector. Selection used to be decorative —
 * these are the two things you actually want to do with a saved source.
 */
export function ConnectorActions({
  connector,
  onImport,
}: {
  connector: Connector;
  onImport: () => void;
}) {
  const testMutation = useTestConnector();
  const removeMutation = useDeleteConnector();
  const openModal = useUiStore((state) => state.openModal);
  const result = testMutation.data;

  // A source nobody has configured is a card on the rail offering a type, not
  // something the customer owns. Removing it would take the type off the
  // screen with no way back, so editing and removing appear once there is
  // something of theirs to edit or remove.
  const isTheirs = connector.status !== "not_configured";

  function handleRemove() {
    const confirmed = window.confirm(
      `Remove "${connector.name}"? Its saved credentials are deleted. Data already ` +
        "imported through it, and any forecast built on that data, is untouched.",
    );
    if (confirmed) removeMutation.mutate(connector.id);
  }

  return (
    <div className="mb-1 mt-1 space-y-1.5 rounded-input border border-border bg-surface-muted/60 px-2 py-2">
      <p className="text-caption text-text-muted">
        {STATUS_LABEL[connector.status]}
        {connector.last_tested_at ? ` · ${formatRelativeTime(connector.last_tested_at)}` : ""}
      </p>

      <div className="flex flex-wrap gap-1.5">
        <Button
          size="sm"
          icon={Download}
          onClick={onImport}
          disabled={!connector.supports_import}
          title={
            connector.supports_import
              ? "Import a table from this connector"
              : "This deployment does not ship a driver for this connector"
          }
        >
          Import
        </Button>
        <Button
          size="sm"
          variant="ghost"
          icon={Plug}
          loading={testMutation.isPending}
          onClick={() => testMutation.mutate({ connector_id: connector.id })}
        >
          Test
        </Button>
        <Button
          size="sm"
          variant="ghost"
          icon={Pencil}
          onClick={() => openModal("edit-connector", connector.id)}
          title="Change the host, the port or the password"
        >
          Edit
        </Button>
        {isTheirs ? (
          <Button
            size="sm"
            variant="ghost"
            icon={Trash2}
            loading={removeMutation.isPending}
            onClick={handleRemove}
            className="text-negative hover:bg-negative-soft"
          >
            Remove
          </Button>
        ) : null}
      </div>

      {result ? (
        <p className={cn("text-caption", result.ok ? "text-positive" : "text-warning")}>
          {result.message}
        </p>
      ) : testMutation.isError ? (
        <InlineError error={testMutation.error} />
      ) : null}
    </div>
  );
}
