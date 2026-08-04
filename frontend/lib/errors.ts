import { ApiError } from "@/lib/api";

const TITLES: Record<number, string> = {
  0: "Can't reach the server",
  400: "That request can't be processed",
  404: "Not found",
  409: "Something changed underneath you",
  413: "That file is too large",
  415: "That file type isn't supported",
  422: "Check the highlighted fields",
  429: "Too many requests",
};

const FALLBACK_TITLE = "Something went wrong";
const FALLBACK_MESSAGE = "Try again in a moment.";

export function errorTitle(error: unknown, fallback = FALLBACK_TITLE): string {
  if (error instanceof ApiError) {
    if (error.status >= 500) return "The server had a problem";
    return TITLES[error.status] ?? fallback;
  }
  return fallback;
}

export function errorMessage(error: unknown, fallback = FALLBACK_MESSAGE): string {
  if (error instanceof ApiError) {
    return error.status >= 500 && error.requestId
      ? `${error.message} (reference ${error.requestId})`
      : error.message;
  }
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

export function isRetryable(error: unknown): boolean {
  return error instanceof ApiError ? error.isRetryable : true;
}
