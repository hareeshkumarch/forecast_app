import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Modal } from "@/components/ui/modal";
import { useConfirmStore } from "@/stores/confirm-store";

function open(props: Partial<Parameters<typeof Modal>[0]> = {}) {
  const onClose = vi.fn();
  render(
    <Modal open onClose={onClose} title="Add Connector" {...props}>
      <p>body</p>
    </Modal>,
  );
  return onClose;
}

beforeEach(() => {
  useConfirmStore.getState().resolve(false);
});

describe("a dialog with a request in the air", () => {
  it("closes on the close button when nothing is running", () => {
    const onClose = open();
    fireEvent.click(screen.getByLabelText("Close"));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("disables the close button while it is busy", () => {
    const onClose = open({ busy: true });
    const close = screen.getByLabelText("Close");

    expect(close).toBeDisabled();
    fireEvent.click(close);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("does not let Escape throw away an upload that is still going", () => {
    const onClose = open({ busy: true });
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
  });

  it("says it is busy to anything reading the page for that", () => {
    open({ busy: true });
    expect(screen.getByRole("dialog")).toHaveAttribute("aria-busy", "true");
  });
});

describe("a dialog with something typed into it", () => {
  it("asks before discarding it", async () => {
    const onClose = open({ dirty: true });

    await act(async () => {
      fireEvent.click(screen.getByLabelText("Close"));
    });

    expect(onClose).not.toHaveBeenCalled();
    expect(useConfirmStore.getState().request?.confirmLabel).toBe("Discard");
  });

  it("stays open when the answer is to keep editing", async () => {
    const onClose = open({ dirty: true });

    await act(async () => {
      fireEvent.click(screen.getByLabelText("Close"));
    });
    await act(async () => {
      useConfirmStore.getState().resolve(false);
    });

    expect(onClose).not.toHaveBeenCalled();
  });

  it("closes once discarding is confirmed", async () => {
    const onClose = open({ dirty: true });

    await act(async () => {
      fireEvent.click(screen.getByLabelText("Close"));
    });
    await act(async () => {
      useConfirmStore.getState().resolve(true);
    });

    expect(onClose).toHaveBeenCalledOnce();
  });

  it("asks once, however many times the backdrop is clicked", async () => {
    open({ dirty: true });

    await act(async () => {
      fireEvent.click(screen.getByLabelText("Close"));
      fireEvent.click(screen.getByLabelText("Close"));
      fireEvent.click(screen.getByLabelText("Close"));
    });

    const asked = useConfirmStore.getState().request;
    expect(asked?.confirmLabel).toBe("Discard");

    await act(async () => {
      useConfirmStore.getState().resolve(false);
    });
    expect(useConfirmStore.getState().request).toBeNull();
  });
});
