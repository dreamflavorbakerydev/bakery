from django.forms.models import model_to_dict
from bakery.models import MasterDataChange


def snapshot(obj):
    return {key: str(value) if value is not None else None for key, value in model_to_dict(obj).items()}


def record_change(obj, before, source, actor=None):
    after = snapshot(obj)
    if before != after:
        MasterDataChange.objects.create(model_name=obj._meta.label, record_key=str(obj.pk),
            before=before, after=after, source=source, actor=actor)
