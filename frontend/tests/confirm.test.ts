import { beforeEach, describe, expect, it } from "vitest";

import { confirm, useConfirmStore } from "@/stores/confirm-store";

const question = { title: "Delete this dataset?", message: "It cannot be undone." };

beforeEach(() => {
  useConfirmStore.setState({ request: null });
});

describe("in-app confirmation", () => {
  it("opens a request and resolves true when accepted", async () => {
    const answer = confirm(question);

    expect(useConfirmStore.getState().request?.title).toBe("Delete this dataset?");

    useConfirmStore.getState().resolve(true);

    await expect(answer).resolves.toBe(true);
    expect(useConfirmStore.getState().request).toBeNull();
  });

  it("resolves false when declined, so the caller does nothing", async () => {
    const answer = confirm(question);
    useConfirmStore.getState().resolve(false);

    await expect(answer).resolves.toBe(false);
    expect(useConfirmStore.getState().request).toBeNull();
  });

  it("answers an outstanding question rather than stranding its caller", async () => {
    const first = confirm(question);
    const second = confirm({ title: "Clear this run?", message: "Exports go too." });

    await expect(first).resolves.toBe(false);
    expect(useConfirmStore.getState().request?.title).toBe("Clear this run?");

    useConfirmStore.getState().resolve(true);
    await expect(second).resolves.toBe(true);
  });

  it("carries the labels the dialog renders", () => {
    void confirm({ ...question, confirmLabel: "Delete dataset", tone: "danger" });

    const { request } = useConfirmStore.getState();
    expect(request?.confirmLabel).toBe("Delete dataset");
    expect(request?.tone).toBe("danger");

    useConfirmStore.getState().resolve(false);
  });
});
