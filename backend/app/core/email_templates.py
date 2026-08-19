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
REASON_ACCESS = "somebody asked for access to it"
REASON_DECIDED = "you asked for access to it"
REASON_WELCOME = "your account was approved"
REASON_INVITED = "somebody invited you to it"
REASON_ACCOUNT = "it concerns your account"


def layout(
    heading: str,
    paragraphs: list[str],
    actions: list[Action],
    footnote: str = "",
    reason: str = REASON_ACCESS,
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
    reason: str = REASON_ACCESS,
) -> Message:
    return Message(
        subject=subject,
        text=_plain(heading, paragraphs, actions, footnote),
        html=layout(heading, paragraphs, actions, footnote, reason),
    )


def access_request(who: str, email: str, approve_url: str, reject_url: str, hours: int) -> Message:
    return _message(
        subject=f"{who} is asking for access",
        heading="Someone wants in",
        paragraphs=[
            f"<strong style='color:{INK};'>{who}</strong> signed in with {email} and is waiting "
            "for you to let them in. They cannot see anything until you do.",
        ],
        actions=[Action("Approve", approve_url), Action("Reject", reject_url, primary=False)],
        footnote=(
            f"These links work without signing in and expire in {hours} hours. You can also "
            "decide from the Account page in the app."
        ),
    )


def request_received(app_url: str) -> Message:
    return _message(
        subject="Your access request is with an administrator",
        heading="Thanks — your request is in",
        paragraphs=[
            "Somebody has to approve your account before you can see anything. We have passed "
            "it on and you will get an email the moment it is decided.",
            "There is nothing else for you to do, and no need to keep the page open.",
        ],
        actions=[Action("Open the app", app_url)],
        reason=REASON_DECIDED,
    )


def access_approved(app_url: str) -> Message:
    return _message(
        subject="Your access has been approved",
        heading="You're in",
        paragraphs=[
            "An administrator has approved your account, so the workspace is open to you now.",
            "Sign in with the same address you asked with and everything is where you left it.",
        ],
        actions=[Action("Open the app", app_url)],
        reason=REASON_DECIDED,
    )


def access_restored(app_url: str) -> Message:
    """For somebody let back in after being turned away.

    "You're in" reads oddly to a person who was told no last week, and worse
    to one who never knew they had been refused. Naming the change is the
    honest version and costs one sentence.
    """
    return _message(
        subject="Your access has been restored",
        heading="You're back in",
        paragraphs=[
            "Your access to this workspace has been turned back on. Nothing was lost while it "
            "was off — your datasets and forecast runs are exactly as you left them.",
        ],
        actions=[Action("Open the app", app_url)],
        reason=REASON_ACCOUNT,
    )


def access_refused() -> Message:
    """Softened, but not untrue.

    Nothing here says "rejected" or "removed", and nothing blames the reader —
    a refusal is usually about who a deployment is for rather than about them.
    What it will not do is invent a fault that does not exist. Telling somebody
    the service is having problems leaves them waiting for a fix that is not
    coming, checking back, and asking a colleague who will tell them otherwise.
    A soft no they can act on beats a warm sentence that wastes their week.
    """
    return _message(
        subject="About your access request",
        heading="We can't set you up right now",
        paragraphs=[
            "We are not able to give you access to this workspace at the moment. Nothing has "
            "gone wrong on your side, and there is nothing you need to do.",
            "If you were expecting access, the person who looks after this is the one to have "
            "a word with — they can turn it on straight away.",
        ],
        actions=[],
        reason=REASON_DECIDED,
    )


def access_revoked() -> Message:
    """A different message from a refusal, because it is a different event.

    This person had access and was using it. Sending them "we can't set you up
    right now" would read as a mistake, and leave them wondering whether their
    work is still there. So: say plainly that it was turned off, say the work
    is untouched, and point them at somebody who can turn it back on.
    """
    return _message(
        subject="Your access has been turned off",
        heading="Your access has been turned off",
        paragraphs=[
            "An administrator has switched off your access to this workspace, so signing in "
            "will no longer let you through.",
            "Nothing has been deleted. Your datasets and forecast runs are kept as they are, "
            "and they come back with you if your access is turned on again.",
            "If this is not what you expected, ask whoever looks after this workspace — they "
            "can restore it in one click.",
        ],
        actions=[],
        reason=REASON_ACCOUNT,
    )


def promoted(app_url: str) -> Message:
    return _message(
        subject="You are now an administrator",
        heading="You can approve people now",
        paragraphs=[
            "You have been made an administrator of this workspace. Alongside everything you "
            "could already do, you can now approve or turn away people asking for access, "
            "invite somebody by email, and change what others are allowed to do.",
            "All of it lives on the Account page.",
        ],
        actions=[Action("Open the Account page", f"{app_url}/account")],
        reason=REASON_ACCOUNT,
    )


def demoted(app_url: str) -> Message:
    return _message(
        subject="A change to what you can do",
        heading="You are no longer an administrator",
        paragraphs=[
            "Your administrator role for this workspace has been handed back, so approving "
            "people and changing what others can do has moved to somebody else.",
            "Your own access has not changed — your datasets, forecast runs and connectors are "
            "all still yours.",
        ],
        actions=[Action("Open the app", app_url)],
        reason=REASON_ACCOUNT,
    )


def welcome(name: str | None, app_url: str) -> Message:
    greeting = f"Welcome, {name}." if name else "Welcome."
    return _message(
        subject=f"Welcome to {PRODUCT}",
        heading=greeting,
        paragraphs=[
            "You are in. Upload a file and the platform works out what its columns mean, "
            "splits it into series, and forecasts each one — you do not have to describe the "
            "shape of your data first.",
            "Every number it shows you is computed and checked against what actually happened, "
            "so you can ask it how well it has been doing.",
        ],
        actions=[Action("Start with a file", f"{app_url}/datasets")],
        footnote="This is the only message you will get from us unless something needs you.",
        reason=REASON_WELCOME,
    )


def invitation(inviter: str, app_url: str) -> Message:
    return _message(
        subject=f"{inviter} invited you to {PRODUCT}",
        heading=f"You have been invited to {PRODUCT}",
        paragraphs=[
            f"<strong style='color:{INK};'>{inviter}</strong> has given you access. Sign in with "
            "this email address and you are straight in — no approval to wait for.",
        ],
        actions=[Action("Sign in", app_url)],
        footnote="Use the same address this was sent to; the invitation is tied to it.",
        reason=REASON_INVITED,
    )
