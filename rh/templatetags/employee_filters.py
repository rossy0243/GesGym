from django import template

register = template.Library()

@register.filter
def get_item(dictionary, key):
    """Récupère un élément d'un dictionnaire par sa clé"""
    field_name = f'attendance_{key}'
    return dictionary[field_name]


@register.filter
def split(value, arg):
    """Split une chaîne par le séparateur"""
    return value.split(arg)