from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("photos", "0007_character_importance_original_name")]

    operations = [
        migrations.AddField(model_name="title", name="age_rating", field=models.CharField(blank=True, choices=[("g", "G"), ("pg", "PG"), ("pg13", "PG-13"), ("r17", "R-17"), ("rplus", "R+"), ("rx", "Rx")], max_length=12, verbose_name="Возрастной рейтинг")),
        migrations.AddField(model_name="title", name="audience", field=models.CharField(blank=True, choices=[("shounen", "Сёнен"), ("shoujo", "Сёдзё"), ("seinen", "Сэйнэн"), ("josei", "Дзёсэй"), ("kids", "Детское")], max_length=16, verbose_name="Аудитория")),
        migrations.AddField(model_name="title", name="episodes", field=models.PositiveSmallIntegerField(blank=True, null=True, verbose_name="Количество эпизодов")),
        migrations.AddField(model_name="title", name="format", field=models.CharField(blank=True, choices=[("tv", "TV-сериал"), ("movie", "Фильм"), ("ova", "OVA"), ("ona", "ONA"), ("special", "Спецвыпуск"), ("short", "Короткометражное"), ("music", "Клип"), ("other", "Другое")], max_length=16, verbose_name="Формат")),
        migrations.AddField(model_name="title", name="genres", field=models.CharField(blank=True, max_length=500, verbose_name="Жанры")),
        migrations.AddField(model_name="title", name="release_status", field=models.CharField(blank=True, choices=[("announced", "Анонсировано"), ("ongoing", "Выходит"), ("completed", "Завершено"), ("paused", "Приостановлено")], max_length=16, verbose_name="Статус выхода")),
        migrations.AddField(model_name="title", name="score", field=models.DecimalField(blank=True, decimal_places=1, max_digits=3, null=True, verbose_name="Оценка")),
        migrations.AddField(model_name="title", name="season", field=models.CharField(blank=True, choices=[("winter", "Зима"), ("spring", "Весна"), ("summer", "Лето"), ("autumn", "Осень")], max_length=12, verbose_name="Сезон")),
        migrations.AddField(model_name="title", name="themes", field=models.CharField(blank=True, max_length=500, verbose_name="Темы")),
        migrations.AddField(model_name="title", name="year", field=models.PositiveSmallIntegerField(blank=True, null=True, verbose_name="Год выхода")),
    ]
