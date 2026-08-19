"use client";

import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import {
  Ban,
  Check,
  MoreHorizontal,
  Shield,
  ShieldOff,
  Trash2,
  UserPlus,
  UserRound,
  X,
  type LucideIcon,
} from "lucide-react";
import { type FormEvent, type ReactNode, useState } from "react";

import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Input,
  PanelHeader,
  Skeleton,
} from "@/components/ui/primitives";
import {
  useCurrentUser,
  useInvite,
  useBulkDecision,
  useBulkRemove,
  useManagedUsers,
  useRemovePerson,
  useUserDecision,
  useUserRole,
} from "@/hooks/use-dashboard";
import { formatRelativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { AccessStatus, ManagedUser } from "@/types/api";

const STATUS_TONE: Record<AccessStatus, "positive" | "warning" | "negative"> = {
  approved: "positive",
  pending: "warning",
  rejected: "negative",
};

export function AccountWorkspace() {
  const { data: me, isPending } = useCurrentUser();

  return (
    <main id="main-content" className="min-w-0 flex-1 overflow-y-auto">
      <div className="mx-auto w-full max-w-[1100px] px-4 py-4 sm:px-6 sm:py-5">
        <header className="mb-4">
          <h1 className="text-heading font-semibold tracking-[-0.02em] text-text-primary">
            Account
          </h1>
          <p className="mt-0.5 text-caption text-text-muted">
            Who you are signed in as
            {me?.is_admin ? ", and who else may sign in" : ""}
          </p>
        </header>

        {isPending ? <Skeleton className="h-32 w-full" /> : <Profile />}
        {me?.is_admin ? <People /> : null}
      </div>
    </main>
  );
}

function Profile() {
  const { data } = useCurrentUser();
  if (!data?.authenticated) {
    return (
      <Card>
        <EmptyState
          icon={UserRound}
          title="Not signed in"
          message="This deployment is not enforcing sign-in, so there is no account to show."
        />
      </Card>
    );
  }

  return (
    <Card className="p-4">
      <div className="flex items-start gap-3.5">
        {data.picture ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={data.picture}
            alt=""
            className="h-11 w-11 rounded-full object-cover"
            referrerPolicy="no-referrer"
          />
        ) : (
          <span className="flex h-11 w-11 items-center justify-center rounded-full bg-surface-muted">
            <UserRound className="h-5 w-5 text-text-muted" aria-hidden />
          </span>
        )}
        <div className="min-w-0">
          <p className="truncate text-body font-medium text-text-primary">
            {data.name || data.email}
          </p>
          {data.name ? (
            <p className="truncate text-meta text-text-secondary">{data.email}</p>
          ) : null}
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <Badge tone={data.role === "admin" ? "positive" : "neutral"}>
              {data.role === "admin" ? "Administrator" : "Member"}
            </Badge>
            {data.status ? (
              <Badge tone={STATUS_TONE[data.status]}>{data.status}</Badge>
            ) : null}
          </div>
        </div>
      </div>
    </Card>
  );
}

