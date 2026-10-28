# DocRepo test vectors

Expected values computed by the browse tool mockup's reference code (`docs/browse-tool/mockup/model.js`) from its made-up sample data, with today = 2026-10-08, a Thursday. Use them as expected results in DocRepo's tests. Regenerate this file instead of editing it.

## Capacity: scheduled hours per person and week

Rules from the brainstorm's "Capacity calendar": each window's hours are spread evenly over its workdays (Monday to Friday), everyone in a role gets that role's full hours, Parked tasks are skipped, and closed tasks stop at their close date. Weeks start on Monday. Hours are rounded to two decimals.

| Person | 5 Oct | 12 Oct | 19 Oct | 26 Oct | 2 Nov | 9 Nov | 16 Nov | 23 Nov | 30 Nov |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Me | 3.47 | 3.47 | 7.47 | 10.47 | 2.56 | 2.56 | 2.56 | 4.56 | 2.00 |
| Priya Shah | 2.75 | 3.75 | 3.75 | 1.50 | 1.50 | 1.50 | 1.50 | 1.50 | 1.50 |
| Tom Becker | 2.25 | 8.25 | 38.25 | 32.25 | 2.25 | 2.25 | 2.25 | 2.25 | 1.00 |
| Mike Ortiz | 5.67 | 4.79 | 32.54 | 31.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| Tyler Nguyen | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| Todd | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |

- Unestimated (people but no hours): T000017 Rails need to be painted red; T000019 Book the alignment contractor
- Unscheduled (hours but no dates): T000016 Holiday coverage schedule

## Capacity: week of 19 Oct, by task

| Person | Task | Hours |
|---|---|---:|
| Me | T000008 Installation | 4.00 |
| Me | T000001 Reactor impeller upgrade | 1.56 |
| Me | T000010 Business team meeting | 1.00 |
| Me | T000002 Verification walkthrough readiness | 0.91 |
| Priya Shah | T000010 Business team meeting | 1.50 |
| Priya Shah | T000009 Vendor drawing package | 1.25 |
| Priya Shah | T000011 Draft monitoring plan | 1.00 |
| Tom Becker | T000008 Installation | 30.00 |
| Tom Becker | T000011 Draft monitoring plan | 6.00 |
| Tom Becker | T000001 Reactor impeller upgrade | 1.25 |
| Tom Becker | T000010 Business team meeting | 1.00 |
| Mike Ortiz | T000008 Installation | 30.00 |
| Mike Ortiz | T000018 Update area 3 guard drawings | 1.54 |
| Mike Ortiz | T000010 Business team meeting | 1.00 |

## Days until due

Due, else Deadline. A routine task counts to the end of its next occurrence. Negative means overdue.

| Task | Date used | Days |
|---|---|---:|
| T000001 Reactor impeller upgrade | Due 2026-11-27 | 50 |
| T000002 Verification walkthrough readiness | Deadline 2026-10-31 | 23 |
| T000006 Monthly safety report | Next 2026-10-30 | 22 |
| T000008 Installation | Due 2026-10-30 | 22 |
| T000009 Vendor drawing package | Due 2026-10-23 | 15 |
| T000010 Business team meeting | Next 2026-10-13 | 5 |
| T000011 Draft monitoring plan | Due 2026-10-23 | 15 |
| T000012 Rigging plan | Due 2026-10-14 | 6 |
| T000015 Q4 overtime budget | None |  |
| T000016 Holiday coverage schedule | None |  |
| T000017 Rails need to be painted red | Due 2026-10-16 | 8 |
| T000018 Update area 3 guard drawings | Due 2026-10-23 | 15 |
| T000019 Book the alignment contractor | Due 2026-10-09 | 1 |

## Lists

Open tasks only. Routine tasks are left out of "Overdue and next 7 days".

- Overdue and next 7 days: T000019, T000012
- Reminders: T000016, T000018, T000019
- Waiting on others: T000019, T000012, T000017, T000009, T000011, T000018, T000008, T000001
- Assigned to me: T000010, T000006, T000016
- Urgent: T000019
- No dates or hours: T000019, T000017, T000016

## Labels and parent chains

Inherited labels are in italics. A chain runs from a top-level task down to the task.

| Task | Labels | Chains |
|---|---|---|
| T000001 Reactor impeller upgrade | Line 1, Strategic Plan | T000001 |
| T000002 Verification walkthrough readiness | Safety | T000002 |
| T000003 Q4 cost reduction | Profitability | T000003 |
| T000004 Line 2 extruder screw replacement | Line 2 | T000004 |
| T000005 Cooling tower fan gearbox | Line 1 | T000005 |
| T000006 Monthly safety report | Safety | T000006 |
| T000007 Order spare mechanical seal | _Line 1_, _Strategic Plan_ | T000001 › T000007 |
| T000008 Installation | _Line 1_, _Strategic Plan_ | T000001 › T000008 |
| T000009 Vendor drawing package | _Line 1_, _Strategic Plan_ | T000001 › T000009 |
| T000010 Business team meeting |  | T000010 |
| T000011 Draft monitoring plan | _Line 1_, _Strategic Plan_ | T000001 › T000011 |
| T000012 Rigging plan | _Line 1_, _Strategic Plan_ | T000001 › T000008 › T000012 |
| T000015 Q4 overtime budget | _Profitability_, _Line 1_, _Strategic Plan_ | T000003 › T000015; T000001 › T000008 › T000015 |
| T000016 Holiday coverage schedule |  | T000016 |
| T000017 Rails need to be painted red | _Safety_ | T000002 › T000017 |
| T000018 Update area 3 guard drawings | _Safety_ | T000002 › T000018 |
| T000019 Book the alignment contractor | Safety, _Line 1_, _Strategic Plan_ | T000001 › T000008 › T000019 |

