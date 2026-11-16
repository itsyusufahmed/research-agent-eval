# Score views from `grading`, 16 facts

Per 100 graded facts. Net score: a right answer adds one, a wrong answer subtracts its cost, a blank adds nothing.

| config | right | wrong | blank | net, wrong costs 1 | 95% interval | wrong costs 0 | wrong costs 2 | wrong costs 3 |
|---|---|---|---|---|---|---|---|---|
| exa-agent-medium-A-v1 | 83.3 | 13.0 | 3.7 | **70.2** | 66.7 to 73.4 | 83.3 | 57.2 | 44.1 |
| exa-agent-high-B-v1 | 89.2 | 8.0 | 2.8 | **81.2** | 78.3 to 84.1 | 89.2 | 73.2 | 65.2 |
| exa-agent-xhigh-v1 | 90.3 | 7.2 | 2.5 | **83.2** | 80.5 to 85.7 | 90.3 | 76.0 | 68.9 |
| claygent-luna-v1 | 74.8 | 14.5 | 10.8 | **60.3** | 56.7 to 63.8 | 74.8 | 45.8 | 31.4 |
| claygent-auto-A-v1 | 82.9 | 10.8 | 6.3 | **72.0** | 68.6 to 75.3 | 82.9 | 61.2 | 50.3 |
| claygent-argon-B-v1 | 86.8 | 11.7 | 1.5 | **75.1** | 71.9 to 78.0 | 86.8 | 63.4 | 51.8 |
| parallel-core-A-v1 | 87.0 | 12.0 | 1.1 | **75.0** | 71.9 to 77.8 | 87.0 | 63.0 | 51.0 |
| parallel-pro-B-v1 | 86.7 | 10.7 | 2.5 | **76.0** | 72.8 to 79.0 | 86.7 | 65.3 | 54.6 |
| parallel-ultra-C-v1 | 88.5 | 9.9 | 1.5 | **78.6** | 75.9 to 81.2 | 88.5 | 68.6 | 58.7 |

## Rank at each cost of a wrong answer

| wrong costs | order, best first |
|---|---|
| 0 | exa-agent-xhigh-v1 (90.3), exa-agent-high-B-v1 (89.2), parallel-ultra-C-v1 (88.5), parallel-core-A-v1 (87.0), claygent-argon-B-v1 (86.8), parallel-pro-B-v1 (86.7), exa-agent-medium-A-v1 (83.3), claygent-auto-A-v1 (82.9), claygent-luna-v1 (74.8) |
| 0.5 | exa-agent-xhigh-v1 (86.7), exa-agent-high-B-v1 (85.2), parallel-ultra-C-v1 (83.6), parallel-pro-B-v1 (81.4), claygent-argon-B-v1 (81.0), parallel-core-A-v1 (81.0), claygent-auto-A-v1 (77.4), exa-agent-medium-A-v1 (76.7), claygent-luna-v1 (67.5) |
| 1 | exa-agent-xhigh-v1 (83.2), exa-agent-high-B-v1 (81.2), parallel-ultra-C-v1 (78.6), parallel-pro-B-v1 (76.0), claygent-argon-B-v1 (75.1), parallel-core-A-v1 (75.0), claygent-auto-A-v1 (72.0), exa-agent-medium-A-v1 (70.2), claygent-luna-v1 (60.3) |
| 1.5 | exa-agent-xhigh-v1 (79.6), exa-agent-high-B-v1 (77.2), parallel-ultra-C-v1 (73.6), parallel-pro-B-v1 (70.6), claygent-argon-B-v1 (69.3), parallel-core-A-v1 (69.0), claygent-auto-A-v1 (66.6), exa-agent-medium-A-v1 (63.7), claygent-luna-v1 (53.1) |
| 2 | exa-agent-xhigh-v1 (76.0), exa-agent-high-B-v1 (73.2), parallel-ultra-C-v1 (68.6), parallel-pro-B-v1 (65.3), claygent-argon-B-v1 (63.4), parallel-core-A-v1 (63.0), claygent-auto-A-v1 (61.2), exa-agent-medium-A-v1 (57.2), claygent-luna-v1 (45.8) |
| 3 | exa-agent-xhigh-v1 (68.9), exa-agent-high-B-v1 (65.2), parallel-ultra-C-v1 (58.7), parallel-pro-B-v1 (54.6), claygent-argon-B-v1 (51.8), parallel-core-A-v1 (51.0), claygent-auto-A-v1 (50.3), exa-agent-medium-A-v1 (44.1), claygent-luna-v1 (31.4) |

## Paired differences on the net score (wrong costs 1), second minus first

| first | second | difference | 95% interval | clear of zero |
|---|---|---|---|---|
| exa-agent-medium-A-v1 | exa-agent-xhigh-v1 | +12.9 | +9.6 to +16.4 | yes |
| exa-agent-medium-A-v1 | exa-agent-high-B-v1 | +11.0 | +7.4 to +14.4 | yes |
| exa-agent-high-B-v1 | exa-agent-xhigh-v1 | +1.9 | -0.7 to +4.6 | no |
| claygent-auto-A-v1 | claygent-argon-B-v1 | +3.1 | -0.8 to +7.0 | no |
| claygent-luna-v1 | claygent-auto-A-v1 | +11.7 | +8.2 to +15.3 | yes |
| parallel-core-A-v1 | parallel-pro-B-v1 | +1.1 | -1.7 to +3.7 | no |
| parallel-core-A-v1 | parallel-ultra-C-v1 | +3.6 | +1.3 to +6.0 | yes |
| parallel-pro-B-v1 | parallel-ultra-C-v1 | +2.6 | +0.1 to +5.3 | yes |
| claygent-argon-B-v1 | parallel-pro-B-v1 | +0.9 | -1.8 to +3.6 | no |
