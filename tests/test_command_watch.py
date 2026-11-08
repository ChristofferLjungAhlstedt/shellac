from shellac.command_watch import (
    Attention,
    CommandWatch,
    FinishedCommand,
    attention,
    format_duration,
    notification_text,
)
from shellac.config import Config


def test_a_command_is_reported_when_it_ends():
    watch = CommandWatch()
    assert watch.update(False, None, 0.0) is None  # idle prompt
    assert watch.update(True, "make", 1.0) is None  # starts
    assert watch.update(True, "make", 5.0) is None
    assert watch.update(False, None, 13.0) == FinishedCommand("make", 12.0)


def test_it_is_reported_once_and_the_watch_resets():
    watch = CommandWatch()
    watch.update(True, "sleep", 0.0)
    assert watch.update(False, None, 3.0) is not None
    assert watch.update(False, None, 4.0) is None
    watch.update(True, "ls", 10.0)
    assert watch.update(False, None, 11.0) == FinishedCommand("ls", 1.0)


def test_the_latest_program_name_wins_and_unknown_names_do_not_erase_it():
    watch = CommandWatch()
    watch.update(True, "make", 0.0)
    watch.update(True, "cc1", 2.0)  # a build runs many programs in turn
    watch.update(True, None, 3.0)  # could not be read this time
    assert watch.update(False, None, 4.0) == FinishedCommand("cc1", 4.0)


def test_a_command_never_named_is_still_reported():
    watch = CommandWatch()
    watch.update(True, None, 0.0)
    assert watch.update(False, None, 9.0) == FinishedCommand(None, 9.0)


def test_time_never_goes_negative():
    watch = CommandWatch()
    watch.update(True, "x", 10.0)
    assert watch.update(False, None, 9.0).seconds == 0.0


def test_who_is_told():
    both = dict(marker_on=True, notification_on=True)
    # Another tab is showing and the window is in use: just the marker.
    assert attention(tab_selected=False, window_active=True, **both) == Attention(True, False)
    # Away from the window: a notification, and the marker if the tab is not the one showing.
    assert attention(tab_selected=False, window_active=False, **both) == Attention(True, True)
    assert attention(tab_selected=True, window_active=False, **both) == Attention(False, True)
    # Watching it end: nothing.
    assert attention(tab_selected=True, window_active=True, **both) == Attention(False, False)


def test_each_channel_can_be_turned_off():
    assert attention(
        tab_selected=False, window_active=False, marker_on=False, notification_on=True
    ) == Attention(False, True)
    assert attention(
        tab_selected=False, window_active=False, marker_on=True, notification_on=False
    ) == Attention(True, False)
    assert attention(
        tab_selected=False, window_active=False, marker_on=False, notification_on=False
    ) == Attention(False, False)


def test_durations_read_naturally():
    assert format_duration(0.4) == "0 s"
    assert format_duration(42) == "42 s"
    assert format_duration(59.6) == "1 min"
    assert format_duration(60) == "1 min"
    assert format_duration(185) == "3 min 5 s"
    assert format_duration(3600) == "1 h"
    assert format_duration(3720) == "1 h 2 min"


def test_notification_text():
    title, body = notification_text("~/project", FinishedCommand("make", 75))
    assert title == "~/project"
    assert body == "“make” finished after 1 min 15 s."
    title, body = notification_text("", FinishedCommand(None, 12))
    assert title == "Shellac" and body == "A command finished after 12 s."


def test_defaults_are_on_after_ten_seconds():
    general = Config().general
    assert general.finished_tab_marker is True
    assert general.finished_notification is True
    assert general.finished_after_seconds == 10
