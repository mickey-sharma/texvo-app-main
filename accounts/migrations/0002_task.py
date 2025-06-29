# Generated by Django 4.2.7 on 2025-06-20 17:28

import accounts.models
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='Task',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('task_code', models.CharField(editable=False, max_length=20, unique=True)),
                ('module_code', models.CharField(max_length=50)),
                ('module_name', models.CharField(max_length=200)),
                ('word_count', models.PositiveIntegerField()),
                ('additional_words', models.PositiveIntegerField(default=0)),
                ('deadline', models.DateTimeField()),
                ('quoted_price', models.DecimalField(decimal_places=2, max_digits=10)),
                ('status', models.CharField(choices=[('Pending', 'Pending'), ('InProgress', 'In Progress'), ('Completed', 'Completed'), ('Failed', 'Failed'), ('Cancelled', 'Cancelled')], default='Pending', max_length=20)),
                ('notes', models.TextField(blank=True, null=True)),
                ('attachments', models.FileField(blank=True, null=True, upload_to=accounts.models.task_attachment_upload_path)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('allocation', models.ForeignKey(blank=True, limit_choices_to={'role': 'expert'}, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='created_tasks', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]