function People() {
  const { data, isPending, isError, error, refetch } = useManagedUsers(true);
  const decision = useUserDecision();
  const role = useUserRole();
  const remove = useRemovePerson();
  const bulkDecide = useBulkDecision();
  const bulkRemove = useBulkRemove();
  const [picked, setPicked] = useState<Set<string>>(new Set());

  const busy =
    decision.isPending ||
    role.isPending ||
    remove.isPending ||
    bulkDecide.isPending ||
    bulkRemove.isPending;

  const rows = data ?? [];
  const waiting = rows.filter((row) => row.status === "pending").length;
  // Your own account is never selectable — every bulk action would refuse it
  // anyway, and offering a tick box that cannot do anything is a small lie.
  const selectable = rows.filter((row) => !row.is_self);
  const allPicked = selectable.length > 0 && picked.size === selectable.length;

  function toggle(id: string) {
    setPicked((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function afterBulk(result: { skipped: Record<string, string> }) {
    // Keep anything that was refused selected, so the reason on screen still
    // has the rows it refers to.
    setPicked(new Set(Object.keys(result.skipped).filter((key) => key.includes("@")) ));
  }

  const chosen = [...picked];
  const skipped = bulkDecide.data?.skipped ?? bulkRemove.data?.skipped ?? {};

  return (
    <Card className="mt-4 overflow-hidden">
      <PanelHeader
        title="People"
        subtitle={
          waiting > 0
            ? `${waiting} waiting for a decision`
            : "Everyone who has signed in to this deployment"
        }
      />

      <InviteForm />

      {chosen.length > 0 ? (
        <div className="flex flex-wrap items-center gap-2 border-t border-border bg-surface-muted px-4 py-2.5">
          <span className="text-caption font-medium text-text-primary">
            {chosen.length} selected
          </span>
          <div className="ml-auto flex flex-wrap items-center gap-1.5">
            <Button
              size="sm"
              variant="secondary"
              icon={Check}
              loading={bulkDecide.isPending}
              onClick={() =>
                bulkDecide.mutate(
                  { ids: chosen, status: "approved" },
                  { onSuccess: afterBulk },
                )
              }
            >
              Approve
            </Button>
            <Button
              size="sm"
              variant="secondary"
              icon={Ban}
              loading={bulkDecide.isPending}
              onClick={() =>
                bulkDecide.mutate(
                  { ids: chosen, status: "rejected" },
                  { onSuccess: afterBulk },
                )
              }
            >
              Remove access
            </Button>
            <Button
              size="sm"
              variant="ghost"
              icon={Trash2}
              loading={bulkRemove.isPending}
              onClick={() => bulkRemove.mutate(chosen, { onSuccess: afterBulk })}
            >
              Forget
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setPicked(new Set())}>
              Clear
            </Button>
          </div>
        </div>
      ) : null}

      {Object.keys(skipped).length > 0 ? (
        <div className="border-t border-border bg-warning-soft px-4 py-2" role="status">
          {Object.entries(skipped).map(([who, why]) => (
            <p key={who} className="text-caption text-text-primary">
              <span className="font-medium">{who}</span> — {why}
            </p>
          ))}
        </div>
      ) : null}

      {isError ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : isPending ? (
        <div className="space-y-2 px-4 pb-4">
          {Array.from({ length: 3 }).map((_, index) => (
            <Skeleton key={index} className="h-12 w-full" />
          ))}
        </div>
      ) : rows.length === 0 ? (
        <EmptyState
          icon={UserRound}
          title="Nobody has signed in yet"
          message="The first person to sign in will appear here waiting for your approval."
        />
      ) : (
        <div className="divide-y divide-border border-t border-border">
          {selectable.length > 1 ? (
            <label className="flex items-center gap-3 px-4 py-2 text-caption text-text-muted">
              <input
                type="checkbox"
                checked={allPicked}
                onChange={() =>
                  setPicked(allPicked ? new Set() : new Set(selectable.map((r) => r.id)))
                }
                className="h-3.5 w-3.5 accent-accent"
                aria-label="Select everyone"
              />
              Select everyone
            </label>
          ) : null}
          {rows.map((row) => (
            <Person
              key={row.id}
              row={row}
              busy={busy}
              picked={picked.has(row.id)}
              onPick={() => toggle(row.id)}
              onDecide={(status) => decision.mutate({ id: row.id, status })}
              onRole={(next) => role.mutate({ id: row.id, role: next })}
              onRemove={() => remove.mutate(row.id)}
            />
          ))}
        </div>
      )}

      {decision.isError || role.isError || remove.isError || bulkDecide.isError ? (
        <p className="border-t border-border px-4 py-2 text-caption text-negative" role="alert">
          {(decision.error ?? role.error ?? remove.error ?? bulkDecide.error)?.message ??
            "That change could not be made."}
        </p>
      ) : null}
    </Card>
  );
}

function InviteForm() {
  const [email, setEmail] = useState("");
  const invite = useInvite();

  function submit(event: FormEvent) {
    event.preventDefault();
    const address = email.trim();
    if (!address) return;
    invite.mutate(address, { onSuccess: () => setEmail("") });
  }

  return (
    <form onSubmit={submit} className="flex flex-wrap items-center gap-2 px-4 pb-3">
      <Input
        type="email"
        value={email}
        onChange={(event) => setEmail(event.target.value)}
        placeholder="Invite someone by email"
        aria-label="Invite someone by email"
        className="min-w-0 flex-1 sm:max-w-xs"
      />
      <Button type="submit" variant="secondary" icon={UserPlus} loading={invite.isPending}>
        Invite
      </Button>
      {invite.isSuccess ? (
        <span className="text-caption text-positive" role="status">
          Invitation sent — they are approved the moment they sign in.
        </span>
      ) : null}
      {invite.isError ? (
        <span className="text-caption text-negative" role="alert">
          {invite.error.message}
        </span>
      ) : null}
    </form>
  );
}

/**
 * One person, and everything you can do to them.
 *
 * The decision that matters sits on the row as a button; everything else is
 * behind a menu. A row of five buttons makes "approve" and "delete for ever"
 * look like equally ordinary choices, which on this screen they are not.
 */
function Person({
  row,
  busy,
  picked,
  onPick,
  onDecide,
  onRole,
  onRemove,
}: {
  row: ManagedUser;
  busy: boolean;
  picked: boolean;
  onPick: () => void;
  onDecide: (status: AccessStatus) => void;
  onRole: (role: "admin" | "member") => void;
  onRemove: () => void;
}) {
  const pending = row.status === "pending";
  const invited = row.subject_pending;

  return (
    <div className="flex items-center gap-3 px-4 py-2.5">
      {row.is_self ? (
        <span className="w-3.5 shrink-0" aria-hidden />
      ) : (
        <input
          type="checkbox"
          checked={picked}
          onChange={onPick}
          className="h-3.5 w-3.5 shrink-0 accent-accent"
          aria-label={`Select ${row.email}`}
        />
      )}
      <Avatar src={row.picture} />

      <div className="min-w-0 flex-1">
        <p className="flex items-center gap-1.5 truncate text-meta font-medium text-text-primary">
          <span className="truncate">{row.name || row.email}</span>
          {row.is_self ? <span className="shrink-0 text-text-muted">(you)</span> : null}
          {row.role === "admin" ? (
            <Shield className="h-3 w-3 shrink-0 text-accent" aria-label="Administrator" />
          ) : null}
        </p>
        <p className="truncate text-caption text-text-muted">
          {row.name ? `${row.email} · ` : ""}
          {describe(row)}
        </p>
      </div>

      <Badge tone={STATUS_TONE[row.status]}>{invited ? "invited" : row.status}</Badge>

      <div className={cn("flex items-center gap-1", busy && "pointer-events-none opacity-50")}>
        {pending ? (
          <Button size="sm" variant="primary" icon={Check} onClick={() => onDecide("approved")}>
            Approve
          </Button>
        ) : null}

        <DropdownMenu.Root>
          <DropdownMenu.Trigger asChild>
            <button
              type="button"
              aria-label={`Actions for ${row.email}`}
              className="inline-flex h-8 w-8 items-center justify-center rounded-chip text-text-muted transition-colors duration-fast hover:bg-surface-muted hover:text-text-primary"
            >
              <MoreHorizontal className="h-4 w-4" aria-hidden />
            </button>
          </DropdownMenu.Trigger>
          <DropdownMenu.Portal>
            <DropdownMenu.Content
              align="end"
              sideOffset={4}
              className="z-50 min-w-[190px] rounded-card border border-border bg-surface p-1 shadow-[var(--shadow-popover)]"
            >
              {row.status !== "approved" ? (
                <Item icon={Check} onSelect={() => onDecide("approved")}>
                  {pending ? "Approve" : "Restore access"}
                </Item>
              ) : null}

              {row.status === "approved" && !row.is_self ? (
                <Item icon={Ban} tone="negative" onSelect={() => onDecide("rejected")}>
                  Remove access
                </Item>
              ) : null}

              {pending ? (
                <Item icon={X} tone="negative" onSelect={() => onDecide("rejected")}>
                  Reject
                </Item>
              ) : null}

              {!row.is_self && row.status === "approved" ? (
                row.role === "admin" ? (
                  <Item icon={ShieldOff} onSelect={() => onRole("member")}>
                    Remove administrator
                  </Item>
                ) : (
                  <Item icon={Shield} onSelect={() => onRole("admin")}>
                    Make administrator
                  </Item>
                )
              ) : null}

              {!row.is_self ? (
                <>
                  <DropdownMenu.Separator className="my-1 h-px bg-border" />
                  <Item icon={Trash2} tone="negative" onSelect={onRemove}>
                    Forget this account
                  </Item>
                </>
              ) : null}
            </DropdownMenu.Content>
          </DropdownMenu.Portal>
        </DropdownMenu.Root>
      </div>
    </div>
  );
}

function Item({
  icon: Icon,
  tone,
  onSelect,
  children,
}: {
  icon: LucideIcon;
  tone?: "negative";
  onSelect: () => void;
  children: ReactNode;
}) {
  return (
    <DropdownMenu.Item
      onSelect={onSelect}
      className={cn(
        "flex cursor-pointer select-none items-center gap-2 rounded-input px-2 py-1.5 text-meta outline-none",
        "data-[highlighted]:bg-surface-muted",
        tone === "negative" ? "text-negative" : "text-text-primary",
      )}
    >
      <Icon className="h-3.5 w-3.5 opacity-70" aria-hidden />
      {children}
    </DropdownMenu.Item>
  );
}

function Avatar({ src }: { src: string | null }) {
  if (src) {
    // eslint-disable-next-line @next/next/no-img-element
    return (
      <img
        src={src}
        alt=""
        className="h-8 w-8 shrink-0 rounded-full object-cover"
        referrerPolicy="no-referrer"
      />
    );
  }
  return (
    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-surface-muted">
      <UserRound className="h-4 w-4 text-text-muted" aria-hidden />
    </span>
  );
}

/** The one line of history worth showing on a row. */
function describe(row: ManagedUser): string {
  if (row.subject_pending) {
    return `invited by ${row.invited_by ?? "an administrator"} · not signed in yet`;
  }
  if (row.status === "pending") return `asked ${formatRelativeTime(row.requested_at)}`;
  if (row.decided_by) return `${row.status} by ${row.decided_by}`;
  return row.status;
}