## Raw text log

The entries in each task's raw text log, oldest first (round 23). A capture belongs to the task it created; to the task it picked, unless it only made a subtask there (New task without Update); and to the task it was filed to. A document version (V, with its document's ID) belongs to every task its document belongs to. Unfiled captures and notes put only on an agenda belong to no task.

| Task | Entries |
|---|---|
| T000001 Reactor impeller upgrade | C000001, C000003, C000008, C000014 |
| T000005 Cooling tower fan gearbox | C000004 |
| T000007 Order spare mechanical seal | C000002, C000007 |
| T000008 Installation | C000005, V D000002 2026-10-05, C000013 |
| T000009 Vendor drawing package | C000006, C000017 |
| T000010 Business team meeting | C000009 |
| T000011 Draft monitoring plan | C000010, C000025 |
| T000012 Rigging plan | C000012 |
| T000015 Q4 overtime budget | C000015 |
| T000016 Holiday coverage schedule | C000016 |
| T000017 Rails need to be painted red | C000018 |
| T000018 Update area 3 guard drawings | C000019 |
| T000019 Book the alignment contractor | C000020 |

- Unfiled: C000021, C000022, C000023

## Agendas

Agenda items are links from a task, or a note with no task, to a meeting, another task or a person (round 23). Open items carry over until they're closed by hand, as Discussed or Removed.

| Target | Open items | Closed items |
|---|---|---|
| T000010 Business team meeting | T000001; T000015; T000016; note "Ask whether the December shutdown dates are confirmed." | T000008 (discussed 2026-10-06) |
| P003 Tom Becker | T000011 | none |

- T000001 Reactor impeller upgrade is on the agenda of Business team meeting
- T000011 Draft monitoring plan is on the agenda of Tom Becker
- T000015 Q4 overtime budget is on the agenda of Business team meeting
- T000016 Holiday coverage schedule is on the agenda of Business team meeting

## Paths

- Longest path in the sample data root: 122 characters.
- `C:\Users\<user>\DocRepoData\Tasks\T000008\Files\_old versions\2026-09-22 Installation procedure (replaced 2026-10-05).docx`

## Parse and populate

Results of `parseCapture` in `docs/browse-tool/mockup/parse.js`, with today = 2026-10-08. The people list is Me, Priya Shah, Tom Becker, Mike Ortiz, Tyler Nguyen, with Rob Lee on it as retired. Todd and Marcus aren't on it, so they're added as new people. Labels and their keywords are the sample data's, listed in Contents.md. The first three cases and the last five are the brainstorm's. A rate of hours becomes a total from Start (today, unless the text gives one) to Due. Fields not listed are left empty. There's no Description to fill: a new task's description is its whole content text (round 23).

| Capture type | Content text | Fills |
|---|---|---|
| New task | Rails need to be painted red. Try to have this done by next Friday. Deadline is the next verification walkthrough at the end of October. We'll assign this one to Todd. | Title "Rails need to be painted red". Due 2026-10-16. Deadline 2026-10-31. Deadline description "Next verification walkthrough". Labels [Safety]. Assignees [Todd (new person)]. |
| New task | Remind Tyler tomorrow that he needs to book the alignment contractor. Urgent: hard deadline is the turnaround on Oct 19. Safety review needed before mobilizing. | Title "Book the alignment contractor". Due 2026-10-09. Deadline 2026-10-19. Deadline description "Turnaround". Reminder 2026-10-09. Urgent. Labels [Safety]. Lead [Me]. Assignees [Tyler Nguyen]. |
| Update | Vendor drawings came in late, so the package is now due Oct 23. | Current status "Vendor drawings came in late, so the package is now due Oct 23.". Due 2026-10-23. |
| New task | Tom to draft the vibration monitoring plan for the new impeller, 12 Oct to 23 Oct. Priya to review. | Title "Draft the vibration monitoring plan for the new impeller". Due 2026-10-23. Start 2026-10-12. Assignees [Tom Becker, Priya Shah]. |
| New task | Safety walkthrough every Monday starting Oct 19. Mike owns it; I'll attend. | Title "Safety walkthrough". Start 2026-10-19. Recurrence Weekly. Labels [Safety]. Lead [Mike Ortiz]. Assignees [Me]. |
| New task | Ask Priya to send the overtime numbers ASAP. | Title "Send the overtime numbers". Urgent. Labels [Profitability]. Lead [Me]. Assignees [Priya Shah]. |
| New task | Marcus needs to check shift coverage for first day of trial to test whether he wants double coverage. Remind him early next week. Due by end of next week. | Title "Check shift coverage for first day of trial to test whether he wants double coverage". Due 2026-10-16. Reminder 2026-10-12. Lead [Me]. Assignees [Marcus (new person)]. |
| Update | Closed. Mike confirmed he doesn't want extra coverage. | State Closed. Current status "Mike confirmed he doesn't want extra coverage.". |
| New task | Describes the overall site initiative for adopting standard 6B and closing all gaps. Target date is 1Q27. Deadline is the external audit on May 25 2027. Priya is leading. | Title "Describes the overall site initiative for adopting standard 6B and closing all gaps". Due 2027-03-31. Deadline 2027-05-25. Deadline description "External audit". Lead [Priya Shah]. |
| New task | Complete the vendor initial screening. Due December 12.  Tyler is leading, probably 1 hours a week work load for lead. Mike is completing the items, probably total 6 hours of work. | Title "Complete the vendor initial screening". Due 2026-12-12. Lead [Tyler Nguyen]. Assignees [Mike Ortiz]. Lead hours 9.5. Assignee hours 6. |
| New task | Monthly safety statistics review. Mike to prepare it, about 3 hours a month. | Title "Monthly safety statistics review". Recurrence Monthly. Labels [Safety]. Assignees [Mike Ortiz]. Assignee hours 3. |

