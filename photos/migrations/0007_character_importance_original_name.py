from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("photos", "0006_todoitem_completed_at_todoitem_priority"),
    ]

    operations = [
        migrations.AddField(
            model_name="character",
            name="importance",
            field=models.CharField(
                choices=[
                    ("main", "Главный персонаж"),
                    ("supporting", "Второстепенный персонаж"),
                    ("episodic", "Эпизодический персонаж"),
                ],
                default="supporting",
                max_length=20,
                verbose_name="Роль в сюжете",
            ),
        ),
        migrations.AddField(
            model_name="character",
            name="original_name",
            field=models.CharField(blank=True, max_length=220, verbose_name="Оригинальное имя"),
        ),
    ]
