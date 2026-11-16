# Score views from `grading`, withdrawn fact included

Per 100 graded facts. Net score: a right answer adds one, a wrong answer subtracts its cost, a blank adds nothing.

| config | right | wrong | blank | net, wrong costs 1 | 95% interval | wrong costs 0 | wrong costs 2 | wrong costs 3 |
|---|---|---|---|---|---|---|---|---|
| exa-agent-medium-A-v1 | 82.2 | 14.3 | 3.5 | **67.9** | 64.4 to 71.2 | 82.2 | 53.6 | 39.3 |
| exa-agent-high-B-v1 | 87.7 | 9.6 | 2.7 | **78.1** | 75.3 to 80.9 | 87.7 | 68.5 | 58.9 |
| exa-agent-xhigh-v1 | 89.1 | 8.5 | 2.4 | **80.6** | 77.8 to 83.2 | 89.1 | 72.0 | 63.5 |
| claygent-luna-v1 | 72.7 | 15.9 | 11.4 | **56.8** | 53.1 to 60.3 | 72.7 | 40.9 | 25.0 |
| claygent-auto-A-v1 | 81.0 | 13.0 | 6.0 | **68.1** | 64.6 to 71.4 | 81.0 | 55.1 | 42.2 |
| claygent-argon-B-v1 | 85.6 | 13.0 | 1.4 | **72.6** | 69.2 to 75.8 | 85.6 | 59.7 | 46.7 |
| parallel-core-A-v1 | 85.7 | 13.4 | 1.0 | **72.3** | 68.9 to 75.4 | 85.7 | 58.9 | 45.6 |
| parallel-pro-B-v1 | 85.6 | 12.1 | 2.4 | **73.5** | 70.2 to 76.5 | 85.6 | 61.4 | 49.3 |
| parallel-ultra-C-v1 | 87.2 | 11.4 | 1.4 | **75.8** | 73.1 to 78.4 | 87.2 | 64.4 | 53.0 |

## Rank at each cost of a wrong answer

| wrong costs | order, best first |
|---|---|
| 0 | exa-agent-xhigh-v1 (89.1), exa-agent-high-B-v1 (87.7), parallel-ultra-C-v1 (87.2), parallel-core-A-v1 (85.7), claygent-argon-B-v1 (85.6), parallel-pro-B-v1 (85.6), exa-agent-medium-A-v1 (82.2), claygent-auto-A-v1 (81.0), claygent-luna-v1 (72.7) |
| 0.5 | exa-agent-xhigh-v1 (84.8), exa-agent-high-B-v1 (82.9), parallel-ultra-C-v1 (81.5), parallel-pro-B-v1 (79.5), claygent-argon-B-v1 (79.1), parallel-core-A-v1 (79.0), exa-agent-medium-A-v1 (75.1), claygent-auto-A-v1 (74.6), claygent-luna-v1 (64.7) |
| 1 | exa-agent-xhigh-v1 (80.6), exa-agent-high-B-v1 (78.1), parallel-ultra-C-v1 (75.8), parallel-pro-B-v1 (73.5), claygent-argon-B-v1 (72.6), parallel-core-A-v1 (72.3), claygent-auto-A-v1 (68.1), exa-agent-medium-A-v1 (67.9), claygent-luna-v1 (56.8) |
| 1.5 | exa-agent-xhigh-v1 (76.3), exa-agent-high-B-v1 (73.3), parallel-ultra-C-v1 (70.1), parallel-pro-B-v1 (67.4), claygent-argon-B-v1 (66.2), parallel-core-A-v1 (65.6), claygent-auto-A-v1 (61.6), exa-agent-medium-A-v1 (60.8), claygent-luna-v1 (48.9) |
| 2 | exa-agent-xhigh-v1 (72.0), exa-agent-high-B-v1 (68.5), parallel-ultra-C-v1 (64.4), parallel-pro-B-v1 (61.4), claygent-argon-B-v1 (59.7), parallel-core-A-v1 (58.9), claygent-auto-A-v1 (55.1), exa-agent-medium-A-v1 (53.6), claygent-luna-v1 (40.9) |
| 3 | exa-agent-xhigh-v1 (63.5), exa-agent-high-B-v1 (58.9), parallel-ultra-C-v1 (53.0), parallel-pro-B-v1 (49.3), claygent-argon-B-v1 (46.7), parallel-core-A-v1 (45.6), claygent-auto-A-v1 (42.2), exa-agent-medium-A-v1 (39.3), claygent-luna-v1 (25.0) |

## Paired differences on the net score (wrong costs 1), second minus first

| first | second | difference | 95% interval | clear of zero |
|---|---|---|---|---|
| exa-agent-medium-A-v1 | exa-agent-xhigh-v1 | +12.6 | +9.2 to +16.0 | yes |
| exa-agent-medium-A-v1 | exa-agent-high-B-v1 | +10.1 | +6.6 to +13.6 | yes |
| exa-agent-high-B-v1 | exa-agent-xhigh-v1 | +2.5 | -0.2 to +5.3 | no |
| claygent-auto-A-v1 | claygent-argon-B-v1 | +4.6 | +0.5 to +8.4 | yes |
| claygent-luna-v1 | claygent-auto-A-v1 | +11.3 | +7.7 to +15.0 | yes |
| parallel-core-A-v1 | parallel-pro-B-v1 | +1.2 | -1.6 to +4.0 | no |
| parallel-core-A-v1 | parallel-ultra-C-v1 | +3.5 | +1.2 to +6.0 | yes |
| parallel-pro-B-v1 | parallel-ultra-C-v1 | +2.3 | -0.0 to +4.9 | no |
| claygent-argon-B-v1 | parallel-pro-B-v1 | +0.8 | -2.1 to +3.8 | no |
