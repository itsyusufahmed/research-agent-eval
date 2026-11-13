# Score views from `grading`, 16 facts

Per 100 graded facts. Net score: a right answer adds one, a wrong answer subtracts its cost, a blank adds nothing.

| config | right | wrong | blank | net, wrong costs 1 | 95% interval | wrong costs 0 | wrong costs 2 | wrong costs 3 |
|---|---|---|---|---|---|---|---|---|
| exa-agent-medium-A-v1 | 83.3 | 13.0 | 3.7 | **70.2** | 66.7 to 73.4 | 83.3 | 57.2 | 44.1 |
| exa-agent-high-B-v1 | 89.1 | 8.0 | 2.8 | **81.1** | 78.2 to 83.9 | 89.1 | 73.0 | 65.0 |
| exa-agent-xhigh-v1 | 90.2 | 7.2 | 2.6 | **83.0** | 80.3 to 85.5 | 90.2 | 75.8 | 68.6 |
| claygent-luna-v1 | 74.7 | 14.5 | 10.8 | **60.2** | 56.6 to 63.8 | 74.7 | 45.8 | 31.3 |
| claygent-auto-A-v1 | 82.8 | 10.8 | 6.4 | **72.0** | 68.5 to 75.3 | 82.8 | 61.1 | 50.3 |
| claygent-argon-B-v1 | 86.8 | 11.7 | 1.5 | **75.1** | 71.8 to 77.9 | 86.8 | 63.3 | 51.6 |
| parallel-core-A-v1 | 87.0 | 12.0 | 1.0 | **74.9** | 71.8 to 77.8 | 87.0 | 62.9 | 50.8 |
| parallel-pro-B-v1 | 86.7 | 10.8 | 2.5 | **75.9** | 72.7 to 78.8 | 86.7 | 65.0 | 54.2 |
| parallel-ultra-C-v1 | 88.5 | 10.0 | 1.5 | **78.4** | 75.8 to 81.0 | 88.5 | 68.4 | 58.3 |

## Rank at each cost of a wrong answer

| wrong costs | order, best first |
|---|---|
| 0 | exa-agent-xhigh-v1 (90.2), exa-agent-high-B-v1 (89.1), parallel-ultra-C-v1 (88.5), parallel-core-A-v1 (87.0), claygent-argon-B-v1 (86.8), parallel-pro-B-v1 (86.7), exa-agent-medium-A-v1 (83.3), claygent-auto-A-v1 (82.8), claygent-luna-v1 (74.7) |
| 0.5 | exa-agent-xhigh-v1 (86.6), exa-agent-high-B-v1 (85.1), parallel-ultra-C-v1 (83.5), parallel-pro-B-v1 (81.3), claygent-argon-B-v1 (80.9), parallel-core-A-v1 (80.9), claygent-auto-A-v1 (77.4), exa-agent-medium-A-v1 (76.7), claygent-luna-v1 (67.5) |
| 1 | exa-agent-xhigh-v1 (83.0), exa-agent-high-B-v1 (81.1), parallel-ultra-C-v1 (78.4), parallel-pro-B-v1 (75.9), claygent-argon-B-v1 (75.1), parallel-core-A-v1 (74.9), claygent-auto-A-v1 (72.0), exa-agent-medium-A-v1 (70.2), claygent-luna-v1 (60.2) |
| 1.5 | exa-agent-xhigh-v1 (79.4), exa-agent-high-B-v1 (77.0), parallel-ultra-C-v1 (73.4), parallel-pro-B-v1 (70.4), claygent-argon-B-v1 (69.2), parallel-core-A-v1 (68.9), claygent-auto-A-v1 (66.5), exa-agent-medium-A-v1 (63.7), claygent-luna-v1 (53.0) |
| 2 | exa-agent-xhigh-v1 (75.8), exa-agent-high-B-v1 (73.0), parallel-ultra-C-v1 (68.4), parallel-pro-B-v1 (65.0), claygent-argon-B-v1 (63.3), parallel-core-A-v1 (62.9), claygent-auto-A-v1 (61.1), exa-agent-medium-A-v1 (57.2), claygent-luna-v1 (45.8) |
| 3 | exa-agent-xhigh-v1 (68.6), exa-agent-high-B-v1 (65.0), parallel-ultra-C-v1 (58.3), parallel-pro-B-v1 (54.2), claygent-argon-B-v1 (51.6), parallel-core-A-v1 (50.8), claygent-auto-A-v1 (50.3), exa-agent-medium-A-v1 (44.1), claygent-luna-v1 (31.3) |

## Paired differences on the net score (wrong costs 1), second minus first

| first | second | difference | 95% interval | clear of zero |
|---|---|---|---|---|
| exa-agent-medium-A-v1 | exa-agent-xhigh-v1 | +12.8 | +9.4 to +16.1 | yes |
| exa-agent-medium-A-v1 | exa-agent-high-B-v1 | +10.8 | +7.2 to +14.2 | yes |
| exa-agent-high-B-v1 | exa-agent-xhigh-v1 | +1.9 | -0.7 to +4.6 | no |
| claygent-auto-A-v1 | claygent-argon-B-v1 | +3.1 | -0.8 to +7.0 | no |
| claygent-luna-v1 | claygent-auto-A-v1 | +11.7 | +8.2 to +15.3 | yes |
| parallel-core-A-v1 | parallel-pro-B-v1 | +0.9 | -1.7 to +3.6 | no |
| parallel-core-A-v1 | parallel-ultra-C-v1 | +3.5 | +1.2 to +5.9 | yes |
| parallel-pro-B-v1 | parallel-ultra-C-v1 | +2.6 | +0.1 to +5.3 | yes |
| claygent-argon-B-v1 | parallel-pro-B-v1 | +0.8 | -1.9 to +3.5 | no |
