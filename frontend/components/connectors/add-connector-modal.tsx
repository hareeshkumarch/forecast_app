"use client";


import { CheckCircle2, XCircle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { CONNECTOR_LOGOS, type ConnectorLogoKey } from "@/components/connectors/connector-logos";
import { Modal } from "@/components/ui/modal";
import { Button, Field, InlineError, Input, Skeleton } from "@/components/ui/primitives";
import { errorMessage } from "@/lib/errors";
import {
  useConnectors,
  useConnectorTypes,
  useCreateConnector,
  useTestConnector,
  useUpdateConnector,
} from "@/hooks/use-dashboard";
import { cn } from "@/lib/utils";
import { useUiStore } from "@/stores/ui-store";
import type { ConnectorFormField, ConnectorType } from "@/types/api";

type FormValues = Record<string, string | boolean>;

/**
 * The one connector form, for adding and for correcting.
 *
 * Editing was the missing half: the route to update a saved connector had
 * been there all along with nothing calling it, so a wrong host or a rotated
 * password meant living with a broken source or making a second one with a
 * slightly different name.
 *
 * The type cannot change once saved — a Postgres connector is not a Snowflake
 * one with different fields — so the picker is only shown when adding.
 */
export function AddConnectorModal() {
  const modal = useUiStore((state) => state.modal);
  const closeModal = useUiStore((state) => state.closeModal);
  const targetId = useUiStore((state) => state.modalTargetId);
  const editing = modal === "edit-connector";
  const open = editing || modal === "add-connector";

  const { data: types, isLoading } = useConnectorTypes();
  const { data: connectors } = useConnectors();
  const existing = editing ? (connectors?.find((item) => item.id === targetId) ?? null) : null;
  const testMutation = useTestConnector();
  const createMutation = useCreateConnector();
  const updateMutation = useUpdateConnector();

  const [selectedType, setSelectedType] = useState<ConnectorType | null>(null);
  const [name, setName] = useState("");
  const [values, setValues] = useState<FormValues>({});
  const [formError, setFormError] = useState<string | null>(null);

  const activeType = useMemo(
    () => types?.find((item) => item.type === selectedType) ?? null,
    [types, selectedType],
  );

  
  useEffect(() => {
    if (!open || selectedType !== null) return;

    if (existing) {
      // Everything but the secrets, which the API deliberately never returns.
      // A blank secret field means "keep the stored one" rather than "clear
      // it", which is what the PATCH does with an absent key.
      setSelectedType(existing.type);
      setName(existing.name);
      setValues(
        Object.fromEntries(
          Object.entries(existing.config ?? {}).map(([key, value]) => [
            key,
            typeof value === "boolean" ? value : String(value ?? ""),
          ]),
        ),
      );
      return;
    }

    const first = types?.[0];
    if (first) {
      setSelectedType(first.type);
      setName(first.display_name);
    }
  }, [open, types, selectedType, existing]);


  useEffect(() => {
    if (!open) {
      setSelectedType(null);
      setName("");
      setValues({});
      setFormError(null);
      testMutation.reset();
      createMutation.reset();
      updateMutation.reset();
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
      // A secret already saved counts as filled: the form cannot show it, so
      // demanding it again would mean retyping the password to rename a host.
      .filter((field) => !(editing && field.secret))
      .map((field) => field.label);
  }

  function handleTest() {
    if (!selectedType) return;
    setFormError(null);
    const { config, credentials } = splitValues();
    // Testing a saved connector by id lets the server fill in the secrets it
    // holds, so an untouched password is still tested rather than sent blank.
    testMutation.mutate(
      editing && existing
        ? { connector_id: existing.id, type: selectedType, config, credentials }
        : { type: selectedType, config, credentials },
    );
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
    const settle = {
      onSuccess: () => closeModal(),
      onError: (error: unknown) => setFormError(errorMessage(error)),
    };

    if (editing && existing) {
      updateMutation.mutate(
        { id: existing.id, name: name.trim(), config, credentials },
        settle,
      );
      return;
    }

    createMutation.mutate({ name: name.trim(), type: selectedType, config, credentials }, settle);
  }

  const testResult = testMutation.data;
  const saving = createMutation.isPending || updateMutation.isPending;

  return (
    <Modal
      open={open}
      onClose={closeModal}
      title={editing ? `Edit ${existing?.name ?? "connector"}` : "Add Connector"}
      description={
        editing
          ? "Change the details this source connects with. Leave a password blank to keep the one already stored — it is encrypted and never sent back to the browser."
          : "Connect a data source. Credentials are encrypted before they are stored and are never returned to the browser."
      }
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
            loading={saving}
            disabled={!selectedType}
          >
            {editing ? "Save changes" : "Save"}
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
          
          {/* Only when adding: a saved connector's type is fixed, because its
              fields, its driver and its stored credentials all follow from it. */}
          <div hidden={editing}>
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
                    keepsStoredSecret={editing}
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

              {testMutation.isError ? <InlineError error={testMutation.error} /> : null}
              <InlineError message={formError ?? undefined} />
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
  keepsStoredSecret = false,
}: {
  field: ConnectorFormField;
  value: string | boolean | undefined;
  onChange: (next: string | boolean) => void;
  /** Editing, so an empty secret keeps what is stored rather than clearing it. */
  keepsStoredSecret?: boolean;
}) {
  const secretIsOptional = keepsStoredSecret && field.secret;
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
    <Field
      label={field.label}
      required={field.required && !secretIsOptional}
      hint={secretIsOptional ? "Leave blank to keep the saved one" : field.help_text}
    >
      <Input
        type={field.kind === "password" ? "password" : field.kind === "number" ? "number" : "text"}
        value={String(value ?? "")}
        onChange={(event) => onChange(event.target.value)}
        placeholder={secretIsOptional ? "••••••••" : field.placeholder}
        autoComplete={field.secret ? "new-password" : "off"}
      />
    </Field>
  );
}
