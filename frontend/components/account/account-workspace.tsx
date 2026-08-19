"use client";

import { Check, Shield, ShieldOff, UserPlus, UserRound, X } from "lucide-react";
import { type FormEvent, useState } from "react";

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
  useManagedUsers,
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
  const busy = decision.isPending || role.isPending;

  const waiting = (data ?? []).filter((row) => row.status === "pending").length;

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

      {isError ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : isPending ? (
        <div className="space-y-2 px-4 pb-4">
          {Array.from({ length: 3 }).map((_, index) => (
            <Skeleton key={index} className="h-12 w-full" />
          ))}
        </div>
      ) : (data?.length ?? 0) === 0 ? (
        <EmptyState
          icon={UserRound}
          title="Nobody has signed in yet"
          message="The first person to sign in will appear here waiting for your approval."
        />
      ) : (
        <div className="divide-y divide-border border-t border-border">
          {data?.map((row) => (
            <Person
              key={row.id}
              row={row}
              busy={busy}
              onDecide={(status) => decision.mutate({ id: row.id, status })}
              onRole={(next) => role.mutate({ id: row.id, role: next })}
            />
          ))}
        </div>
      )}

      {decision.isError || role.isError ? (
        <p className="px-4 py-2 text-caption text-negative" role="alert">
          {(decision.error ?? role.error)?.message ?? "That change could not be made."}
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

function Person({
  row,
  busy,
  onDecide,
  onRole,
}: {
  row: ManagedUser;
  busy: boolean;
  onDecide: (status: AccessStatus) => void;
  onRole: (role: "admin" | "member") => void;
}) {
  const pending = row.status === "pending";

  return (
    <div className="flex flex-wrap items-center gap-3 px-4 py-3">
      {row.picture ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={row.picture}
          alt=""
          className="h-8 w-8 shrink-0 rounded-full object-cover"
          referrerPolicy="no-referrer"
        />
      ) : (
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-surface-muted">
          <UserRound className="h-4 w-4 text-text-muted" aria-hidden />
        </span>
      )}

      <div className="min-w-0 flex-1">
        <p className="truncate text-meta font-medium text-text-primary">
          {row.name || row.email}
          {row.is_self ? <span className="ml-1.5 text-text-muted">(you)</span> : null}
        </p>
        <p className="truncate text-caption text-text-muted">
          {row.name ? `${row.email} · ` : ""}
          {pending
            ? `asked ${formatRelativeTime(row.requested_at)}`
            : row.decided_by
              ? `${row.status} by ${row.decided_by}`
              : row.status}
        </p>
      </div>

      <div className="flex items-center gap-1.5">
        <Badge tone={STATUS_TONE[row.status]}>{row.status}</Badge>
        {row.role === "admin" ? <Badge tone="positive">admin</Badge> : null}
      </div>

      <div className={cn("flex items-center gap-1.5", busy && "pointer-events-none opacity-60")}>
        {pending ? (
          <>
            <Button size="sm" variant="primary" icon={Check} onClick={() => onDecide("approved")}>
              Approve
            </Button>
            <Button size="sm" variant="ghost" icon={X} onClick={() => onDecide("rejected")}>
              Reject
            </Button>
          </>
        ) : row.status === "rejected" ? (
          <Button size="sm" variant="secondary" icon={Check} onClick={() => onDecide("approved")}>
            Allow
          </Button>
        ) : row.is_self ? null : row.role === "admin" ? (
          <Button size="sm" variant="ghost" icon={ShieldOff} onClick={() => onRole("member")}>
            Remove admin
          </Button>
        ) : (
          <Button size="sm" variant="ghost" icon={Shield} onClick={() => onRole("admin")}>
            Make admin
          </Button>
        )}
      </div>
    </div>
  );
}
