from django.db import migrations


def forward(apps, schema_editor):
    Tooth, ToothEvent = apps.get_model("clinica", "Tooth"), apps.get_model("clinica", "ToothEvent")
    # el estado actual se toma como punto de partida del historial (sin autor: anterior al historial)
    ToothEvent.objects.bulk_create(
        ToothEvent(clinic_id=t.clinic_id, patient_id=t.patient_id, number=t.number, state=t.state, surfaces=t.surfaces) for t in Tooth.objects.all()
    )
    Notification = apps.get_model("clinica", "Notification")
    for n in Notification.objects.select_related("appointment"):
        n.scheduled_for = n.appointment.start
        n.save(update_fields=["scheduled_for"])


class Migration(migrations.Migration):
    dependencies = [("clinica", "0010_anulaciones_historial")]
    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
