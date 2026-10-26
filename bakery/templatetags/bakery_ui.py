import re

from django import template

register = template.Library()


@register.filter
def phone_display(value):
    raw = str(value or '').strip()
    if not re.fullmatch(r'[\d\s()+.\-]+', raw):
        return raw
    digits = re.sub(r'\D', '', raw)
    prefix = ''
    if len(digits) == 11 and digits.startswith('1'):
        prefix, digits = '+1 ', digits[1:]
    if len(digits) == 10:
        return f'{prefix}({digits[:3]}) {digits[3:6]}-{digits[6:]}'
    return raw


@register.simple_tag(takes_context=True)
def table_query(context, **changes):
    query = context['request'].GET.copy()
    for name, value in changes.items():
        if value is None:
            query.pop(name, None)
        else:
            query[name] = value
    return '?' + query.urlencode()


@register.inclusion_tag('bakery/sort_header.html', takes_context=True)
def sort_header(context, key, label):
    active = context.get('sort') == key
    descending = active and context.get('direction') == 'asc'
    direction = 'desc' if descending else 'asc'
    return {
        'label': label, 'active': active,
        'aria_sort': ('ascending' if context.get('direction') == 'asc' else 'descending') if active else 'none',
        'next_direction': 'descending' if descending else 'ascending',
        'url': table_query(context, sort=key, direction=direction, page=None),
    }
