"use client";

import * as RadixSelect from "@radix-ui/react-select";
import { Check, ChevronDown, ChevronUp } from "lucide-react";
import { forwardRef, useContext, type ComponentType } from "react";

import { FieldContext } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";

export type SelectIcon = ComponentType<{ className?: string }>;

export interface SelectOption<T extends string = string> {
  value: T;
  label: string;

  hint?: string;
  icon?: SelectIcon;

  iconKeepsColour?: boolean;
  disabled?: boolean;
}

export interface SelectGroup<T extends string = string> {
  label: string;
  options: SelectOption<T>[];
}

type Items<T extends string> = SelectOption<T>[] | SelectGroup<T>[];

function isGrouped<T extends string>(items: Items<T>): items is SelectGroup<T>[] {
  return items.length > 0 && "options" in items[0]!;
}

function flatten<T extends string>(items: Items<T>): SelectOption<T>[] {
  return isGrouped(items) ? items.flatMap((group) => group.options) : items;
}

const TRIGGER = cn(
  "group flex h-11 w-full items-center gap-2 rounded-input border border-border bg-surface px-2.5 fine:h-8",
  "text-meta text-text-primary",
  "transition-colors duration-fast",
  "hover:border-border-strong",
  "focus:outline-none focus-visible:border-accent focus-visible:ring-2 focus-visible:ring-accent-soft",
  "data-[state=open]:border-accent",
  "data-[placeholder]:text-text-muted",
  "disabled:cursor-not-allowed disabled:bg-surface-muted disabled:text-text-muted disabled:hover:border-border",
);

const SCROLL_BUTTON = "flex h-5 items-center justify-center text-text-muted";

function Option<T extends string>({ option }: { option: SelectOption<T> }) {
  const Icon = option.icon;

  return (
    <RadixSelect.Item
      value={option.value}
      disabled={option.disabled}
      className={cn(
        "relative flex cursor-pointer select-none items-start gap-2 rounded-chip py-1.5 pl-2 pr-7 outline-none",
        "data-[highlighted]:bg-surface-muted",
        "data-[state=checked]:bg-accent-soft",
        "data-[disabled]:cursor-not-allowed data-[disabled]:opacity-50",
      )}
    >
      {Icon ? (
        <Icon
          className={cn(
            "mt-0.5 h-3.5 w-3.5 shrink-0",
            option.iconKeepsColour ? undefined : "text-text-muted",
          )}
        />
      ) : null}
      <span className="min-w-0 flex-1">
        <RadixSelect.ItemText>
          <span className="block truncate text-meta text-text-primary">{option.label}</span>
        </RadixSelect.ItemText>
        {option.hint ? (
          <span className="mt-0.5 block text-caption leading-[15px] text-text-muted">
            {option.hint}
          </span>
        ) : null}
      </span>
      <RadixSelect.ItemIndicator className="absolute right-2 top-2">
        <Check className="h-3.5 w-3.5 text-accent" aria-hidden />
      </RadixSelect.ItemIndicator>
    </RadixSelect.Item>
  );
}

export interface SelectProps<T extends string = string> {
  value: T;
  onChange: (value: T) => void;
  options: Items<T>;
  placeholder?: string;
  disabled?: boolean;

  label?: string;
  className?: string;

  menuClassName?: string;
  id?: string;
}

export const Select = forwardRef<HTMLButtonElement, SelectProps>(function Select(
  { value, onChange, options, placeholder = "Select…", disabled, label, className, menuClassName, id },
  ref,
) {
  const field = useContext(FieldContext);
  const selected = flatten(options).find((option) => option.value === value);
  const SelectedIcon = selected?.icon;

  return (
    <RadixSelect.Root value={value} onValueChange={onChange} disabled={disabled}>
      <RadixSelect.Trigger
        ref={ref}
        id={id ?? field?.controlId}
        aria-label={label}
        aria-describedby={field?.describedBy}
        aria-invalid={field?.invalid || undefined}
        className={cn(TRIGGER, className)}
      >
        {SelectedIcon ? (
          <SelectedIcon
            className={cn(
              "h-3.5 w-3.5 shrink-0",
              selected?.iconKeepsColour ? undefined : "text-text-muted",
            )}
          />
        ) : null}
        <span className="min-w-0 flex-1 truncate text-left">
          <RadixSelect.Value placeholder={placeholder} />
        </span>
        <RadixSelect.Icon asChild>
          <ChevronDown
            className="h-3.5 w-3.5 shrink-0 text-text-muted transition-transform duration-fast group-data-[state=open]:rotate-180"
            aria-hidden
          />
        </RadixSelect.Icon>
      </RadixSelect.Trigger>

      <RadixSelect.Portal>
        <RadixSelect.Content
          position="popper"
          sideOffset={4}
          collisionPadding={8}
          className={cn(
            "z-50 max-h-[min(22rem,var(--radix-select-content-available-height))]",
            "w-[var(--radix-select-trigger-width)] min-w-[9rem] max-w-[calc(100vw-16px)]",
            "overflow-hidden rounded-card border border-border bg-surface shadow-popover",
            menuClassName,
          )}
        >
          <RadixSelect.ScrollUpButton className={SCROLL_BUTTON}>
            <ChevronUp className="h-3.5 w-3.5" aria-hidden />
          </RadixSelect.ScrollUpButton>

          <RadixSelect.Viewport className="p-1">
            {isGrouped(options)
              ? options.map((group, index) => (
                  <RadixSelect.Group key={group.label}>
                    {index > 0 ? (
                      <RadixSelect.Separator className="my-1 h-px bg-border" />
                    ) : null}
                    <RadixSelect.Label className="px-2 pb-1 pt-1.5 text-caption font-medium uppercase tracking-[0.04em] text-text-muted">
                      {group.label}
                    </RadixSelect.Label>
                    {group.options.map((option) => (
                      <Option key={option.value} option={option} />
                    ))}
                  </RadixSelect.Group>
                ))
              : options.map((option) => <Option key={option.value} option={option} />)}
          </RadixSelect.Viewport>

          <RadixSelect.ScrollDownButton className={SCROLL_BUTTON}>
            <ChevronDown className="h-3.5 w-3.5" aria-hidden />
          </RadixSelect.ScrollDownButton>
        </RadixSelect.Content>
      </RadixSelect.Portal>
    </RadixSelect.Root>
  );
}) as <T extends string>(props: SelectProps<T> & { ref?: React.Ref<HTMLButtonElement> }) => JSX.Element;
