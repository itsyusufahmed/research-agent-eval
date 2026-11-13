# Score views from `grading`, 16 facts

Per 100 graded facts. Net score: a right answer adds one, a wrong answer subtracts its cost, a blank adds nothing.

| config | right | wrong | blank | net, wrong costs 1 | 95% interval | wrong costs 0 | wrong costs 2 | wrong costs 3 |
|---|---|---|---|---|---|---|---|---|
| exa-agent-medium-A-v1 | 82.9 | 13.5 | 3.6 | **69.3** | 66.0 to 72.5 | 82.9 | 55.8 | 42.3 |
| exa-agent-high-B-v1 | 88.8 | 8.4 | 2.7 | **80.4** | 77.5 to 83.4 | 88.8 | 72.0 | 63.6 |
| exa-agent-xhigh-v1 | 89.8 | 7.6 | 2.6 | **82.2** | 79.4 to 84.7 | 89.8 | 74.5 | 66.9 |
| claygent-luna-v1 | 74.7 | 14.5 | 10.8 | **60.2** | 56.5 to 63.8 | 74.7 | 45.7 | 31.1 |
| claygent-auto-A-v1 | 82.2 | 11.5 | 6.3 | **70.6** | 67.2 to 74.1 | 82.2 | 59.1 | 47.6 |
| claygent-argon-B-v1 | 86.7 | 11.9 | 1.4 | **74.8** | 71.4 to 77.7 | 86.7 | 62.9 | 51.0 |
| parallel-core-A-v1 | 86.6 | 12.4 | 1.0 | **74.3** | 71.2 to 77.2 | 86.6 | 61.9 | 49.6 |
| parallel-pro-B-v1 | 86.3 | 11.3 | 2.4 | **75.1** | 71.8 to 78.2 | 86.3 | 63.8 | 52.6 |
| parallel-ultra-C-v1 | 88.2 | 10.3 | 1.5 | **77.9** | 75.3 to 80.6 | 88.2 | 67.6 | 57.3 |

## Rank at each cost of a wrong answer

| wrong costs | order, best first |
|---|---|
| 0 | exa-agent-xhigh-v1 (89.8), exa-agent-high-B-v1 (88.8), parallel-ultra-C-v1 (88.2), claygent-argon-B-v1 (86.7), parallel-core-A-v1 (86.6), parallel-pro-B-v1 (86.3), exa-agent-medium-A-v1 (82.9), claygent-auto-A-v1 (82.2), claygent-luna-v1 (74.7) |
| 0.5 | exa-agent-xhigh-v1 (86.0), exa-agent-high-B-v1 (84.6), parallel-ultra-C-v1 (83.1), claygent-argon-B-v1 (80.7), parallel-pro-B-v1 (80.7), parallel-core-A-v1 (80.5), claygent-auto-A-v1 (76.4), exa-agent-medium-A-v1 (76.1), claygent-luna-v1 (67.4) |
| 1 | exa-agent-xhigh-v1 (82.2), exa-agent-high-B-v1 (80.4), parallel-ultra-C-v1 (77.9), parallel-pro-B-v1 (75.1), claygent-argon-B-v1 (74.8), parallel-core-A-v1 (74.3), claygent-auto-A-v1 (70.6), exa-agent-medium-A-v1 (69.3), claygent-luna-v1 (60.2) |
| 1.5 | exa-agent-xhigh-v1 (78.4), exa-agent-high-B-v1 (76.2), parallel-ultra-C-v1 (72.8), parallel-pro-B-v1 (69.4), claygent-argon-B-v1 (68.9), parallel-core-A-v1 (68.1), claygent-auto-A-v1 (64.9), exa-agent-medium-A-v1 (62.6), claygent-luna-v1 (52.9) |
| 2 | exa-agent-xhigh-v1 (74.5), exa-agent-high-B-v1 (72.0), parallel-ultra-C-v1 (67.6), parallel-pro-B-v1 (63.8), claygent-argon-B-v1 (62.9), parallel-core-A-v1 (61.9), claygent-auto-A-v1 (59.1), exa-agent-medium-A-v1 (55.8), claygent-luna-v1 (45.7) |
| 3 | exa-agent-xhigh-v1 (66.9), exa-agent-high-B-v1 (63.6), parallel-ultra-C-v1 (57.3), parallel-pro-B-v1 (52.6), claygent-argon-B-v1 (51.0), parallel-core-A-v1 (49.6), claygent-auto-A-v1 (47.6), exa-agent-medium-A-v1 (42.3), claygent-luna-v1 (31.1) |

## Paired differences on the net score (wrong costs 1), second minus first

| first | second | difference | 95% interval | clear of zero |
|---|---|---|---|---|
| exa-agent-medium-A-v1 | exa-agent-xhigh-v1 | +12.8 | +9.6 to +16.2 | yes |
| exa-agent-medium-A-v1 | exa-agent-high-B-v1 | +11.1 | +7.4 to +14.6 | yes |
| exa-agent-high-B-v1 | exa-agent-xhigh-v1 | +1.7 | -0.9 to +4.4 | no |
| claygent-auto-A-v1 | claygent-argon-B-v1 | +4.2 | -0.1 to +8.2 | no |
| claygent-luna-v1 | claygent-auto-A-v1 | +10.5 | +7.0 to +14.0 | yes |
| parallel-core-A-v1 | parallel-pro-B-v1 | +0.8 | -2.0 to +3.4 | no |
| parallel-core-A-v1 | parallel-ultra-C-v1 | +3.6 | +1.3 to +6.1 | yes |
| parallel-pro-B-v1 | parallel-ultra-C-v1 | +2.8 | +0.3 to +5.6 | yes |
| claygent-argon-B-v1 | parallel-pro-B-v1 | +0.3 | -2.4 to +2.9 | no |
