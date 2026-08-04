"use client";


import { CheckCircle2, XCircle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { CONNECTOR_LOGOS, type ConnectorLogoKey } from "@/components/connectors/connector-logos";
import { Modal } from "@/components/ui/modal";
import { Button, Field, Input, Skeleton } from "@/components/ui/primitives";
import { useConnectorTypes, useCreateConnector, useTestConnector } from "@/hooks/use-dashboard";
import { cn } from "@/lib/utils";
import { useUiStore } from "@/stores/ui-store";
import type { ConnectorFormField, ConnectorType } from "@/types/api";

type FormValues = Record<string, string | boolean>;

export function AddConnectorModal() {
  const modal = useUiStore((state) => state.modal);
  const closeModal = useUiStore((state) => state.closeModal);
  const open = modal === "add-connector";

  const { data: types, isLoading } = useConnectorTypes();
  const testMutation = useTestConnector();
  const createMutation = useCreateConnector();

  const [selectedType, setSelectedType] = useState<ConnectorType | null>(null);
  const [name, setName] = useState("");
  const [values, setValues] = useState<FormValues>({});
  const [formError, setFormError] = useState<string | null>(null);

  const activeType = useMemo(
    () => types?.find((item) => item.type === selectedType) ?? null,
    [types, selectedType],
  );

  
  useEffect(() => {
    if (open && types && types.length > 0 && selectedType === null) {
      const first = types[0];
      if (first) {
        setSelectedType(first.type);
        setName(first.display_name);
      }
    }
  }, [open, types, selectedType]);

  
  useEffect(() => {
    if (!open) {
      setSelectedType(null);
      setName("");
      setValues({});
      setFormError(null);
      testMutation.reset();
      createMutation.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  function chooseType(type: ConnectorType, displayName: string, defaultPort: number | null) {
    setSelectedType(type);
    setName(displayName);
    setValues(defaultPort ? { port: String(defaultPort) } : {});
    setFormError(null);
    testMutation.reset();
  }

  function splitValues() {
    const config: Record<string, unknown> = {};
    const credentials: Record<string, string> = {};

    for (const field of activeType?.fields ?? []) {
      const raw = values[field.key];
      if (raw === undefined || raw === "") continue;

      if (field.secret) {
        credentials[field.key] = String(raw);
      } else if (field.kind === "number") {
        const parsed = Number(raw);
        if (Number.isFinite(parsed)) config[field.key] = parsed;
      } else if (field.kind === "checkbox") {
        config[field.key] = Boolean(raw);
      } else {
        config[field.key] = String(raw);
      }
    }
    return { config, credentials };
  }

  function missingRequired(): string[] {
    return (activeType?.fields ?? [])
      .filter((field) => field.required && !String(values[field.key] ?? "").trim())
      .map((field) => field.label);
  }

  function handleTest() {
    if (!selectedType) return;
    setFormError(null);
    const { config, credentials } = splitValues();
    testMutation.mutate({ type: selectedType, config, credentials });
  }

  function handleSave() {
    if (!selectedType) return;

    const missing = missingRequired();
    if (missing.length > 0) {
      setFormError(`Fill in the required field(s): ${missing.join(", ")}.`);
      return;
    }
    if (!name.trim()) {
      setFormError("Give the connector a name.");
      return;
    }

    setFormError(null);
    const { config, credentials } = splitValues();

    createMutation.mutate(
      { name: name.trim(), type: selectedType, config, credentials },
      {
        onSuccess: () => closeModal(),
        onError: (error) => setFormError(error.message),
      },
    );
  }

  const testResult = testMutation.data;

  return (
    <Modal
      open={open}
      onClose={closeModal}
      title="Add Connector"
      description="Connect a data source. Credentials are encrypted before they are stored and are never returned to the browser."
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={closeModal}>
            Cancel
          </Button>
          <Button
            variant="secondary"
            onClick={handleTest}
            loading={testMutation.isPending}
            disabled={!selectedType}
          >
            Test Connection
          </Button>
          <Button
            variant="primary"
            onClick={handleSave}
            loading={createMutation.isPending}
            disabled={!selectedType}
          >
            Save
          </Button>
        </>
      }
    >
      {isLoading ? (
        <div className="space-y-3" aria-hidden>
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
        </div>
      ) : (
        <div className="space-y-4">
          
          <div>
            <span className="mb-1.5 block text-caption font-medium text-text-secondary">
              Connector type
            </span>
            <div className="grid grid-cols-3 gap-1.5 sm:grid-cols-5">
              {(types ?? []).map((type) => {
                const Logo = CONNECTOR_LOGOS[type.type as ConnectorLogoKey] ?? CONNECTOR_LOGOS.csv;
                const isActive = type.type === selectedType;
                return (
                  <button
                    key={type.type}
                    type="button"
                    onClick={() => chooseType(type.type, type.display_name, type.default_port)}
                    className={cn(
                      "flex flex-col items-center gap-1 rounded-input border px-1.5 py-2",
                      "transition-colors duration-fast",
                      isActive
                        ? "border-accent bg-accent-soft"
                        : "border-border hover:border-border-strong hover:bg-surface-muted",
                    )}
                  >
                    <Logo className="h-4 w-4" />
                    <span className="w-full truncate text-center text-caption text-text-secondary">
                      {type.display_name}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          {activeType ? (
            <>
              <Field label="Connector name" required>
                <Input
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="Production warehouse"
                />
              </Field>

              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                {activeType.fields.map((field) => (
                  <FormFieldInput
                    key={field.key}
                    field={field}
                    value={values[field.key]}
                    onChange={(next) => setValues((prev) => ({ ...prev, [field.key]: next }))}
                  />
                ))}
              </div>

              {!activeType.supports_import ? (
                <p className="rounded-card border border-border bg-surface-muted px-3 py-2 text-caption text-text-secondary">
                  {activeType.display_name} credentials can be saved, but this deployment does not
                  ship its driver — the connector will show as{" "}
                  <span className="font-medium">Not configured</span> until one is installed.
                </p>
              ) : null}

              {testResult ? (
                <div
                  className={cn(
                    "flex items-start gap-2 rounded-card border px-3 py-2",
                    testResult.ok
                      ? "border-positive-border bg-positive-soft"
                      : "border-warning-border bg-warning-soft",
                  )}
                >
                  {testResult.ok ? (
                    <CheckCircle2 className="mt-px h-3.5 w-3.5 shrink-0 text-positive" aria-hidden />
                  ) : (
                    <XCircle className="mt-px h-3.5 w-3.5 shrink-0 text-warning" aria-hidden />
                  )}
                  <div className="min-w-0">
                    <p
                      className={cn(
                        "text-caption font-medium",
                        testResult.ok ? "text-positive" : "text-warning",
                      )}
                    >
                      {testResult.message}
                    </p>
                    {testResult.latency_ms !== null ? (
                      <p className="mt-0.5 text-caption text-text-muted num">
                        {testResult.latency_ms.toFixed(0)} ms
                        {testResult.server_version ? ` · ${testResult.server_version}` : ""}
                      </p>
                    ) : null}
                  </div>
                </div>
              ) : null}

              {testMutation.isError ? (
                <p className="text-caption text-negative">{testMutation.error.message}</p>
              ) : null}
              {formError ? <p className="text-caption text-negative">{formError}</p> : null}
            </>
          ) : null}
        </div>
      )}
    </Modal>
  );
}

function FormFieldInput({
  field,
  value,
  onChange,
}: {
  field: ConnectorFormField;
  value: string | boolean | undefined;
  onChange: (next: string | boolean) => void;
}) {
  if (field.kind === "checkbox") {
    return (
      <label className="flex items-center gap-2 self-end pb-1">
        <input
          type="checkbox"
          checked={Boolean(value)}
          onChange={(event) => onChange(event.target.checked)}
          className="h-3.5 w-3.5 rounded-[3px] border-border accent-[color:var(--accent)]"
        />
        <span className="text-meta text-text-secondary">{field.label}</span>
      </label>
    );
  }

  if (field.kind === "textarea") {
    return (
      <div className="sm:col-span-2">
        <Field label={field.label} required={field.required} hint={field.help_text}>
          <textarea
            value={String(value ?? "")}
            onChange={(event) => onChange(event.target.value)}
            placeholder={field.placeholder}
            rows={3}
            className="w-full rounded-input border border-border bg-surface px-2.5 py-1.5 text-meta text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
          />
        </Field>
      </div>
    );
  }

  return (
    <Field label={field.label} required={field.required} hint={field.help_text}>
      <Input
        type={field.kind === "password" ? "password" : field.kind === "number" ? "number" : "text"}
        value={String(value ?? "")}
        onChange={(event) => onChange(event.target.value)}
        placeholder={field.placeholder}
        autoComplete={field.secret ? "new-password" : "off"}
      />
    </Field>
  );
}
