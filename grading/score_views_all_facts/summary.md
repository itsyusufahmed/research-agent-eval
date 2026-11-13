# Score views from `grading`, withdrawn fact included

Per 100 graded facts. Net score: a right answer adds one, a wrong answer subtracts its cost, a blank adds nothing.

| config | right | wrong | blank | net, wrong costs 1 | 95% interval | wrong costs 0 | wrong costs 2 | wrong costs 3 |
|---|---|---|---|---|---|---|---|---|
| exa-agent-medium-A-v1 | 82.2 | 14.3 | 3.5 | **67.9** | 64.4 to 71.2 | 82.2 | 53.6 | 39.3 |
| exa-agent-high-B-v1 | 87.6 | 9.6 | 2.8 | **77.9** | 75.2 to 80.7 | 87.6 | 68.3 | 58.6 |
| exa-agent-xhigh-v1 | 89.0 | 8.6 | 2.5 | **80.4** | 77.7 to 83.0 | 89.0 | 71.8 | 63.3 |
| claygent-luna-v1 | 72.6 | 15.9 | 11.5 | **56.8** | 53.0 to 60.3 | 72.6 | 40.9 | 25.0 |
| claygent-auto-A-v1 | 81.0 | 13.0 | 6.0 | **68.0** | 64.5 to 71.4 | 81.0 | 55.1 | 42.1 |
| claygent-argon-B-v1 | 85.6 | 13.0 | 1.4 | **72.6** | 69.2 to 75.7 | 85.6 | 59.6 | 46.6 |
| parallel-core-A-v1 | 85.7 | 13.4 | 0.9 | **72.2** | 68.9 to 75.4 | 85.7 | 58.8 | 45.4 |
| parallel-pro-B-v1 | 85.5 | 12.2 | 2.3 | **73.3** | 70.1 to 76.3 | 85.5 | 61.2 | 49.0 |
| parallel-ultra-C-v1 | 87.1 | 11.5 | 1.4 | **75.7** | 73.0 to 78.3 | 87.1 | 64.2 | 52.7 |

## Rank at each cost of a wrong answer

| wrong costs | order, best first |
|---|---|
| 0 | exa-agent-xhigh-v1 (89.0), exa-agent-high-B-v1 (87.6), parallel-ultra-C-v1 (87.1), parallel-core-A-v1 (85.7), claygent-argon-B-v1 (85.6), parallel-pro-B-v1 (85.5), exa-agent-medium-A-v1 (82.2), claygent-auto-A-v1 (81.0), claygent-luna-v1 (72.6) |
| 0.5 | exa-agent-xhigh-v1 (84.7), exa-agent-high-B-v1 (82.8), parallel-ultra-C-v1 (81.4), parallel-pro-B-v1 (79.4), claygent-argon-B-v1 (79.1), parallel-core-A-v1 (78.9), exa-agent-medium-A-v1 (75.1), claygent-auto-A-v1 (74.5), claygent-luna-v1 (64.7) |
| 1 | exa-agent-xhigh-v1 (80.4), exa-agent-high-B-v1 (77.9), parallel-ultra-C-v1 (75.7), parallel-pro-B-v1 (73.3), claygent-argon-B-v1 (72.6), parallel-core-A-v1 (72.2), claygent-auto-A-v1 (68.0), exa-agent-medium-A-v1 (67.9), claygent-luna-v1 (56.8) |
| 1.5 | exa-agent-xhigh-v1 (76.1), exa-agent-high-B-v1 (73.1), parallel-ultra-C-v1 (69.9), parallel-pro-B-v1 (67.2), claygent-argon-B-v1 (66.1), parallel-core-A-v1 (65.5), claygent-auto-A-v1 (61.6), exa-agent-medium-A-v1 (60.8), claygent-luna-v1 (48.8) |
| 2 | exa-agent-xhigh-v1 (71.8), exa-agent-high-B-v1 (68.3), parallel-ultra-C-v1 (64.2), parallel-pro-B-v1 (61.2), claygent-argon-B-v1 (59.6), parallel-core-A-v1 (58.8), claygent-auto-A-v1 (55.1), exa-agent-medium-A-v1 (53.6), claygent-luna-v1 (40.9) |
| 3 | exa-agent-xhigh-v1 (63.3), exa-agent-high-B-v1 (58.6), parallel-ultra-C-v1 (52.7), parallel-pro-B-v1 (49.0), claygent-argon-B-v1 (46.6), parallel-core-A-v1 (45.4), claygent-auto-A-v1 (42.1), exa-agent-medium-A-v1 (39.3), claygent-luna-v1 (25.0) |

## Paired differences on the net score (wrong costs 1), second minus first

| first | second | difference | 95% interval | clear of zero |
|---|---|---|---|---|
| exa-agent-medium-A-v1 | exa-agent-xhigh-v1 | +12.5 | +9.1 to +15.9 | yes |
| exa-agent-medium-A-v1 | exa-agent-high-B-v1 | +10.0 | +6.5 to +13.4 | yes |
| exa-agent-high-B-v1 | exa-agent-xhigh-v1 | +2.5 | -0.2 to +5.3 | no |
| claygent-auto-A-v1 | claygent-argon-B-v1 | +4.6 | +0.5 to +8.4 | yes |
| claygent-luna-v1 | claygent-auto-A-v1 | +11.3 | +7.7 to +15.0 | yes |
| parallel-core-A-v1 | parallel-pro-B-v1 | +1.1 | -1.7 to +3.8 | no |
| parallel-core-A-v1 | parallel-ultra-C-v1 | +3.4 | +1.1 to +5.8 | yes |
| parallel-pro-B-v1 | parallel-ultra-C-v1 | +2.3 | -0.0 to +4.9 | no |
| claygent-argon-B-v1 | parallel-pro-B-v1 | +0.7 | -2.2 to +3.7 | no |
