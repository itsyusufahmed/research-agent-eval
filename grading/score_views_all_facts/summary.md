# Score views from `grading`, withdrawn fact included

Per 100 graded facts. Net score: a right answer adds one, a wrong answer subtracts its cost, a blank adds nothing.

| config | right | wrong | blank | net, wrong costs 1 | 95% interval | wrong costs 0 | wrong costs 2 | wrong costs 3 |
|---|---|---|---|---|---|---|---|---|
| exa-agent-medium-A-v1 | 82.2 | 14.3 | 3.5 | **67.9** | 64.4 to 71.2 | 82.2 | 53.6 | 39.3 |
| exa-agent-high-B-v1 | 87.6 | 9.6 | 2.8 | **78.0** | 75.2 to 80.8 | 87.6 | 68.4 | 58.8 |
| exa-agent-xhigh-v1 | 89.1 | 8.5 | 2.4 | **80.7** | 77.9 to 83.2 | 89.1 | 72.2 | 63.7 |
| claygent-luna-v1 | 72.6 | 15.9 | 11.5 | **56.7** | 53.0 to 60.3 | 72.6 | 40.8 | 24.9 |
| claygent-auto-A-v1 | 81.0 | 13.0 | 6.1 | **68.0** | 64.5 to 71.3 | 81.0 | 55.0 | 42.1 |
| claygent-argon-B-v1 | 85.6 | 13.0 | 1.4 | **72.6** | 69.2 to 75.8 | 85.6 | 59.7 | 46.7 |
| parallel-core-A-v1 | 85.7 | 13.3 | 1.0 | **72.3** | 69.0 to 75.5 | 85.7 | 59.0 | 45.7 |
| parallel-pro-B-v1 | 85.5 | 12.0 | 2.5 | **73.5** | 70.2 to 76.5 | 85.5 | 61.5 | 49.4 |
| parallel-ultra-C-v1 | 87.2 | 11.2 | 1.5 | **76.0** | 73.3 to 78.6 | 87.2 | 64.8 | 53.5 |

## Rank at each cost of a wrong answer

| wrong costs | order, best first |
|---|---|
| 0 | exa-agent-xhigh-v1 (89.1), exa-agent-high-B-v1 (87.6), parallel-ultra-C-v1 (87.2), parallel-core-A-v1 (85.7), claygent-argon-B-v1 (85.6), parallel-pro-B-v1 (85.5), exa-agent-medium-A-v1 (82.2), claygent-auto-A-v1 (81.0), claygent-luna-v1 (72.6) |
| 0.5 | exa-agent-xhigh-v1 (84.9), exa-agent-high-B-v1 (82.8), parallel-ultra-C-v1 (81.6), parallel-pro-B-v1 (79.5), claygent-argon-B-v1 (79.1), parallel-core-A-v1 (79.0), exa-agent-medium-A-v1 (75.0), claygent-auto-A-v1 (74.5), claygent-luna-v1 (64.6) |
| 1 | exa-agent-xhigh-v1 (80.7), exa-agent-high-B-v1 (78.0), parallel-ultra-C-v1 (76.0), parallel-pro-B-v1 (73.5), claygent-argon-B-v1 (72.6), parallel-core-A-v1 (72.3), claygent-auto-A-v1 (68.0), exa-agent-medium-A-v1 (67.9), claygent-luna-v1 (56.7) |
| 1.5 | exa-agent-xhigh-v1 (76.4), exa-agent-high-B-v1 (73.2), parallel-ultra-C-v1 (70.4), parallel-pro-B-v1 (67.5), claygent-argon-B-v1 (66.2), parallel-core-A-v1 (65.7), claygent-auto-A-v1 (61.5), exa-agent-medium-A-v1 (60.7), claygent-luna-v1 (48.8) |
| 2 | exa-agent-xhigh-v1 (72.2), exa-agent-high-B-v1 (68.4), parallel-ultra-C-v1 (64.8), parallel-pro-B-v1 (61.5), claygent-argon-B-v1 (59.7), parallel-core-A-v1 (59.0), claygent-auto-A-v1 (55.0), exa-agent-medium-A-v1 (53.6), claygent-luna-v1 (40.8) |
| 3 | exa-agent-xhigh-v1 (63.7), exa-agent-high-B-v1 (58.8), parallel-ultra-C-v1 (53.5), parallel-pro-B-v1 (49.4), claygent-argon-B-v1 (46.7), parallel-core-A-v1 (45.7), claygent-auto-A-v1 (42.1), exa-agent-medium-A-v1 (39.3), claygent-luna-v1 (24.9) |

## Paired differences on the net score (wrong costs 1), second minus first

| first | second | difference | 95% interval | clear of zero |
|---|---|---|---|---|
| exa-agent-medium-A-v1 | exa-agent-xhigh-v1 | +12.8 | +9.3 to +16.1 | yes |
| exa-agent-medium-A-v1 | exa-agent-high-B-v1 | +10.1 | +6.6 to +13.5 | yes |
| exa-agent-high-B-v1 | exa-agent-xhigh-v1 | +2.7 | +0.0 to +5.5 | no |
| claygent-auto-A-v1 | claygent-argon-B-v1 | +4.7 | +0.6 to +8.5 | yes |
| claygent-luna-v1 | claygent-auto-A-v1 | +11.3 | +7.7 to +15.0 | yes |
| parallel-core-A-v1 | parallel-pro-B-v1 | +1.1 | -1.7 to +3.9 | no |
| parallel-core-A-v1 | parallel-ultra-C-v1 | +3.7 | +1.3 to +6.1 | yes |
| parallel-pro-B-v1 | parallel-ultra-C-v1 | +2.5 | +0.1 to +5.0 | yes |
| claygent-argon-B-v1 | parallel-pro-B-v1 | +0.8 | -2.1 to +3.8 | no |