### Edge cases (round 24)

Made-up captures that test the rules' edges: phrasing that should, or shouldn't, fill a field. Each row is what the code does now. A line break in the content text is shown as \n.

#### Dates

| Capture type | Content text | Fills |
|---|---|---|
| New task | Send the revised guard drawings to Norvane by Friday, Oct 16. | Title "Send the revised guard drawings to Norvane". Due 2026-10-16. Labels [Safety]. |
| New task | Pump trial on Monday the 19th. Tom will run it. | Title "Pump trial". Due 2026-10-19. Assignees [Tom Becker]. |
| New task | Tom to finish the isolation list by Wednesday next week. | Title "Finish the isolation list". Due 2026-10-14. Assignees [Tom Becker]. |
| New task | Get the scaffold quote by EOD Friday. | Title "Get the scaffold quote". Due 2026-10-09. |
| New task | Get the scaffold quote by close of business Monday. | Title "Get the scaffold quote". Due 2026-10-12. |
| New task | Mike will install the new guards Oct 19-23. | Title "Install the new guards". Due 2026-10-23. Start 2026-10-19. Labels [Safety]. Assignees [Mike Ortiz]. |
| New task | Installation is planned for the turnaround, 19 to 30 Oct. | Title "Installation is planned for the turnaround". Deadline 2026-10-30. Deadline description "Turnaround". Start 2026-10-19. |
| New task | Hydrotest between Oct 12 and Oct 16. | Title "Hydrotest". Due 2026-10-16. Start 2026-10-12. |
| New task | Run the pump trials from Monday to Friday. | Title "Run the pump trials". Due 2026-10-16. Start 2026-10-12. |
| New task | Shutdown work Oct 26 – Nov 6. | Title "Shutdown work". Deadline 2026-11-06. Deadline description "Shutdown". Start 2026-10-26. |
| New task | Finalize the Q4 budget forecast next month. | Title "Finalize the Q4 budget forecast". Due 2026-11-30. Labels [Profitability]. |
| New task | Update the cost tracker within 2 weeks. | Title "Update the cost tracker". Due 2026-10-22. Labels [Profitability]. |
| New task | Renew the crane certification in a month. | Title "Renew the crane certification". Due 2026-11-08. |
| New task | Close out the punch list by the end of the month. | Title "Close out the punch list". Due 2026-10-31. |
| New task | Draft the 2027 maintenance plan by end of next quarter. | Title "Draft the 2027 maintenance plan". Due 2027-03-31. |
| New task | Order the replacement seal the day after tomorrow. | Title "Order the replacement seal". Due 2026-10-10. |
| New task | Book the crane for the week after next. | Title "Book the crane". Due 2026-10-23. |
| New task | Rebuild the Line 1 gearbox in November. | Title "Rebuild the Line 1 gearbox". Due 2026-11-30. Labels [Line 1]. |
| New task | Starting in June, Tom will cover the weekend checks. | Title "Cover the weekend checks". Start 2027-06-01. Assignees [Tom Becker]. |
| New task | Starting next week, Tom will run the pump checks every day. | Title "Run the pump checks". Start 2026-10-12. Recurrence Daily. Assignees [Tom Becker]. |
| New task | Close out in Q4 2026. | Title "Close out". Due 2026-12-31. |
| New task | Install new rails on the mezzanine. Start 10/19, finish 10/30. Tom 20 hours, Mike 20 hours. | Title "Install new rails on the mezzanine". Due 2026-10-30. Start 2026-10-19. Labels [Safety]. Assignees [Tom Becker, Mike Ortiz]. Assignee hours 20. |

#### Due or Deadline

| Capture type | Content text | Fills |
|---|---|---|
| New task | Submit the permit package. Due Friday, deadline Oct 30. | Title "Submit the permit package". Due 2026-10-09. Deadline 2026-10-30. |
| New task | Order the spare seal. Must be done by Friday. Deadline is Oct 30 for the outage. | Title "Order the spare seal". Due 2026-10-09. Deadline 2026-10-30. Deadline description "Outage". |
| New task | Print a hard copy of the drawings by Friday. | Title "Print a hard copy of the drawings". Due 2026-10-09. |
| New task | The audit report is due Friday. | Title "The audit report". Due 2026-10-09. |
| New task | Prepare the audit binder by Friday. | Title "Prepare the audit binder". Deadline 2026-10-09. Deadline description "Audit". |
| New task | Order parts for the Line 2 pumps by the outage on Nov 3. | Title "Order parts for the Line 2 pumps". Deadline 2026-11-03. Deadline description "Outage". Labels [Line 2]. |
| New task | Change the filters. Deadline: Oct 30 (turnaround start). | Title "Change the filters". Deadline 2026-10-30. Deadline description "Turnaround start". |
| New task | Rigging plan to Tom by Oct 14, ahead of the lift on Oct 16. | Title "Rigging plan to Tom". Due 2026-10-14. Deadline 2026-10-16. Deadline description "Lift". Assignees [Tom Becker]. |
| New task | Oct 30 is the deadline, Friday is the target. | Title "Oct 30 is the deadline, Friday is the target". Due 2026-10-09. Deadline 2026-10-30. |
| New task | Finish the install Oct 30 at the latest. | Title "Finish the install". Deadline 2026-10-30. |
| New task | Mike must review the drawings by Friday. | Title "Review the drawings". Deadline 2026-10-09. Assignees [Mike Ortiz]. |
| New task | Plan the Line 2 outage for March 2027. | Title "Plan the Line 2 outage". Deadline 2027-03-31. Deadline description "Line 2 outage". Labels [Line 2]. |
| New task | Plan for a 4 hour outage on Oct 20. | Title "Plan for a 4 hour outage". Deadline 2026-10-20. Deadline description "4 hour outage". |
| New task | Prepare for the audit on Oct 30. | Title "Prepare for the audit". Deadline 2026-10-30. Deadline description "Audit". |
| Update | Was due Oct 16, now due Oct 23. | Current status "Was due Oct 16, now due Oct 23.". Due 2026-10-23. |
| Update | Slipped from Oct 16 to Oct 23 because of the late drawings. | Current status "Slipped from Oct 16 to Oct 23 because of the late drawings.". Due 2026-10-23. |
| Update | Deadline was Oct 30, now Nov 6. | Current status "Deadline was Oct 30, now Nov 6.". Deadline 2026-11-06. |
| Update | pushed the install to next Tuesday because of the crane | Current status "pushed the install to next Tuesday because of the crane". Due 2026-10-20. |

