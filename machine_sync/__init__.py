"""Two-way sync between the desktop and the laptop (code through GitHub, data through Syncthing outboxes), and the
daily-run claim the launcher takes before a daily task. Design: docs/superpowers/specs/2026-11-17-two-way-machine-sync-design.md.
Standard library only: it runs on the standalone Python, outside every venv it may update."""

NOTE_FORMAT = 1  # bump when a note's layout changes; a PC reading a newer format stops importing and following
