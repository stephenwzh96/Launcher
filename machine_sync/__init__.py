"""Sync between the PCs (desktop, laptop and the VPS: code through GitHub, data through one Syncthing outbox per
machine), and the daily-run claim the launcher takes before a daily task. Design:
docs/superpowers/specs/2026-11-17-two-way-machine-sync-design.md and, for the third machine,
docs/superpowers/specs/2026-11-20-three-machine-design.md.
Standard library only: it runs on the standalone Python, outside every venv it may update."""

# bump when a note's layout or meaning changes; a PC reading a newer format stops importing and following.
# 2 (three machines, 20 Nov 2026): an outbox holds only its own machine's changes and the VPS's outbox exists, so an
# older (two-PC) tool must not follow a three-machine note until it has updated itself.
NOTE_FORMAT = 2
