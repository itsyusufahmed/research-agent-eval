# Score views from `grading`, 16 facts

Per 100 graded facts. Net score: a right answer adds one, a wrong answer subtracts its cost, a blank adds nothing.

| config | right | wrong | blank | net, wrong costs 1 | 95% interval | wrong costs 0 | wrong costs 2 | wrong costs 3 |
|---|---|---|---|---|---|---|---|---|
| exa-agent-medium-A-v1 | 83.2 | 13.0 | 3.7 | **70.2** | 66.7 to 73.4 | 83.2 | 57.1 | 44.1 |
| exa-agent-high-B-v1 | 89.1 | 8.0 | 2.9 | **81.1** | 78.2 to 84.0 | 89.1 | 73.1 | 65.1 |
| exa-agent-xhigh-v1 | 90.4 | 7.1 | 2.5 | **83.3** | 80.6 to 85.9 | 90.4 | 76.2 | 69.1 |
| claygent-luna-v1 | 74.6 | 14.5 | 10.9 | **60.2** | 56.6 to 63.7 | 74.6 | 45.7 | 31.2 |
| claygent-auto-A-v1 | 82.7 | 10.8 | 6.4 | **71.9** | 68.5 to 75.2 | 82.7 | 61.1 | 50.2 |
| claygent-argon-B-v1 | 86.8 | 11.7 | 1.5 | **75.1** | 71.8 to 78.0 | 86.8 | 63.4 | 51.8 |
| parallel-core-A-v1 | 87.0 | 11.9 | 1.1 | **75.0** | 72.0 to 77.9 | 87.0 | 63.1 | 51.1 |
| parallel-pro-B-v1 | 86.7 | 10.7 | 2.6 | **76.0** | 72.7 to 79.0 | 86.7 | 65.3 | 54.7 |
| parallel-ultra-C-v1 | 88.6 | 9.8 | 1.6 | **78.8** | 76.2 to 81.4 | 88.6 | 69.0 | 59.2 |

## Rank at each cost of a wrong answer

| wrong costs | order, best first |
|---|---|
| 0 | exa-agent-xhigh-v1 (90.4), exa-agent-high-B-v1 (89.1), parallel-ultra-C-v1 (88.6), parallel-core-A-v1 (87.0), claygent-argon-B-v1 (86.8), parallel-pro-B-v1 (86.7), exa-agent-medium-A-v1 (83.2), claygent-auto-A-v1 (82.7), claygent-luna-v1 (74.6) |
| 0.5 | exa-agent-xhigh-v1 (86.8), exa-agent-high-B-v1 (85.1), parallel-ultra-C-v1 (83.7), parallel-pro-B-v1 (81.4), parallel-core-A-v1 (81.0), claygent-argon-B-v1 (81.0), claygent-auto-A-v1 (77.3), exa-agent-medium-A-v1 (76.7), claygent-luna-v1 (67.4) |
| 1 | exa-agent-xhigh-v1 (83.3), exa-agent-high-B-v1 (81.1), parallel-ultra-C-v1 (78.8), parallel-pro-B-v1 (76.0), claygent-argon-B-v1 (75.1), parallel-core-A-v1 (75.0), claygent-auto-A-v1 (71.9), exa-agent-medium-A-v1 (70.2), claygent-luna-v1 (60.2) |
| 1.5 | exa-agent-xhigh-v1 (79.7), exa-agent-high-B-v1 (77.1), parallel-ultra-C-v1 (73.9), parallel-pro-B-v1 (70.7), claygent-argon-B-v1 (69.3), parallel-core-A-v1 (69.0), claygent-auto-A-v1 (66.5), exa-agent-medium-A-v1 (63.7), claygent-luna-v1 (52.9) |
| 2 | exa-agent-xhigh-v1 (76.2), exa-agent-high-B-v1 (73.1), parallel-ultra-C-v1 (69.0), parallel-pro-B-v1 (65.3), claygent-argon-B-v1 (63.4), parallel-core-A-v1 (63.1), claygent-auto-A-v1 (61.1), exa-agent-medium-A-v1 (57.1), claygent-luna-v1 (45.7) |
| 3 | exa-agent-xhigh-v1 (69.1), exa-agent-high-B-v1 (65.1), parallel-ultra-C-v1 (59.2), parallel-pro-B-v1 (54.7), claygent-argon-B-v1 (51.8), parallel-core-A-v1 (51.1), claygent-auto-A-v1 (50.2), exa-agent-medium-A-v1 (44.1), claygent-luna-v1 (31.2) |

## Paired differences on the net score (wrong costs 1), second minus first

| first | second | difference | 95% interval | clear of zero |
|---|---|---|---|---|
| exa-agent-medium-A-v1 | exa-agent-xhigh-v1 | +13.1 | +9.8 to +16.5 | yes |
| exa-agent-medium-A-v1 | exa-agent-high-B-v1 | +10.9 | +7.3 to +14.3 | yes |
| exa-agent-high-B-v1 | exa-agent-xhigh-v1 | +2.2 | -0.5 to +4.7 | no |
| claygent-auto-A-v1 | claygent-argon-B-v1 | +3.2 | -0.7 to +7.1 | no |
| claygent-luna-v1 | claygent-auto-A-v1 | +11.7 | +8.2 to +15.3 | yes |
| parallel-core-A-v1 | parallel-pro-B-v1 | +1.0 | -1.7 to +3.7 | no |
| parallel-core-A-v1 | parallel-ultra-C-v1 | +3.8 | +1.5 to +6.2 | yes |
| parallel-pro-B-v1 | parallel-ultra-C-v1 | +2.8 | +0.3 to +5.4 | yes |
| claygent-argon-B-v1 | parallel-pro-B-v1 | +0.9 | -1.8 to +3.6 | no |
