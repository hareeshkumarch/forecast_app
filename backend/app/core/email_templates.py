from __future__ import annotations

from dataclasses import dataclass

INK = "#111512"
INK_SOFT = "#4e554e"
INK_MUTED = "#7d847e"
ACCENT = "#287b59"
ACCENT_DARK = "#175a3e"
SURFACE = "#ffffff"
CANVAS = "#f1f3ef"
RULE = "#d8ddd7"

FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"

PRODUCT = "Forecast Hub"


@dataclass(slots=True, frozen=True)
class Action:
    label: str
    url: str
    primary: bool = True


@dataclass(slots=True, frozen=True)
class Message:
    subject: str
    text: str
    html: str


def _button(action: Action) -> str:
    if not action.primary:
        return (
            f'<a href="{action.url}" style="display:inline-block;vertical-align:middle;'
            f"color:{INK_SOFT};font-size:14px;line-height:40px;text-decoration:underline;"
            f'padding:0 14px;font-family:{FONT};">{action.label}</a>'
        )
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'style="display:inline-block;vertical-align:middle;"><tr><td '
        f'style="background:{ACCENT};border-radius:4px;">'
        f'<a href="{action.url}" style="display:inline-block;padding:11px 22px;'
        f"color:#ffffff;font-size:14px;font-weight:600;text-decoration:none;"
        f'font-family:{FONT};">{action.label}</a></td></tr></table>'
    )


REASON_DECIDED = "you asked for access to it"


def layout(
    heading: str,
    paragraphs: list[str],
    actions: list[Action],
    footnote: str = "",
    reason: str = REASON_DECIDED,
) -> str:
    body = "".join(
        f'<p style="margin:0 0 14px;color:{INK_SOFT};font-size:15px;line-height:1.6;">{p}</p>'
        for p in paragraphs
    )
    buttons = (
        '<div style="margin:22px 0 4px;">'
        + "".join(_button(action) for action in actions)
        + "</div>"
        if actions
        else ""
    )
    tail = (
        f'<p style="margin:22px 0 0;padding-top:16px;border-top:1px solid {RULE};'
        f'color:{INK_MUTED};font-size:12px;line-height:1.6;">{footnote}</p>'
        if footnote
        else ""
    )

    return f"""<!doctype html>
<html><body style="margin:0;padding:0;background:{CANVAS};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
       style="background:{CANVAS};padding:32px 16px;">
  <tr><td align="center">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
           style="max-width:520px;background:{SURFACE};border:1px solid {RULE};border-radius:6px;">
      <tr><td style="padding:26px 28px 0;">
        <span style="font-family:{FONT};font-size:15px;font-weight:600;color:{INK};
                     letter-spacing:-0.01em;">{PRODUCT}</span>
      </td></tr>
      <tr><td style="padding:18px 28px 28px;font-family:{FONT};">
        <h1 style="margin:0 0 12px;font-size:19px;line-height:1.3;font-weight:600;
                   color:{INK};letter-spacing:-0.02em;">{heading}</h1>
        {body}{buttons}{tail}
      </td></tr>
    </table>
    <p style="max-width:520px;margin:14px auto 0;font-family:{FONT};font-size:11px;
              line-height:1.6;color:{INK_MUTED};text-align:center;">
      Sent by {PRODUCT} because {reason}.
    </p>
  </td></tr>
</table>
</body></html>"""


def _plain(heading: str, paragraphs: list[str], actions: list[Action], footnote: str = "") -> str:
    lines = [heading, ""]
    lines += [_strip(p) for p in paragraphs]
    if actions:
        lines.append("")
        lines += [f"{action.label}: {action.url}" for action in actions]
    if footnote:
        lines += ["", _strip(footnote)]
    return "\n".join(lines)


def _strip(html: str) -> str:
    import re

    return re.sub(r"<[^>]+>", "", html)


def _message(
    subject: str,
    heading: str,
    paragraphs: list[str],
    actions: list[Action],
    footnote: str = "",
    reason: str = REASON_DECIDED,
) -> Message:
    return Message(
        subject=subject,
        text=_plain(heading, paragraphs, actions, footnote),
        html=layout(heading, paragraphs, actions, footnote, reason),
    )


def request_received(app_url: str) -> Message:
    return _message(
        subject="Your access request is with an administrator",
        heading="Thanks — your request is in",
        paragraphs=[
            "Somebody has to approve your account before you can see anything. We have passed "
            "it on, and you will get an email the moment it is decided.",
            "There is nothing else for you to do, and no need to keep the page open.",
        ],
        actions=[Action("Open the app", app_url)],
        reason=REASON_DECIDED,
    )


def access_approved(app_url: str) -> Message:
    return _message(
        subject="You have access to Forecast Hub",
        heading="You're in",
        paragraphs=[
            "Your account has been approved and the workspace is open to you. Sign in with "
            "this email address and you are straight through.",
            "Upload a file and the platform works out what its columns mean, splits it into "
            "series and forecasts each one — you do not have to describe the shape of your "
            "data first.",
        ],
        actions=[Action("Start with a file", f"{app_url}/datasets")],
        reason=REASON_DECIDED,
    )
