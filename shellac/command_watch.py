"""Finished-command notifications: when did a command start and end, and who should hear?

GTK-free. A ``CommandWatch`` follows one pane. The window samples whether a command is in the
foreground of the pane's terminal (``TerminalPane.is_running_command``) about once a second
and feeds the answer to ``update``; a command that ran and then handed the terminal back to
the shell comes back as a ``FinishedCommand``. This needs no setup in the shell, so it works
with bash, zsh and fish alike. What it cannot know is how the command ended (the exit status),
and it does not see commands shorter than the sampling interval, which no threshold would
report anyway.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FinishedCommand:
    name: str | None  # what ran, if it could be read while it ran
    seconds: float


@dataclass
class CommandWatch:
    started: float | None = None
    name: str | None = None

    def update(self, running: bool, name: str | None, now: float) -> FinishedCommand | None:
        """Feed one sample. ``name`` is what runs now (only read while ``running``)."""
        if running:
            if self.started is None:
                self.started = now
            if name:
                self.name = name  # the latest foreground program, e.g. make then its compiler
            return None
        if self.started is None:
            return None
        finished = FinishedCommand(self.name, max(0.0, now - self.started))
        self.started = None
        self.name = None
        return finished


@dataclass(frozen=True)
class Attention:
    mark_tab: bool
    notify: bool


def attention(
    *,
    tab_selected: bool,
    window_active: bool,
    marker_on: bool,
    notification_on: bool,
) -> Attention:
    """Who is told about a finished command.

    The tab gets a marker when it is not the one showing: with it showing, the output is in
    front of you. A desktop notification is for when the window is not the active one: with
    it active, the marker (or the output) already does the job and a popup would only nag.
    """
    return Attention(
        mark_tab=marker_on and not tab_selected,
        notify=notification_on and not window_active,
    )


def format_duration(seconds: float) -> str:
    """``42 s``, ``3 min 5 s``, ``1 h 2 min``: short, for a notification."""
    total = int(round(seconds))
    if total < 60:
        return f"{total} s"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes} min {secs} s" if secs else f"{minutes} min"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes} min" if minutes else f"{hours} h"


def notification_text(tab_title: str, finished: FinishedCommand) -> tuple[str, str]:
    """Title and body of the desktop notification."""
    what = f"“{finished.name}”" if finished.name else "A command"
    return tab_title or "Shellac", f"{what} finished after {format_duration(finished.seconds)}."
