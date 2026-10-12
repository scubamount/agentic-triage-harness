# Example: repro parity rejects a plausible reproduction ("the hang")

Case summary (from the public writeup "How to effectively debug when you no
longer understand the code", Cindy Sridharan, 2026 — paraphrased, used as a
teaching example with attribution):

A desktop daemon exposed a remote storage service as a virtual filesystem.
Users reported frequent 60s timeouts. No crashes, no errors in the logs, no
server-side latency anomaly at the timeout timestamps. Packet captures showed
the TCP handshake and Websocket upgrade succeeding, then silence except
periodic pings/pongs — the daemon connected but never issued read/write
requests after the upgrade.

## The tempting repro

A coworker reproduced the hang in a test harness: the harness simulated clock
skew, the daemon presented a token the server considered expired, the server
rejected it, the daemon retried session establishment forever. Symptoms looked
exactly like the user reports.

## Why it was noise

A repro lives in the derivative tier — it proves *a* bug exists, not that it is
*the* bug under investigation. Two high-fidelity signals from the factual tier
settled it:

| Signal | User reports | Coworker's repro | Verdict |
|---|---|---|---|
| Packet sequence per connection | Identical across every reported hang: handshake, upgrade, then nothing but pings | Started the same, then diverged (auth traffic the users never showed) | Diverged |
| Kernel IPC tables | Authentication daemon still held the one-time reply right for the daemon's unanswered request, 67 hours later | No unanswered reply right existed | Diverged |

The repro was real — clock skew is a real distributed-systems problem — but it
reproduced a *different* signal set, so it was falsified against the factual
tier and discarded. The actual root cause (the authentication daemon accepted
an XPC request but never called the completion handler) was found by descending
layers: logs (uninformative) → packet capture (healthy connection, then
silence) → process state (nothing in the auth path was running, so something
was *waiting*, not looping) → kernel IPC table (the strong signal).

## The rule

Before relaying "reproduced": name the user-reported signal verbatim, show the
repro emits the same signal, and treat divergence as a different bug. A
falsified repro plays no further part in the investigation. Conversely, the
memory-leak bug's repro *was* trustworthy because its heap profile showed the
exact frame the reporter attached — signal parity is what makes a repro
admissible.
