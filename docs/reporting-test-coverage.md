# Reporting Test Coverage

## Coverage Matrix

Axes covered by the canonical reporting suite:

| Axis | Values |
| --- | --- |
| Periods | `today`, `yesterday`, `week`, `month`, `year`, `custom` |
| Standard sections | `journalier`, `mensuel` |
| Custom section | `personnalise` |
| Custom data types | `transactions`, `members`, `access`, `subscriptions`, `registers` |
| Custom columns | `date`, `dataset`, `client`, `description`, `amount_cdf`, `method`, `status`, `reference`, `source` |
| Groupings | `none`, `day`, `week`, `month`, `type` |
| Export formats | `csv`, `xlsx` |
| Invariants | tenant scope, journal sums, net total, header order, grouped count conservation |

## Canonical Dataset

Reference date: `2026-05-21`

Tenant A:

- Organization: `Org Canonique`
- Gym: `Gym Canonique`
- Register opening amount: `1000.00`
- Exchange rate: `2800.00`
- Members created in scope:
  - `Alice Canon` on `2026-05-20 07:30`
  - `Brice Canon` on `2026-05-21 12:00`
- Subscription plan: `Mensuel Premium`
- Subscription start: `2026-05-20`
- Payments:
  - `2026-01-15 08:00` income `5600 CDF` category `other` description `Location salle`
  - `2026-05-20 09:15` income `10 USD` / `28000 CDF` category `subscription` description `Abonnement Alice`
  - `2026-05-21 11:45` income `9000 CDF` category `product` description `Boisson isotonique`
  - `2026-05-21 17:30` expense `7000 CDF` category `salary` description `Prime coach`
- Access logs:
  - granted on `2026-05-20 18:15`
  - denied on `2026-05-21 07:40`

Tenant B:

- Organization: `Org Externe`
- Gym: `Gym Externe`
- One member, one subscription, one payment, one access log
- Purpose: verify cross-tenant leakage never occurs

## Stable Expected Outputs

Expected month report (`2026-05-01` to `2026-05-21`) for `Gym Canonique`:

- Transaction count: `3`
- Register count: `1`
- Total entries CDF: `37000.00`
- Total exits CDF: `7000.00`
- Net total CDF: `30000.00`
- USD reference total: `10.00`
- Ordered journal descriptions:
  - `Abonnement Alice`
  - `Boisson isotonique`
  - `Prime coach`

## Automatic Invariants

Every canonical report test should enforce:

- No row mentions the external tenant or its data.
- `sum(incomes) == total_entries_cdf`
- `sum(expenses) == total_exits_cdf`
- `total_entries_cdf - total_exits_cdf == net_total_cdf`
- `len(journal_rows) == transaction_count`
- `len(register_rows) == register_count`
- Requested custom columns define header order exactly.
- Grouped custom reports preserve the original ungrouped row count.