#### Recurrence

| Capture type | Content text | Fills |
|---|---|---|
| New task | Present the pump trial results at the weekly meeting on Monday. | Title "Present the pump trial results at the weekly meeting". Due 2026-10-12. |
| New task | Walk down the Line 1 guards every other Monday. | Title "Walk down the Line 1 guards". Start 2026-10-12. Recurrence Bi-weekly. Labels [Line 1, Safety]. |
| New task | Check the LOTO boards every weekday. | Title "Check the LOTO boards". Recurrence Daily. Labels [Safety]. |
| New task | Read the boiler logs every morning. | Title "Read the boiler logs". Recurrence Daily. |
| New task | Annual PSV inspection due Nov 30. | Title "Annual PSV inspection". Due 2026-11-30. Recurrence Yearly. |
| New task | Every 2nd Tuesday, send the cost report to finance. | Title "Send the cost report to finance". Start 2026-10-13. Recurrence Bi-weekly. Labels [Profitability]. |
| New task | Quarterly review of the spare parts list, starting in January. | Title "Quarterly review of the spare parts list". Start 2027-01-01. Recurrence Quarterly. |
| New task | Send the safety stats on Mondays. | Title "Send the safety stats". Start 2026-10-12. Recurrence Weekly. Labels [Safety]. |
| New task | Team meeting weekly on Tuesdays at 9. | Title "Team meeting". Start 2026-10-13. Recurrence Weekly. |
| New task | Prepare the monthly report by the 5th. | Title "Prepare the monthly report". Due 2026-11-05. Recurrence Monthly. |
| New task | Safety committee on the second Tuesday of each month. | Title "Safety committee". Start 2026-10-13. Recurrence Monthly. Labels [Safety]. |
| New task | From next month, send the cost report monthly. | Title "Send the cost report". Start 2026-11-01. Recurrence Monthly. Labels [Profitability]. |
| New task | Weekly 1:1 with Tom on Thursdays, 30 min. | Title "Weekly 1:1 with Tom". Start 2026-10-15. Recurrence Weekly. Assignees [Tom Becker]. Assignee hours 0.5. |
| New task | Tom is on annual leave next week. | Title "Tom is on annual leave". Due 2026-10-16. Assignees [Tom Becker]. |

#### People

| Capture type | Content text | Fills |
|---|---|---|
| New task | Rebuild the seal pot. Lead: Tom. Assignees: Mike, Priya. | Title "Rebuild the seal pot". Lead [Tom Becker]. Assignees [Mike Ortiz, Priya Shah]. |
| New task | Clean the cooling tower basin. Owner - Mike. | Title "Clean the cooling tower basin". Lead [Mike Ortiz]. |
| New task | Seal kit replacement, led by Priya. | Title "Seal kit replacement". Lead [Priya Shah]. |
| New task | Ask Purchasing to expedite the coupling. | Title "Expedite the coupling". |
| New task | Ask Sarah's team to quote the scaffold. | Title "Quote the scaffold". Lead [Me]. Assignees [Sarah (new person)]. |
| New task | Ask Dr. Patel to sign off the PSSR. | Title "Sign off the PSSR". Lead [Me]. Assignees [Patel (new person)]. |
| New task | Tom and Mike will pull the old impeller on Oct 20. | Title "Pull the old impeller". Due 2026-10-20. Assignees [Tom Becker, Mike Ortiz]. |
| New task | Tom, Mike and Priya to review the P&ID markups. | Title "Review the P&ID markups". Assignees [Tom Becker, Mike Ortiz, Priya Shah]. |
| New task | Priya and I will draft the 2027 capital plan in November, about 10 hours each. | Title "Draft the 2027 capital plan". Due 2026-11-30. Assignees [Priya Shah, Me]. Assignee hours 10. |
| New task | I'll ask Tom to check the coupling alignment. | Title "Check the coupling alignment". Lead [Me]. Assignees [Tom Becker]. |
| New task | Need Tom to check the guard bolts. | Title "Check the guard bolts". Labels [Safety]. Assignees [Tom Becker]. |
| New task | Have Mike swap the filters on line 1. | Title "Swap the filters on line 1". Labels [Line 1]. Assignees [Mike Ortiz]. |
| New task | Remind me on Monday to call the crane vendor. | Title "Call the crane vendor". Due 2026-10-12. Reminder 2026-10-12. Assignees [Me]. |
| New task | Remind Tom and Mike to sign the permit. | Title "Sign the permit". Lead [Me]. Assignees [Tom Becker, Mike Ortiz]. |
| New task | Fix the guard latch. Assigned to: Priya | Title "Fix the guard latch". Labels [Safety]. Assignees [Priya Shah]. |
| New task | Ask Rob to check the trap survey. | Title "Check the trap survey". Not added: Rob Lee is retired on the people list. |
| New task | Ping Tyler N. about the alignment report on Friday. | Title "Ping Tyler N. about the alignment report". Due 2026-10-09. Reminder 2026-10-09. Lead [Me]. Assignees [Tyler Nguyen]. |
| New task | @mike please check the guard interlock. | Title "Check the guard interlock". Labels [Safety]. Assignees [Mike Ortiz]. |
| New task | Tom will lead, Mike and Priya will do the work. | Title "Tom will lead". Lead [Tom Becker]. Assignees [Mike Ortiz, Priya Shah]. |
| New task | Tom: pull the coupling. Mike: check the alignment. Due Wednesday. | Title "Pull the coupling". Due 2026-10-14. Assignees [Tom Becker, Mike Ortiz]. |
| New task | PS: the guard drawings are in the shared folder. | Title "The guard drawings are in the shared folder". Labels [Safety]. |
| New task | From: Priya Shah\nSent: Thursday, October 8, 2026 9:14 AM\nSubject: RE: Coupling guard delivery\n\nThe coupling guard now ships on Oct 14. Please confirm the mounting holes by Oct 12. | Title "Coupling guard delivery". Due 2026-10-14. Labels [Safety]. |

