from django.conf import settings


def market(request):
    """The deployment's market (brand, country, domain) for every template: {{ market.brand }}."""
    return {"market": settings.MARKET}
