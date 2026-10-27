"""Entry point: ``shellac`` or ``python -m shellac``."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import APP_NAME, __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=APP_NAME, description="A GTK4 terminal emulator.")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    parser.add_argument(
        "--config", type=Path, metavar="FILE", help="use FILE instead of the default config.toml"
    )
    parser.add_argument(
        "--print-shell-integration",
        action="store_true",
        help="print the zsh snippet that reports the working directory (OSC 7) and exit",
    )
    parser.add_argument(
        "--install-desktop",
        action="store_true",
        help="add shellac to the application menu (launcher and icon, for this user) and exit",
    )
    parser.add_argument(
        "--uninstall-desktop",
        action="store_true",
        help="remove what --install-desktop added and exit",
    )
    parser.add_argument("--debug", action="store_true", help="enable debug logging")
    return parser


_DARK_THEME_WARNING = "gtk-application-prefer-dark-theme"


def _quiet_known_warnings() -> None:
    """Drop one libadwaita warning that is not about shellac.

    KDE's GTK settings sync writes ``gtk-application-prefer-dark-theme`` into
    ``~/.config/gtk-4.0/settings.ini``; libadwaita then warns about it on every start. Color
    scheme handling here goes through ``AdwStyleManager`` already, so the setting does nothing.
    """
    from gi.repository import GLib

    def handler(domain: str | None, level: GLib.LogLevelFlags, message: str, _data: object) -> None:
        if _DARK_THEME_WARNING in message:
            return
        GLib.log_default_handler(domain, level, message, None)

    GLib.log_set_handler("Adwaita", GLib.LogLevelFlags.LEVEL_WARNING, handler, None)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.print_shell_integration:
        from .shell_integration import ZSH_SNIPPET

        sys.stdout.write(ZSH_SNIPPET)
        return 0

    if args.install_desktop or args.uninstall_desktop:
        from . import desktop

        done = desktop.uninstall() if args.uninstall_desktop else desktop.install()
        verb = "Removed" if args.uninstall_desktop else "Installed"
        for path in done:
            sys.stdout.write(f"{verb} {path}\n")
        if not done:
            sys.stdout.write("Nothing to remove.\n")
        return 0

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(name)s: %(levelname)s: %(message)s",
    )

    # Imported here so --version and --print-shell-integration work without GTK.
    from .application import Application

    _quiet_known_warnings()

    app = Application(config_file=args.config)
    # Hand GTK only the program name: our own flags are already parsed above.
    return app.run(sys.argv[:1])


if __name__ == "__main__":
    sys.exit(main())