#### Hours

| Capture type | Content text | Fills |
|---|---|---|
| New task | Tom to rewire the panel, 2-3 hours. | Title "Rewire the panel". Assignees [Tom Becker]. Assignee hours 3. |
| New task | Calibrate the transmitters, about 90 minutes. | Title "Calibrate the transmitters". Assignee hours 1.5. |
| New task | Tom to write the procedure, roughly 2 days of work. | Title "Write the procedure". Assignees [Tom Becker]. Assignee hours 16. |
| New task | Mike to inspect the guards, .5 hours. | Title "Inspect the guards". Labels [Safety]. Assignees [Mike Ortiz]. Assignee hours 0.5. |
| New task | Priya to support the trial, 4 hours a week for 3 weeks. | Title "Support the trial". Assignees [Priya Shah]. Assignee hours 12. |
| New task | Tom to check the trap survey, a couple of hours. | Title "Check the trap survey". Assignees [Tom Becker]. Assignee hours 2. |
| New task | Set up the trial skid. Lead hours: 4. Assignee hours: 10. | Title "Set up the trial skid". Lead hours 4. Assignee hours 10. |
| New task | Tyler will lead (2 h/week) and Mike will do the install (12 h). Due Oct 30. | Title "Tyler will lead". Due 2026-10-30. Lead [Tyler Nguyen]. Assignees [Mike Ortiz]. Lead hours 7. Assignee hours 12. |
| New task | Call Tom back in 2 hours about the crane. | Title "Call Tom back in 2 hours about the crane". Assignees [Tom Becker]. |
| New task | Give 24 hours notice before the isolation. | Title "Give 24 hours notice before the isolation". |
| New task | Order spare mechanical seal for P-101A, lead time 6 weeks, needed before the Q1 2027 outage. | Title "Order spare mechanical seal for P-101A, lead time 6 weeks, needed". Deadline 2027-03-31. Deadline description "Outage". |

#### Titles

| Capture type | Content text | Fills |
|---|---|---|
| New task | Please send the drawings to Tom by Friday. | Title "Send the drawings to Tom". Due 2026-10-09. Assignees [Tom Becker]. |
| New task | Can we get the hydrotest results by Monday? | Title "Get the hydrotest results". Due 2026-10-12. |
| New task | Urgent! Replace the cracked guard on line 1. | Title "Replace the cracked guard on line 1". Urgent. Labels [Line 1, Safety]. |
| New task | Todo:\nOrder the spare seal\nCheck the coupling | Title "Order the spare seal". |
| New task | - Order the spare seal by Friday\n- Check the coupling | Title "Order the spare seal". Due 2026-10-09. |
| New task | Order the seal by Oct. 19 for the outage. | Title "Order the seal". Deadline 2026-10-19. Deadline description "Outage". |
| New task | Re: Steam trap survey quote | Title "Steam trap survey quote". |
| New task | On Friday, send the cost report to Priya. | Title "Send the cost report to Priya". Due 2026-10-09. Labels [Profitability]. Assignees [Priya Shah]. |
| New task | Don’t forget to renew the LOTO locks. | Title "Renew the LOTO locks". Labels [Safety]. |
| New task | Approx. 20 guards need new labels before the audit on Oct 30. | Title "Approx. 20 guards need new labels". Deadline 2026-10-30. Deadline description "Audit". Labels [Safety]. |
| New task | Chase the vendor for the datasheet. | Title "Chase the vendor for the datasheet". |
| New task | Need the PSSR signed off by 10/23 - Priya to sign, Tom to witness. | Title "Need the PSSR signed off". Due 2026-10-23. Assignees [Priya Shah, Tom Becker]. |
| New task | Check with Tyler whether the crane is booked for Oct 20th; if not, book it by Monday. | Title "Check with Tyler whether the crane is booked". Due 2026-10-20. Assignees [Tyler Nguyen]. |
| New task | remind tyler tomorrow to book the alignment contractor hard deadline is the turnaround on oct 19 | Title "Book the alignment contractor". Due 2026-10-09. Deadline 2026-10-19. Deadline description "Turnaround". Reminder 2026-10-09. Lead [Me]. Assignees [Tyler Nguyen]. |
| New task | tom needs to finish the rigging plan by next friday and mike will review it | Title "Finish the rigging plan". Due 2026-10-16. Assignees [Tom Becker, Mike Ortiz]. |
| New task | new task replace the seal on the line 2 feed pump about 4 hours for mike due end of next week | Title "Replace the seal on the line 2 feed pump". Due 2026-10-16. Labels [Line 2]. Assignees [Mike Ortiz]. Assignee hours 4. |
| New task | so basically we need to get the guard drawings updated before the audit which is on the 30th and priya is leading that | Title "Get the guard drawings updated before the audit". Deadline 2026-10-30. Deadline description "Audit". Labels [Safety]. Lead [Priya Shah]. |
| New task | ok so the weekly safety walkthrough every monday at 7 mike owns it | Title "The weekly safety walkthrough". Start 2026-10-12. Recurrence Weekly. Labels [Safety]. Lead [Mike Ortiz]. |
| New task | URGENT - LOTO audit findings due tomorrow COB, Mike and Tom to close them out (~3 hrs each) | Title "LOTO audit findings". Due 2026-10-09. Urgent. Labels [Safety]. Assignees [Mike Ortiz, Tom Becker]. Assignee hours 3. |

