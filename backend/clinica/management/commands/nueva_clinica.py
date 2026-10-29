from django.core.management.base import BaseCommand
from django.db import transaction

from clinica.management.commands.seed import CONSENT_BODY, CONSENTS, PROCEDURES, SUPPLIES
from clinica.models import Chair, Clinic, ConsentTemplate, Procedure, RecipeLine, Supply


class Command(BaseCommand):
    help = "Da de alta una clínica (tenant) con sillones y catálogos base: formatos de consentimiento, procedimientos e insumos sin stock."

    def add_arguments(self, parser):
        parser.add_argument("nombre")
        parser.add_argument("--sillones", type=int, default=2)

    @transaction.atomic
    def handle(self, nombre, sillones, **options):
        clinic, created = Clinic.objects.get_or_create(name=nombre)
        for n in range(1, sillones + 1):
            Chair.objects.get_or_create(clinic=clinic, name=f"Sillón {n}")
        for procedure, risks in CONSENTS.items():
            ConsentTemplate.objects.get_or_create(clinic=clinic, procedure=procedure, defaults={"body": CONSENT_BODY.replace("{riesgos}", risks)})
        for name, (unit, _stock, minimum, cost) in SUPPLIES.items():
            Supply.objects.get_or_create(clinic=clinic, name=name, defaults={"unit": unit, "min_stock": minimum, "unit_cost": cost})
        for code, (name, fee, lab, recipe) in PROCEDURES.items():
            proc, new = Procedure.objects.get_or_create(clinic=clinic, code=code, defaults={"name": name, "fee": fee, "lab_cost": lab})
            if new:
                for supply, qty in recipe.items():
                    RecipeLine.objects.create(procedure=proc, supply=Supply.objects.get(clinic=clinic, name=supply), quantity=qty)
        self.stdout.write(f"Clínica «{clinic.name}» {'creada' if created else 'actualizada'} (id {clinic.pk}). "
                          "Registra el stock inicial desde Inventario y crea usuarios con `manage.py usuario`.")
