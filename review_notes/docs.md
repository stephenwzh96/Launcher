# Notes from the docs builder (team review, 20 Nov 2026)

## For the launcher's `README.md` (not edited: README.md is the lead's to fold in)

Add as the second paragraph, under the title:

> New here? Start with [`START_HERE.md`](START_HERE.md): the program's status, the day's timetable, the machines
> and the reading order. Open work is in [`BACKLOG.md`](BACKLOG.md); dependencies and their expiry in
> [`RISKS.md`](RISKS.md).

## For the lead, when merging the other branches

- `BACKLOG.md` lists the review's decisions and next batch as open. Remove the rows a merged branch finishes, and
  set the matching status in IBKR `docs/GO_LIVE.md` (rows 9 to 15).
- IBKR's untracked `TODO.md` (main checkout) is folded into `BACKLOG.md` sections 2 and 3; it was not touched.