#### Urgent

| Capture type | Content text | Fills |
|---|---|---|
| New task | Not urgent: tidy the spares cage. | Title "Tidy the spares cage". |
| New task | Non-critical: repaint the handrail. | Title "Repaint the handrail". |
| New task | This is on the critical path for the restart. | Title "This is on the critical path for the restart". |
| New task | High priority: fix the guard interlock. | Title "Fix the guard interlock". Urgent. Labels [Safety]. |
| New task | Need the coupling urgently. | Title "Need the coupling". Urgent. |

#### Quick updates

| Capture type | Content text | Fills |
|---|---|---|
| Update | Done. Tom confirmed the alignment. | State Closed. Current status "Tom confirmed the alignment.". |
| Update | On hold - waiting for the 2027 budget. | State Parked. Current status "Waiting for the 2027 budget.". |
| Update | In progress: scaffold is up. | State In progress. Current status "Scaffold is up.". |
| Update | Closed | State Closed. |
| Update | Closed the valve and tagged it out. | Current status "Closed the valve and tagged it out.". |
| Update | Parked. Waiting on capital approval, revisit Jan 11. | State Parked. Current status "Waiting on capital approval, revisit Jan 11.". Due 2027-01-11. |
| Update | Reopened. The seal is leaking again. | State In progress. Current status "The seal is leaking again.". |
| Update | Not started - waiting on the permit. | State Not started. Current status "Waiting on the permit.". |
| Update | in progress, scaffold up, insulation off by Friday | State In progress. Current status "Scaffold up, insulation off by Friday". Due 2026-10-09. |
| Update | Done by Friday: the guards. | Current status "Done by Friday: the guards.". Due 2026-10-09. |

#### Not dates, people or hours

| Capture type | Content text | Fills |
|---|---|---|
| New task | Replace the 3/4 inch drain valve on line 2. | Title "Replace the 3/4 inch drain valve on line 2". Labels [Line 2]. |
| New task | Order 1/2" tubing and fittings. | Title "Order 1/2" tubing and fittings". |
| New task | About 1/3 of the guards are missing. | Title "About 1/3 of the guards are missing". Labels [Safety]. |
| New task | Fit a 1 1/2 in. ball valve on the drain. | Title "Fit a 1 1/2 in. ball valve on the drain". |
| New task | We may need extra scaffold. | Title "We may need extra scaffold". |
| New task | Prepare next year's budget by Dec 1. | Title "Prepare next year's budget". Due 2026-12-01. Labels [Profitability]. |
| New task | Send this week's numbers to Priya. | Title "Send this week's numbers to Priya". Assignees [Priya Shah]. |
| New task | Finish the review in the 4th quarter. | Title "Finish the review in the 4th quarter". |
| New task | Lead time is 6 weeks for the new seal. | Title "Lead time is 6 weeks for the new seal". |
| New task | Ask Engineering for the calcs. | Title "Ask Engineering for the calcs". |
| New task | Pump No. 3 needs a new seal by Friday. | Title "Pump No. 3 needs a new seal". Due 2026-10-09. |
| New task | Get the quote in an hour. | Title "Get the quote in an hour". |
| New task | Book the crane for the turnaround. | Title "Book the crane for the turnaround". |
| New task | Check the bolts\nC:\\Projects\\Tom\\bolt list.xlsx | Title "Check the bolts". |

### Mods log round 1

Made-up versions of what Parse and populate missed in DocRepo's first use (2026-10-19): a list of names, "is lead", half years with the year joined on, and an update's first sentence as its Current status.

