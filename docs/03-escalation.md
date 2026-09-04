# Using the evidence

Collecting data is the easy half. This is about turning it into something an
operator acts on.

---

## Work out what is actually broken first

Before you write to anyone, decide which of these you are looking at. They call
for different fixes, and asking for the wrong one wastes weeks.

| Cause | Signature in the data | What to ask for |
|---|---|---|
| Physical / optical fault | Loss spread evenly across the day; modem optical levels drift over weeks; error counters climb; restarts barely help | A field technician with a meter, and the operator's line-side readings |
| Modem firmware or memory fault | Degrades with uptime; a restart restores it; optical levels fine | Replacement of the modem |
| Congestion | Loss concentrated in the evening peak; clean overnight | Capacity on your segment — a different conversation, and a weaker one |
| Operator DNS fault | DNS failures while ICMP and TCP stay clean | Nothing about the line. Point your resolver elsewhere. |
| A daily restart making things worse | Heavy loss in the hours *after* each restart, clean later | Stop restarting — see below |

Section 5 of the report (loss by time of day) separates congestion from
hardware. Section 6 separates DNS from the line. Section 4 covers the last row,
if you enable the experiment.

---

## If you restart the modem on a timer, test it

A nightly power cycle is a common folk remedy and a genuinely ambiguous one.
The same symptom fits "the restart is fixing a device that degrades" and "the
restart triggers a re-registration that costs hours". Some operators apply
hold-down timers when the client behind a modem changes, in which case the cure
is producing the outage.

`ispbust experiment` settles it by randomising restart and no-restart nights
from a fixed seed, so the schedule is committed in advance and cannot drift to
fit the result:

```bash
# 1. commit to a schedule and keep the file
ispbust experiment plan --days 28 > schedule.txt

# 2. from cron on whatever controls the plug, at the configured hour
0 3 * * * docker run --rm -v ...  ispbust-report experiment run

# 3. after two weeks or more
ispbust experiment analyse --since 2026-09-01
```

It reports one of four readings: the restart is harmful, helpful, makes no
difference, or there is not enough data yet. Two weeks is the minimum worth
quoting.

---

## What to ask the operator for

Email, not phone. You want a ticket number and a paper trail, and a phone
agent cannot read out line-side measurements anyway.

Ask for the things only they can see:

1. **Line-side signal measurements** for your connection — on fibre, the
   optical receive power at their end for your modem, current and historical.
2. **Per-line error counters** — FEC, BIP, CRC, whatever their access
   technology exposes.
3. **The session log for your line** — every deactivation, reactivation,
   re-ranging event and dying gasp their equipment recorded, with timestamps.
   Line this up against section 3 of your report.
4. **The port's error history**, and whether neighbouring subscribers on the
   same segment show correlated events.
5. **A field appointment with a meter** at the customer termination point — not
   a remote "we see no fault" check.

Attach the report as PDF (print from the browser). Quote the ticket number in
every later message.

---

## The escalation ladder

**1. Formal fault report.** In writing, with the report attached. Get a ticket
number *and the date they received it* in writing — in many jurisdictions that
date starts a statutory clock.

**2. Keep measuring.** Do not stop when you open the ticket. A second report
showing no improvement after their "fix" is more powerful than the first, and
it costs you nothing because the probes are already running.

**3. Statutory remedies.** Most jurisdictions give consumers something:
compensation for repair delays, a rate reduction for sustained
underperformance, or a right to terminate. These usually have **formal
evidence requirements that your own tooling does not satisfy** — often a
regulator-provided measurement app, run to a prescribed schedule. Your data
proves the fault exists and tells you *when* to run their official
measurement; it does not replace it. Look up what your regulator requires
before you rely on a remedy, and time their measurement to land inside the
degraded hours your own report identifies.

**4. Regulator or ombudsman.** If the operator will not act, most countries
have a telecoms dispute body. A continuous measurement archive with checksums
and a pre-committed experiment schedule is unusually strong material for that
forum — far better than the screenshots they normally receive.

---

## Writing the covering message

The report does the arguing. Keep the message short and factual.

What works:

- **Lead with the paired comparison.** "Over the same minutes, from the same
  network, with the same hardware, the second connection lost 0.09 % of packets
  and yours lost 8.8 %." That closes off "the problem is on your side" before
  anyone raises it.
- **Point at their own first hop.** Loss measured against the operator's edge
  router is inside their network, before any handover. It is the hardest number
  in the document to deflect.
- **Give absolute counts, not adjectives.** "298 minutes of total outage" beats
  "constantly dropping out".
- **Offer the raw data.** Saying it is available, with checksums, signals that
  the numbers will survive scrutiny. Almost nobody asks.

What does not work: adjectives, frustration, and technical theories about their
network. State what you measured and what you want done.

---

## Before you demand a replacement device

If your goal is swapping the operator's modem for your own hardware, get the
fault documented **first**. Swap it before the fault is on record and you have
handed them a permanent deflection: *"you are not using our equipment."*

And be honest about whether a new modem would help at all — check the table at
the top of this page. If the fault is in the line, replacing the box changes
nothing and gives them a reason to stop looking.
