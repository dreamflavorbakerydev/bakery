"""Allowlisted ordering for paginated workspace tables."""
from django.db.models import F


def sort_records(request, records, columns, default):
    key = request.GET.get('sort', default)
    if key not in columns:
        key = default
    direction = 'desc' if request.GET.get('direction') == 'desc' else 'asc'
    fields = columns[key]
    if not isinstance(fields, tuple):
        fields = (fields,)
    ordering = []
    for field in fields:
        expression = F(field) if isinstance(field, str) else field
        ordering.append(expression.desc(nulls_last=True) if direction == 'desc' else expression.asc(nulls_last=True))
    return records.order_by(*ordering, 'pk'), {'sort': key, 'direction': direction}