| Capture type | Content text | Fills |
|---|---|---|
| New task | Pilot run window. October 26 to October 30. 40 hours per assignee. Priya, Tom, Mike and Tyler. | Title "Pilot run window". Due 2026-10-30. Start 2026-10-26. Assignees [Priya Shah, Tom Becker, Mike Ortiz, Tyler Nguyen]. Assignee hours 40. |
| New task | Pilot run window. October 26 to October 30. 40 hours per assignee. Priya, Tom, Todd and Marcus. | Title "Pilot run window". Due 2026-10-30. Start 2026-10-26. Assignees [Priya Shah, Tom Becker, Todd (new person), Marcus (new person)]. Assignee hours 40. |
| New task | Prep the spares list. 6 hours each: Tom, Mike and Todd. | Title "Prep the spares list". Assignees [Tom Becker, Mike Ortiz, Todd (new person)]. Assignee hours 6. |
| New task | Walk the line with Tom and Mike. | Title "Walk the line with Tom and Mike". |
| New task | Tom, Mike. | Title "Tom, Mike". Assignees [Tom Becker, Mike Ortiz]. |
| New task | Valves, Pumps and Motors. | Title "Valves, Pumps and Motors". |
| New task | Sort the spares. QA, HR and Tom. | Title "Sort the spares". Assignees [Tom Becker]. |
| New task | Line 2 rework. Tom is Lead. Due 2H2027. | Title "Line 2 rework". Due 2027-12-31. Labels [Line 2]. Lead [Tom Becker]. |
| New task | Line 2 rework. Tom is the lead, due 2H 2027. | Title "Line 2 rework". Due 2027-12-31. Labels [Line 2]. Lead [Tom Becker]. |
| New task | Line 2 rework, Tom as lead. Mike to scope it, 2H 2027. | Title "Line 2 rework, Tom as lead". Due 2027-12-31. Labels [Line 2]. Lead [Tom Becker]. Assignees [Mike Ortiz]. |
| New task | Strip the old coating. Tom is lead-certified. | Title "Strip the old coating". Assignees [Tom Becker]. |
| New task | Spare parts review, due Q42026. | Title "Spare parts review". Due 2026-12-31. |
| New task | Pump survey, 2 h of work for Mike. | Title "Pump survey". Assignees [Mike Ortiz]. Assignee hours 2. |
| Update | Vendor confirmed the parts ship Friday. Install is the week after. | Current status "Vendor confirmed the parts ship Friday.". Due 2026-10-09. |
| Update | Scaffold is up and insulation is off | Current status "Scaffold is up and insulation is off". |
| Update | Closed. Mike confirmed he doesn't want extra coverage. | State Closed. Current status "Mike confirmed he doesn't want extra coverage.". |

### Plant events (mods log round 3)

"Plant event" and "major event" tick Plant event, unless denied or done before, for or during one, and a plant event's end date is its Due. The event words alone don't.

| Capture type | Content text | Fills |
|---|---|---|
| New task | Plant event: Spring outage, 2 to 6 Nov. | Title "Spring outage". Due 2026-11-06. Start 2026-11-02. Plant event. |
| New task | The line 2 rebuild is a major event, 9 to 20 Nov. | Title "The line 2 rebuild is a major event". Due 2026-11-20. Start 2026-11-09. Plant event. Labels [Line 2]. |
| New task | Prep the scaffolding for the plant event. | Title "Prep the scaffolding for the plant event". |
| New task | Not a plant event, just a weekend shutdown of line 1. | Title "Not a plant event, just a weekend shutdown of line 1". Labels [Line 1]. |
| New task | Major event planning meeting with Tom on Friday. | Title "Major event planning meeting with Tom". Due 2026-10-09. Assignees [Tom Becker]. |
| Update | Now a plant event: the dates moved to 16 to 20 Nov. | Current status "Now a plant event: the dates moved to 16 to 20 Nov.". Due 2026-11-20. Plant event. |

### Naming assignees (mods log round 4)

"Mike assists", "Mike and Priya assist", "assign Mike", "assigned to Mike" and "assignees Mike and Tyler" name the assignees, with known people only, and leave the title, as "Tom leads" does.

| Capture type | Content text | Fills |
|---|---|---|
| New task | Survey the existing guards, Mike assists. | Title "Survey the existing guards". Labels [Safety]. Assignees [Mike Ortiz]. |
| New task | Survey the existing guards, Tom leads, Mike and Priya assist. | Title "Survey the existing guards". Labels [Safety]. Lead [Tom Becker]. Assignees [Mike Ortiz, Priya Shah]. |
| New task | Survey the existing guards, Tyler assisting. | Title "Survey the existing guards". Labels [Safety]. Assignees [Tyler Nguyen]. |
| New task | Fabricate the guards, assign Mike. | Title "Fabricate the guards". Labels [Safety]. Assignees [Mike Ortiz]. |
| New task | Fabricate the guards and assign it to Tyler by Friday. | Title "Fabricate the guards". Due 2026-10-09. Labels [Safety]. Assignees [Tyler Nguyen]. |
| New task | Install the guards, assigned to Mike and Priya. | Title "Install the guards". Labels [Safety]. Assignees [Mike Ortiz, Priya Shah]. |
| New task | Install the guards. Assignees Mike and Tyler. | Title "Install the guards". Labels [Safety]. Assignees [Mike Ortiz, Tyler Nguyen]. |
| New task | Install the guards, assignees: Mike, Priya. | Title "Install the guards". Labels [Safety]. Assignees [Mike Ortiz, Priya Shah]. |
| New task | Guarding sign-off walkthrough, Tom leads, Mike assists, 3 hours a week, due Nov 20. | Title "Guarding sign-off walkthrough". Due 2026-11-20. Labels [Safety]. Lead [Tom Becker]. Assignees [Mike Ortiz]. Assignee hours 19. |
| New task | Reassign the old guard drawings to the archive. | Title "Reassign the old guard drawings to the archive". Labels [Safety]. |

### Reference fields (release 5.9)

