from bakery.services.access import is_office, is_production
from bakery.services.notifications import has_new_orders

def navigation(request):
    return {'office_user': is_office(request.user), 'production_user': is_production(request.user),
        'has_new_orders': has_new_orders(request.user)}
