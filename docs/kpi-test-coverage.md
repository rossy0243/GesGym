# KPI Test Coverage

## Coverage Matrix

Axes covered by the canonical KPI suite:

| Axis | Values |
| --- | --- |
| Periods | `day`, `week`, `month`, `year` |
| Modules | `machines`, `rh`, `products`, `coaching` |
| Surfaces | direct builder output, dashboard context injection |
| Invariants | tenant scope, non-negative counts, chart totals, ratios in range, dashboard-to-builder consistency |

## Canonical Dataset

Reference date: `2026-05-21`

Tenant A (`Gym KPI A`):

- Machines:
  - `Tapis A` status `ok`
  - `Velo A` status `maintenance`
  - `Presse A` status `broken`
  - maintenance logs: `75` on `2026-05-20`, `25` on `2026-01-12`
- Products:
  - `Whey` price `10`, quantity `8`
  - `Barre` price `5`, quantity `3`
  - `Shaker` price `7`, quantity `0`
  - `Ancien` inactive, quantity `2`
  - movements in period: `+5`, `-2`
- RH:
  - one active employee at `100/day`
  - one inactive employee at `80/day`
  - attendances: present/present/absent in scope
  - one salary POS payment + payment record
- Coaching:
  - one active coach with 2 assigned members
  - one inactive coach
  - one overdue follow-up
  - one low/sensitive feedback
  - one positive feedback

Tenant B (`Gym KPI B`) contains pollution data for every module and must never appear in tenant A outputs.

## Stable Expected Outputs

Month expectations for `Gym KPI A`:

- Machines:
  - total `3`
  - ok `1`
  - maintenance `1`
  - broken `1`
  - availability `33.3`
  - period maintenance cost `75.00`
- Products:
  - active total `3`
  - inactive `1`
  - stock status values `[1, 1, 1]`
  - stock total value `95.00`
- RH:
  - employees total `2`
  - active `1`
  - inactive `1`
  - today rate `50.0`
  - period rate `66.7`
  - payroll `200.00`
- Coaching:
  - coaches total `2`
  - active `1`
  - inactive `1`
  - assigned members `2`
  - unassigned `1`
  - feedback average `3.0`

## Automatic Invariants

Every KPI test should enforce:

- No foreign tenant object leaks into collections or labels.
- Machine status counts add up to total machines.
- Product chart totals add up to active products.
- Coaching status chart totals add up to total coaches.
- RH attendance rates stay within `0..100`.
- Dashboard context values match direct builder outputs for the same period.
