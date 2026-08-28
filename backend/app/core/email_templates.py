"""The HTML for the mail this platform sends.

Written the way email has to be written rather than the way the app is: one
table, inline styles, hex colours, no stylesheet and no web font. Mail clients
strip a <style> block, ignore CSS variables and often refuse to load anything
remote, so every rule that matters has to sit on the element it styles.

Kept in one place because the alternative is four messages that gradually stop
looking like each other.
"""

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
    #: The first action is the one being recommended and is drawn as a filled
    #: button; anything after it is a plain link, so a message never asks
    #: somebody to choose between two things that look equally intended.
    primary: bool = True


@dataclass(slots=True, frozen=True)
class Message:
    subject: str
    text: str
    html: str


def _button(action: Action) -> str:
    if not action.primary:
        # vertical-align matters: without it the secondary link sits on the
        # text baseline and the button on its own box, so the two land at
        # different heights and the row reads as a mistake.
        return (
            f'<a href="{action.url}" style="display:inline-block;vertical-align:middle;'
            f"color:{INK_SOFT};font-size:14px;line-height:40px;text-decoration:underline;"
            f'padding:0 14px;font-family:{FONT};">{action.label}</a>'
        )
    # A table rather than a padded anchor: Outlook ignores padding on inline
    # elements and the button collapses to bare text.
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'style="display:inline-block;vertical-align:middle;"><tr><td '
        f'style="background:{ACCENT};border-radius:4px;">'
        f'<a href="{action.url}" style="display:inline-block;padding:11px 22px;'
        f"color:#ffffff;font-size:14px;font-weight:600;text-decoration:none;"
        f'font-family:{FONT};">{action.label}</a></td></tr></table>'
    )


#: Why this message arrived. Not decoration — a message that cannot say why it
#: was sent is the shape of one people report as spam.
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
    """The only message a request produces, and the only one it needs.

    Nobody is emailed about somebody else's request any more. The person who
    can act on it sees it on the People page, live, the moment it arrives —
    so the one message worth sending is to the person who asked, telling them
    it landed and that they do not have to do anything else.
    """
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
    """The one message that says you are in, however you got here.

    Sent to somebody approved after asking and to somebody invited without
    asking, so the wording carries neither assumption — no "the address you
    asked with" for a person who never asked, and no "somebody invited you"
    for a person who did. Two templates saying the same thing would be two
    things to keep true.
    """
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
