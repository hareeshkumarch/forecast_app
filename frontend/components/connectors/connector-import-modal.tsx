"use client";


import { AlertTriangle, Database, Table2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Modal } from "@/components/ui/modal";
import { Button, Field, InlineError, Input, Skeleton } from "@/components/ui/primitives";
import { Select } from "@/components/ui/select";
import { errorMessage } from "@/lib/errors";
import {
  useConnectorSchemas,
  useConnectors,
  useImportFromConnector,
} from "@/hooks/use-dashboard";
import { formatInteger } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useUiStore } from "@/stores/ui-store";
import type { ConnectorType, SchemaTable } from "@/types/api";

/** Only these adapters run arbitrary SQL; the rest import a whole table. */
const SQL_TYPES: ConnectorType[] = [
  "postgresql",
  "mysql",
  "sqlserver",
  "snowflake",
  "redshift",
  "bigquery",
];

const DEFAULT_ROW_LIMIT = 500_000;

function tableKey(table: SchemaTable): string {
  return table.schema_name ? `${table.schema_name}.${table.table_name}` : table.table_name;
}

/**
 * The other half of the connector story: the rail could always *save* a
 * source, but there was no way to pull data out of one.
 */
export function ConnectorImportModal() {
  const modal = useUiStore((state) => state.modal);
  const connectorId = useUiStore((state) => state.modalConnectorId);
  const closeModal = useUiStore((state) => state.closeModal);
  const openModal = useUiStore((state) => state.openModal);
  const open = modal === "connector-import";

  const { data: connectors } = useConnectors();
  const connector = connectors?.find((item) => item.id === connectorId) ?? null;

  const schemasQuery = useConnectorSchemas(open ? connectorId : null);
  const importMutation = useImportFromConnector();

  const [mode, setMode] = useState<"table" | "query">("table");
  const [selected, setSelected] = useState("");
  const [query, setQuery] = useState("");
  const [datasetName, setDatasetName] = useState("");
  const [rowLimit, setRowLimit] = useState(DEFAULT_ROW_LIMIT);
  const [error, setError] = useState<string | null>(null);

  const tables = useMemo(() => schemasQuery.data?.tables ?? [], [schemasQuery.data]);
  const activeTable = tables.find((table) => tableKey(table) === selected) ?? null;
  const supportsQuery = connector ? SQL_TYPES.includes(connector.type) : false;

  useEffect(() => {
    if (!open) {
      setMode("table");
      setSelected("");
      setQuery("");
      setDatasetName("");
      setRowLimit(DEFAULT_ROW_LIMIT);
      setError(null);
      importMutation.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);


  useEffect(() => {
    if (!open || selected || tables.length === 0) return;
    const first = tables[0];
    if (first) setSelected(tableKey(first));
  }, [open, selected, tables]);

  function handleImport() {
    if (!connectorId) return;

    if (mode === "query" && !query.trim()) {
      setError("Write a SELECT statement, or import a table instead.");
      return;
    }
    if (mode === "table" && !activeTable) {
      setError("Choose a table to import.");
      return;
    }
    setError(null);

    importMutation.mutate(
      {
        id: connectorId,
        row_limit: rowLimit,
        dataset_name: datasetName.trim() || null,
        ...(mode === "query"
          ? { query: query.trim(), schema_name: null, table_name: null }
          : {
              schema_name: activeTable?.schema_name || null,
              table_name: activeTable?.table_name ?? null,
              query: null,
            }),
      },
      {
        onSuccess: () => {

          openModal("configure-forecast");
        },
        onError: (mutationError) => setError(errorMessage(mutationError)),
      },
    );
  }

  return (
    <Modal
      open={open}
      onClose={closeModal}
      title={connector ? `Import from ${connector.name}` : "Import data"}
      description="Pulls rows into a dataset you can profile and forecast."
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={closeModal}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={handleImport}
            loading={importMutation.isPending}
            disabled={!connector?.supports_import}
          >
            Import
          </Button>
        </>
      }
    >
      {!connector ? (
        <p className="text-caption text-text-muted">Select a connector from the rail first.</p>
      ) : !connector.supports_import ? (
        <p className="rounded-card border border-border bg-surface-muted px-3 py-2.5 text-caption text-text-secondary">
          This deployment does not ship a driver for {connector.name}, so it cannot import data.
        </p>
      ) : (
        <div className="space-y-4">
          {supportsQuery ? (
            <div className="flex gap-1 rounded-input border border-border bg-surface-muted p-0.5">
              {(["table", "query"] as const).map((value) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setMode(value)}
                  className={cn(
                    "flex flex-1 items-center justify-center gap-1.5 rounded-[7px] px-2 py-1.5 text-meta font-medium",
                    "transition-colors duration-fast",
                    mode === value
                      ? "bg-surface text-text-primary shadow-card"
                      : "text-text-secondary hover:text-text-primary",
                  )}
                >
                  {value === "table" ? (
                    <Table2 className="h-3.5 w-3.5" aria-hidden />
                  ) : (
                    <Database className="h-3.5 w-3.5" aria-hidden />
                  )}
                  {value === "table" ? "Pick a table" : "SQL query"}
                </button>
              ))}
            </div>
          ) : null}

          {mode === "table" ? (
            schemasQuery.isLoading ? (
              <div className="space-y-2" aria-hidden>
                <Skeleton className="h-8 w-full" />
                <Skeleton className="h-16 w-full" />
              </div>
            ) : schemasQuery.isError ? (
              <div className="flex items-start gap-2 rounded-card border border-warning-border bg-warning-soft px-3 py-2">
                <AlertTriangle className="mt-px h-3.5 w-3.5 shrink-0 text-warning" aria-hidden />
                <div>
                  <p className="text-caption text-warning">{errorMessage(schemasQuery.error)}</p>
                  <p className="mt-1 text-caption text-text-muted">
                    Check the connector&apos;s credentials, then test it from the rail.
                  </p>
                </div>
              </div>
            ) : tables.length === 0 ? (
              <p className="text-caption text-text-muted">
                This connector reported no tables to import.
              </p>
            ) : (
              <>
                <Field label="Table" required>
                  <Select
                    value={selected}
                    onChange={setSelected}
                    options={tables.map((table) => ({
                      value: tableKey(table),
                      label: tableKey(table),
                      hint:
                        table.row_estimate !== null
                          ? `~${formatInteger(table.row_estimate)} rows · ${table.columns.length} columns`
                          : `${table.columns.length} columns`,
                    }))}
                  />
                </Field>

                {activeTable ? (
                  <div className="rounded-card border border-border bg-surface-muted px-3 py-2.5">
                    <p className="text-caption font-medium text-text-secondary">
                      {activeTable.columns.length} columns
                    </p>
                    <div className="mt-1.5 flex flex-wrap gap-1">
                      {activeTable.columns.slice(0, 24).map((column) => (
                        <span
                          key={column.name}
                          title={`${column.data_type}${column.nullable ? " · nullable" : ""}`}
                          className="rounded-chip border border-border bg-surface px-1.5 py-0.5 text-caption text-text-secondary"
                        >
                          {column.name}
                        </span>
                      ))}
                      {activeTable.columns.length > 24 ? (
                        <span className="px-1 py-0.5 text-caption text-text-muted">
                          +{activeTable.columns.length - 24} more
                        </span>
                      ) : null}
                    </div>
                  </div>
                ) : null}
              </>
            )
          ) : (
            <Field label="SELECT statement" required hint="Read-only: only SELECT and WITH are accepted.">
              <textarea
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                rows={5}
                spellCheck={false}
                placeholder="SELECT order_date, region, revenue FROM public.sales"
                className="w-full rounded-input border border-border bg-surface px-2.5 py-1.5 font-mono text-caption text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
              />
            </Field>
          )}

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Field label="Dataset name" hint="Defaults to the table name">
              <Input
                value={datasetName}
                onChange={(event) => setDatasetName(event.target.value)}
                placeholder={activeTable?.table_name ?? `${connector.name} import`}
              />
            </Field>
            <Field label="Row limit" hint="Caps a very large table">
              <Input
                type="number"
                min={1}
                max={5_000_000}
                value={rowLimit}
                onChange={(event) => setRowLimit(Number(event.target.value) || DEFAULT_ROW_LIMIT)}
              />
            </Field>
          </div>

          <InlineError message={error ?? undefined} />
        </div>
      )}
    </Modal>
  );
}
