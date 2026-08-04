"use client";


import { Plus } from "lucide-react";

import { CONNECTOR_LOGOS, type ConnectorLogoKey } from "@/components/connectors/connector-logos";
import { Skeleton } from "@/components/ui/primitives";
import { useConnectors } from "@/hooks/use-dashboard";
import { cn } from "@/lib/utils";
import { useUiStore } from "@/stores/ui-store";
import type { Connector, ConnectorStatus } from "@/types/api";


const RAIL_ORDER: ConnectorLogoKey[] = [
  "bigquery",
  "snowflake",
  "redshift",
  "sqlserver",
  "mysql",
  "postgresql",
  "google_sheets",
  "excel",
  "rest_api",
  "salesforce",
];

const STATUS_DOT: Record<ConnectorStatus, string> = {
  connected: "bg-positive",
  configured: "bg-warning",
  error: "bg-negative",
  not_configured: "bg-border-strong",
};

const STATUS_LABEL: Record<ConnectorStatus, string> = {
  connected: "Connected",
  configured: "Configured, not tested",
  error: "Connection error",
  not_configured: "Not configured",
};

function orderConnectors(connectors: Connector[]): Connector[] {
  const rank = new Map(RAIL_ORDER.map((type, index) => [type, index] as const));
  return [...connectors].sort(
    (a, b) => (rank.get(a.type as ConnectorLogoKey) ?? 99) - (rank.get(b.type as ConnectorLogoKey) ?? 99),
  );
}

export function ConnectorRail() {
  const { data, isLoading, isError } = useConnectors();
  const selectedId = useUiStore((state) => state.selectedConnectorId);
  const selectConnector = useUiStore((state) => state.selectConnector);
  const openModal = useUiStore((state) => state.openModal);

  const connectors = data ? orderConnectors(data) : [];

  return (
    <aside
      aria-label="Data connectors"
      className="flex w-rail shrink-0 flex-col border-r border-border bg-surface"
    >
      <div className="px-4 pb-2 pt-4">
        <h2 className="eyebrow">Data Connectors</h2>
      </div>

      <nav className="scroll-thin flex-1 overflow-y-auto px-2.5 pb-2">
        {isLoading ? (
          <ul className="space-y-1" aria-hidden>
            {RAIL_ORDER.map((key) => (
              <li key={key} className="flex items-center gap-2.5 px-2 py-[7px]">
                <Skeleton className="h-4 w-4 rounded" />
                <Skeleton className="h-3 flex-1" />
              </li>
            ))}
          </ul>
        ) : isError ? (
          <p className="px-2 py-3 text-caption text-text-muted">
            Connectors unavailable. The API may still be starting.
          </p>
        ) : (
          <ul className="space-y-0.5">
            {connectors.map((connector) => {
              const Logo = CONNECTOR_LOGOS[connector.type as ConnectorLogoKey] ?? CONNECTOR_LOGOS.csv;
              const isSelected = connector.id === selectedId;

              return (
                <li key={connector.id}>
                  <button
                    type="button"
                    onClick={() => selectConnector(isSelected ? null : connector.id)}
                    aria-pressed={isSelected}
                    className={cn(
                      "group flex w-full items-center gap-2.5 rounded-input border px-2 py-[7px] text-left",
                      "transition-colors duration-fast",
                      isSelected
                        ? "border-[#eeddba] bg-accent-soft"
                        : "border-transparent hover:bg-surface-muted",
                    )}
                  >
                    <Logo className="h-4 w-4 shrink-0" />
                    <span
                      className={cn(
                        "flex-1 truncate text-meta",
                        isSelected ? "font-medium text-text-primary" : "text-text-secondary",
                      )}
                    >
                      {connector.name}
                    </span>
                    <span
                      className={cn("h-1.5 w-1.5 shrink-0 rounded-full", STATUS_DOT[connector.status])}
                      title={STATUS_LABEL[connector.status]}
                      aria-label={STATUS_LABEL[connector.status]}
                    />
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </nav>

      <div className="border-t border-border p-2.5">
        <button
          type="button"
          onClick={() => openModal("add-connector")}
          className={cn(
            "flex w-full items-center justify-center gap-1.5 rounded-input",
            "border border-dashed border-border-strong bg-surface px-2 py-[7px]",
            "text-meta font-medium text-text-secondary",
            "transition-colors duration-fast hover:border-accent hover:bg-accent-soft hover:text-accent",
          )}
        >
          <Plus className="h-3.5 w-3.5" aria-hidden />
          Add Connector
        </button>
      </div>
    </aside>
  );
}
