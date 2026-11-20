# Start here

The entry point to the trading program: Trend (the model), IBKR (the replica and its books) and this launcher (team
review, 20 Nov 2026, project manager 10).

## Status (20 Nov 2026)

- **IBKR paper** has traded MTFA since 17 Nov 2026, at the paper account's NAV of about US$280k (IBKR D44). MTFB and
  MTFC are estimated beside it and are paper-traded later, one at a time. **Live has not started.** What must be true
  first: IBKR `docs/GO_LIVE.md`.
- **Trend**: Stage E ran on 24 Oct 2026, verdict `same_family`, one check short of `close`; the hold-out is spent.
  The official design runs every day at Start of Day (Trend `IMPLEMENTATION_PLAN.md`, Status).
- **The team review of 20 Nov 2026**: IBKR `reports/reviews/team_review_2026-11-20.md`. Stephen took its 16
  decisions; they are IBKR D44 to D60. What is left to build is in `BACKLOG.md`.

## The day (Sydney time)

Times from November to early March. From April the afternoon deadline is half an hour earlier and the night ends
about two hours earlier: the season table is in IBKR `docs/runbook.md`, "The day".

| When | What | Where |
|---|---|---|
| from about 09:30 | Settlements pull (scheduled) | VPS |
| from about 09:30 | *MTFA Start of Day*: press Start. It waits for every market's close until 14:30 and writes the envelopes by 15:15; GO or HOLD | this launcher (`localhost:9000`) |
| about 15:15 | *IBKR paper cycle*, first press: pre-open, books, the trade list; Telegram says it waits for approval | this launcher |
| by about 16:15 | Approve the list on *MTFA Operations* (the Approval box), then press *Start trading* | the Operations page (port 5181), this launcher |
| 16:25 to 08:01 | The windows: ASX 16:25, London ETFs 03:30, CME currencies 06:55, US ETFs at the close 07:40. The cycle's PC stays on and online | the cycle's PC |
| about 08:21 | The reconcile and the morning summary on Telegram. No summary by about 08:45: check `python -m src.operations status` | phone |
| morning | The Operations page, the incidents, the books against IBKR | IBKR runbook, "The day" |

Nothing runs on a schedule on the PCs: both daily tasks are started by hand (Trend `DECISIONS.md` 2026-10-27).

## Machines

| Machine | Runs |
|---|---|
| Desktop | this launcher, Trend's dashboard (5180), the Operations page (5181), Start of Day and the cycle |
| Laptop | the alternate PC, on a day it holds the launcher's claim ("Take over") |
| VPS, over Tailscale | IB Gateway (paper 4002), PostgreSQL, the settlements pull, the laptop watch |

The files the repos share, and what a missing one does: IBKR `docs/architecture.md`.

## Where things are

| | |
|---|---|
| Repos | Trend `C:\Users\User\Trend\AIJPMT1A_build`; IBKR `C:\Users\User\IBKR`; launcher `C:\Users\User\Marco\launcher` |
| Open work | `BACKLOG.md` (here) |
| Dependencies and their expiry | `RISKS.md` (here) |
| Decisions | IBKR `DECISIONS.md` (D1 onward); Trend `DECISIONS.md` (an index at its top) |
| Before live money | IBKR `docs/GO_LIVE.md` |
| When something fails | IBKR `docs/runbook.md`, "When something fails" |

## Reading order

The project manager's order (team review, 20 Nov 2026), then the documents written since:

1. This repo's `README.md`.
2. IBKR `CLAUDE.md`, its first sections (overview, status, architecture, toolchain).
3. IBKR `docs/runbook.md`, "The day", with its season table.
4. Trend `dashboard/README.md`.
5. Trend `CLAUDE.md`: the non-negotiables and "Production".
6. IBKR `IMPLEMENTATION_PLAN.md` §7, §9 and §12, and IBKR `DECISIONS.md` (the plan's §11 until 20 Nov 2026).
7. IBKR `docs/architecture.md`, `docs/GO_LIVE.md`; here, `BACKLOG.md` and `RISKS.md`.
