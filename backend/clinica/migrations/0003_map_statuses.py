from django.db import migrations

OLD_TO_NEW = {"programada": "programado", "completada": "atendido", "cancelada": "cancelado"}


def forward(apps, schema_editor):
    Appointment = apps.get_model("clinica", "Appointment")
    for old, new in OLD_TO_NEW.items():
        Appointment.objects.filter(status=old).update(status=new)


class Migration(migrations.Migration):
    dependencies = [("clinica", "0002_srs_fase1")]
    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
