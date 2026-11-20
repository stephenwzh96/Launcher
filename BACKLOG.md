# Backlog

The one list of open work for Trend, IBKR and the launcher (team review, 20 Nov 2026, project manager 10). It
replaces six lists: IBKR's untracked `TODO.md`, Trend's `TODO.md`, the IBKR plan's §11.4, §12 "Remaining" and §16,
and the review's next batch. Those now point here; Trend's `TODO.md` keeps the detail of its four research items.

- **Owner**: *Stephen* (decisions, accounts, money, system settings, reference files, merges), *Claude* (builds on a
  branch with tests; Stephen merges), or *both*.
- **Done when**: the test of done. A done item leaves the list; its commit or decision says so.
- **Source** in brackets: `D` = IBKR `DECISIONS.md`; `GL` = IBKR `docs/GO_LIVE.md` row; review role and item
  (`reports/reviews/2026-11-20/` in IBKR); `T-TODO` = Trend `TODO.md`.

## 1. The review's work: what is left after the 20 Nov branches

Built on 20 Nov 2026 and merged with the review's branches (IBKR D44 to D60; Trend `DECISIONS.md` 2026-11-20): the
size limits, input gates, exposure override, the four halts, the slot freeze, the margin review, final settlements,
close versions and accruals, execution choices, drawdown levels, the envelope contract, the two trials, `run`
resuming last night's cycle, the fills work, the version handshake, the PM's screens, the holiday FX carry, manual
fills, days to first notice, the estimated books' P&L, Start of Day's run record, the code trees in the envelope and
the pin, and a press without GitHub. What is left of them:

