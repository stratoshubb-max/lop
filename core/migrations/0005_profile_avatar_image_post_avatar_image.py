# Generated for the stepped signup + profile photo feature.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_alter_post_published_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='avatar_image',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='post',
            name='avatar_image',
            field=models.TextField(blank=True, default=''),
        ),
    ]
