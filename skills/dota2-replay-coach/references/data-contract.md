# Replay fact bundle contract

The extractor expects the parsed JSON shape used by `gem-dota` in this project: `players`, `combat_log`, `opendota_teamfights` (or `teamfights`), `radiant_gold_adv`, `objectives`, `draft`, and player fields such as `net_worth_t_min`, `lh_t_min`, `purchase_log`, `ability_uses`, `item_uses`, and `position_log`.

The bundle also carries: `lane_role` per lineup entry (1=safe, 2=mid, 3=off; reliable — use it for lane assignment), `detection_purchases_by_player` (dust/sentry/gem counts from PURCHASE events, for counter-purchase audits), and `data_quality.reincarnation_pseudo_deaths_ignored` (fake deaths filtered from the death list). See [data-traps.md](data-traps.md) before interpreting raw fields.

The output is evidence, not a verdict. The coaching layer should cite exact timestamps and distinguish:

- observed facts: events, kills, deaths, purchases, gold/last-hit checkpoints, tower/Roshan events;
- derived metrics: teamfight kill difference, final-six-second defensive-spell availability, resource slope;
- coaching inference: safer entry, target priority, item choice, or BP recommendation.

If a field is absent, omit the metric and state the limitation. Never infer draft order from the final lineup. Keep snapshots bounded: no more than 50 datasets, 2,000 rows per dataset, or 3 MB total.

