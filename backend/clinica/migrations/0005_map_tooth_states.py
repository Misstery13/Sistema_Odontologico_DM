from django.db import migrations

# caries/obturado eran estados de pieza completa; ahora son hallazgos de superficie
MAP = {"caries": ("sano", {"O": "caries"}), "obturado": ("sano", {"O": "restauracion"}), "corona": ("protesis_fija", {})}


def forward(apps, schema_editor):
    Tooth = apps.get_model("clinica", "Tooth")
    for old, (state, surfaces) in MAP.items():
        Tooth.objects.filter(state=old).update(state=state, surfaces=surfaces)


class Migration(migrations.Migration):
    dependencies = [("clinica", "0004_srs_fase2")]
    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