Read with two made-up reference fields in Settings, "Work order #" and "Permit no.": a field's name (without its # or no.), then a number. The first for each field counts. The other sections are read with none.

| Capture type | Content text | Fills |
|---|---|---|
| New task | Swap the seal on Pump 3, work order 48213, by Friday. | Title "Swap the seal on Pump 3, work order 48213". Due 2026-10-09. Work order # 48213. |
| New task | Work order #48213: replace the gasket. | Title "Work order #48213: replace the gasket". Work order # 48213. |
| New task | Replace the gasket under work order no. 48213, permit 7781. | Title "Replace the gasket under work order no. 48213, permit 7781". Work order # 48213. Permit no. 7781. |
| New task | Work order: 2026-0142 for the guard rail. | Title "Work order: 2026-0142 for the guard rail". Labels [Safety]. Work order # 2026-0142. |
| New task | Raise a work order for the crane. | Title "Raise a work order for the crane". |
| New task | Work orders 4 and 5 are closed. | Title "Work orders 4 and 5 are closed". |
| Update | Permit no. 7781 is signed off. Work order # 48213 closes Friday. | Current status "Permit no. 7781 is signed off.". Due 2026-10-09. Work order # 48213. Permit no. 7781. |

### Date phrases

Each phrase on its own, as `findDates` reads it with today = 2026-10-08, a Thursday. A range's first day becomes the Start.

| Phrase | Date |
|---|---|
| today | 2026-10-08 |
| EOD | 2026-10-08 |
| tomorrow | 2026-10-09 |
| Friday | 2026-10-09 |
| this Friday | 2026-10-09 |
| next Friday | 2026-10-16 |
| Monday | 2026-10-12 |
| next Monday | 2026-10-19 |
| by the 15th | 2026-10-15 |
| by the 5th | 2026-11-05 |
| this week | 2026-10-09 |
| end of week | 2026-10-09 |
| next week | 2026-10-16 |
| end of next week | 2026-10-16 |
| early next week | 2026-10-12 |
| mid next week | 2026-10-14 |
| late next week | 2026-10-16 |
| in 2 weeks | 2026-10-22 |
| in two weeks | 2026-10-22 |
| a week from today | 2026-10-15 |
| in 3 days | 2026-10-11 |
| end of month | 2026-10-31 |
| EOM | 2026-10-31 |
| end of next month | 2026-11-30 |
| end of October | 2026-10-31 |
| late October | 2026-10-31 |
| mid-October | 2026-10-15 |
| beginning of November | 2026-11-01 |
| early November | 2026-11-01 |
| mid-September | 2027-09-15 |
| end of the quarter | 2026-12-31 |
| end of Q4 | 2026-12-31 |
| end of Q1 | 2027-03-31 |
| Q1 2027 | 2027-03-31 |
| 1Q27 | 2027-03-31 |
| Q1'27 | 2027-03-31 |
| end of Q1 2027 | 2027-03-31 |
| by Q2 | 2027-06-30 |
| in Q3 | 2027-09-30 |
| Q4 budget | not a date |
| 2H27 | 2027-12-31 |
| H1 2027 | 2027-06-30 |
| end of year | 2026-12-31 |
| year-end | 2026-12-31 |
| Oct 19 | 2026-10-19 |
| October 19th, 2026 | 2026-10-19 |
| 19 October | 2026-10-19 |
| 10/19 | 2026-10-19 |
| 10/19/26 | 2026-10-19 |
| 2026-10-19 | 2026-10-19 |
| Sep 30 | 2027-09-30 |
| Friday, Oct 16 | 2026-10-16 |
| Monday the 19th | 2026-10-19 |
| Mon 19 Oct | 2026-10-19 |
| Wednesday next week | 2026-10-14 |
| Friday this week | 2026-10-09 |
| EOD Friday | 2026-10-09 |
| COB Monday | 2026-10-12 |
| day after tomorrow | 2026-10-10 |
| next month | 2026-11-30 |
| end of this month | 2026-10-31 |
| early next month | 2026-11-01 |
| mid next month | 2026-11-15 |
| next quarter | 2027-03-31 |
| this quarter | 2026-12-31 |
| next year | 2027-12-31 |
| the week after next | 2026-10-23 |
| in a month | 2026-11-08 |
| in 2 months | 2026-12-08 |
| within 10 days | 2026-10-18 |
| 3 days from now | 2026-10-11 |
| two weeks from today | 2026-10-22 |
| 30-Oct | 2026-10-30 |
| 30-Oct-26 | 2026-10-30 |
| Oct. 19 | 2026-10-19 |
| 2026/10/19 | 2026-10-19 |
| Oct 19-23 | 2026-10-23, Start 2026-10-19 |
| Oct 19 to 23 | 2026-10-23, Start 2026-10-19 |
| 19 to 30 Oct | 2026-10-30, Start 2026-10-19 |
| by November | 2026-11-30 |
| in March 2027 | 2027-03-31 |
| by Nov. | 2026-11-30 |
| by May | 2027-05-31 |
| we may | not a date |
| by fri | 2026-10-09 |
| EOB | 2026-10-08 |
| 3/4 inch | not a date |
| 1/2" valve | not a date |
| 1 1/2 pipe | not a date |
| 3/4 of the crew | not a date |
| 24/7 | not a date |
| 2:30pm | not a date |
| next year's budget | not a date |
| this week's numbers | not a date |
| the 4th quarter | not a date |
| 2H2027 | 2027-12-31 |
| Q42026 | 2026-12-31 |
| 1H2027 | 2027-06-30 |
| 2H 2027 | 2027-12-31 |
| due 2H | 2026-12-31 |
