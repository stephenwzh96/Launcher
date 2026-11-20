# Backlog

The one list of open work for Trend, IBKR and the launcher (team review, 20 Nov 2026, project manager 10). It
replaces six lists: IBKR's untracked `TODO.md`, Trend's `TODO.md`, the IBKR plan's §11.4, §12 "Remaining" and §16,
and the review's next batch. Those now point here; Trend's `TODO.md` keeps the detail of its four research items.

- **Owner**: *Stephen* (decisions, accounts, money, system settings, reference files, merges), *Claude* (builds on a
  branch with tests; Stephen merges), or *both*.
- **Done when**: the test of done. A done item leaves the list; its commit or decision says so.
- **Source** in brackets: `D` = IBKR `DECISIONS.md`; `GL` = IBKR `docs/GO_LIVE.md` row; review role and item
  (`reports/reviews/2026-11-20/` in IBKR); `T-TODO` = Trend `TODO.md`.

## 1. The review's decisions, to build (D45-D60)

| # | Item | Owner | Done when |
|---|---|---|---|
| 1.1 | Hard size limits in `reference/limits.yaml` [D45, GL 9] | Claude | the cycle reads the file; each limit halts as decided; a test per limit fails without it |
| 1.2 | Input sanity gates: NAV 5%, FX 1%, settlement max(10%, 8 sigma), quote band at send [D46, GL 10] | Claude | each gate halts or freezes as decided, with tests |
| 1.3 | Exposure override and a "Flatten" runbook section [D47, GL 11] | Claude, then both | the override is a command, booked on the override line; Flatten drilled on paper once |
| 1.4 | Four reviews become halts [D48, GL 9] | Claude | policy divergence, a weight with no sigma, continuity above 2%, live dirty code halt; tests |
| 1.5 | A failed leg freezes its slot [D49, GL 9] | Claude | one unresolvable leg leaves the other slots trading; test |
| 1.6 | IBKR's margin against the estimate, on the page [D50, GL 10] | Claude | a review above the cap or 1.25x the estimate; both shown |
| 1.7 | Final settlements; a day closed again when a mark moved [D51, GL 10] | Claude | finality table applied; moved marks re-close the day and are logged; tests |
| 1.8 | Close versions, accrual lines, the period lock [D52, GL 12] | Claude; lock date Stephen | an append-only version on every re-close; accruals booked and reversed; a locked day refuses a re-close |
| 1.9 | The resume task [D56] | Claude builds; Stephen registers | a task every 10 min, 16:00-08:30, reruns `run` only when the list is approved and the cycle not done |
| 1.10 | The night on the VPS with an outside dead-man [D56, GL 15] | both | 5 paper nights run there, watched from outside |
| 1.11 | GTD by default; MOC cancelled on a stop; legged-roll incident; band per product on delayed venues [D57] | Claude | each with a test; GTD on without a `.env` line |
| 1.12 | Drawdown levels from the current runs [D59] | Claude; Stephen reviews | `reference/drawdown_levels.yaml` regenerated from the pinned runs, merged by Stephen |
| 1.13 | The envelope schema contract, `target_portfolio/1` [D60] | Claude (both repos) | one JSON Schema committed in both; Trend's envelope test validates against it |
| 1.14 | Two Trend trials: band against the scaled target; 252-day covariance [D58] | Claude; Stephen adopts or not | pre-registered in Trend `DECISIONS.md`, runs logged, a short report; nothing adopted without Stephen |

## 2. The review's next batch, and the paper test

| # | Item | Owner | Done when |
|---|---|---|---|
| 2.1 | `run` without `--day` resumes last night's unfinished cycle [trade operations 2] | Claude | a rerun after the reconcile halt resumes it, or refuses and prints the command; test |
| 2.2 | Fills, the rest: finished orders' fills recovered; a unique index on the execution id; reconnect lock-out at most 30 s; window-end cancels retried on reconnect [developer 2, trader 4 and 7, GL 13] | Claude | integration tests on the embedded database |
| 2.3 | Version handshake: the IBKR commit with every cycle; refuse a database newer than the code [architect 6] | Claude | recorded in the cycle's detail; a start on a newer database refuses |
| 2.4 | The day side on Telegram: Start of Day's GO, HOLD or FAILED; press reminders; the VPS watch's false alarm on an early end; each PC's switches at the first press; backup failure or a dump over 36 h old [trade operations 4, 5, 7, 8] | Claude; Stephen redeploys the VPS watch | each line seen on the phone once |
| 2.5 | The PM's screens: a "Next" column and the threshold test on Trend's Allocation; each volatility named by its basis on both pages; live P&L by market and class; macro data health in the envelope (after 1.13) [portfolio manager 3, 5, 6, 9] | Claude | both pages show them; the two pages' labels agree |
| 2.6 | Books: FX carried over a holiday, **before 28 Dec 2026**; a way to book a trade the replica did not make; days to first notice on the page and in halt alerts [accountant 2, 7; risk manager 5] | Claude | tests; 28 Dec closes on carried rates |
| 2.7 | Estimated books keep their own P&L, so MTFA, MTFB and MTFC compare over the same days [review decision 8; portfolio manager 2] | Claude | each estimated book marked to stored settlements less estimated costs, charted beside the real one |
| 2.8 | Capital adequacy and the replay rerun at the paper NAV on the current pins; a minimum live NAV per product [D44; plan §16 3; P4 remaining; GL 18] | Claude; Stephen sets the minimums | dated reports in IBKR `reports/`; minimums recorded as a decision |
| 2.9 | The paper month reconciled to the cent against IBKR's Flex statements [plan P3 and P7 remaining] | Claude | the November statement days reconcile; breaks explained |
| 2.10 | Each failure in the runbook drilled once and dated; one restore; one cold start on a real statement [P13 remaining; trade operations 7; GL 7] | both | a dated list in the runbook |
| 2.11 | The weekly reference check scheduled with a Telegram line; a review within 30 days of `holidays.yaml`'s end [trade operations 11] | Claude; Stephen registers | the check runs weekly (newest report today: 2 Nov) |
| 2.12 | November month-end report [plan §8; project manager] | Claude runs; Stephen reads | `scripts/monthly_report.py 2026-11` read in the first week of December |
| 2.13 | Start of Day commits and pushes its own run record; the next start warns when yesterday's is missing on GitHub [project manager 3] | Claude | the day's `trial_log.csv` rows and record reach GitHub the same day |
| 2.14 | The pin records the model's code, not only its config: tree hashes in the envelope [architect 4] | Claude; Stephen decides | a code change without a config change is a review |
| 2.15 | The launcher may start without the claim when GitHub errors, now the run lock exists [architect 3; trade operations 9] | Claude | an offline press by the day's holder works; test |

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
| 3.13 | The RBA 2-year yield stamped a day late but published weekly: an open point-in-time breach [review decision 14; Trend `DECISIONS.md` 2026-11-01] | decided in Trend `DECISIONS.md` |
| 3.14 | Equity index rolls 1-2 days apart in Trend and IBKR [Trend `reports/paper_readiness_2026-11-16.md`] | aligned, or the gap accepted |
| 3.15 | The twelve empty legacy folders under IBKR `src/` and the five stale documents: archive or delete (your no-delete rule) [review next batch 9] | your say recorded; the documents carry superseded banners meanwhile |
| 3.16 | A Bank of Korea key for KRW_MP2Y; `data import-french` for TZ_TPX after the library's next update [T-TODO; Trend independent review 17 Nov] | key in `.env`; import done |

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
