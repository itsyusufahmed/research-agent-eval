# Score views from `grading`, withdrawn fact included

Per 100 graded facts. Net score: a right answer adds one, a wrong answer subtracts its cost, a blank adds nothing.

| config | right | wrong | blank | net, wrong costs 1 | 95% interval | wrong costs 0 | wrong costs 2 | wrong costs 3 |
|---|---|---|---|---|---|---|---|---|
| exa-agent-medium-A-v1 | 81.8 | 14.7 | 3.4 | **67.1** | 63.7 to 70.4 | 81.8 | 52.4 | 37.6 |
| exa-agent-high-B-v1 | 87.3 | 10.0 | 2.7 | **77.3** | 74.4 to 80.3 | 87.3 | 67.3 | 57.3 |
| exa-agent-xhigh-v1 | 88.6 | 9.0 | 2.5 | **79.6** | 76.8 to 82.2 | 88.6 | 70.7 | 61.7 |
| claygent-luna-v1 | 72.6 | 15.9 | 11.4 | **56.7** | 53.0 to 60.4 | 72.6 | 40.8 | 24.8 |
| claygent-auto-A-v1 | 80.4 | 13.6 | 6.0 | **66.8** | 63.3 to 70.2 | 80.4 | 53.2 | 39.6 |
| claygent-argon-B-v1 | 85.5 | 13.2 | 1.3 | **72.3** | 68.8 to 75.6 | 85.5 | 59.2 | 46.0 |
| parallel-core-A-v1 | 85.4 | 13.7 | 0.9 | **71.6** | 68.2 to 74.8 | 85.4 | 57.9 | 44.2 |
| parallel-pro-B-v1 | 85.2 | 12.6 | 2.3 | **72.6** | 69.3 to 75.7 | 85.2 | 60.0 | 47.5 |
| parallel-ultra-C-v1 | 86.9 | 11.7 | 1.4 | **75.2** | 72.5 to 77.8 | 86.9 | 63.4 | 51.7 |

## Rank at each cost of a wrong answer

| wrong costs | order, best first |
|---|---|
| 0 | exa-agent-xhigh-v1 (88.6), exa-agent-high-B-v1 (87.3), parallel-ultra-C-v1 (86.9), claygent-argon-B-v1 (85.5), parallel-core-A-v1 (85.4), parallel-pro-B-v1 (85.2), exa-agent-medium-A-v1 (81.8), claygent-auto-A-v1 (80.4), claygent-luna-v1 (72.6) |
| 0.5 | exa-agent-xhigh-v1 (84.1), exa-agent-high-B-v1 (82.3), parallel-ultra-C-v1 (81.0), claygent-argon-B-v1 (78.9), parallel-pro-B-v1 (78.9), parallel-core-A-v1 (78.5), exa-agent-medium-A-v1 (74.5), claygent-auto-A-v1 (73.6), claygent-luna-v1 (64.7) |
| 1 | exa-agent-xhigh-v1 (79.6), exa-agent-high-B-v1 (77.3), parallel-ultra-C-v1 (75.2), parallel-pro-B-v1 (72.6), claygent-argon-B-v1 (72.3), parallel-core-A-v1 (71.6), exa-agent-medium-A-v1 (67.1), claygent-auto-A-v1 (66.8), claygent-luna-v1 (56.7) |
| 1.5 | exa-agent-xhigh-v1 (75.1), exa-agent-high-B-v1 (72.3), parallel-ultra-C-v1 (69.3), parallel-pro-B-v1 (66.3), claygent-argon-B-v1 (65.8), parallel-core-A-v1 (64.8), claygent-auto-A-v1 (60.0), exa-agent-medium-A-v1 (59.7), claygent-luna-v1 (48.7) |
| 2 | exa-agent-xhigh-v1 (70.7), exa-agent-high-B-v1 (67.3), parallel-ultra-C-v1 (63.4), parallel-pro-B-v1 (60.0), claygent-argon-B-v1 (59.2), parallel-core-A-v1 (57.9), claygent-auto-A-v1 (53.2), exa-agent-medium-A-v1 (52.4), claygent-luna-v1 (40.8) |
| 3 | exa-agent-xhigh-v1 (61.7), exa-agent-high-B-v1 (57.3), parallel-ultra-C-v1 (51.7), parallel-pro-B-v1 (47.5), claygent-argon-B-v1 (46.0), parallel-core-A-v1 (44.2), claygent-auto-A-v1 (39.6), exa-agent-medium-A-v1 (37.6), claygent-luna-v1 (24.8) |

## Paired differences on the net score (wrong costs 1), second minus first

| first | second | difference | 95% interval | clear of zero |
|---|---|---|---|---|
| exa-agent-medium-A-v1 | exa-agent-xhigh-v1 | +12.5 | +9.1 to +16.0 | yes |
| exa-agent-medium-A-v1 | exa-agent-high-B-v1 | +10.2 | +6.7 to +13.7 | yes |
| exa-agent-high-B-v1 | exa-agent-xhigh-v1 | +2.3 | -0.5 to +5.2 | no |
| claygent-auto-A-v1 | claygent-argon-B-v1 | +5.5 | +1.2 to +9.6 | yes |
| claygent-luna-v1 | claygent-auto-A-v1 | +10.1 | +6.7 to +13.6 | yes |
| parallel-core-A-v1 | parallel-pro-B-v1 | +0.9 | -2.0 to +3.7 | no |
| parallel-core-A-v1 | parallel-ultra-C-v1 | +3.5 | +1.2 to +6.0 | yes |
| parallel-pro-B-v1 | parallel-ultra-C-v1 | +2.6 | +0.2 to +5.2 | yes |
| claygent-argon-B-v1 | parallel-pro-B-v1 | +0.2 | -2.6 to +3.2 | no |