| # | Item | Owner | Done when |
|---|---|---|---|
| 1.3 | Drill "Flatten" on paper once [D47, GL 11] | both | the drill dated in the runbook |
| 1.9 | Register the resume task (`scripts/resume_if_needed.py`; the `schtasks` line is in the IBKR runbook) [D56] | Stephen registers | the task runs every 10 min, 16:00-08:30 |
| 1.10 | The VPS runs the daily run: Start of Day and the night, with an outside dead-man; the desktop or laptop only when Stephen starts a day there by hand (VPS Claude's design) [D56, D65, GL 15] | both | D65's readiness list done (memory, Norgate, Trend checkout and sync, a timed trial Start of Day), then 5 paper days run there, watched from outside |
| 1.12 | Review the regenerated drawdown levels (`reference/drawdown_levels.yaml`, from the 18 Nov runs) [D59] | Stephen | reviewed, or changed in a reviewed commit |
| 1.14 | Adopt T20b (the 3-day covariance) for MTFB and MTFC, or not: it changes all three design hashes [D58] | Stephen | a line in Trend `DECISIONS.md` |
| 2.4 | Turn on the day side's phone lines: Start of Day's Telegram (two user variables, then `notify_telegram: true`); redeploy the VPS watch, which now knows a run that ended [trade operations 4, 5] | Stephen | each line seen on the phone once |
| 2.8 | The replay rerun at the paper NAV on the current pins; confirm the minimum live NAV per product (`capital.min_nav` in IBKR `reference/limits.yaml`, US$1m, a review) [D44; plan §16 3; P4 remaining; GL 18] | Claude; Stephen confirms | a dated report in IBKR `reports/`; the minimums recorded as a decision |
| 2.9 | The paper month reconciled to the cent against IBKR's Flex statements [plan P3 and P7 remaining] | Claude | the November statement days reconcile; breaks explained |
| 2.10 | Each failure in the runbook drilled once and dated; one restore; one cold start on a real statement [P13 remaining; trade operations 7; GL 7] | both | a dated list in the runbook |
| 2.11 | Register the weekly reference check (`scripts/reference_check.py --quiet` sends its Telegram line) [trade operations 11] | Stephen registers | the check runs weekly (newest report today: 2 Nov) |
| 2.12 | November month-end report [plan §8; project manager] | Claude runs; Stephen reads | `scripts/monthly_report.py 2026-11` read in the first week of December |
| 2.16 | Fill the pins' `code_trees` at the next promotion or re-pin [architect 4] | Claude, at the promotion | a pin carries the trees and the target gate compares them |

## 3. Stephen's

| # | Item | Done when |
|---|---|---|
| 3.1 | Confirm or change the numbers in `docs/GO_LIVE.md` [D55] | each number confirmed in a decision |
| 3.2 | Accept Stage E's `same_family` as the model's acceptance, or not [GL 1] | a line in Trend `DECISIONS.md` |
| 3.3 | Reset the paper balance to about HKD 7.8m, or keep about US$280k [D44] | the choice recorded |
| 3.4 | Set the period lock date [D52] | the date recorded |
| 3.5 | Windows Update active hours on the cycle PC [D56; trade operations 6] | no restart window over the night |
| 3.6 | London ETFs (IEAC, IHYG) never fill on paper: order before 16:30 London, or accept the gap [IBKR TODO] | decided and recorded |
| 3.7 | IHYG's placeholder name in Trend `reference/spec/universe.csv` line 55 (a reference edit) [IBKR TODO] | renamed with a Trend decision entry |
| 3.8 | Close incidents 1, 2, 4-11 [IBKR TODO; GL 6] | none open more than 2 trade days |
| 3.9 | The ARCA market-data subscription (incident 2) [IBKR TODO; GL 17] | subscribed or declined |
| 3.10 | Rotate the Telegram token; the gateway's auto-start on the VPS; Windows clock sync (W32Time); the idle desktop-to-VPS link; delete the temporary database dumps [IBKR TODO] | each done once |
| 3.11 | Write the unknown dates into `RISKS.md`: the Flex token's expiry, the VPS term, Tailscale, the accounts | no "unknown" left |
| 3.12 | Renew Norgate by early April 2027 [RISKS] | renewed before 23 Apr 2027 |
| 3.14 | Equity index rolls 1-2 days apart in Trend and IBKR [Trend `reports/paper_readiness_2026-11-16.md`] | aligned, or the gap accepted |
| 3.15 | The twelve empty legacy folders under IBKR `src/` and the five stale documents: archive or delete (your no-delete rule) [review next batch 9] | your say recorded; the documents carry superseded banners meanwhile |
| 3.16 | A Bank of Korea key for KRW_MP2Y; `data import-french` for TZ_TPX after the library's next update [T-TODO; Trend independent review 17 Nov] | key in `.env`; import done |
| 3.17 | On "no envelope" or "envelope rejected", a maintenance list (the rolls and the closes due, from the last traded envelope, always waiting for a person) instead of a halt [risk manager 5; IBKR gates builder] | your yes or no; on a yes Claude builds it (about a day, with tests) |

## 4. Model research (Trend; each a pre-registered trial, adopted only by Stephen)

| # | Item | Owner | Done when |
|---|---|---|---|
| 4.1 | Fill the missing macro legs left: KRW, HKD and NZD MP2Y [T-TODO] | Claude (KRW after 3.16) | filled with a source, or recorded as unavailable |
| 4.2 | Rebuild the liquidity weights from market data and compare with the deck's 54 [T-TODO] | Claude | a report with the comparison and a recommendation |
| 4.3 | A separate price-trend signal combined with the macro trend [T-TODO] | Claude | variants logged; a report |
| 4.4 | Whether the AVT adds value, and how much; with the note that vol targeting is a tail tool outside equity and credit [T-TODO; IBKR plan §11.4] | Claude | the trial logged; a report; the Performance tab shows it |
| 4.5 | Credit stand-in volatility (~1% against 1.5-2.5% for the real indices) [IBKR plan §11.4] | Claude | `tools/fit_credit_proxies.py` revisited; a report |
| 4.6 | Aim-portfolio shrinkage (Gârleanu and Pedersen, Prop. 4) [IBKR plan §11.4] | Claude | a pre-registered trial or a note why not |
| 4.7 | Small-tick contracts and the universe; breadth against cost [IBKR plan §11.4] | Claude | a short report from the monthly cost-against-contribution view |

## 5. Housekeeping

| # | Item | Owner | Done when |
|---|---|---|---|
| 5.1 | Renormalize line endings after the 20 Nov branches merge (`.gitattributes` added in each repo); `core.autocrlf=false` [developer 9] | Claude (the lead) | one renormalize commit per repo; `git ls-files --eol` shows no CRLF in the index outside `*.ps1 *.bat *.cmd` |
| 5.2 | Git hooks installed in each repo; CI for IBKR's database tests, Trend's fast tests and the launcher [developer 3] | Claude; Stephen enables CI | hooks in `.git/hooks`; each repo's CI green |
| 5.3 | Fold IBKR's untracked `TODO.md` into this list and retire it | Stephen | its items are here; the file deleted or kept by Stephen |
